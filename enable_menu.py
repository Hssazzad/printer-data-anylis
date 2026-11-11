import database

menus = database.get_sidebar_menus()
for m in menus:
    if m.get("submenus"):
        for sub in m["submenus"]:
            if "Affinity" in sub["title"]:
                print("Affinity submenu:", sub)
