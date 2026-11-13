"""Permission-aware filtered sales reports and period comparisons."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Mapping

from .connection import get_connection


def can_view_reports(user: Mapping[str, Any] | None) -> bool:
    """Reports are read-only and available to authenticated users with a menu grant."""
    if not user:
        return False
    allowed = user.get("allowed_menus", "*")
    return allowed == "*" or "reports" in allowed or "report" in allowed or user.get("role") == "Admin"


def _date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    return date.fromisoformat(value)


def normalize_filters(filters: Mapping[str, Any]) -> Dict[str, Any]:
    end = _date(filters.get("end_date"), date.today())
    start = _date(filters.get("start_date"), end - timedelta(days=29))
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    return {
        "start_date": start,
        "end_date": end,
        "product_id": (filters.get("product_id") or "").strip() or None,
        "category_id": (filters.get("category_id") or "").strip() or None,
        "customer_id": (filters.get("customer_id") or "").strip() or None,
    }


def _query(filters: Mapping[str, Any]) -> List[Dict[str, Any]]:
    f = normalize_filters(filters)
    clauses = ["DATE(s.SALES_DATE) BETWEEN %s AND %s"]
    params: List[Any] = [f["start_date"], f["end_date"]]
    if f["product_id"]:
        clauses.append("sd.PRODUCT_ID = %s")
        params.append(f["product_id"])
    if f["category_id"]:
        clauses.append("p.CATEGORY_ID = %s")
        params.append(f["category_id"])
    if f["customer_id"]:
        clauses.append("s.CS_ID = %s")
        params.append(f["customer_id"])
    sql = f"""
        SELECT DATE(s.SALES_DATE) AS sales_date, sd.PRODUCT_ID AS product_id,
               p.PRODUCT_NAME AS product_name, c.CATEGORY_NAME AS category_name,
               s.CS_ID AS customer_id, COALESCE(cs.CS_NAME, s.CASH_CS_NAME, 'Cash Customer') AS customer_name,
               SUM(sd.QTY) AS quantity, ROUND(SUM(sd.QTY * sd.UNIT_PRICE), 2) AS revenue
        FROM sales s JOIN sales_details sd ON sd.SALES_ID = s.SALES_ID
        JOIN product p ON p.PRODUCT_ID = sd.PRODUCT_ID
        LEFT JOIN category c ON c.CATEGORY_ID = p.CATEGORY_ID
        LEFT JOIN cs ON cs.CS_ID = s.CS_ID
        WHERE {' AND '.join(clauses)}
        GROUP BY DATE(s.SALES_DATE), sd.PRODUCT_ID, p.PRODUCT_NAME,
                 c.CATEGORY_NAME, s.CS_ID, customer_name
        ORDER BY sales_date DESC
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    for row in rows:
        row["quantity"] = float(row.get("quantity") or 0)
        row["revenue"] = float(row.get("revenue") or 0)
        if hasattr(row.get("sales_date"), "strftime"):
            row["sales_date"] = row["sales_date"].strftime("%Y-%m-%d")
    return rows


def get_sales_report(filters: Mapping[str, Any]) -> Dict[str, Any]:
    f = normalize_filters(filters)
    rows = _query(filters)
    period_days = (f["end_date"] - f["start_date"]).days + 1
    previous = {
        "start_date": (f["start_date"] - timedelta(days=period_days)).isoformat(),
        "end_date": (f["start_date"] - timedelta(days=1)).isoformat(),
        "product_id": f["product_id"],
        "category_id": f["category_id"],
        "customer_id": f["customer_id"],
    }
    previous_rows = _query(previous)
    revenue = sum(r["revenue"] for r in rows)
    previous_revenue = sum(r["revenue"] for r in previous_rows)
    return {
        "filters": {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in f.items()},
        "rows": rows,
        "summary": {
            "revenue": round(revenue, 2),
            "quantity": round(sum(r["quantity"] for r in rows), 2),
            "invoice_lines": len(rows),
            "previous_revenue": round(previous_revenue, 2),
            "change_percent": round((revenue - previous_revenue) / previous_revenue * 100, 2) if previous_revenue else None,
        },
    }
