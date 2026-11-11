import json
import database

ov = database.get_affinity_overview()
json_ov = json.dumps(ov)
print("Overview OK:", json_ov[:100], "len:", len(json_ov))

drop = database.get_customers_dropdown()
json_drop = json.dumps(drop)
print("Dropdown OK, count:", len(drop), "len:", len(json_drop))

custs = database.get_customer_affinity_list(limit=20)
json_custs = json.dumps(custs)
print("Custs OK, count:", len(custs), "len:", len(json_custs))

if custs:
    sample_id = custs[0]["customer_id"]
    detail = database.get_customer_product_breakdown(sample_id)
    json_detail = json.dumps(detail)
    print("Detail OK for ID", sample_id, "len:", len(json_detail))
    print("Detail keys:", detail.keys(), "Product count:", len(detail["products"]))

print("ALL AFFINITY JSON SERIALIZATION TESTS PASSED SUCCESSFULLY!")
