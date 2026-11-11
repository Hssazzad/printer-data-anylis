from typing import Dict, Any, List
import time
from .connection import get_connection

_KPIS_CACHE: Dict[str, Any] = {"data": None, "ts": 0}
_TREND_CACHE: Dict[str, Any] = {"data": None, "ts": 0, "months": None}
_TOPP_CACHE: Dict[str, Any] = {"data": None, "ts": 0, "limit": None}
_RECENT_CACHE: Dict[str, Any] = {"data": None, "ts": 0, "limit": None}
_INV_CACHE: Dict[str, Any] = {"data": None, "ts": 0, "limit": None}
_TOPC_CACHE: Dict[str, Any] = {"data": None, "ts": 0, "limit": None}
_TTL = 60

def clear_analytics_cache():
    for c in (_KPIS_CACHE, _TREND_CACHE, _TOPP_CACHE, _RECENT_CACHE, _INV_CACHE, _TOPC_CACHE):
        c["data"] = None

def get_dashboard_kpis() -> Dict[str, Any]:
    now = time.time()
    if _KPIS_CACHE["data"] and (now - _KPIS_CACHE["ts"]) < _TTL:
        return _KPIS_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Sales stats
            cur.execute("""
                SELECT 
                    COUNT(*) as total_invoices,
                    COALESCE(SUM(NET_SALES), 0) as total_revenue,
                    COALESCE(AVG(NET_SALES), 0) as avg_order_value
                FROM sales
            """)
            sales_stats = cur.fetchone() or {}

            # Product count
            cur.execute("SELECT COUNT(*) as total_products FROM product")
            prod_stats = cur.fetchone() or {}

            # Customer count
            cur.execute("SELECT COUNT(*) as total_customers FROM cs")
            cs_stats = cur.fetchone() or {}

            # Stock stats
            cur.execute("""
                SELECT 
                    COALESCE(SUM(STOCK_QTY), 0) as total_stock_qty,
                    COALESCE(SUM(STOCK_AMT), 0) as total_stock_value,
                    COUNT(DISTINCT PRODUCT_ID) as stocked_products_count
                FROM stock_non_serial
            """)
            stock_stats = cur.fetchone() or {}

            # Latest day sales
            cur.execute("""
                SELECT 
                    COUNT(*) as today_sales_count,
                    COALESCE(SUM(NET_SALES), 0) as today_revenue
                FROM sales 
                WHERE DATE(SALES_DATE) = (SELECT DATE(MAX(SALES_DATE)) FROM sales)
            """)
            latest_day_sales = cur.fetchone() or {}

            data = {
                "total_revenue": float(sales_stats.get("total_revenue", 0)),
                "total_invoices": int(sales_stats.get("total_invoices", 0)),
                "avg_order_value": float(sales_stats.get("avg_order_value", 0)),
                "total_products": int(prod_stats.get("total_products", 0)),
                "total_customers": int(cs_stats.get("total_customers", 0)),
                "total_stock_qty": float(stock_stats.get("total_stock_qty", 0)),
                "total_stock_value": float(stock_stats.get("total_stock_value", 0)),
                "stocked_products_count": int(stock_stats.get("stocked_products_count", 0)),
                "latest_day_invoices": int(latest_day_sales.get("today_sales_count", 0)),
                "latest_day_revenue": float(latest_day_sales.get("today_revenue", 0)),
            }
            _KPIS_CACHE.update(data=data, ts=now)
            return data

def get_monthly_sales_trend(months: int = 12) -> List[Dict[str, Any]]:
    months = int(months)
    now = time.time()
    if _TREND_CACHE["data"] is not None and _TREND_CACHE.get("months") == months and (now - _TREND_CACHE["ts"]) < _TTL:
        return _TREND_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT 
                    LEFT(SALES_DATE, 7) as ym,
                    COUNT(*) as invoices,
                    ROUND(SUM(NET_SALES), 2) as revenue
                FROM sales
                WHERE SALES_DATE IS NOT NULL
                GROUP BY ym
                ORDER BY ym DESC
                LIMIT {int(months)}
            """)
            rows = cur.fetchall()
            result = []
            for r in reversed(rows):
                ym = r["ym"] or ""
                label = ym
                if len(ym) == 7:
                    parts = ym.split("-")
                    months_map = {"01":"Jan", "02":"Feb", "03":"Mar", "04":"Apr", "05":"May", "06":"Jun", 
                                  "07":"Jul", "08":"Aug", "09":"Sep", "10":"Oct", "11":"Nov", "12":"Dec"}
                    label = f"{months_map.get(parts[1], parts[1])} {parts[0]}"
                result.append({
                    "year_month": ym,
                    "month_label": label,
                    "invoices": int(r["invoices"]),
                    "revenue": float(r["revenue"] or 0),
                })
            _TREND_CACHE.update(data=result, ts=now, months=months)
            return result

def get_top_selling_products(limit: int = 6) -> List[Dict[str, Any]]:
    limit = int(limit)
    now = time.time()
    if _TOPP_CACHE["data"] is not None and _TOPP_CACHE.get("limit") == limit and (now - _TOPP_CACHE["ts"]) < _TTL:
        return _TOPP_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Aggregate first on sales_details (index-only), join product/category only for top-N
            cur.execute(f"""
                SELECT
                    agg.PRODUCT_ID,
                    p.PRODUCT_NAME,
                    COALESCE(c.CATEGORY_NAME, 'Printing Item') as category_name,
                    agg.total_qty_sold,
                    agg.total_sales_amt
                FROM (
                    SELECT PRODUCT_ID,
                        ROUND(SUM(QTY), 0) as total_qty_sold,
                        ROUND(SUM(QTY * UNIT_PRICE), 2) as total_sales_amt
                    FROM sales_details
                    GROUP BY PRODUCT_ID
                    ORDER BY total_sales_amt DESC
                    LIMIT {limit}
                ) agg
                JOIN product p ON agg.PRODUCT_ID = p.PRODUCT_ID
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
            """)
            rows = cur.fetchall()
            for r in rows:
                r["total_qty_sold"] = int(r["total_qty_sold"] or 0)
                r["total_sales_amt"] = float(r["total_sales_amt"] or 0)
            _TOPP_CACHE.update(data=rows, ts=now, limit=limit)
            return rows

def get_recent_invoices(limit: int = 8) -> List[Dict[str, Any]]:
    limit = int(limit)
    now = time.time()
    if _RECENT_CACHE["data"] is not None and _RECENT_CACHE.get("limit") == limit and (now - _RECENT_CACHE["ts"]) < _TTL:
        return _RECENT_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT 
                    s.SALES_ID,
                    s.SALES_DATE,
                    COALESCE(c.CS_NAME, s.CASH_CS_NAME, 'Cash Customer') as customer_name,
                    COALESCE(c.MOBILE, s.MOBILE, '-') as customer_phone,
                    ROUND(s.TOTAL_PRICE, 2) as total_price,
                    ROUND(s.NET_SALES, 2) as net_sales,
                    s.PAY_STATUS
                FROM sales s
                LEFT JOIN cs c ON s.CS_ID = c.CS_ID
                ORDER BY s.SALES_DATE DESC
                LIMIT {int(limit)}
            """)
            rows = cur.fetchall()
            for r in rows:
                dt = r.get("SALES_DATE")
                if dt and hasattr(dt, "strftime"):
                    r["sales_date_formatted"] = dt.strftime("%d %b %Y, %I:%M %p")
                else:
                    r["sales_date_formatted"] = str(dt or "-")
                del r["SALES_DATE"]
                r["total_price"] = float(r["total_price"] or 0)
                r["net_sales"] = float(r["net_sales"] or 0)
            _RECENT_CACHE.update(data=rows, ts=now, limit=limit)
            return rows

def get_inventory_summary(limit: int = 8) -> List[Dict[str, Any]]:
    limit = int(limit)
    now = time.time()
    if _INV_CACHE["data"] is not None and _INV_CACHE.get("limit") == limit and (now - _INV_CACHE["ts"]) < _TTL:
        return _INV_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT 
                    p.PRODUCT_ID,
                    p.PRODUCT_NAME,
                    COALESCE(c.CATEGORY_NAME, 'General') as category,
                    COALESCE(p.SALES_PRICE, 0) as sales_price,
                    COALESCE(SUM(s.STOCK_QTY), 0) as current_stock,
                    ROUND(COALESCE(SUM(s.STOCK_AMT), 0), 2) as stock_valuation
                FROM product p
                LEFT JOIN stock_non_serial s ON p.PRODUCT_ID = s.PRODUCT_ID
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                GROUP BY p.PRODUCT_ID, p.PRODUCT_NAME, c.CATEGORY_NAME, p.SALES_PRICE
                ORDER BY current_stock DESC
                LIMIT {int(limit)}
            """)
            rows = cur.fetchall()
            for r in rows:
                r["current_stock"] = float(r["current_stock"] or 0)
                r["stock_valuation"] = float(r["stock_valuation"] or 0)
                r["sales_price"] = float(r["sales_price"] or 0)
            _INV_CACHE.update(data=rows, ts=now, limit=limit)
            return rows

def get_top_customers(limit: int = 6) -> List[Dict[str, Any]]:
    limit = int(limit)
    now = time.time()
    if _TOPC_CACHE["data"] is not None and _TOPC_CACHE.get("limit") == limit and (now - _TOPC_CACHE["ts"]) < _TTL:
        return _TOPC_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT 
                    c.CS_ID,
                    c.CS_NAME,
                    COALESCE(c.MOBILE, '-') as mobile,
                    COALESCE(c.ADDRESS, '-') as address,
                    COUNT(s.SALES_ID) as order_count,
                    ROUND(SUM(s.NET_SALES), 2) as total_purchased
                FROM sales s
                JOIN cs c ON s.CS_ID = c.CS_ID
                GROUP BY c.CS_ID, c.CS_NAME, c.MOBILE, c.ADDRESS
                ORDER BY total_purchased DESC
                LIMIT {int(limit)}
            """)
            rows = cur.fetchall()
            for r in rows:
                r["total_purchased"] = float(r["total_purchased"] or 0)
                r["order_count"] = int(r["order_count"] or 0)
            _TOPC_CACHE.update(data=rows, ts=now, limit=limit)
            return rows
