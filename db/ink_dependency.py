from typing import Dict, Any, List, Optional
from datetime import date, datetime
from decimal import Decimal
import time
from .connection import get_connection

_OVERVIEW_CACHE: Dict[str, Any] = {"data": None, "ts": 0}
_PRINTERS_CACHE: Dict[str, Any] = {"data": None, "ts": 0}
_INKS_CACHE: Dict[str, Any] = {"data": None, "ts": 0}
_REFILL_CACHE: Dict[str, Any] = {"data": None, "ts": 0}
_TTL = 60

def clear_ink_cache():
    for c in (_OVERVIEW_CACHE, _PRINTERS_CACHE, _INKS_CACHE, _REFILL_CACHE):
        c["data"] = None

def format_date(dt) -> str:
    if not dt:
        return "-"
    if isinstance(dt, (date, datetime)):
        return dt.strftime("%d %b %Y")
    return str(dt)

def extract_color(name: str) -> Dict[str, str]:
    """Detect ink/toner color from product name."""
    n = name.upper()
    if "CYAN" in n or " (C)" in n:
        return {"color": "Cyan", "badge": "bg-sky-50 text-sky-700 border-sky-300", "dot": "#0ea5e9"}
    elif "MAGENTA" in n or " (M)" in n:
        return {"color": "Magenta", "badge": "bg-pink-50 text-pink-700 border-pink-300", "dot": "#ec4899"}
    elif "YELLOW" in n or " (Y)" in n:
        return {"color": "Yellow", "badge": "bg-amber-50 text-amber-700 border-amber-300", "dot": "#eab308"}
    elif "BLACK" in n or "(BK)" in n or " BK" in n or "BH7" in n or "810" in n:
        return {"color": "Black", "badge": "bg-slate-900 text-white border-slate-700", "dot": "#0f172a"}
    elif "COLOR" in n or "CH7" in n or "811" in n or "TRI-COLOR" in n:
        return {"color": "Color (CMY)", "badge": "bg-purple-50 text-purple-700 border-purple-300", "dot": "#a855f7"}
    elif "790" in n or "003" in n or "664" in n or "057" in n or "BOTTLE" in n:
        return {"color": "Ink Bottle", "badge": "bg-blue-50 text-blue-700 border-blue-300", "dot": "#3b82f6"}
    else:
        return {"color": "Black (Mono)", "badge": "bg-slate-100 text-slate-700 border-slate-300", "dot": "#475569"}

def clean_record(d: Any) -> Any:
    """Ensure all values in a record are standard JSON-serializable types."""
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

def get_ink_dependency_overview() -> Dict[str, Any]:
    """Overview KPIs for Printer & Ink Synergy module."""
    now = time.time()
    if _OVERVIEW_CACHE["data"] and (now - _OVERVIEW_CACHE["ts"]) < _TTL:
        return _OVERVIEW_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Total printer models
            cur.execute("""
                SELECT COUNT(DISTINCT PRODUCT_ID) as total_printers
                FROM product
                WHERE CATEGORY_ID = 'CAT006' OR PRODUCT_NAME LIKE '%PRINTER%'
            """)
            printers_count = cur.fetchone().get("total_printers") or 0

            # 2. Total ink / toner / consumable items
            cur.execute("""
                SELECT COUNT(DISTINCT PRODUCT_ID) as total_consumables
                FROM product
                WHERE PRODUCT_NAME LIKE '%TONER%' 
                   OR PRODUCT_NAME LIKE '%INK%' 
                   OR PRODUCT_NAME LIKE '%CARTRIDGE%' 
                   OR PRODUCT_NAME LIKE '%RIBBON%'
            """)
            consumables_count = cur.fetchone().get("total_consumables") or 0

            # 3. Synergy rate: % of printer buyers who also purchase consumables
            # (Two indexed COUNT DISTINCTs instead of a s1 x s2 self-join fan-out)
            cur.execute("""
                SELECT COUNT(DISTINCT sd.CS_ID) as total_printer_buyers
                FROM sales_details sd
                JOIN product p ON sd.PRODUCT_ID = p.PRODUCT_ID
                WHERE (p.CATEGORY_ID = 'CAT006' OR p.PRODUCT_NAME LIKE '%PRINTER%')
                  AND sd.CS_ID IS NOT NULL AND sd.CS_ID != ''
            """)
            pb_row = cur.fetchone() or {}
            total_pb = pb_row.get("total_printer_buyers") or 0
            cur.execute("""
                SELECT COUNT(DISTINCT sd.CS_ID) as joint_buyers
                FROM sales_details sd
                JOIN product p ON sd.PRODUCT_ID = p.PRODUCT_ID
                WHERE (p.PRODUCT_NAME LIKE '%TONER%' OR p.PRODUCT_NAME LIKE '%INK%' OR p.PRODUCT_NAME LIKE '%CARTRIDGE%' OR p.PRODUCT_NAME LIKE '%RIBBON%')
                  AND sd.CS_ID IS NOT NULL AND sd.CS_ID != ''
                  AND sd.CS_ID IN (
                    SELECT DISTINCT sd2.CS_ID FROM sales_details sd2
                    JOIN product p2 ON sd2.PRODUCT_ID = p2.PRODUCT_ID
                    WHERE (p2.CATEGORY_ID = 'CAT006' OR p2.PRODUCT_NAME LIKE '%PRINTER%')
                  )
            """)
            syn = cur.fetchone() or {}
            joint_b = syn.get("joint_buyers") or 0
            if not total_pb:
                total_pb = 1
            synergy_rate = round((joint_b / total_pb * 100), 1) if total_pb > 0 else 0

            # 4. Total consumable volume sold
            cur.execute("""
                SELECT 
                    ROUND(SUM(sd.QTY), 0) as total_units,
                    ROUND(SUM(sd.QTY * sd.UNIT_PRICE), 2) as total_revenue
                FROM sales_details sd
                JOIN product p ON sd.PRODUCT_ID = p.PRODUCT_ID
                WHERE p.PRODUCT_NAME LIKE '%TONER%' 
                   OR p.PRODUCT_NAME LIKE '%INK%' 
                   OR p.PRODUCT_NAME LIKE '%CARTRIDGE%' 
                   OR p.PRODUCT_NAME LIKE '%RIBBON%'
            """)
            ink_sales = cur.fetchone() or {}

            data = {
                "total_printers": int(printers_count),
                "total_consumables": int(consumables_count),
                "synergy_rate": float(synergy_rate),
                "total_ink_units_sold": int(ink_sales.get("total_units") or 0),
                "total_ink_revenue": float(ink_sales.get("total_revenue") or 0),
            }
            _OVERVIEW_CACHE.update(data=data, ts=now)
            return data

def get_printer_models_list() -> List[Dict[str, Any]]:
    """List of all printers with active sales and owner metrics."""
    now = time.time()
    if _PRINTERS_CACHE["data"] and (now - _PRINTERS_CACHE["ts"]) < _TTL:
        return _PRINTERS_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    p.PRODUCT_ID as product_id,
                    p.PRODUCT_NAME as product_name,
                    COALESCE(c.CATEGORY_NAME, 'PRINTER') as category_name,
                    COALESCE(st.stock_qty, 0) as current_stock,
                    COALESCE(p.SALES_PRICE, 0) as sales_price,
                    COUNT(DISTINCT sd.SALES_ID) as sales_count,
                    COALESCE(SUM(sd.QTY), 0) as total_units_sold,
                    COUNT(DISTINCT sd.CS_ID) as unique_owners
                FROM product p
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                LEFT JOIN (
                    SELECT PRODUCT_ID, SUM(STOCK_QTY) as stock_qty 
                    FROM stock_non_serial 
                    GROUP BY PRODUCT_ID
                ) st ON p.PRODUCT_ID = st.PRODUCT_ID
                LEFT JOIN sales_details sd ON p.PRODUCT_ID = sd.PRODUCT_ID
                WHERE p.CATEGORY_ID = 'CAT006' OR p.PRODUCT_NAME LIKE '%PRINTER%'
                GROUP BY p.PRODUCT_ID, p.PRODUCT_NAME, category_name, st.stock_qty, p.SALES_PRICE
                ORDER BY total_units_sold DESC, sales_count DESC
            """)
            rows = cur.fetchall()
            for r in rows:
                clean_record(r)
                r["total_units_sold"] = int(r["total_units_sold"] or 0)
                r["sales_count"] = int(r["sales_count"] or 0)
                r["unique_owners"] = int(r["unique_owners"] or 0)
                r["current_stock"] = int(r["current_stock"] or 0)
                r["sales_price"] = float(r["sales_price"] or 0)
                # Brand extraction
                name_upper = r["product_name"].upper()
                if "EPSON" in name_upper:
                    r["brand"] = "Epson"
                elif "CANON" in name_upper:
                    r["brand"] = "Canon"
                elif "HP" in name_upper:
                    r["brand"] = "HP"
                elif "BROTHER" in name_upper:
                    r["brand"] = "Brother"
                elif "PANTUM" in name_upper:
                    r["brand"] = "Pantum"
                else:
                    r["brand"] = "Other"
            _PRINTERS_CACHE.update(data=rows, ts=now)
            return rows

def get_ink_products_list() -> List[Dict[str, Any]]:
    """List of all consumable toners and inks with sales performance."""
    now = time.time()
    if _INKS_CACHE["data"] and (now - _INKS_CACHE["ts"]) < _TTL:
        return _INKS_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    p.PRODUCT_ID as product_id,
                    p.PRODUCT_NAME as product_name,
                    COALESCE(c.CATEGORY_NAME, 'Consumable') as category_name,
                    COALESCE(st.stock_qty, 0) as current_stock,
                    COALESCE(p.SALES_PRICE, 0) as sales_price,
                    COUNT(DISTINCT sd.SALES_ID) as orders_count,
                    COALESCE(SUM(sd.QTY), 0) as total_units_sold,
                    ROUND(COALESCE(SUM(sd.QTY * sd.UNIT_PRICE), 0), 2) as total_revenue,
                    COUNT(DISTINCT sd.CS_ID) as unique_buyers
                FROM product p
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                LEFT JOIN (
                    SELECT PRODUCT_ID, SUM(STOCK_QTY) as stock_qty 
                    FROM stock_non_serial 
                    GROUP BY PRODUCT_ID
                ) st ON p.PRODUCT_ID = st.PRODUCT_ID
                LEFT JOIN sales_details sd ON p.PRODUCT_ID = sd.PRODUCT_ID
                WHERE p.PRODUCT_NAME LIKE '%TONER%' 
                   OR p.PRODUCT_NAME LIKE '%INK%' 
                   OR p.PRODUCT_NAME LIKE '%CARTRIDGE%' 
                   OR p.PRODUCT_NAME LIKE '%RIBBON%'
                GROUP BY p.PRODUCT_ID, p.PRODUCT_NAME, category_name, st.stock_qty, p.SALES_PRICE
                ORDER BY total_units_sold DESC
            """)
            rows = cur.fetchall()
            for r in rows:
                clean_record(r)
                r["total_units_sold"] = int(r["total_units_sold"] or 0)
                r["orders_count"] = int(r["orders_count"] or 0)
                r["unique_buyers"] = int(r["unique_buyers"] or 0)
                r["current_stock"] = int(r["current_stock"] or 0)
                r["sales_price"] = float(r["sales_price"] or 0)
                r["total_revenue"] = float(r["total_revenue"] or 0)
                # Type categorization
                name_upper = r["product_name"].upper()
                if "TONER" in name_upper:
                    r["ink_type"] = "Toner Cartridge"
                elif "RIBBON" in name_upper:
                    r["ink_type"] = "Ribbon"
                elif "CARTRIDGE" in name_upper:
                    r["ink_type"] = "Ink Cartridge"
                elif "BOTTLE" in name_upper or "ECOTANK" in name_upper:
                    r["ink_type"] = "Ink Bottle"
                else:
                    r["ink_type"] = "Ink/Powder"
            _INKS_CACHE.update(data=rows, ts=now)
            return rows

def get_printer_ink_matrix(printer_id: str) -> Dict[str, Any]:
    """
    Module 03 (Part A): Printer to Ink Dependent.
    For a selected printer, find all consumables bought by customers who own this printer.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Printer info
            cur.execute("""
                SELECT 
                    p.PRODUCT_ID, p.PRODUCT_NAME, COALESCE(c.CATEGORY_NAME, 'PRINTER') as CATEGORY_NAME,
                    COALESCE(st.stock_qty, 0) as current_stock, p.SALES_PRICE
                FROM product p
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                LEFT JOIN (
                    SELECT PRODUCT_ID, SUM(STOCK_QTY) as stock_qty 
                    FROM stock_non_serial 
                    WHERE PRODUCT_ID = %s
                    GROUP BY PRODUCT_ID
                ) st ON p.PRODUCT_ID = st.PRODUCT_ID
                WHERE p.PRODUCT_ID = %s
            """, (printer_id, printer_id))
            printer = cur.fetchone()
            if not printer:
                return {}
            clean_record(printer)

            # 2. Customers who bought this printer
            cur.execute("""
                SELECT 
                    COUNT(DISTINCT sd.CS_ID) as total_buyers,
                    COALESCE(SUM(sd.QTY), 0) as printer_units_sold
                FROM sales_details sd
                WHERE sd.PRODUCT_ID = %s AND sd.CS_ID IS NOT NULL AND sd.CS_ID != ''
            """, (printer_id,))
            p_stats = cur.fetchone() or {}

            # 3. Consumables bought by owners of this printer
            # (buyers CTE keeps the join set small; avoids s1 x s2 fan-out blow-up)
            cur.execute("""
                WITH buyers AS (
                    SELECT DISTINCT CS_ID FROM sales_details
                    WHERE PRODUCT_ID = %s AND CS_ID IS NOT NULL AND CS_ID != ''
                )
                SELECT
                    p2.PRODUCT_ID as ink_id,
                    p2.PRODUCT_NAME as ink_name,
                    COALESCE(c2.CATEGORY_NAME, 'Consumable') as category_name,
                    COALESCE(st2.stock_qty, 0) as warehouse_stock,
                    ROUND(AVG(s2.UNIT_PRICE), 2) as avg_price,
                    COALESCE(SUM(s2.QTY), 0) as total_units_bought,
                    ROUND(SUM(s2.QTY * s2.UNIT_PRICE), 2) as total_spent,
                    COUNT(DISTINCT s2.SALES_ID) as refill_orders_count,
                    COUNT(DISTINCT s2.CS_ID) as repeat_customers_count,
                    MAX(s2.SALES_DATE) as last_refill_date
                FROM sales_details s2
                JOIN buyers b ON s2.CS_ID = b.CS_ID
                JOIN product p2 ON s2.PRODUCT_ID = p2.PRODUCT_ID
                LEFT JOIN category c2 ON p2.CATEGORY_ID = c2.CATEGORY_ID
                LEFT JOIN (
                    SELECT PRODUCT_ID, SUM(STOCK_QTY) as stock_qty
                    FROM stock_non_serial
                    GROUP BY PRODUCT_ID
                ) st2 ON p2.PRODUCT_ID = st2.PRODUCT_ID
                WHERE s2.PRODUCT_ID != %s
                  AND p2.CATEGORY_ID != 'CAT006'
                  AND p2.PRODUCT_NAME NOT LIKE '%%PRINTER%%'
                  AND p2.PRODUCT_NAME NOT LIKE '%%SCANNER%%'
                  AND p2.PRODUCT_NAME NOT LIKE '%%IMAGECLASS%%'
                  AND p2.PRODUCT_NAME NOT LIKE '%%PHOTOCOPIER%%'
                  AND (
                    p2.PRODUCT_NAME LIKE '%%TONER%%'
                    OR p2.PRODUCT_NAME LIKE '%%INK%%'
                    OR p2.PRODUCT_NAME LIKE '%%CARTRIDGE%%'
                    OR p2.PRODUCT_NAME LIKE '%%RIBBON%%'
                    OR p2.PRODUCT_NAME LIKE '%%BOTTLE%%'
                    OR p2.PRODUCT_NAME LIKE '%%POWDER%%'
                    OR p2.PRODUCT_NAME LIKE '%%CHIP%%'
                    OR p2.PRODUCT_NAME LIKE '%%DRUM%%'
                    OR p2.PRODUCT_NAME LIKE '%%BOX%%'
                  )
                GROUP BY p2.PRODUCT_ID, p2.PRODUCT_NAME, category_name, st2.stock_qty
                ORDER BY total_units_bought DESC
                LIMIT 50
            """, (printer_id, printer_id))
            consumables = cur.fetchall()

            total_ink_spend = sum(float(c.get("total_spent") or 0) for c in consumables)
            total_ink_units = sum(int(c.get("total_units_bought") or 0) for c in consumables)

            for c in consumables:
                clean_record(c)
                c["total_units_bought"] = int(c.get("total_units_bought") or 0)
                c["warehouse_stock"] = int(c.get("warehouse_stock") or 0)
                c["total_spent"] = float(c.get("total_spent") or 0)
                c["avg_price"] = float(c.get("avg_price") or 0)
                c["refill_orders_count"] = int(c.get("refill_orders_count") or 0)
                c["repeat_customers_count"] = int(c.get("repeat_customers_count") or 0)
                c["last_refill_formatted"] = format_date(c.get("last_refill_date"))

                # Color classification
                col_info = extract_color(c["ink_name"])
                c["color"] = col_info["color"]
                c["color_badge"] = col_info["badge"]
                c["color_dot"] = col_info["dot"]
                
                # Estimated consumption cycle
                if c["refill_orders_count"] > 1:
                    c["est_cycle_days"] = max(15, min(90, round(365 / c["refill_orders_count"])))
                else:
                    c["est_cycle_days"] = 45  # Standard benchmark
                
                # Recommended restock quantity
                c["restock_recommendation"] = max(10, round(c["total_units_bought"] * 0.25))

            return {
                "printer": {
                    "product_id": printer["PRODUCT_ID"],
                    "product_name": printer["PRODUCT_NAME"],
                    "category": printer["CATEGORY_NAME"],
                    "warehouse_stock": int(printer.get("current_stock") or 0),
                    "sales_price": float(printer.get("SALES_PRICE") or 0),
                    "total_buyers": int(p_stats.get("total_buyers") or 0),
                    "printer_units_sold": int(p_stats.get("printer_units_sold") or 0),
                },
                "total_ink_units": total_ink_units,
                "total_ink_spend": round(total_ink_spend, 2),
                "consumables_count": len(consumables),
                "consumables": consumables,
            }

def get_ink_printer_matrix(ink_id: str) -> Dict[str, Any]:
    """
    Module 03 (Part B): Ink to Printer Dependent.
    For a selected ink/toner, find all printer models used by customers who buy this consumable.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Consumable info
            cur.execute("""
                SELECT 
                    p.PRODUCT_ID, p.PRODUCT_NAME, COALESCE(c.CATEGORY_NAME, 'Consumable') as CATEGORY_NAME,
                    COALESCE(st.stock_qty, 0) as current_stock, p.SALES_PRICE
                FROM product p
                LEFT JOIN category c ON p.CATEGORY_ID = c.CATEGORY_ID
                LEFT JOIN (
                    SELECT PRODUCT_ID, SUM(STOCK_QTY) as stock_qty 
                    FROM stock_non_serial 
                    WHERE PRODUCT_ID = %s
                    GROUP BY PRODUCT_ID
                ) st ON p.PRODUCT_ID = st.PRODUCT_ID
                WHERE p.PRODUCT_ID = %s
            """, (ink_id, ink_id))
            ink = cur.fetchone()
            if not ink:
                return {}
            clean_record(ink)

            # 2. Total buyers & volume for this ink
            cur.execute("""
                SELECT 
                    COUNT(DISTINCT sd.CS_ID) as total_buyers,
                    COALESCE(SUM(sd.QTY), 0) as total_units_sold,
                    ROUND(COALESCE(SUM(sd.QTY * sd.UNIT_PRICE), 0), 2) as total_revenue
                FROM sales_details sd
                WHERE sd.PRODUCT_ID = %s AND sd.CS_ID IS NOT NULL AND sd.CS_ID != ''
            """, (ink_id,))
            ink_stats = cur.fetchone() or {}

            # 3. Printers owned by buyers of this ink
            # (buyers CTE keeps the join set small; avoids s1 x s2 fan-out blow-up)
            cur.execute("""
                WITH buyers AS (
                    SELECT DISTINCT CS_ID FROM sales_details
                    WHERE PRODUCT_ID = %s AND CS_ID IS NOT NULL AND CS_ID != ''
                )
                SELECT
                    p2.PRODUCT_ID as printer_id,
                    p2.PRODUCT_NAME as printer_name,
                    COALESCE(c2.CATEGORY_NAME, 'PRINTER') as category_name,
                    COALESCE(st2.stock_qty, 0) as printer_stock,
                    COALESCE(SUM(s2.QTY), 0) as printer_units_owned,
                    COUNT(DISTINCT s2.CS_ID) as shared_customers_count,
                    MAX(s2.SALES_DATE) as last_printer_purchase
                FROM sales_details s2
                JOIN buyers b ON s2.CS_ID = b.CS_ID
                JOIN product p2 ON s2.PRODUCT_ID = p2.PRODUCT_ID
                LEFT JOIN category c2 ON p2.CATEGORY_ID = c2.CATEGORY_ID
                LEFT JOIN (
                    SELECT PRODUCT_ID, SUM(STOCK_QTY) as stock_qty
                    FROM stock_non_serial
                    GROUP BY PRODUCT_ID
                ) st2 ON p2.PRODUCT_ID = st2.PRODUCT_ID
                WHERE s2.PRODUCT_ID != %s
                  AND (p2.CATEGORY_ID = 'CAT006' OR p2.PRODUCT_NAME LIKE '%%PRINTER%%')
                GROUP BY p2.PRODUCT_ID, p2.PRODUCT_NAME, category_name, st2.stock_qty
                ORDER BY printer_units_owned DESC
                LIMIT 30
            """, (ink_id, ink_id))
            printers = cur.fetchall()

            for p in printers:
                clean_record(p)
                p["printer_units_owned"] = int(p.get("printer_units_owned") or 0)
                p["printer_stock"] = int(p.get("printer_stock") or 0)
                p["shared_customers_count"] = int(p.get("shared_customers_count") or 0)
                p["last_printer_formatted"] = format_date(p.get("last_printer_purchase"))

            # 4. Top active customers buying this ink
            cur.execute("""
                SELECT 
                    sd.CS_ID as customer_id,
                    COALESCE(c.CS_NAME, 'Client') as customer_name,
                    COALESCE(c.MOBILE, '-') as phone,
                    COALESCE(SUM(sd.QTY), 0) as units_bought,
                    ROUND(COALESCE(SUM(sd.QTY * sd.UNIT_PRICE), 0), 2) as total_spent,
                    COUNT(DISTINCT sd.SALES_ID) as purchase_count,
                    MAX(sd.SALES_DATE) as last_bought_date
                FROM sales_details sd
                LEFT JOIN cs c ON sd.CS_ID = c.CS_ID
                WHERE sd.PRODUCT_ID = %s AND sd.CS_ID IS NOT NULL AND sd.CS_ID != ''
                GROUP BY sd.CS_ID, customer_name, phone
                ORDER BY units_bought DESC
                LIMIT 20
            """, (ink_id,))
            buyers = cur.fetchall()

            for b in buyers:
                clean_record(b)
                b["units_bought"] = int(b.get("units_bought") or 0)
                b["total_spent"] = float(b.get("total_spent") or 0)
                b["purchase_count"] = int(b.get("purchase_count") or 0)
                b["last_bought_formatted"] = format_date(b.get("last_bought_date"))

            return {
                "ink": {
                    "product_id": ink["PRODUCT_ID"],
                    "product_name": ink["PRODUCT_NAME"],
                    "category": ink["CATEGORY_NAME"],
                    "warehouse_stock": int(ink.get("current_stock") or 0),
                    "sales_price": float(ink.get("SALES_PRICE") or 0),
                    "total_buyers": int(ink_stats.get("total_buyers") or 0),
                    "total_units_sold": int(ink_stats.get("total_units_sold") or 0),
                    "total_revenue": float(ink_stats.get("total_revenue") or 0),
                },
                "printers_count": len(printers),
                "printers": printers,
                "top_buyers": buyers,
            }

def get_refill_due_alerts() -> List[Dict[str, Any]]:
    """
    Actionable alerts: Customers who previously bought printer or ink,
    whose estimated consumption cycle has passed (> 40 days) without a refill.
    """
    now = time.time()
    if _REFILL_CACHE["data"] and (now - _REFILL_CACHE["ts"]) < _TTL:
        return _REFILL_CACHE["data"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    sd.CS_ID as customer_id,
                    COALESCE(c.CS_NAME, 'Client') as customer_name,
                    COALESCE(c.MOBILE, '-') as phone,
                    COALESCE(c.ADDRESS, '-') as address,
                    p.PRODUCT_NAME as last_product_name,
                    COALESCE(cat.CATEGORY_NAME, 'Consumable') as category_name,
                    MAX(sd.SALES_DATE) as last_purchase_date,
                    DATEDIFF(CURRENT_DATE, MAX(sd.SALES_DATE)) as days_since_purchase,
                    ROUND(SUM(sd.QTY), 0) as total_units_bought
                FROM sales_details sd
                JOIN product p ON sd.PRODUCT_ID = p.PRODUCT_ID
                LEFT JOIN category cat ON p.CATEGORY_ID = cat.CATEGORY_ID
                LEFT JOIN cs c ON sd.CS_ID = c.CS_ID
                WHERE sd.CS_ID IS NOT NULL AND sd.CS_ID != ''
                  AND (p.PRODUCT_NAME LIKE '%TONER%' 
                       OR p.PRODUCT_NAME LIKE '%INK%' 
                       OR p.PRODUCT_NAME LIKE '%CARTRIDGE%' 
                       OR p.CATEGORY_ID = 'CAT006')
                GROUP BY sd.CS_ID, customer_name, phone, address, p.PRODUCT_NAME, category_name
                HAVING days_since_purchase >= 30
                ORDER BY days_since_purchase DESC
                LIMIT 50
            """)
            rows = cur.fetchall()
            for r in rows:
                clean_record(r)
                r["days_since_purchase"] = int(r.get("days_since_purchase") or 0)
                r["total_units_bought"] = int(r.get("total_units_bought") or 0)
                r["last_purchase_formatted"] = format_date(r.get("last_purchase_date"))
                # Urgency assessment
                dsp = r["days_since_purchase"]
                if dsp > 90:
                    r["urgency"] = "High (Overdue)"
                    r["urgency_badge"] = "bg-rose-50 text-rose-700 border-rose-200"
                elif dsp >= 60:
                    r["urgency"] = "Medium (Due Now)"
                    r["urgency_badge"] = "bg-amber-50 text-amber-700 border-amber-200"
                else:
                    r["urgency"] = "Upcoming"
                    r["urgency_badge"] = "bg-blue-50 text-blue-700 border-blue-200"
            _REFILL_CACHE.update(data=rows, ts=now)
            return rows
