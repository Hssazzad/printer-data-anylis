"""Read-only, explainable dashboard alerts."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from .connection import get_connection


def build_alert(kind: str, reason: str, data_date: Any, **values: Any) -> Dict[str, Any]:
    return {
        "kind": kind,
        "reason": reason,
        "data_date": data_date.strftime("%Y-%m-%d") if hasattr(data_date, "strftime") else str(data_date or "-"),
        **values,
    }


def get_smart_alerts(inactive_days: int = 90, low_stock_threshold: float = 0) -> List[Dict[str, Any]]:
    """Return low-stock, refill, and inactive-customer alerts with source dates."""
    cutoff = date.today() - timedelta(days=int(inactive_days))
    alerts: List[Dict[str, Any]] = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.PRODUCT_ID AS product_id, p.PRODUCT_NAME AS product_name,
                       COALESCE(SUM(s.STOCK_QTY), 0) AS current_stock
                FROM product p LEFT JOIN stock_non_serial s ON p.PRODUCT_ID = s.PRODUCT_ID
                GROUP BY p.PRODUCT_ID, p.PRODUCT_NAME
                HAVING current_stock <= %s
                ORDER BY current_stock ASC
                LIMIT 100
                """,
                (low_stock_threshold,),
            )
            for row in cur.fetchall():
                alerts.append(build_alert(
                    "low_stock",
                    f"Stock is at or below {low_stock_threshold:g} units.",
                    date.today(),
                    product_id=row["product_id"],
                    product_name=row["product_name"],
                    current_stock=float(row["current_stock"] or 0),
                ))
            cur.execute(
                """
                SELECT c.CS_ID AS customer_id, c.CS_NAME AS customer_name,
                       MAX(s.SALES_DATE) AS last_purchase
                FROM cs c LEFT JOIN sales s ON s.CS_ID = c.CS_ID
                GROUP BY c.CS_ID, c.CS_NAME
                HAVING last_purchase IS NULL OR last_purchase < %s
                ORDER BY last_purchase
                LIMIT 100
                """,
                (cutoff,),
            )
            for row in cur.fetchall():
                alerts.append(build_alert(
                    "inactive_customer",
                    f"No purchase in the last {inactive_days} days.",
                    row.get("last_purchase") or cutoff,
                    customer_id=row["customer_id"],
                    customer_name=row["customer_name"],
                    last_purchase=row.get("last_purchase") or None,
                ))
    # Reuse the existing consumption-cycle analysis so refill alerts remain
    # consistent with the ink dependency screen.
    from .ink_dependency import get_refill_due_alerts
    for row in get_refill_due_alerts():
        alerts.append(build_alert(
            "ink_refill",
            f"Consumable purchase is {row.get('days_since_purchase', 0)} days old.",
            row.get("last_purchase_date"),
            customer_id=row.get("customer_id"),
            customer_name=row.get("customer_name"),
            product_name=row.get("last_product_name"),
            days_since_purchase=int(row.get("days_since_purchase") or 0),
        ))
    return alerts
