import hashlib
import secrets
import json
from typing import Dict, Any, List
from .connection import get_connection
from .auth import init_auth_system

def get_dashboard_users_list() -> List[Dict[str, Any]]:
    """Retrieve all dashboard login users."""
    init_auth_system()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, username, phone, role, allowed_menus, created_at 
                FROM dashboard_auth 
                ORDER BY id ASC
            """)
            rows = cur.fetchall()
            for r in rows:
                dt = r.get("created_at")
                if dt and hasattr(dt, "strftime"):
                    r["created_at_formatted"] = dt.strftime("%d %b %Y, %I:%M %p")
                    r["created_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    r["created_at_formatted"] = str(dt or "-")
                    r["created_at"] = str(dt or "")
                
                raw_menus = r.get("allowed_menus")
                if not raw_menus or raw_menus == "*":
                    r["allowed_menus"] = "*"
                else:
                    try:
                        r["allowed_menus"] = json.loads(raw_menus)
                    except Exception:
                        r["allowed_menus"] = [int(x.strip()) for x in str(raw_menus).split(",") if x.strip().isdigit()]
            return rows

def create_dashboard_user(data: Dict[str, Any]) -> int:
    """Create a new dashboard user."""
    init_auth_system()
    username = (data.get("username") or "").strip()
    phone = (data.get("phone") or "").strip()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "Admin").strip()
    allowed_menus = data.get("allowed_menus")
    if isinstance(allowed_menus, list):
        allowed_menus_str = json.dumps(allowed_menus)
    elif not allowed_menus:
        allowed_menus_str = "*"
    else:
        allowed_menus_str = str(allowed_menus)

    if not username:
        raise ValueError("Username is required")
    if not password:
        raise ValueError("Password is required")

    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO dashboard_auth (username, phone, role, allowed_menus, password_salt, password_hash)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (username, phone, role, allowed_menus_str, salt, pwd_hash))
            conn.commit()
            return cur.lastrowid

def update_dashboard_user(user_id: int, data: Dict[str, Any]) -> bool:
    """Update user information and optionally password."""
    init_auth_system()
    username = (data.get("username") or "").strip()
    phone = (data.get("phone") or "").strip()
    role = (data.get("role") or "Admin").strip()
    password = (data.get("password") or "").strip()
    allowed_menus = data.get("allowed_menus")
    if isinstance(allowed_menus, list):
        allowed_menus_str = json.dumps(allowed_menus)
    elif not allowed_menus:
        allowed_menus_str = "*"
    else:
        allowed_menus_str = str(allowed_menus)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM dashboard_auth WHERE id = %s", (user_id,))
            if not cur.fetchone():
                return False

            if password:
                salt = secrets.token_hex(16)
                pwd_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
                cur.execute("""
                    UPDATE dashboard_auth 
                    SET username = %s, phone = %s, role = %s, allowed_menus = %s, password_salt = %s, password_hash = %s
                    WHERE id = %s
                """, (username, phone, role, allowed_menus_str, salt, pwd_hash, user_id))
            else:
                cur.execute("""
                    UPDATE dashboard_auth 
                    SET username = %s, phone = %s, role = %s, allowed_menus = %s
                    WHERE id = %s
                """, (username, phone, role, allowed_menus_str, user_id))
            conn.commit()
            return True

def delete_dashboard_user(user_id: int) -> bool:
    """Delete a dashboard user."""
    init_auth_system()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dashboard_auth WHERE id = %s", (user_id,))
            conn.commit()
            return cur.rowcount > 0
