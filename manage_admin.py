"""Create the initial administrator or reset its password from a trusted shell."""
import argparse
import getpass
import os

from db.auth import hash_password, init_auth_system
from db.connection import get_connection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'reset'])
    args = parser.parse_args()
    password = os.environ.get('DASHBOARD_ADMIN_PASSWORD')
    if password is None:
        password = getpass.getpass('New administrator password: ')
        if password != getpass.getpass('Confirm password: '):
            parser.error('Passwords do not match')
    if not password or password == 'admin' or password != password.strip():
        parser.error('Choose a nonempty password other than admin, without surrounding whitespace')
    init_auth_system()
    with get_connection() as conn:
        with conn.cursor() as cur:
            if args.action == 'setup':
                cur.execute("SELECT id FROM dashboard_auth WHERE username = 'admin'")
                if cur.fetchone():
                    parser.error('The admin account already exists; use reset')
                cur.execute("INSERT INTO dashboard_auth (username, phone, role, allowed_menus, password_salt, password_hash) VALUES ('admin', NULL, 'Admin', '*', '', %s)", (hash_password(password),))
            else:
                cur.execute("SELECT id FROM dashboard_auth WHERE username = 'admin' FOR UPDATE")
                rows = cur.fetchall()
                if len(rows) != 1:
                    parser.error('Expected exactly one admin account')
                user_id = rows[0]['id']
                cur.execute("UPDATE dashboard_auth SET password_salt = '', password_hash = %s WHERE id = %s", (hash_password(password), user_id))
                cur.execute('DELETE FROM dashboard_session WHERE user_id = %s', (user_id,))
            conn.commit()
    print('Administrator credentials configured.')


if __name__ == '__main__':
    main()
