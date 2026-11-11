from typing import Dict, Any, List
from datetime import date, datetime
from decimal import Decimal
import time
from .connection import get_connection

_OVERVIEW_CACHE: Dict[str, Any] = {"data": None, "ts": 0}
_LIST_CACHE: Dict[str, Any] = {"data": None, "ts": 0, "limit": None}
_OVERVIEW_TTL = 60
_LIST_TTL = 60

def format_date(dt) -> str:
    if not dt:
        return "-"
    if isinstance(dt, (date, datetime)):
        return dt.strftime("%d %b %Y")
    return str(dt)

def clean_record(d: Any) -> Any:
    if isinstance(d, dict):
        for k, v in list(d.items()):
            if isinstance(v, (date, datetime)):
                d[k] = v.strftime("%Y-%m-%d")
            elif isinstance(v, Decimal):
                d[k] = float(v)
            elif isinstance(v, (dict, list)):
                d[k] = clean_record(v)
        return d
    elif isinstance(d, list):
        return [clean_record(i) for i in d]
    return d

def clear_affinity_cache():
    _OVERVIEW_CACHE["data"] = None
    _LIST_CACHE["data"] = None

def get_affinity_overview() -> Dict[str, Any]:
    now = time.time()
    if _OVERVIEW_CACHE["data"] and (now - _OVERVIEW_CACHE["ts"]) < _OVERVIEW_TTL:
        return _OVERVIEW_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Single pass for base KPIs (uses idx_sd_cs covering index)
            cur.execute("""
                SELECT
                    COUNT(DISTINCT CS_ID) as total_active_customers,
                    COUNT(DISTINCT PRODUCT_ID) as total_purchased_products,
                    ROUND(COALESCE(SUM(QTY * UNIT_PRICE),0), 2) as total_volume
                FROM sales_details
                WHERE CS_ID IS NOT NULL AND CS_ID != ''
            """)
            stats = cur.fetchone() or {}
            # Repeat buyers + top category in one round-trip via two indexed queries on same connection
            cur.execute("""
                SELECT COUNT(*) as repeat_buyers FROM (
                    SELECT CS_ID FROM sales_details
                    WHERE CS_ID IS NOT NULL AND CS_ID != ''
                    GROUP BY CS_ID HAVING COUNT(DISTINCT SALES_ID) >= 3
                ) t
            """)
            rep = cur.fetchone() or {}
            cur.execute("""
                SELECT COALESCE(c.CATEGORY_NAME, 'General') as cat, COUNT(*) as cnt
                FROM sales_details sd
                JOIN product p ON sd.PRODUCT_ID = p.PRODUCT_ID
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                GROUP BY cat ORDER BY cnt DESC LIMIT 1
            """)
            top_cat = cur.fetchone() or {}
    total_cust = int(stats.get("total_active_customers") or 0)
    rep_cust = int(rep.get("repeat_buyers") or 0)
    rep_rate = round((rep_cust / total_cust * 100), 1) if total_cust > 0 else 0
    data = {
        "total_active_customers": total_cust,
        "total_purchased_products": int(stats.get("total_purchased_products") or 0),
        "repeat_buyers": rep_cust,
        "repeat_buyer_rate": rep_rate,
        "top_category": str(top_cat.get("cat", "General")),
        "total_volume": float(stats.get("total_volume") or 0),
    }
    _OVERVIEW_CACHE.update(data=data, ts=now)
    return data

def get_customer_affinity_list(limit: int = 500) -> List[Dict[str, Any]]:
    limit = int(limit)
    now = time.time()
    if _LIST_CACHE["data"] is not None and _LIST_CACHE.get("limit") == limit and (now - _LIST_CACHE["ts"]) < _LIST_TTL:
        return _LIST_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Aggregate first (index-only scan on sales_details), join cs only for top-N rows
            cur.execute(f"""
                SELECT
                    agg.customer_id,
                    COALESCE(c.CS_NAME, 'Direct Client') as customer_name,
                    COALESCE(c.MOBILE, '-') as phone,
                    COALESCE(c.ADDRESS, '-') as address,
                    agg.total_orders,
                    agg.unique_products_bought,
                    agg.total_units_bought,
                    agg.total_spent,
                    agg.last_purchase_date
                FROM (
                    SELECT
                        CS_ID as customer_id,
                        COUNT(DISTINCT SALES_ID) as total_orders,
                        COUNT(DISTINCT PRODUCT_ID) as unique_products_bought,
                        ROUND(SUM(QTY), 0) as total_units_bought,
                        ROUND(SUM(QTY * UNIT_PRICE), 2) as total_spent,
                        MAX(SALES_DATE) as last_purchase_date
                    FROM sales_details
                    WHERE CS_ID IS NOT NULL AND CS_ID != ''
                    GROUP BY CS_ID
                    ORDER BY total_spent DESC
                    LIMIT {limit}
                ) agg
                LEFT JOIN cs c ON agg.customer_id = c.CS_ID
            """)
            rows = cur.fetchall()
            for r in rows:
                clean_record(r)
                r["total_units_bought"] = int(r["total_units_bought"] or 0)
                r["total_spent"] = float(r["total_spent"] or 0)
                r["total_orders"] = int(r["total_orders"] or 0)
                r["unique_products_bought"] = int(r["unique_products_bought"] or 0)
                r["last_purchase_formatted"] = format_date(r.get("last_purchase_date"))
                r["avg_order_value"] = round(r["total_spent"] / r["total_orders"], 2) if r["total_orders"] > 0 else 0
            _LIST_CACHE.update(data=rows, ts=now, limit=limit)
            return rows

def get_customer_product_breakdown(customer_id: str) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT CS_ID, CS_NAME, MOBILE, ADDRESS, PHONE, EMAIL, BALANCE, CREDIT_LIMIT
                FROM cs WHERE CS_ID = %s LIMIT 1
            """, (customer_id,))
            cust = cur.fetchone() or {
                "CS_ID": customer_id,
                "CS_NAME": f"Customer ({customer_id})",
                "MOBILE": "-",
                "ADDRESS": "-"
            }
            clean_record(cust)
            cur.execute("""
                SELECT
                    sd.PRODUCT_ID as product_id,
                    p.PRODUCT_NAME as product_name,
                    COALESCE(c.CATEGORY_NAME, 'General') as category_name,
                    ROUND(SUM(sd.QTY), 0) as qty_bought,
                    ROUND(AVG(sd.UNIT_PRICE), 2) as avg_unit_price,
                    ROUND(SUM(sd.QTY * sd.UNIT_PRICE), 2) as total_spent,
                    COUNT(DISTINCT sd.SALES_ID) as purchase_frequency,
                    MAX(sd.SALES_DATE) as last_bought_date
                FROM sales_details sd
                JOIN product p ON sd.PRODUCT_ID = p.PRODUCT_ID
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                WHERE sd.CS_ID = %s
                GROUP BY sd.PRODUCT_ID, p.PRODUCT_NAME, category_name
                ORDER BY total_spent DESC
            """, (customer_id,))
            products = cur.fetchall()
            total_client_spent = sum(float(p.get("total_spent") or 0) for p in products)
            total_client_units = sum(int(p.get("qty_bought") or 0) for p in products)
            category_summary: Dict[str, float] = {}
            for p in products:
                clean_record(p)
                cat = str(p.get("category_name") or "General")
                amt = float(p.get("total_spent") or 0)
                category_summary[cat] = category_summary.get(cat, 0.0) + amt
                p["qty_bought"] = int(p.get("qty_bought") or 0)
                p["total_spent"] = float(p.get("total_spent") or 0)
                p["avg_unit_price"] = float(p.get("avg_unit_price") or 0)
                p["purchase_frequency"] = int(p.get("purchase_frequency") or 0)
                p["last_bought_formatted"] = format_date(p.get("last_bought_date"))
                p["basket_share_pct"] = round((p["total_spent"] / total_client_spent * 100), 1) if total_client_spent > 0 else 0
            category_list = [
                {"category": k, "amount": round(v, 2), "pct": round(v / total_client_spent * 100, 1) if total_client_spent > 0 else 0}
                for k, v in sorted(category_summary.items(), key=lambda x: x[1], reverse=True)
            ]
            return {
                "customer": {
                    "id": cust.get("CS_ID"),
                    "name": cust.get("CS_NAME") or "Direct Client",
                    "mobile": cust.get("MOBILE") or "-",
                    "address": cust.get("ADDRESS") or "-",
                    "total_spent": round(total_client_spent, 2),
                    "total_units": total_client_units,
                    "products_count": len(products),
                },
                "category_affinity": category_list,
                "products": products,
            }

def get_product_customer_affinity(product_id: str) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.PRODUCT_ID, p.PRODUCT_NAME, COALESCE(c.CATEGORY_NAME, 'General') as category_name, p.SALES_PRICE
                FROM product p
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                WHERE p.PRODUCT_ID = %s
            """, (product_id,))
            prod = cur.fetchone()
            if not prod:
                return {}
            clean_record(prod)
            cur.execute("""
                SELECT
                    agg.customer_id,
                    COALESCE(c.CS_NAME, 'Direct Client') as customer_name,
                    COALESCE(c.MOBILE, '-') as mobile,
                    COALESCE(c.ADDRESS, '-') as address,
                    agg.qty_bought, agg.total_spent, agg.orders_count, agg.last_purchase_date
                FROM (
                    SELECT CS_ID as customer_id,
                        ROUND(SUM(QTY), 0) as qty_bought,
                        ROUND(SUM(QTY * UNIT_PRICE), 2) as total_spent,
                        COUNT(DISTINCT SALES_ID) as orders_count,
                        MAX(SALES_DATE) as last_purchase_date
                    FROM sales_details
                    WHERE PRODUCT_ID = %s AND CS_ID IS NOT NULL AND CS_ID != ''
                    GROUP BY CS_ID ORDER BY total_spent DESC LIMIT 50
                ) agg
                LEFT JOIN cs c ON agg.customer_id = c.CS_ID
            """, (product_id,))
            customers = cur.fetchall()
            total_units = sum(int(c.get("qty_bought") or 0) for c in customers)
            total_amt = sum(float(c.get("total_spent") or 0) for c in customers)
            for c in customers:
                clean_record(c)
                c["qty_bought"] = int(c.get("qty_bought") or 0)
                c["total_spent"] = float(c.get("total_spent") or 0)
                c["orders_count"] = int(c.get("orders_count") or 0)
                c["last_purchase_formatted"] = format_date(c.get("last_purchase_date"))
            return {
                "product_id": prod["PRODUCT_ID"],
                "product_name": prod["PRODUCT_NAME"],
                "category_name": prod.get("category_name", "General"),
                "total_units_sold": total_units,
                "total_revenue": round(total_amt, 2),
                "unique_buyers": len(customers),
                "customers": customers,
            }

def get_customers_dropdown() -> List[Dict[str, str]]:
    now = time.time()
    if _LIST_CACHE["data"] is not None and _LIST_CACHE.get("limit") is not None and (now - _LIST_CACHE["ts"]) < _LIST_TTL:
        # Derive dropdown from cached list (avoids second full scan)
        return [{"id": r["customer_id"], "name": f'{r["customer_name"]} ({r["customer_id"]})'} for r in _LIST_CACHE["data"][:200]]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT agg.customer_id as id,
                    CONCAT(COALESCE(c.CS_NAME, 'Client'), ' (', agg.customer_id, ')') as name
                FROM (
                    SELECT CS_ID as customer_id
                    FROM sales_details
                    WHERE CS_ID IS NOT NULL AND CS_ID != ''
                    GROUP BY CS_ID
                    ORDER BY SUM(QTY * UNIT_PRICE) DESC
                    LIMIT 200
                ) agg
                LEFT JOIN cs c ON agg.customer_id = c.CS_ID
            """)
            rows = cur.fetchall()
            for r in rows:
                clean_record(r)
            return rows

get_customer_affinity_overview = get_affinity_overview
get_customer_dropdown_list = get_customers_dropdown
