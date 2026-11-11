"""
Database package for Printer Analytics Dashboard.
Organized into clear modules:
- connection: Database connection & ping
- analytics: KPIs, monthly trends, top sales, invoices, inventory
- peak_period: Seasonality & peak period analytics
- auth: Authentication & session management
- users: Dashboard user management & RBAC
- menus: Dynamic sidebar menu management
"""

from .connection import get_connection, test_connection
from .analytics import (
    get_dashboard_kpis,
    get_monthly_sales_trend,
    get_top_selling_products,
    get_recent_invoices,
    get_inventory_summary,
    get_top_customers,
)
from .peak_period import (
    format_ym,
    get_peak_timing_summary,
    get_products_peak_ranking,
    get_product_peak_detail,
    get_products_dropdown_list,
    get_categories_list,
)
from .customer_affinity import (
    get_affinity_overview,
    get_customer_affinity_list,
    get_customer_product_breakdown,
    get_product_customer_affinity,
    get_customers_dropdown,
    get_customer_affinity_overview,
    get_customer_dropdown_list,
)
from .ink_dependency import (
    get_ink_dependency_overview,
    get_printer_models_list,
    get_ink_products_list,
    get_printer_ink_matrix,
    get_ink_printer_matrix,
    get_refill_due_alerts,
)
from .auth import (
    init_auth_system,
    authenticate_user,
    create_session,
    verify_session,
    destroy_session,
    get_session_user,
)
from .users import (
    get_dashboard_users_list,
    create_dashboard_user,
    update_dashboard_user,
    delete_dashboard_user,
)
from .menus import (
    init_menus_table,
    get_sidebar_menus,
    create_sidebar_menu,
    update_sidebar_menu,
    delete_sidebar_menu,
    get_main_menus_table,
    get_submenus_table,
)

__all__ = [
    "get_connection",
    "test_connection",
    "get_dashboard_kpis",
    "get_monthly_sales_trend",
    "get_top_selling_products",
    "get_recent_invoices",
    "get_inventory_summary",
    "get_top_customers",
    "format_ym",
    "get_peak_timing_summary",
    "get_products_peak_ranking",
    "get_product_peak_detail",
    "get_products_dropdown_list",
    "get_categories_list",
    "get_affinity_overview",
    "get_customer_affinity_list",
    "get_customer_product_breakdown",
    "get_product_customer_affinity",
    "get_customers_dropdown",
    "get_ink_dependency_overview",
    "get_printer_models_list",
    "get_ink_products_list",
    "get_printer_ink_matrix",
    "get_ink_printer_matrix",
    "get_refill_due_alerts",
    "init_auth_system",
    "authenticate_user",
    "create_session",
    "verify_session",
    "destroy_session",
    "get_session_user",
    "get_dashboard_users_list",
    "create_dashboard_user",
    "update_dashboard_user",
    "delete_dashboard_user",
    "init_menus_table",
    "get_sidebar_menus",
    "create_sidebar_menu",
    "update_sidebar_menu",
    "delete_sidebar_menu",
    "get_main_menus_table",
    "get_submenus_table",
]
