"""Filtered, read-only Customer vs Product report calculations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional

from .connection import get_connection


def normalize_affinity_filters(filters: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    start = (filters.get("start_date") or "").strip() or None
    end = (filters.get("end_date") or "").strip() or None
    if start:
        date.fromisoformat(start)
    if end:
        date.fromisoformat(end)
    if start and end and start > end:
        raise ValueError("start_date must be on or before end_date")
    return {
        "start_date": start,
        "end_date": end,
        "customer_id": (filters.get("customer_id") or "").strip() or None,
        "product_id": (filters.get("product_id") or "").strip() or None,
        "category_id": (filters.get("category_id") or "").strip() or None,
    }


def _row_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _amount(row: Mapping[str, Any], quantity: float) -> float:
    if row.get("net_amount") is not None:
        return float(row["net_amount"] or 0)
    amount = quantity * float(row.get("unit_price", 0) or 0)
    return amount - float(row.get("discount", 0) or 0)


def aggregate_affinity_rows(rows: List[Mapping[str, Any]], filters: Mapping[str, Any]) -> Dict[str, Any]:
    """Build both customer and product views from synthetic/database-shaped rows."""
    selected = normalize_affinity_filters(filters)
    selected_rows = []
    for row in rows:
        current = _row_date(row.get("sales_date"))
        if not current:
            continue
        if selected["start_date"] and current < date.fromisoformat(selected["start_date"]):
            continue
        if selected["end_date"] and current > date.fromisoformat(selected["end_date"]):
            continue
        customer_id = str(row.get("customer_id") or "")
        if selected["customer_id"] and customer_id != selected["customer_id"]:
            continue
        if selected["product_id"] and str(row.get("product_id")) != selected["product_id"]:
            continue
        if selected["category_id"] and selected["category_id"] not in (
            str(row.get("category_id")), str(row.get("category_name"))
        ):
            continue
        quantity = float(row.get("quantity", row.get("qty", 0)) or 0)
        selected_rows.append({
            **row, "sales_date": current, "customer_id": customer_id or None,
            "customer_name": row.get("customer_name") or "Direct Client",
            "quantity": quantity, "amount": _amount(row, quantity),
        })

    customer_map: Dict[str, Dict[str, Any]] = {}
    product_map: Dict[str, Dict[str, Any]] = {}
    repeat_map: Dict[str, set] = {}
    monthly: Dict[str, Dict[str, float]] = {}
    for row in selected_rows:
        customer_key = str(row["customer_id"] or "DIRECT")
        product_key = str(row.get("product_id") or "")
        customer = customer_map.setdefault(customer_key, {
            "customer_id": row["customer_id"], "customer_name": row["customer_name"],
            "quantity": 0.0, "spending": 0.0, "invoices": set(), "products": set(),
            "last_purchase_date": None,
        })
        customer["quantity"] += row["quantity"]
        customer["spending"] += row["amount"]
        if row.get("sale_id") is not None:
            customer["invoices"].add(str(row["sale_id"]))
        customer["products"].add(product_key)
        customer["last_purchase_date"] = max(customer["last_purchase_date"] or row["sales_date"], row["sales_date"])
        repeat_map.setdefault(customer_key, set()).add(str(row.get("sale_id") or row["sales_date"]))

        product = product_map.setdefault(product_key, {
            "product_id": row.get("product_id"), "product_name": row.get("product_name") or product_key,
            "category_name": row.get("category_name") or "General", "quantity": 0.0,
            "spending": 0.0, "customers": set(), "invoices": set(), "last_purchase_date": None,
        })
        product["quantity"] += row["quantity"]
        product["spending"] += row["amount"]
        product["customers"].add(customer_key)
        if row.get("sale_id") is not None:
            product["invoices"].add(str(row["sale_id"]))
        product["last_purchase_date"] = max(product["last_purchase_date"] or row["sales_date"], row["sales_date"])

        period = row["sales_date"].strftime("%Y-%m")
        monthly.setdefault(period, {"quantity": 0.0, "spending": 0.0, "repeat_purchases": 0})
        monthly[period]["quantity"] += row["quantity"]
        monthly[period]["spending"] += row["amount"]

    def clean(item: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("invoices", "products", "customers"):
            if isinstance(item.get(key), set):
                item[key] = len(item[key])
        if item.get("last_purchase_date"):
            item["last_purchase_date"] = item["last_purchase_date"].isoformat()
        item["quantity"] = round(item.get("quantity", 0), 2)
        item["spending"] = round(item.get("spending", 0), 2)
        item["purchase_frequency"] = item.pop("invoices", 0)
        return item

    customers = [clean(item) for item in customer_map.values()]
    products = [clean(item) for item in product_map.values()]
    customers.sort(key=lambda item: item["spending"], reverse=True)
    products.sort(key=lambda item: item["spending"], reverse=True)
    repeat_purchases = sum(1 for invoices in repeat_map.values() if len(invoices) > 1)
    for item in monthly.values():
        item["quantity"] = round(item["quantity"], 2)
        item["spending"] = round(item["spending"], 2)
        item["repeat_purchases"] = repeat_purchases
    return {
        "filters": selected,
        "customer_view": customers,
        "product_view": products,
        "monthly": [{"period": period, **values} for period, values in sorted(monthly.items())],
        "summary": {
            "customers": len(customers), "products": len(products),
            "quantity": round(sum(item["quantity"] for item in customers), 2),
            "spending": round(sum(item["spending"] for item in customers), 2),
            "repeat_customers": repeat_purchases,
            "sales_lines": len(selected_rows),
        },
    }


def get_filtered_affinity_report(filters: Mapping[str, Any]) -> Dict[str, Any]:
    selected = normalize_affinity_filters(filters)
    clauses = ["s.SALES_DATE IS NOT NULL"]
    params: List[Any] = []
    if selected["start_date"]:
        clauses.append("DATE(s.SALES_DATE) >= %s")
        params.append(selected["start_date"])
    if selected["end_date"]:
        clauses.append("DATE(s.SALES_DATE) <= %s")
        params.append(selected["end_date"])
    if selected["customer_id"]:
        clauses.append("COALESCE(sd.CS_ID, s.CS_ID) = %s")
        params.append(selected["customer_id"])
    if selected["product_id"]:
        clauses.append("sd.PRODUCT_ID = %s")
        params.append(selected["product_id"])
    if selected["category_id"]:
        clauses.append("(p.CATEGORY_ID = %s OR c.CATEGORY_NAME = %s)")
        params.extend([selected["category_id"], selected["category_id"]])
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.SALES_ID AS sale_id, DATE(s.SALES_DATE) AS sales_date,
                       COALESCE(sd.CS_ID, s.CS_ID) AS customer_id,
                       COALESCE(cs.CS_NAME, 'Direct Client') AS customer_name,
                       sd.PRODUCT_ID AS product_id, p.PRODUCT_NAME AS product_name,
                       p.CATEGORY_ID AS category_id, c.CATEGORY_NAME AS category_name,
                       sd.QTY AS quantity, sd.UNIT_PRICE AS unit_price
                FROM sales s
                JOIN sales_details sd ON sd.SALES_ID = s.SALES_ID
                JOIN product p ON p.PRODUCT_ID = sd.PRODUCT_ID
                LEFT JOIN category c ON c.CATEGORY_ID = p.CATEGORY_ID
                LEFT JOIN cs ON cs.CS_ID = COALESCE(sd.CS_ID, s.CS_ID)
                WHERE {' AND '.join(clauses)}
                ORDER BY s.SALES_DATE ASC
            """, params)
            rows = cur.fetchall()
    report = aggregate_affinity_rows(rows, selected)
    report["generated_at"] = datetime.now().isoformat(timespec="seconds")
    report["calculation"] = {
        "spending": "SUM(QTY * UNIT_PRICE); negative quantities remain negative for returns.",
        "discounts": "A dedicated discount/net amount field is not present in the current query; UNIT_PRICE is treated as the effective line price.",
        "frequency": "COUNT(DISTINCT SALES_ID), so multiple products on one invoice count as one purchase.",
        "missing_customers": "Missing CS_ID/customer rows are grouped as Direct Client.",
    }
    return report
