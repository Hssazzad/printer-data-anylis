"""Read-only business context and Gemini responses for the dashboard assistant."""

import json
import logging
import os
import random
import time
from typing import Any, Dict

import database
from config import load_dotenv, env_int
from db.forecasting import fill_monthly_gaps, forecast_revenue

load_dotenv()

logger = logging.getLogger(__name__)
_CONTEXT_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_CONTEXT_TTL = 30

_MAX_ATTEMPTS = 3
_BASE_RETRY_DELAY = 0.5
_MAX_RETRY_DELAY = 4.0
_RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_STATUSES = frozenset({"UNAVAILABLE", "RESOURCE_EXHAUSTED", "INTERNAL", "DEADLINE_EXCEEDED"})
_RETRYABLE_TRANSPORT_ERRORS = frozenset({
    "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout",
    "ConnectError", "ReadError", "RemoteProtocolError", "TransportError",
})


def _timeout_ms() -> int:
    return env_int("GEMINI_TIMEOUT_MS", 60000, minimum=1000)


def _http_options():
    from google.genai import types

    return types.HttpOptions(timeout=_timeout_ms())


class AIServiceError(RuntimeError):
    """Expected AI configuration or provider failure."""


def _get_client():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise AIServiceError("GEMINI_API_KEY is not configured on the server.")

    try:
        from google import genai
    except ImportError as exc:
        raise AIServiceError("The google-genai package is not installed on the server.") from exc

    return genai.Client(api_key=api_key, http_options=_http_options())


def build_business_context() -> Dict[str, Any]:
    """Build a bounded, read-only snapshot from existing analytics services."""
    now = time.time()
    cached = _CONTEXT_CACHE.get("data")
    if cached is not None and now - _CONTEXT_CACHE["ts"] < _CONTEXT_TTL:
        return cached

    with database.read_only_connection_mode():
        context = {
            "kpis": database.get_dashboard_kpis(),
            "monthly_sales_trend": database.get_monthly_sales_trend(months=12),
            "top_products": database.get_top_selling_products(limit=10),
            "inventory_summary": database.get_inventory_summary(limit=10),
            "top_customers": database.get_top_customers(limit=10),
            "customer_affinity_overview": database.get_affinity_overview(),
        }
        trend, missing_months = fill_monthly_gaps(context["monthly_sales_trend"], months=12)
        context["monthly_sales_trend"] = trend
        try:
            timing = database.get_peak_timing_summary()
        except Exception:
            logger.warning("Peak-period analytics unavailable for AI context", exc_info=True)
            timing = {}

    # Customer contact fields are not useful for analytics and must not leave
    # the application for an external provider.
    for customer in context["top_customers"]:
        for field in ("mobile", "address", "phone", "email", "MOBILE", "ADDRESS", "PHONE", "EMAIL"):
            customer.pop(field, None)

    observed_months = [row for row in trend if not row.get("missing")]
    context["forecast_three_month"] = forecast_revenue(observed_months, periods=3)
    latest_month = trend[-1].get("year_month") if trend else None
    peak_month = timing.get("peak_month") or {}
    peak_day = timing.get("peak_day") or {}
    peak_hour = timing.get("peak_hour") or {}
    context["provenance"] = {
        "as_of": time.strftime("%Y-%m-%d"),
        "sales_period": {
            "from": trend[0].get("year_month") if trend else None,
            "to": latest_month,
        },
        "latest_sales_month": latest_month,
        "data_is_stale": bool(latest_month and latest_month < time.strftime("%Y-%m")),
        "missing_months": missing_months,
        "window_months": 12,
        "sources": ["sales", "sales_details", "product", "stock_non_serial", "cs"],
    }
    context["forecast_readiness"] = {
        "window_months": len(trend),
        "observed_months": len(observed_months),
        "missing_months": missing_months,
        "sufficient": len(observed_months) >= 3,
        "minimum_required": 3,
    }
    context["peak_period"] = {
        "available": bool(peak_month or peak_day or peak_hour),
        "basis": "all_time",
        "months_covered": len(timing.get("month_distribution") or []),
        "peak_day": peak_day or None,
        "peak_hour": peak_hour or None,
        "peak_month": peak_month or None,
    }
    _CONTEXT_CACHE.update(data=context, ts=now)
    return context


def context_metadata(context: Dict[str, Any]) -> Dict[str, Any]:
    """Return non-sensitive freshness metadata for the assistant UI."""
    provenance = context.get("provenance") or {}
    readiness = context.get("forecast_readiness") or {}
    forecast = context.get("forecast_three_month") or {}
    return {
        "as_of": provenance.get("as_of"),
        "sales_period": provenance.get("sales_period") or {"from": None, "to": None},
        "missing_months": provenance.get("missing_months") or [],
        "data_is_stale": bool(provenance.get("data_is_stale")),
        "forecast_status": forecast.get("status"),
        "forecast_sufficient": bool(readiness.get("sufficient")),
        "forecast_is_directional": True,
    }


def _context_text(context: Dict[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=False, default=str)


def _model_name() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"


def _prompt(system_prompt: str, user_prompt: str, context: Dict[str, Any]) -> str:
    return (
        f"{system_prompt}\n\n"
        f"Business data (read-only JSON):\n{_context_text(context)}\n\n"
        f"Request:\n{user_prompt}"
    )


def _exception_code(exc: Exception) -> int | None:
    code = getattr(exc, "code", None)
    if code is None:
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
    try:
        return int(code)
    except (TypeError, ValueError):
        return None


def _exception_status(exc: Exception) -> str:
    status = getattr(exc, "status", None)
    details = getattr(exc, "details", None)
    if not status and isinstance(details, dict):
        nested = details.get("error")
        status = details.get("status") or (nested.get("status") if isinstance(nested, dict) else None)
    return str(status or "").upper()


def _is_retryable(exc: Exception) -> bool:
    if _exception_code(exc) in _RETRYABLE_CODES:
        return True
    if _exception_status(exc) in _RETRYABLE_STATUSES:
        return True
    return isinstance(exc, (TimeoutError, ConnectionError)) or type(exc).__name__ in _RETRYABLE_TRANSPORT_ERRORS


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter; attempt is zero-based and delay is capped."""
    ceiling = min(_MAX_RETRY_DELAY, _BASE_RETRY_DELAY * (2 ** attempt))
    return random.uniform(ceiling / 2, ceiling)


def _friendly_provider_message(exc: Exception) -> str:
    code = _exception_code(exc)
    status = _exception_status(exc)
    if code in (401, 403) or status in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
        return "The AI assistant is not configured correctly. Please contact an administrator."
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        return "The AI service is handling too many requests right now. Please try again in a minute."
    if _is_retryable(exc):
        return "The AI service is temporarily busy. Please try again in a minute."
    return "The AI assistant could not respond right now. Please try again."


def _provider_error(exc: Exception) -> AIServiceError:
    logger.exception("AI provider request failed")
    return AIServiceError(_friendly_provider_message(exc))


def _complete(system_prompt: str, user_prompt: str, context: Dict[str, Any]) -> str:
    client = _get_client()
    prompt = _prompt(system_prompt, user_prompt, context)
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.models.generate_content(
                model=_model_name(),
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 700,
                },
            )
            content = response.text
            if not content:
                raise AIServiceError("The AI provider returned an empty response.")
            return content.strip()
        except AIServiceError:
            raise
        except Exception as exc:
            if attempt + 1 >= _MAX_ATTEMPTS or not _is_retryable(exc):
                raise _provider_error(exc) from exc
            delay = _retry_delay(attempt)
            logger.warning(
                "AI provider request failed (attempt %d/%d, %s); retrying in %.2fs",
                attempt + 1, _MAX_ATTEMPTS, type(exc).__name__, delay,
            )
            time.sleep(delay)


def _stream_complete(system_prompt: str, user_prompt: str, context: Dict[str, Any]):
    """Yield the answer incrementally, retrying only while no text has been emitted."""
    client = _get_client()
    prompt = _prompt(system_prompt, user_prompt, context)
    for attempt in range(_MAX_ATTEMPTS):
        emitted = False
        try:
            stream = client.models.generate_content_stream(
                model=_model_name(),
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 700,
                },
            )
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    emitted = True
                    yield text
            if not emitted:
                raise AIServiceError("The AI provider returned an empty response.")
            return
        except AIServiceError:
            raise
        except Exception as exc:
            if emitted or attempt + 1 >= _MAX_ATTEMPTS or not _is_retryable(exc):
                raise _provider_error(exc) from exc
            delay = _retry_delay(attempt)
            logger.warning(
                "AI provider stream failed before output (attempt %d/%d, %s); retrying in %.2fs",
                attempt + 1, _MAX_ATTEMPTS, type(exc).__name__, delay,
            )
            time.sleep(delay)


_SYSTEM_PROMPT = """You are the Printer Analytics business intelligence assistant.
Answer in clear Bengali unless the user asks for another language. Use only the supplied
business data; do not invent figures or recalculate supplied forecast numbers. Explain
uncertainty and distinguish observations, assumptions, and recommendations. State the
supporting data sources and period, and explicitly say when data is missing, stale, or
insufficient. Treat forecast values as directional estimates, not guarantees. Never
request or reveal customer phone numbers or addresses. Never suggest changing database
records. Keep answers concise, actionable, and suitable for an operations manager."""


def _insights_prompt(context: Dict[str, Any]) -> str:
    peak = context.get("peak_period") or {}
    if peak.get("available"):
        return _INSIGHTS_PROMPT_WITH_PEAK
    return _INSIGHTS_PROMPT


def answer_question(question: str, context: Dict[str, Any]) -> str:
    return _complete(_SYSTEM_PROMPT, question, context)


def generate_insights(context: Dict[str, Any]) -> str:
    return _complete(_SYSTEM_PROMPT, _insights_prompt(context), context)


def generate_forecast(context: Dict[str, Any]) -> str:
    return _complete(_SYSTEM_PROMPT, _FORECAST_PROMPT, context)


_INSIGHTS_PROMPT = (
    "সাম্প্রতিক sales, inventory এবং customer data থেকে 5টি গুরুত্বপূর্ণ "
    "business insight দাও। প্রতিটির সঙ্গে data-based কারণ এবং একটি practical action দাও।"
)

_INSIGHTS_PROMPT_WITH_PEAK = (
    _INSIGHTS_PROMPT + " Peak-period data is available; include at most one insight about "
    "the supplied peak day/hour/month and label it as all-time data."
)

_FORECAST_PROMPT = (
    "Use the supplied monthly_sales_trend (up to 12 months, including zero-filled missing months) "
    "and forecast_three_month as the only source of forecast numbers. Do not calculate or invent different figures. "
    "If forecast_readiness.sufficient is false or forecast_three_month.status is not 'ok', say the data is "
    "insufficient and do not estimate. Otherwise explain the next three months' directional sales/revenue "
    "outlook in Bengali. It is a trend-based directional forecast, not statistical certainty. "
    "For each month mention expected direction, key assumptions, risks, and practical inventory actions. "
    "Also state the sales period and any missing months from provenance."
)


def stream_answer_question(question: str, context: Dict[str, Any]):
    return _stream_complete(_SYSTEM_PROMPT, question, context)


def stream_insights(context: Dict[str, Any]):
    return _stream_complete(_SYSTEM_PROMPT, _insights_prompt(context), context)


def stream_forecast(context: Dict[str, Any]):
    return _stream_complete(_SYSTEM_PROMPT, _FORECAST_PROMPT, context)
