from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from starlette.concurrency import run_in_threadpool
import json
import logging
import threading
import database
from ai_service import (
    AIServiceError,
    answer_question,
    build_business_context,
    generate_forecast,
    generate_insights,
    stream_answer_question,
    stream_forecast,
    stream_insights,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Printer Analytics Dashboard",
    description="Product peak period analysis and sales intelligence powered by FastAPI.",
    version="2.1.0",
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

def is_authenticated(request: Request) -> bool:
    """Check if incoming request has a valid session cookie."""
    token = request.cookies.get("session_token")
    return database.verify_session(token)


def require_ai_auth(request: Request) -> JSONResponse | None:
    if not is_authenticated(request):
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
    return None


# ==============================================================================
# AUTHENTICATION ROUTES (LOGIN / LOGOUT)
# ==============================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render Login Page. Redirect to dashboard if already authenticated."""
    if is_authenticated(request):
        return RedirectResponse(url="/menus/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html")


@app.post("/api/auth/login")
async def process_login(request: Request, response: Response):
    """Authenticate credentials and set secure session cookie."""
    payload = await request.json()
    username = payload.get("username", "").strip()
    password = payload.get("password", "").strip()
    remember = payload.get("remember", False)

    user = database.authenticate_user(username, password)
    if not user:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": "Invalid username or password. Please try again."}
        )

    # Valid login -> create session
    days = 30 if remember else 1
    raw_token = database.create_session(user["id"], days=days)
    
    json_resp = JSONResponse(content={"success": True, "redirect": "/menus/dashboard"})
    json_resp.set_cookie(
        key="session_token",
        value=raw_token,
        max_age=days * 86400,
        httponly=True,
        samesite="lax",
    )
    return json_resp


@app.get("/logout")
async def logout(request: Request):
    """Clear session token from database and cookie, redirect to login."""
    token = request.cookies.get("session_token")
    if token:
        database.destroy_session(token)
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(key="session_token")
    return resp


# ==============================================================================
# PROTECTED DASHBOARD ROUTES
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
async def root_home(request: Request):
    """Admin arrives at full executive dashboard or login if not authenticated."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/menus/dashboard", response_class=HTMLResponse)
async def executive_dashboard_page(request: Request):
    """Full comprehensive business operations dashboard."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/menus/main", response_class=HTMLResponse)
async def main_menus_page(request: Request):
    """Page to view, add, edit, and delete Main Menus."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "main_menus.html")


@app.get("/menus/sub", response_class=HTMLResponse)
async def sub_menus_page(request: Request):
    """Page to view, add, edit, and delete Submenus."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "sub_menus.html")


@app.get("/user", response_class=HTMLResponse)
async def user_page_redirect(request: Request):
    """Convenience redirect from /user to /menus/user."""
    return RedirectResponse(url="/menus/user", status_code=303)


@app.get("/menus/user", response_class=HTMLResponse)
async def user_management_page(request: Request):
    """Page to view, add, and edit dashboard users."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "user_management.html")


# ==============================================================================
# USER MANAGEMENT API
# ==============================================================================

@app.get("/api/users")
async def get_users_list(request: Request):
    """Get all dashboard users."""
    if not is_authenticated(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return database.get_dashboard_users_list()


@app.post("/api/users")
async def create_user(request: Request):
    """Create a new dashboard user."""
    if not is_authenticated(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    payload = await request.json()
    try:
        new_id = database.create_dashboard_user(payload)
        return {"success": True, "id": new_id, "message": "User created successfully"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})


@app.put("/api/users/{user_id}")
async def update_user(user_id: int, request: Request):
    """Update an existing dashboard user."""
    if not is_authenticated(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    payload = await request.json()
    success = database.update_dashboard_user(user_id, payload)
    return {"success": success, "message": "User updated successfully" if success else "User not found"}


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    """Delete a dashboard user."""
    if not is_authenticated(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    success = database.delete_dashboard_user(user_id)
    return {"success": success, "message": "User deleted successfully" if success else "User not found"}


@app.get("/peak-period", response_class=HTMLResponse)
async def peak_period_page(request: Request):
    """Module 01: Product Peak Period Analysis."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "index.html")


@app.get("/menus/customer-affinity", response_class=HTMLResponse)
async def customer_affinity_page(request: Request):
    """Module 02: Customer for against Product (Customer Affinity)."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "customer_affinity.html")


@app.get("/api/customer-affinity/overview")
def get_affinity_overview_endpoint():
    """Get high-level summary KPIs for Customer Affinity."""
    return database.get_affinity_overview()


@app.get("/api/customer-affinity/customers")
def get_affinity_customers_endpoint(limit: int = 500):
    """Get ranked list of customers with affinity metrics."""
    return database.get_customer_affinity_list(limit=limit)


@app.get("/api/customer-affinity/bootstrap")
def get_affinity_bootstrap(limit: int = 1000):
    """Single-request bootstrap: overview + customers + dropdown in one round trip."""
    overview = database.get_affinity_overview()
    customers = database.get_customer_affinity_list(limit=limit)
    dropdown = [{"id": c["customer_id"], "name": f'{c["customer_name"]} ({c["customer_id"]})'} for c in customers[:200]]
    return {"overview": overview, "customers": customers, "dropdown": dropdown}


@app.get("/api/customer-affinity/customer/{customer_id}")
def get_customer_affinity_detail(customer_id: str):
    """Get product basket breakdown and category affinity for a specific customer."""
    return database.get_customer_product_breakdown(customer_id)


@app.get("/api/customer-affinity/product/{product_id}")
def get_product_affinity_detail(product_id: str):
    """Get reverse affinity: all customers who purchased a specific product."""
    return database.get_product_customer_affinity(product_id)


@app.get("/api/customer-affinity/dropdown")
def get_customers_dropdown_endpoint():
    """Get customer list for explorer dropdown."""
    return database.get_customers_dropdown()


@app.get("/menus/ink", response_class=HTMLResponse)
@app.get("/menus/ink-dependency", response_class=HTMLResponse)
async def ink_dependency_page(request: Request):
    """Module 03: Printer to ink dependent and ink to printer dependant."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "ink_dependency.html")


@app.get("/api/ink-dependency/bootstrap")
def get_ink_dependency_bootstrap():
    """Bootstrap: Overview + Printers + Inks + Refill Alerts in one round trip."""
    return {
        "overview": database.get_ink_dependency_overview(),
        "printers": database.get_printer_models_list(),
        "inks": database.get_ink_products_list(),
        "refill_alerts": database.get_refill_due_alerts(),
    }


@app.get("/api/ink-dependency/overview")
def get_ink_overview_endpoint():
    return database.get_ink_dependency_overview()


@app.get("/api/ink-dependency/printers")
def get_ink_printers_endpoint():
    return database.get_printer_models_list()


@app.get("/api/ink-dependency/printer/{printer_id}")
def get_printer_ink_matrix_endpoint(printer_id: str):
    return database.get_printer_ink_matrix(printer_id)


@app.get("/api/ink-dependency/inks")
def get_inks_endpoint():
    return database.get_ink_products_list()


@app.get("/api/ink-dependency/ink/{ink_id}")
def get_ink_printer_matrix_endpoint(ink_id: str):
    return database.get_ink_printer_matrix(ink_id)


@app.get("/api/ink-dependency/refill-alerts")
def get_refill_alerts_endpoint():
    return database.get_refill_due_alerts()


@app.get("/api/dashboard/full-overview")
def get_dashboard_full_overview():
    """Return all high-level business intelligence data in one single response."""
    return {
        "kpis": database.get_dashboard_kpis(),
        "monthly_trend": database.get_monthly_sales_trend(months=12),
        "top_products": database.get_top_selling_products(limit=6),
        "recent_invoices": database.get_recent_invoices(limit=8),
        "inventory_summary": database.get_inventory_summary(limit=6),
        "top_customers": database.get_top_customers(limit=6),
        "db_status": "connected" if database.test_connection() else "disconnected",
    }


@app.get("/api/db-status")
def get_db_status():
    """Verify database health."""
    return {
        "status": "connected" if database.test_connection() else "error",
    }


@app.get("/api/stats")
def get_stats():
    """High level KPIs and overview metrics."""
    return database.get_dashboard_kpis()


# ==============================================================================
# AI BUSINESS ASSISTANT (READ-ONLY)
# ==============================================================================

def _warm_ai_context():
    try:
        build_business_context()
    except Exception:
        logger.exception("AI context warm-up failed")


@app.on_event("startup")
def _startup_warm_ai_context():
    """Pre-build the analytics snapshot so the first AI request is fast."""
    threading.Thread(target=_warm_ai_context, daemon=True).start()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/ai/chat")
async def ai_chat(request: Request):
    """Answer a business question using a bounded read-only analytics snapshot."""
    unauthorized = require_ai_auth(request)
    if unauthorized:
        return unauthorized
    payload = await request.json()
    question = str(payload.get("message", "")).strip()
    if not question:
        return JSONResponse(status_code=422, content={"success": False, "message": "Message is required."})
    if len(question) > 2000:
        return JSONResponse(status_code=422, content={"success": False, "message": "Message is too long."})
    try:
        context = await run_in_threadpool(build_business_context)
        answer = await run_in_threadpool(answer_question, question, context)
        return {"success": True, "answer": answer}
    except AIServiceError as exc:
        return JSONResponse(status_code=503, content={"success": False, "message": str(exc)})
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "message": "Could not prepare business data."})


@app.post("/api/ai/insights")
async def ai_insights(request: Request):
    """Generate management insights from current read-only business data."""
    unauthorized = require_ai_auth(request)
    if unauthorized:
        return unauthorized
    try:
        context = await run_in_threadpool(build_business_context)
        answer = await run_in_threadpool(generate_insights, context)
        return {"success": True, "answer": answer}
    except AIServiceError as exc:
        return JSONResponse(status_code=503, content={"success": False, "message": str(exc)})
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "message": "Could not prepare business data."})


@app.post("/api/ai/forecast")
async def ai_forecast(request: Request):
    """Generate a directional three-month forecast from historical trends."""
    unauthorized = require_ai_auth(request)
    if unauthorized:
        return unauthorized
    try:
        context = await run_in_threadpool(build_business_context)
        answer = await run_in_threadpool(generate_forecast, context)
        return {"success": True, "answer": answer}
    except AIServiceError as exc:
        return JSONResponse(status_code=503, content={"success": False, "message": str(exc)})
    except Exception:
        return JSONResponse(status_code=500, content={"success": False, "message": "Could not prepare business data."})


@app.post("/api/ai/{action}/stream")
async def ai_stream(action: str, request: Request):
    """Stream AI output as server-sent events so text appears token by token."""
    unauthorized = require_ai_auth(request)
    if unauthorized:
        return unauthorized
    if action not in ("chat", "insights", "forecast"):
        return JSONResponse(status_code=404, content={"success": False, "message": "Unknown AI action."})

    question = None
    if action == "chat":
        payload = await request.json()
        question = str(payload.get("message", "")).strip()
        if not question:
            return JSONResponse(status_code=422, content={"success": False, "message": "Message is required."})
        if len(question) > 2000:
            return JSONResponse(status_code=422, content={"success": False, "message": "Message is too long."})

    try:
        context = await run_in_threadpool(build_business_context)
    except Exception:
        logger.exception("Could not build AI business context")
        return JSONResponse(status_code=500, content={"success": False, "message": "Could not prepare business data."})

    if action == "chat":
        chunks = stream_answer_question(question, context)
    elif action == "insights":
        chunks = stream_insights(context)
    else:
        chunks = stream_forecast(context)

    def event_stream():
        try:
            for delta in chunks:
                yield _sse({"delta": delta})
            yield _sse({"done": True})
        except AIServiceError as exc:
            yield _sse({"error": str(exc)})
        except Exception:
            logger.exception("AI streaming request failed")
            yield _sse({"error": "AI request failed."})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ==============================================================================
# 01. PEAK PERIOD OF PRODUCT SELL ENDPOINTS
# ==============================================================================

@app.get("/api/peak-timing")
def get_peak_timing():
    """Get peak day of week, peak hours, and monthly volume distribution."""
    return database.get_peak_timing_summary()


@app.get("/api/products-peak-ranking")
def get_products_peak_ranking(limit: int = 1500):
    """Get all products ranked by sales with their peak month, peak volume, and surge rate."""
    return database.get_products_peak_ranking(limit=limit)


@app.get("/api/peak/bootstrap")
def get_peak_bootstrap(limit: int = 1500):
    """Single-request bootstrap: timing + ranking + products + categories."""
    timing = database.get_peak_timing_summary()
    ranking = database.get_products_peak_ranking(limit=limit)
    products = database.get_products_dropdown_list()
    categories = database.get_categories_list()
    return {"timing": timing, "ranking": ranking, "products": products, "categories": categories}


@app.get("/api/product-peak-detail/{product_id}")
def get_product_peak_detail(product_id: str):
    """Get month-by-month seasonality breakdown for a single product."""
    return database.get_product_peak_detail(product_id)


@app.get("/api/products-list")
def get_products_list():
    """Get product list for search and selection dropdown."""
    return database.get_products_dropdown_list()


@app.get("/api/categories")
def get_categories():
    """Get list of all product categories."""
    return database.get_categories_list()


# ==============================================================================
# 02. DYNAMIC SIDEBAR MENUS (DATABASE CONTROLLED)
# ==============================================================================

@app.get("/api/menus")
async def get_menus(request: Request, all: bool = False):
    """Retrieve all sidebar menus in treeview hierarchy filtered by user permissions."""
    if all:
        # When all=true, return every menu (used by permission checkboxes) — no user filter
        return database.get_sidebar_menus(all_menus=True, user_id=None)
    token = request.cookies.get("session_token")
    user = database.get_session_user(token)
    user_id = user["id"] if user else None
    return database.get_sidebar_menus(all_menus=False, user_id=user_id)


@app.get("/api/menus/main-list")
async def get_main_menus():
    """Retrieve list of all Main Menus."""
    return database.get_main_menus_table()


@app.get("/api/menus/sub-list")
async def get_submenus():
    """Retrieve list of all Submenus."""
    return database.get_submenus_table()


@app.post("/api/menus")
async def create_menu(request: Request):
    """Create a new menu (main or sub) in database."""
    payload = await request.json()
    new_id = database.create_sidebar_menu(payload)
    return {"success": True, "id": new_id, "message": "Menu created successfully"}


@app.put("/api/menus/{menu_id}")
async def update_menu(menu_id: int, request: Request):
    """Update an existing sidebar menu in database."""
    payload = await request.json()
    success = database.update_sidebar_menu(menu_id, payload)
    return {"success": success, "message": "Menu updated successfully" if success else "Menu not found"}


@app.delete("/api/menus/{menu_id}")
async def delete_menu(menu_id: int):
    """Delete a sidebar menu from database."""
    success = database.delete_sidebar_menu(menu_id)
    return {"success": success, "message": "Menu deleted successfully" if success else "Menu not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
