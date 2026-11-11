"""
Database Module - Compatibility facade.
All database logic is now modularized under the `db/` package:
- db/connection.py : Database connection management
- db/analytics.py  : Dashboard KPIs, revenue, stock, and customer stats
- db/peak_period.py: Product peak season analysis
- db/auth.py       : Authentication, passwords, and sessions
- db/users.py      : User management & Role-Based Access Control
- db/menus.py      : Dynamic hierarchical sidebar menus
"""

from db import *
