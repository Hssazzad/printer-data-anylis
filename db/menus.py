import json
from typing import Dict, Any, List, Optional
from .connection import get_connection

_menus_initialized = False

def init_menus_table():
    """Ensure sidebar_menus table exists with parent_id for AdminLTE-style treeview submenus."""
    global _menus_initialized
    if _menus_initialized:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sidebar_menus (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    parent_id INT DEFAULT NULL,
                    title VARCHAR(100) NOT NULL,
                    subtitle VARCHAR(100) DEFAULT NULL,
                    url VARCHAR(255) NOT NULL DEFAULT '#',
                    icon VARCHAR(50) NOT NULL DEFAULT 'circle',
                    badge_text VARCHAR(50) DEFAULT NULL,
                    section VARCHAR(50) NOT NULL DEFAULT 'Analytics Modules',
                    menu_order INT NOT NULL DEFAULT 0,
                    is_active TINYINT(1) NOT NULL DEFAULT 1,
                    is_disabled TINYINT(1) NOT NULL DEFAULT 0,
                    target_blank TINYINT(1) NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_parent (parent_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            
            # Check if parent_id column exists
            cur.execute("""
                SELECT COUNT(*) as cnt 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                  AND TABLE_NAME = 'sidebar_menus' 
                  AND COLUMN_NAME = 'parent_id';
            """)
            if cur.fetchone()["cnt"] == 0:
                cur.execute("ALTER TABLE sidebar_menus ADD COLUMN parent_id INT DEFAULT NULL AFTER id, ADD INDEX idx_parent (parent_id);")
            
            # Check if hierarchy is already set up, if not restructure
            cur.execute("SELECT COUNT(*) as cnt FROM sidebar_menus WHERE parent_id IS NOT NULL")
            has_submenus = cur.fetchone()["cnt"] > 0

            if not has_submenus:
                cur.execute("DELETE FROM sidebar_menus")
                
                # 1. Main Menu: Product Intelligence (Parent)
                cur.execute("""
                    INSERT INTO sidebar_menus (id, parent_id, title, subtitle, url, icon, section, menu_order, is_active, is_disabled, target_blank)
                    VALUES (1, NULL, 'Product Intelligence', 'Core Analytics', '#', 'package', 'Analytics Modules', 1, 1, 0, 0)
                """)
                parent_1 = 1

                # Submenus of Product Intelligence
                cur.execute("""
                    INSERT INTO sidebar_menus (parent_id, title, subtitle, url, icon, section, menu_order, is_active, is_disabled, target_blank)
                    VALUES 
                    (%s, 'Product Peak Period', '', '/peak-period', 'circle', 'Analytics Modules', 1, 1, 0, 0),
                    (%s, 'Customer Affinity', '', '/menus/customer-affinity', 'circle', 'Analytics Modules', 2, 1, 0, 0),
                    (%s, 'Ink Dependency', '', '/menus/ink', 'circle', 'Analytics Modules', 3, 1, 0, 0)
                """, (parent_1, parent_1, parent_1))

                # 2. Main Menu: Client Operations (Parent)
                cur.execute("""
                    INSERT INTO sidebar_menus (id, parent_id, title, subtitle, url, icon, section, menu_order, is_active, is_disabled, target_blank)
                    VALUES (2, NULL, 'Client Operations', 'Risk & Accounts', '#', 'users', 'Analytics Modules', 2, 1, 0, 0)
                """)
                parent_2 = 2

                # Submenus of Client Operations
                cur.execute("""
                    INSERT INTO sidebar_menus (parent_id, title, subtitle, url, icon, section, menu_order, is_active, is_disabled, target_blank)
                    VALUES 
                    (%s, 'Dormant Clients', '', '#', 'circle', 'Analytics Modules', 1, 1, 1, 0),
                    (%s, 'High-Due Alert', '', '#', 'circle', 'Analytics Modules', 2, 1, 1, 0),
                    (%s, 'Client Profitability', '', '#', 'circle', 'Analytics Modules', 3, 1, 1, 0)
                """, (parent_2, parent_2, parent_2))

                # 3. Menus (Parent Management Menu)
                cur.execute("""
                    INSERT INTO sidebar_menus (id, parent_id, title, subtitle, url, icon, section, menu_order, is_active, is_disabled, target_blank)
                    VALUES (3, NULL, 'Menus', 'Navigation Control', '#', 'layers', 'System', 3, 1, 0, 0)
                """)
                parent_3 = 3

                # Submenus of Menus
                cur.execute("""
                    INSERT INTO sidebar_menus (parent_id, title, subtitle, url, icon, section, menu_order, is_active, is_disabled, target_blank)
                    VALUES 
                    (%s, 'Main Menu List', '', '/menus/main', 'circle', 'System', 1, 1, 0, 0),
                    (%s, 'Submenu List', '', '/menus/sub', 'circle', 'System', 2, 1, 0, 0)
                """, (parent_3, parent_3))

                # 4. Direct Link: API Documentation (No submenus)
                cur.execute("""
                    INSERT INTO sidebar_menus (parent_id, title, subtitle, url, icon, section, menu_order, is_active, is_disabled, target_blank)
                    VALUES (NULL, 'API Documentation', '', '/docs', 'book-open', 'System', 4, 1, 0, 1)
                """)

            # Ensure modern module links are updated
            cur.execute("""
                UPDATE sidebar_menus 
                SET url = '/menus/ink', is_disabled = 0 
                WHERE title = 'Ink Dependency'
            """)
            conn.commit()
    _menus_initialized = True

def get_sidebar_menus(all_menus: bool = False, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fetch sidebar menus organized in hierarchy: Main menus with nested submenus, filtered by user permissions."""
    init_menus_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            active_filter = "" if all_menus else "AND is_active = 1"

            # 1. Fetch Main Menus (where parent_id IS NULL or 0)
            cur.execute(f"""
                SELECT id, parent_id, title, subtitle, url, icon, badge_text, section, menu_order, is_active, is_disabled, target_blank
                FROM sidebar_menus 
                WHERE (parent_id IS NULL OR parent_id = 0) {active_filter}
                ORDER BY menu_order ASC, id ASC
            """)
            main_menus = cur.fetchall()

            # 2. Fetch all Submenus
            cur.execute(f"""
                SELECT id, parent_id, title, subtitle, url, icon, badge_text, section, menu_order, is_active, is_disabled, target_blank
                FROM sidebar_menus 
                WHERE parent_id IS NOT NULL AND parent_id > 0 {active_filter}
                ORDER BY menu_order ASC, id ASC
            """)
            all_submenus = cur.fetchall()

            # Check permissions for user if user_id is provided
            allowed_ids = None
            if user_id is not None:
                cur.execute("SELECT role, allowed_menus FROM dashboard_auth WHERE id = %s LIMIT 1", (user_id,))
                user_row = cur.fetchone()
                if user_row:
                    raw = user_row.get("allowed_menus")
                    if raw and raw != "*":
                        try:
                            allowed_ids = set(json.loads(raw))
                        except Exception:
                            allowed_ids = set(int(x.strip()) for x in str(raw).split(",") if x.strip().isdigit())

            # Group submenus under their parent
            submenu_map = {}
            for sub in all_submenus:
                if allowed_ids is not None and sub["id"] not in allowed_ids:
                    continue
                pid = sub["parent_id"]
                if pid not in submenu_map:
                    submenu_map[pid] = []
                submenu_map[pid].append(sub)

            # Filter main menus if role-restricted
            filtered_main_menus = []
            for main in main_menus:
                has_allowed_subs = len(submenu_map.get(main["id"], [])) > 0
                is_main_allowed = (allowed_ids is None) or (main["id"] in allowed_ids)
                if is_main_allowed or has_allowed_subs:
                    main["submenus"] = submenu_map.get(main["id"], [])
                    filtered_main_menus.append(main)

            return filtered_main_menus

def create_sidebar_menu(data: Dict[str, Any]) -> int:
    """Create a new sidebar menu item (main or submenu)."""
    init_menus_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            parent_id = data.get("parent_id")
            if parent_id in ("", None, "0", 0):
                parent_id = None
            else:
                parent_id = int(parent_id)

            cur.execute("""
                INSERT INTO sidebar_menus 
                (parent_id, title, subtitle, url, icon, badge_text, section, menu_order, is_active, is_disabled, target_blank)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                parent_id,
                data.get("title", "New Menu"),
                data.get("subtitle", ""),
                data.get("url", "#"),
                data.get("icon", "circle"),
                data.get("badge_text", ""),
                data.get("section", "Analytics Modules"),
                int(data.get("menu_order", 0)),
                1 if data.get("is_active", True) else 0,
                1 if data.get("is_disabled", False) else 0,
                1 if data.get("target_blank", False) else 0,
            ))
            conn.commit()
            return cur.lastrowid

def update_sidebar_menu(menu_id: int, data: Dict[str, Any]) -> bool:
    """Update an existing sidebar menu item."""
    init_menus_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            parent_id = data.get("parent_id")
            if parent_id in ("", None, "0", 0):
                parent_id = None
            else:
                parent_id = int(parent_id)

            cur.execute("""
                UPDATE sidebar_menus 
                SET parent_id = %s,
                    title = %s,
                    subtitle = %s,
                    url = %s,
                    icon = %s,
                    badge_text = %s,
                    section = %s,
                    menu_order = %s,
                    is_active = %s,
                    is_disabled = %s,
                    target_blank = %s
                WHERE id = %s
            """, (
                parent_id,
                data.get("title", ""),
                data.get("subtitle", ""),
                data.get("url", "#"),
                data.get("icon", "circle"),
                data.get("badge_text", ""),
                data.get("section", "Analytics Modules"),
                int(data.get("menu_order", 0)),
                1 if data.get("is_active", True) else 0,
                1 if data.get("is_disabled", False) else 0,
                1 if data.get("target_blank", False) else 0,
                menu_id
            ))
            conn.commit()
            return True

def delete_sidebar_menu(menu_id: int) -> bool:
    """Delete a menu item and its children submenus."""
    init_menus_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sidebar_menus WHERE parent_id = %s", (menu_id,))
            cur.execute("DELETE FROM sidebar_menus WHERE id = %s", (menu_id,))
            conn.commit()
            return cur.rowcount > 0

def get_main_menus_table() -> List[Dict[str, Any]]:
    """Get list of all main menus with count of submenus."""
    init_menus_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    m.*,
                    COUNT(s.id) as submenus_count
                FROM sidebar_menus m
                LEFT JOIN sidebar_menus s ON s.parent_id = m.id
                WHERE m.parent_id IS NULL OR m.parent_id = 0
                GROUP BY m.id
                ORDER BY m.menu_order ASC, m.id ASC
            """)
            rows = cur.fetchall()
            for r in rows:
                for k, v in list(r.items()):
                    if hasattr(v, "strftime"):
                        r[k] = v.strftime("%Y-%m-%d %H:%M:%S")
            return rows

def get_submenus_table() -> List[Dict[str, Any]]:
    """Get list of all submenus along with their parent menu name."""
    init_menus_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    s.*,
                    COALESCE(p.title, 'No Parent') as parent_title
                FROM sidebar_menus s
                LEFT JOIN sidebar_menus p ON s.parent_id = p.id
                WHERE s.parent_id IS NOT NULL AND s.parent_id > 0
                ORDER BY p.menu_order ASC, s.menu_order ASC, s.id ASC
            """)
            rows = cur.fetchall()
            for r in rows:
                for k, v in list(r.items()):
                    if hasattr(v, "strftime"):
                        r[k] = v.strftime("%Y-%m-%d %H:%M:%S")
            return rows
