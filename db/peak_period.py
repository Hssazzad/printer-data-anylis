from typing import Dict, Any, List
import time
from .connection import get_connection

_TIMING_CACHE: Dict[str, Any] = {"data": None, "ts": 0}
_RANKING_CACHE: Dict[str, Any] = {"data": None, "ts": 0, "limit": None}
_LIST_CACHE: Dict[str, Any] = {"data": None, "ts": 0}
_CAT_CACHE: Dict[str, Any] = {"data": None, "ts": 0}
_TTL = 60

def clear_peak_cache():
    _TIMING_CACHE["data"] = None
    _RANKING_CACHE["data"] = None
    _LIST_CACHE["data"] = None
    _CAT_CACHE["data"] = None

MONTHS_MAP = {
    "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun",
    "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"
}

def format_ym(ym_str: str) -> str:
    if not ym_str or len(ym_str) < 7:
        return ym_str or "-"
    parts = ym_str.split("-")
    return f"{MONTHS_MAP.get(parts[1], parts[1])} {parts[0]}"

def get_peak_timing_summary() -> Dict[str, Any]:
    now = time.time()
    if _TIMING_CACHE["data"] and (now - _TIMING_CACHE["ts"]) < _TTL:
        return _TIMING_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Day of week distribution
            cur.execute("""
                SELECT 
                    DAYNAME(SALES_DATE) as day_name, 
                    DAYOFWEEK(SALES_DATE) as dow, 
                    COUNT(*) as invoices, 
                    ROUND(SUM(NET_SALES), 2) as revenue 
                FROM sales 
                WHERE SALES_DATE IS NOT NULL 
                GROUP BY day_name, dow 
                ORDER BY dow
            """)
            dow_rows = cur.fetchall()
            for r in dow_rows:
                r["invoices"] = int(r["invoices"])
                r["revenue"] = float(r["revenue"] or 0)

            peak_day = max(dow_rows, key=lambda x: x["revenue"]) if dow_rows else {}

            # 2. Hourly distribution
            cur.execute("""
                SELECT 
                    HOUR(SALES_DATE) as hr, 
                    COUNT(*) as invoices, 
                    ROUND(SUM(NET_SALES), 2) as revenue 
                FROM sales 
                WHERE SALES_DATE IS NOT NULL 
                GROUP BY hr 
                ORDER BY hr
            """)
            hour_rows = cur.fetchall()
            for r in hour_rows:
                h = int(r["hr"])
                period = "AM" if h < 12 else "PM"
                h_12 = h if h <= 12 else h - 12
                if h_12 == 0:
                    h_12 = 12
                r["hr_label"] = f"{h_12}:00 {period}"
                r["invoices"] = int(r["invoices"])
                r["revenue"] = float(r["revenue"] or 0)

            peak_hour = max(hour_rows, key=lambda x: x["invoices"]) if hour_rows else {}

            # 3. Monthly distribution
            cur.execute("""
                SELECT 
                    LEFT(SALES_DATE, 7) as ym,
                    COUNT(*) as invoices,
                    ROUND(SUM(NET_SALES), 2) as revenue
                FROM sales
                WHERE SALES_DATE IS NOT NULL
                GROUP BY ym
                ORDER BY ym ASC
            """)
            month_rows = cur.fetchall()
            for r in month_rows:
                r["month_label"] = format_ym(r["ym"])
                r["invoices"] = int(r["invoices"])
                r["revenue"] = float(r["revenue"] or 0)

            peak_month = max(month_rows, key=lambda x: x["revenue"]) if month_rows else {}

            data = {
                "day_distribution": dow_rows,
                "hour_distribution": hour_rows,
                "month_distribution": month_rows,
                "peak_day": peak_day,
                "peak_hour": peak_hour,
                "peak_month": peak_month,
            }
            _TIMING_CACHE.update(data=data, ts=now)
            return data

def get_products_peak_ranking(limit: int = 1500) -> List[Dict[str, Any]]:
    limit = int(limit)
    now = time.time()
    if _RANKING_CACHE["data"] is not None and _RANKING_CACHE.get("limit") == limit and (now - _RANKING_CACHE["ts"]) < _TTL:
        return _RANKING_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Product metadata + Current Stock for ALL products
            cur.execute("""
                SELECT 
                    p.PRODUCT_ID,
                    p.PRODUCT_NAME,
                    COALESCE(c.CATEGORY_NAME, 'General') as category_name,
                    COALESCE(p.SALES_PRICE, 0) as sales_price,
                    COALESCE(st.stock_qty, 0) as current_stock
                FROM product p
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                LEFT JOIN (
                    SELECT PRODUCT_ID, SUM(STOCK_QTY) as stock_qty 
                    FROM stock_non_serial 
                    GROUP BY PRODUCT_ID
                ) st ON p.PRODUCT_ID = st.PRODUCT_ID
            """)
            prod_meta = {r["PRODUCT_ID"]: r for r in cur.fetchall()}

            # 2. Monthly aggregates per product
            cur.execute("""
                SELECT 
                    sd.PRODUCT_ID,
                    LEFT(sd.SALES_DATE, 7) as ym,
                    ROUND(SUM(sd.QTY), 0) as month_qty,
                    ROUND(SUM(sd.QTY * sd.UNIT_PRICE), 2) as month_sales
                FROM sales_details sd
                WHERE sd.SALES_DATE IS NOT NULL
                GROUP BY sd.PRODUCT_ID, ym
            """)
            monthly_data = cur.fetchall()

    by_product = {}
    for row in monthly_data:
        pid = row["PRODUCT_ID"]
        if pid not in by_product:
            by_product[pid] = {
                "months": [],
                "total_qty": 0,
                "total_sales": 0,
            }
        mqty = float(row["month_qty"] or 0)
        msales = float(row["month_sales"] or 0)
        by_product[pid]["months"].append({
            "ym": row["ym"],
            "month_label": format_ym(row["ym"]),
            "qty": mqty,
            "sales": msales,
        })
        by_product[pid]["total_qty"] += mqty
        by_product[pid]["total_sales"] += msales

    results = []
    for pid, meta in prod_meta.items():
        data = by_product.get(pid)
        current_stock = float(meta["current_stock"])

        if not data or not data["months"]:
            # Products with 0 recorded sales yet
            results.append({
                "product_id": pid,
                "product_name": meta["PRODUCT_NAME"],
                "category_name": meta["category_name"],
                "sales_price": float(meta["sales_price"]),
                "total_qty_sold": 0,
                "total_sales_amt": 0.0,
                "peak_qty_month": "-",
                "peak_qty_month_label": "-",
                "peak_qty_val": 0,
                "lowest_qty_month_label": "-",
                "lowest_qty_val": 0,
                "avg_monthly_qty": 0.0,
                "surge_qty_pct": 0.0,
                "peak_sales_month": "-",
                "peak_sales_month_label": "-",
                "peak_sales_val": 0.0,
                "lowest_sales_month_label": "-",
                "lowest_sales_val": 0.0,
                "avg_monthly_sales": 0.0,
                "surge_sales_pct": 0.0,
                "current_stock": int(current_stock),
                "stock_status": "Out of Stock" if current_stock == 0 else "In Stock (No Sales)",
                "badge_color": "slate",
            })
            continue

        months_list = data["months"]
        sorted_by_qty = sorted(months_list, key=lambda x: x["qty"], reverse=True)
        peak_qty_item = sorted_by_qty[0]
        lowest_qty_item = sorted_by_qty[-1]

        sorted_by_sales = sorted(months_list, key=lambda x: x["sales"], reverse=True)
        peak_sales_item = sorted_by_sales[0]
        lowest_sales_item = sorted_by_sales[-1]

        active_months = len(months_list)
        avg_monthly_qty = round(data["total_qty"] / active_months, 1) if active_months > 0 else 0
        surge_qty_pct = round(((peak_qty_item["qty"] - avg_monthly_qty) / avg_monthly_qty) * 100, 1) if avg_monthly_qty > 0 else 0

        avg_monthly_sales = round(data["total_sales"] / active_months, 2) if active_months > 0 else 0
        surge_sales_pct = round(((peak_sales_item["sales"] - avg_monthly_sales) / avg_monthly_sales) * 100, 1) if avg_monthly_sales > 0 else 0

        if current_stock == 0:
            stock_status = "Out of Stock"
            badge_color = "rose"
        elif current_stock < (peak_qty_item["qty"] * 0.3):
            stock_status = "Low Stock"
            badge_color = "amber"
        else:
            stock_status = "In Stock"
            badge_color = "emerald"

        results.append({
            "product_id": pid,
            "product_name": meta["PRODUCT_NAME"],
            "category_name": meta["category_name"],
            "sales_price": float(meta["sales_price"]),
            "total_qty_sold": int(data["total_qty"]),
            "total_sales_amt": round(data["total_sales"], 2),
            "peak_qty_month": peak_qty_item["ym"],
            "peak_qty_month_label": peak_qty_item["month_label"],
            "peak_qty_val": int(peak_qty_item["qty"]),
            "lowest_qty_month_label": lowest_qty_item["month_label"],
            "lowest_qty_val": int(lowest_qty_item["qty"]),
            "avg_monthly_qty": avg_monthly_qty,
            "surge_qty_pct": surge_qty_pct,
            "peak_sales_month": peak_sales_item["ym"],
            "peak_sales_month_label": peak_sales_item["month_label"],
            "peak_sales_val": round(peak_sales_item["sales"], 2),
            "lowest_sales_month_label": lowest_sales_item["month_label"],
            "lowest_sales_val": round(lowest_sales_item["sales"], 2),
            "avg_monthly_sales": avg_monthly_sales,
            "surge_sales_pct": surge_sales_pct,
            "current_stock": int(current_stock),
            "stock_status": stock_status,
            "badge_color": badge_color,
        })

    # Sort so top sellers come first, followed by zero-sales items
    results.sort(key=lambda x: (x["total_sales_amt"] > 0, x["total_sales_amt"]), reverse=True)
    sliced = results[:limit]
    _RANKING_CACHE.update(data=sliced, ts=now, limit=limit)
    return sliced

def get_product_peak_detail(product_id: str) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    p.PRODUCT_ID,
                    p.PRODUCT_NAME,
                    COALESCE(c.CATEGORY_NAME, 'General') as category_name,
                    COALESCE(b.BRAND_NAME, 'General') as brand_name,
                    COALESCE(p.SALES_PRICE, 0) as sales_price,
                    COALESCE(st.stock_qty, 0) as current_stock
                FROM product p
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                LEFT JOIN brand b ON p.BRAND_ID = b.BRAND_ID
                LEFT JOIN (
                    SELECT PRODUCT_ID, SUM(STOCK_QTY) as stock_qty 
                    FROM stock_non_serial 
                    WHERE PRODUCT_ID = %s
                    GROUP BY PRODUCT_ID
                ) st ON p.PRODUCT_ID = st.PRODUCT_ID
                WHERE p.PRODUCT_ID = %s
            """, (product_id, product_id))
            prod = cur.fetchone()
            if not prod:
                return {}

            cur.execute("""
                SELECT 
                    LEFT(SALES_DATE, 7) as ym,
                    COUNT(DISTINCT SALES_ID) as orders_count,
                    ROUND(SUM(QTY), 0) as qty,
                    ROUND(SUM(QTY * UNIT_PRICE), 2) as sales
                FROM sales_details
                WHERE PRODUCT_ID = %s AND SALES_DATE IS NOT NULL
                GROUP BY ym
                ORDER BY ym ASC
            """, (product_id,))
            monthly_rows = cur.fetchall()

    history = []
    total_qty = 0
    total_sales = 0
    for r in monthly_rows:
        mqty = float(r["qty"] or 0)
        msales = float(r["sales"] or 0)
        total_qty += mqty
        total_sales += msales
        history.append({
            "ym": r["ym"],
            "month_label": format_ym(r["ym"]),
            "orders_count": int(r["orders_count"]),
            "qty": int(mqty),
            "sales": msales,
        })

    peak_qty_item = max(history, key=lambda x: x["qty"]) if history else {}
    lowest_qty_item = min(history, key=lambda x: x["qty"]) if history else {}
    avg_qty = round(total_qty / len(history), 1) if history else 0
    surge_qty_pct = round(((peak_qty_item.get("qty", 0) - avg_qty) / avg_qty) * 100, 1) if avg_qty > 0 else 0

    peak_sales_item = max(history, key=lambda x: x["sales"]) if history else {}
    lowest_sales_item = min(history, key=lambda x: x["sales"]) if history else {}
    avg_sales = round(total_sales / len(history), 2) if history else 0
    surge_sales_pct = round(((peak_sales_item.get("sales", 0) - avg_sales) / avg_sales) * 100, 1) if avg_sales > 0 else 0

    return {
        "product_id": prod["PRODUCT_ID"],
        "product_name": prod["PRODUCT_NAME"],
        "category_name": prod["category_name"],
        "brand_name": prod["brand_name"],
        "sales_price": float(prod["sales_price"]),
        "current_stock": int(prod["current_stock"]),
        "total_qty_sold": int(total_qty),
        "total_sales_amt": round(total_sales, 2),
        "peak_qty_month": peak_qty_item.get("month_label", "-"),
        "peak_qty": peak_qty_item.get("qty", 0),
        "lowest_qty_month": lowest_qty_item.get("month_label", "-"),
        "lowest_qty": lowest_qty_item.get("qty", 0),
        "avg_monthly_qty": avg_qty,
        "surge_qty_pct": surge_qty_pct,
        "peak_sales_month": peak_sales_item.get("month_label", "-"),
        "peak_sales": peak_sales_item.get("sales", 0),
        "lowest_sales_month": lowest_sales_item.get("month_label", "-"),
        "lowest_sales": lowest_sales_item.get("sales", 0),
        "avg_monthly_sales": avg_sales,
        "surge_sales_pct": surge_sales_pct,
        "monthly_history": history,
    }

def get_products_dropdown_list() -> List[Dict[str, str]]:
    """Return all catalog products alphabetically for single-product explorer dropdown."""
    now = time.time()
    if _LIST_CACHE["data"] and (now - _LIST_CACHE["ts"]) < _TTL:
        return _LIST_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    p.PRODUCT_ID as id,
                    p.PRODUCT_NAME as name,
                    COALESCE(c.CATEGORY_NAME, 'General') as category
                FROM product p
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                ORDER BY p.PRODUCT_NAME ASC
            """)
            rows = cur.fetchall()
            _LIST_CACHE.update(data=rows, ts=now)
            return rows

def get_categories_list() -> List[str]:
    """Return distinct active product categories for UI filter tabs."""
    now = time.time()
    if _CAT_CACHE["data"] and (now - _CAT_CACHE["ts"]) < _TTL:
        return _CAT_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT COALESCE(c.CATEGORY_NAME, 'General') as cat 
                FROM product p 
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                ORDER BY cat ASC
            """)
            rows = cur.fetchall()
            cats = [r["cat"] for r in rows if r.get("cat")]
            _CAT_CACHE.update(data=cats, ts=now)
            return cats
