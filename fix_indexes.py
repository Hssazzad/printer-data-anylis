import pymysql
conn = pymysql.connect(host='127.0.0.1',port=3306,user='root',password='',database='print_db',charset='utf8mb4', autocommit=True)
cur = conn.cursor()
indexes = [
    ("sales_details", "idx_sd_cs", ["CS_ID"]),
    ("sales_details", "idx_sd_cs_prod", ["CS_ID","PRODUCT_ID","SALES_ID","SALES_DATE"]),
    ("product", "idx_product_id", ["PRODUCT_ID"]),
    ("product", "idx_product_cat", ["CATEGORY_ID"]),
    ("cs", "idx_cs_id", ["CS_ID"]),
    ("category", "idx_category_id", ["CATEGORY_ID"]),
]
for table, name, cols in indexes:
    cur.execute(f"SHOW INDEX FROM {table} WHERE Key_name=%s", (name,))
    if cur.fetchone():
        print(f"SKIP {table}.{name} exists")
        continue
    cols_sql = ", ".join(f"`{c}`" for c in cols)
    sql = f"CREATE INDEX `{name}` ON `{table}` ({cols_sql})"
    print(f"RUN: {sql}")
    cur.execute(sql)
    print(f"OK {table}.{name}")
conn.close()
print("Done - indexes created, re-running perf test")
import time, database
t=time.time(); ov=database.get_affinity_overview(); print(f"overview {time.time()-t:.2f}s", ov)
t=time.time(); rows=database.get_customer_affinity_list(limit=1000); print(f"list1000 {time.time()-t:.2f}s n={len(rows)}")
t=time.time(); d=database.get_customers_dropdown(); print(f"dropdown {time.time()-t:.2f}s n={len(d)}")
t=time.time(); det=database.get_customer_product_breakdown(rows[0]['customer_id']); print(f"detail {time.time()-t:.2f}s products={len(det['products'])}")
