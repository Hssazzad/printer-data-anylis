import contextvars
import os
from contextlib import contextmanager

import pymysql

from config import env_int, load_dotenv

load_dotenv()

_READ_ONLY_MODE = contextvars.ContextVar("db_read_only_mode", default=False)


@contextmanager
def read_only_connection_mode():
    """Route analytics queries through optional read-only credentials."""
    token = _READ_ONLY_MODE.set(True)
    try:
        yield
    finally:
        _READ_ONLY_MODE.reset(token)


def _credentials():
    if _READ_ONLY_MODE.get():
        read_only_user = os.getenv("DB_READONLY_USER", "").strip()
        if read_only_user:
            return read_only_user, os.getenv("DB_READONLY_PASSWORD", "")
    return os.getenv("DB_USER", "root"), os.getenv("DB_PASSWORD", "")


def get_connection():
    """Establish and return a database connection."""
    user, password = _credentials()
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=env_int("DB_PORT", 3306, minimum=1),
        user=user,
        password=password,
        database=os.getenv("DB_NAME", "print_db"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=env_int("DB_CONNECT_TIMEOUT", 5, minimum=1),
        read_timeout=env_int("DB_READ_TIMEOUT", 30, minimum=1),
        write_timeout=env_int("DB_WRITE_TIMEOUT", 30, minimum=1),
    )


def test_connection() -> bool:
    """Check database health."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
    except Exception as e:
        print(f"[DB Error] {e}")
        return False
