import hashlib
import secrets
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from .connection import get_connection

_auth_initialized = False

def init_auth_system():
    """Ensure dashboard_auth and dashboard_session tables are configured with default admin."""
    global _auth_initialized
    if _auth_initialized:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Ensure dashboard_auth exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_auth (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) DEFAULT 'admin',
                    phone VARCHAR(30) DEFAULT NULL,
                    password_salt VARCHAR(64) NOT NULL,
                    password_hash VARCHAR(128) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # Check if username column exists
            cur.execute("""
                SELECT COUNT(*) as cnt 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                  AND TABLE_NAME = 'dashboard_auth' 
                  AND COLUMN_NAME = 'username';
            """)
            if cur.fetchone()["cnt"] == 0:
                cur.execute("ALTER TABLE dashboard_auth ADD COLUMN username VARCHAR(50) DEFAULT 'admin' AFTER id, ADD UNIQUE INDEX idx_username (username);")

            # Check if role column exists
            cur.execute("""
                SELECT COUNT(*) as cnt 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                  AND TABLE_NAME = 'dashboard_auth' 
                  AND COLUMN_NAME = 'role';
            """)
            if cur.fetchone()["cnt"] == 0:
                cur.execute("ALTER TABLE dashboard_auth ADD COLUMN role VARCHAR(30) DEFAULT 'Admin' AFTER phone;")

            # Check if created_at column exists
            cur.execute("""
                SELECT COUNT(*) as cnt 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                  AND TABLE_NAME = 'dashboard_auth' 
                  AND COLUMN_NAME = 'created_at';
            """)
            if cur.fetchone()["cnt"] == 0:
                cur.execute("ALTER TABLE dashboard_auth ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")

            # Check if allowed_menus column exists
            cur.execute("""
                SELECT COUNT(*) as cnt 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                  AND TABLE_NAME = 'dashboard_auth' 
                  AND COLUMN_NAME = 'allowed_menus';
            """)
            if cur.fetchone()["cnt"] == 0:
                cur.execute("ALTER TABLE dashboard_auth ADD COLUMN allowed_menus TEXT DEFAULT '*' AFTER role;")

            cur.execute("""
                SELECT COUNT(*) as cnt FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dashboard_auth'
                  AND COLUMN_NAME = 'otp_secret';
            """)
            if cur.fetchone()["cnt"] == 0:
                cur.execute("ALTER TABLE dashboard_auth ADD COLUMN otp_secret VARCHAR(64) DEFAULT NULL;")

            # 2. Ensure dashboard_session exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_session (
                    token_hash VARCHAR(128) PRIMARY KEY,
                    user_id INT DEFAULT 1,
                    expires_at DATETIME NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_audit_log (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id INT NULL,
                    action VARCHAR(80) NOT NULL,
                    details VARCHAR(255) DEFAULT NULL,
                    ip_address VARCHAR(64) DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_audit_created_at (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)

            # 3. Seed or ensure admin user exists
            cur.execute("SELECT * FROM dashboard_auth WHERE username = 'admin' OR phone = 'admin'")
            admin_user = cur.fetchone()

            if not admin_user:
                salt = secrets.token_hex(16)
                pwd_hash = hashlib.sha256((salt + "admin").encode("utf-8")).hexdigest()
                cur.execute("""
                    INSERT INTO dashboard_auth (username, phone, password_salt, password_hash)
                    VALUES ('admin', '01795469462', %s, %s)
                """, (salt, pwd_hash))
            conn.commit()
    _auth_initialized = True

def authenticate_user(username_or_phone: str, password: str, otp: str = "") -> Optional[Dict[str, Any]]:
    """Authenticate user against dashboard_auth."""
    init_auth_system()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM dashboard_auth 
                WHERE username = %s OR phone = %s
                LIMIT 1
            """, (username_or_phone, username_or_phone))
            user = cur.fetchone()
            if not user:
                return None

            salt = user.get("password_salt") or ""
            expected_hash = user.get("password_hash") or ""
            calculated_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

            if calculated_hash == expected_hash:
                if user.get("otp_secret"):
                    try:
                        import pyotp
                        if not otp or not pyotp.TOTP(user["otp_secret"]).verify(otp):
                            return None
                    except ImportError:
                        return None
                return {
                    "id": user["id"],
                    "username": user.get("username", "admin"),
                    "phone": user.get("phone", ""),
                }
            return None


def audit_event(user_id: Optional[int], action: str, details: str = "", ip_address: str = "") -> None:
    """Write an audit record without changing business data."""
    init_auth_system()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO dashboard_audit_log (user_id, action, details, ip_address) VALUES (%s, %s, %s, %s)",
                (user_id, action[:80], details[:255], ip_address[:64]),
            )
            conn.commit()

def create_session(user_id: int, days: int = 7) -> str:
    """Create a new session token and store hash in database."""
    init_auth_system()
    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now() + timedelta(days=days)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO dashboard_session (token_hash, user_id, expires_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE expires_at = VALUES(expires_at)
            """, (token_hash, user_id, expires_at))
            conn.commit()
            return raw_token

def verify_session(raw_token: str) -> bool:
    """Verify session token validity."""
    if not raw_token:
        return False
    init_auth_system()
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT token_hash FROM dashboard_session 
                WHERE token_hash = %s AND expires_at > NOW()
                LIMIT 1
            """, (token_hash,))
            return cur.fetchone() is not None

def destroy_session(raw_token: str) -> bool:
    """Delete session upon logout."""
    if not raw_token:
        return True
    init_auth_system()
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dashboard_session WHERE token_hash = %s", (token_hash,))
            conn.commit()
            return True

def get_session_user(raw_token: str) -> Optional[Dict[str, Any]]:
    """Get authenticated user info for session."""
    if not raw_token:
        return None
    init_auth_system()
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.username, u.phone, u.role, u.allowed_menus
                FROM dashboard_session s
                JOIN dashboard_auth u ON s.user_id = u.id
                WHERE s.token_hash = %s AND s.expires_at > NOW()
                LIMIT 1
            """, (token_hash,))
            user = cur.fetchone()
            if not user:
                return None
            raw_menus = user.get("allowed_menus")
            if not raw_menus or raw_menus == "*":
                user["allowed_menus"] = "*"
            else:
                try:
                    user["allowed_menus"] = json.loads(raw_menus)
                except Exception:
                    user["allowed_menus"] = [int(x.strip()) for x in str(raw_menus).split(",") if x.strip().isdigit()]
            return user
