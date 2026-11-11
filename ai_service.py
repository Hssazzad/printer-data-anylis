"""Read-only business context and Gemini responses for the dashboard assistant."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict

import database

logger = logging.getLogger(__name__)
_CONTEXT_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0}
_CONTEXT_TTL = 30


def _load_dotenv() -> None:
    """Load GEMINI_* settings from .env so keys survive terminal restarts."""
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        logger.warning("Could not read .env file", exc_info=True)


_load_dotenv()


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

    return genai.Client(api_key=api_key)


def build_business_context() -> Dict[str, Any]:
    """Build a bounded, read-only snapshot from existing analytics services."""
    now = time.time()
    cached = _CONTEXT_CACHE.get("data")
    if cached is not None and now - _CONTEXT_CACHE["ts"] < _CONTEXT_TTL:
        return cached

    context = {
        "kpis": database.get_dashboard_kpis(),
        "monthly_sales_trend": database.get_monthly_sales_trend(months=12),
        "top_products": database.get_top_selling_products(limit=10),
        "inventory_summary": database.get_inventory_summary(limit=10),
        "top_customers": database.get_top_customers(limit=10),
        "customer_affinity_overview": database.get_affinity_overview(),
    }
    _CONTEXT_CACHE.update(data=context, ts=now)
    return context


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


def _provider_error(exc: Exception) -> AIServiceError:
    logger.exception("AI provider request failed")
    detail = str(exc).strip().replace("\n", " ")
    if len(detail) > 300:
        detail = detail[:300] + "..."
    return AIServiceError(f"Gemini request failed: {detail or 'unknown provider error'}")


def _complete(system_prompt: str, user_prompt: str, context: Dict[str, Any]) -> str:
    client = _get_client()
    try:
        response = client.models.generate_content(
            model=_model_name(),
            contents=_prompt(system_prompt, user_prompt, context),
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
        raise _provider_error(exc) from exc


def _stream_complete(system_prompt: str, user_prompt: str, context: Dict[str, Any]):
    """Yield the answer incrementally so the UI can render the first tokens early."""
    client = _get_client()
    try:
        stream = client.models.generate_content_stream(
            model=_model_name(),
            contents=_prompt(system_prompt, user_prompt, context),
            config={
                "temperature": 0.1,
                "max_output_tokens": 700,
            },
        )
        for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                yield text
    except AIServiceError:
        raise
    except Exception as exc:
        raise _provider_error(exc) from exc


_SYSTEM_PROMPT = """You are the Printer Analytics business intelligence assistant.
Answer in clear Bengali unless the user asks for another language. Use only the supplied
business data; do not invent figures. Explain uncertainty and distinguish observations
from recommendations. Never suggest changing database records. Keep answers concise,
actionable, and suitable for an operations manager."""


def answer_question(question: str, context: Dict[str, Any]) -> str:
    return _complete(_SYSTEM_PROMPT, question, context)


def generate_insights(context: Dict[str, Any]) -> str:
    return _complete(_SYSTEM_PROMPT, _INSIGHTS_PROMPT, context)


def generate_forecast(context: Dict[str, Any]) -> str:
    return _complete(_SYSTEM_PROMPT, _FORECAST_PROMPT, context)


_INSIGHTS_PROMPT = (
    "সাম্প্রতিক sales, inventory, customer এবং peak-period data থেকে 5টি গুরুত্বপূর্ণ "
    "business insight দাও। প্রতিটির সঙ্গে data-based কারণ এবং একটি practical action দাও।"
)

_FORECAST_PROMPT = (
    "গত 24 মাসের trend দেখে আগামী 3 মাসের sales/revenue outlook তৈরি করো। "
    "এটি statistical certainty নয়—trend-based directional forecast হিসেবে দাও। "
    "প্রতি মাসে expected direction, প্রধান assumptions, risk এবং inventory action উল্লেখ করো।"
)


def stream_answer_question(question: str, context: Dict[str, Any]):
    return _stream_complete(_SYSTEM_PROMPT, question, context)


def stream_insights(context: Dict[str, Any]):
    return _stream_complete(_SYSTEM_PROMPT, _INSIGHTS_PROMPT, context)


def stream_forecast(context: Dict[str, Any]):
    return _stream_complete(_SYSTEM_PROMPT, _FORECAST_PROMPT, context)
