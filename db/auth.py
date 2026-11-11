import hashlib
import secrets
import hmac

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
import json
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, Any, Optional
from .connection import get_connection

_auth_initialized = False
_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def is_default_admin(user: Dict[str, Any]) -> bool:
    if (user.get("username") or "").casefold() != "admin":
        return False
    return _is_default_password(user.get("password_hash") or "", user.get("password_salt") or "")


@lru_cache(maxsize=128)
def _is_default_password(stored: str, salt: str) -> bool:
    if stored.startswith("$argon2"):
        try:
            return _password_hasher.verify(stored, "admin")
        except (InvalidHashError, VerificationError):
            return False
    legacy = hashlib.sha256((salt + "admin").encode("utf-8")).hexdigest()
    return hmac.compare_digest(stored, legacy)


def init_auth_system():
    """Ensure dashboard_auth and dashboard_session tables exist; account setup is explicit."""
    global _auth_initialized
    if _auth_initialized:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK(CONCAT('printer_auth_', LEFT(SHA2(DATABASE(), 256), 48)), 10) AS acquired")
            if cur.fetchone()["acquired"] != 1:
                raise RuntimeError("Could not acquire authentication initialization lock")
            try:
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
                    cur.execute("ALTER TABLE dashboard_auth ADD COLUMN allowed_menus TEXT DEFAULT NULL AFTER role;")

                # Keep existing accounts intact. Duplicate usernames must be repaired
                # explicitly before a unique index can be added safely.
                cur.execute("""SELECT INDEX_NAME FROM information_schema.STATISTICS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dashboard_auth'
                    GROUP BY INDEX_NAME HAVING COUNT(*) = 1 AND MAX(COLUMN_NAME) = 'username'
                    AND MIN(NON_UNIQUE) = 0""")
                if not cur.fetchone():
                    cur.execute("SELECT username FROM dashboard_auth WHERE username IS NOT NULL GROUP BY username HAVING COUNT(*) > 1 LIMIT 1")
                    if cur.fetchone():
                        raise RuntimeError("Duplicate dashboard usernames must be resolved by an administrator before startup")
                    cur.execute("CREATE UNIQUE INDEX uq_dashboard_auth_username ON dashboard_auth (username)")

                # Preserve legacy NULL/empty permission values, which previously meant
                # full access, before treating newly inserted empty values as denied.
                cur.execute("""CREATE TABLE IF NOT EXISTS dashboard_migrations (
                    migration_key VARCHAR(100) PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
                cur.execute("SELECT migration_key FROM dashboard_migrations WHERE migration_key = %s", ("explicit_menu_permissions_v1",))
                if not cur.fetchone():
                    cur.execute("UPDATE dashboard_auth SET allowed_menus = '*' WHERE allowed_menus IS NULL OR allowed_menus = ''")
                    cur.execute("INSERT INTO dashboard_migrations (migration_key) VALUES (%s)", ("explicit_menu_permissions_v1",))

                # 2. Ensure dashboard_session exists
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS dashboard_session (
                        token_hash VARCHAR(128) PRIMARY KEY,
                        user_id INT DEFAULT 1,
                        expires_at DATETIME NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                conn.commit()
            finally:
                cur.execute("SELECT RELEASE_LOCK(CONCAT('printer_auth_', LEFT(SHA2(DATABASE(), 256), 48)))")
    _auth_initialized = True

def authenticate_user(username_or_phone: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate user against dashboard_auth."""
    init_auth_system()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM dashboard_auth
                WHERE username = %s OR phone = %s
                LIMIT 2
            """, (username_or_phone, username_or_phone))
            matches = cur.fetchall()
            if len(matches) != 1:
                return None
            user = matches[0]

            if is_default_admin(user):
                return None
            stored = user.get("password_hash") or ""
            if stored.startswith("$argon2"):
                try:
                    valid = _password_hasher.verify(stored, password)
                except (InvalidHashError, VerificationError):
                    return None
                needs_upgrade = _password_hasher.check_needs_rehash(stored)
            else:
                salt = user.get("password_salt") or ""
                candidate = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
                valid = hmac.compare_digest(candidate, stored)
                needs_upgrade = valid
            if not valid:
                return None
            if needs_upgrade:
                upgraded = hash_password(password)
                cur.execute("UPDATE dashboard_auth SET password_hash = %s, password_salt = '' WHERE id = %s AND BINARY password_hash = %s", (upgraded, user["id"], stored))
                if cur.rowcount != 1:
                    return None
                conn.commit()
                stored = upgraded
            return {"id": user["id"], "username": user.get("username"), "phone": user.get("phone"), "password_hash": stored}

def create_session(user_id: int, expected_password_hash: str, days: int = 7) -> Optional[str]:
    """Create a new session token and store hash in database."""
    init_auth_system()
    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now() + timedelta(days=days)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Serialize session creation with password changes and account deletion.
            cur.execute("SELECT username, password_hash, password_salt FROM dashboard_auth WHERE id = %s FOR UPDATE", (user_id,))
            user = cur.fetchone()
            if not user or not hmac.compare_digest(user["password_hash"], expected_password_hash) or is_default_admin(user):
                return None
            cur.execute("""
                INSERT INTO dashboard_session (token_hash, user_id, expires_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE expires_at = VALUES(expires_at)
            """, (token_hash, user_id, expires_at))
            conn.commit()
            return raw_token

def verify_session(raw_token: str) -> bool:
    """Verify session token validity."""
    return get_session_user(raw_token) is not None

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
                SELECT u.id, u.username, u.phone, u.role, u.allowed_menus, u.password_hash, u.password_salt
                FROM dashboard_session s
                JOIN dashboard_auth u ON s.user_id = u.id
                WHERE s.token_hash = %s AND s.expires_at > NOW()
                LIMIT 1
            """, (token_hash,))
            user = cur.fetchone()
            if not user or is_default_admin(user):
                return None
            user.pop("password_hash", None)
            user.pop("password_salt", None)
            raw_menus = user.get("allowed_menus")
            if raw_menus == "*":
                user["allowed_menus"] = "*"
            elif not raw_menus:
                user["allowed_menus"] = []
            else:
                try:
                    parsed = json.loads(raw_menus)
                    user["allowed_menus"] = [x for x in parsed if isinstance(x, int) and not isinstance(x, bool)] if isinstance(parsed, list) else []
                except (TypeError, ValueError):
                    user["allowed_menus"] = [int(x.strip()) for x in str(raw_menus).split(",") if x.strip().isdigit()]
            return user
