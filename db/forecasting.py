"""Small, dependency-free demand forecasting helpers."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Mapping


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _valid_period(value: Any) -> str | None:
    period = str(value or "")[:7]
    if len(period) != 7:
        return None
    try:
        date.fromisoformat(period + "-01")
    except ValueError:
        return None
    return period


def _month_label(period: str) -> str:
    return date.fromisoformat(period + "-01").strftime("%b %Y")


def fill_monthly_gaps(history: Iterable[Mapping[str, Any]], months: int = 12) -> tuple[List[Dict[str, Any]], List[str]]:
    """Return a contiguous monthly window ending at the latest observed month.

    Missing months are explicit zero rows and are also returned separately so the
    assistant can state that the data is incomplete instead of hiding the gap.
    """
    months = max(1, int(months))
    observed: Dict[str, Dict[str, Any]] = {}
    for row in history:
        period = _valid_period(row.get("year_month") or row.get("period"))
        if not period:
            continue
        observed[period] = {
            **row,
            "year_month": period,
            "month_label": row.get("month_label") or _month_label(period),
        }
    if not observed:
        return [], []

    latest = date.fromisoformat(max(observed) + "-01")
    start_index = latest.year * 12 + (latest.month - 1) - (months - 1)
    filled: List[Dict[str, Any]] = []
    missing: List[str] = []
    for offset in range(months):
        year, month_index = divmod(start_index + offset, 12)
        period = f"{year:04d}-{month_index + 1:02d}"
        row = observed.get(period)
        if row is None:
            missing.append(period)
            filled.append({
                "year_month": period,
                "month_label": _month_label(period),
                "invoices": 0,
                "revenue": 0.0,
                "missing": True,
            })
        else:
            filled.append(dict(row))
    return filled, missing


def _prepare_rows(history: Iterable[Mapping[str, Any]], value_key: str) -> List[Dict[str, Any]]:
    rows = []
    for row in history:
        period = _valid_period(row.get("period") or row.get("year_month"))
        if period:
            rows.append({"period": period, "value": _number(row.get(value_key))})
    return sorted(rows, key=lambda row: row["period"])


def _forecast_rows(rows: List[Dict[str, Any]], periods: int, output_key: str) -> Dict[str, Any]:
    if len(rows) < 3:
        return {
            "status": "insufficient_data",
            "method": "linear_trend",
            "available_history": len(rows),
            "required_history": 3,
            "forecast": [],
            "accuracy": None,
            "assumptions": ["At least three complete monthly observations are required."],
        }

    values = [row["value"] for row in rows]
    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    denominator = sum((x - x_mean) ** 2 for x in range(n))
    slope = sum((x - x_mean) * (values[x] - y_mean) for x in range(n)) / denominator if denominator else 0
    intercept = y_mean - slope * x_mean

    predictions = [max(0.0, intercept + slope * x) for x in range(n)]
    errors = [abs(actual - predicted) / abs(actual) for actual, predicted in zip(values, predictions) if actual]
    accuracy = round(max(0.0, 100 - (sum(errors) / len(errors) * 100)), 1) if errors else None

    last_period = date.fromisoformat(rows[-1]["period"] + "-01")
    forecast: List[Dict[str, Any]] = []
    for offset in range(1, periods + 1):
        month = last_period.month - 1 + offset
        year = last_period.year + month // 12
        month = month % 12 + 1
        forecast.append({
            "period": f"{year:04d}-{month:02d}",
            output_key: round(max(0.0, intercept + slope * (n - 1 + offset)), 2),
        })
    return {
        "status": "ok",
        "method": "linear_trend",
        "available_history": len(rows),
        "history_from": rows[0]["period"],
        "history_to": rows[-1]["period"],
        "forecast": forecast,
        "accuracy": accuracy,
        "assumptions": [
            "Seasonality, promotions, stock-outs, and price changes are not modelled.",
            "Future demand follows the recent linear direction.",
        ],
    }


def forecast_demand(history: Iterable[Mapping[str, Any]], periods: int = 3) -> Dict[str, Any]:
    """Forecast monthly demand using a linear trend and report its limitations.

    History must contain ``period`` (YYYY-MM) and ``quantity``. Fewer than three
    observations is intentionally reported as insufficient rather than guessed.
    """
    return _forecast_rows(_prepare_rows(history, "quantity"), periods, "quantity")


def forecast_revenue(history: Iterable[Mapping[str, Any]], periods: int = 3) -> Dict[str, Any]:
    """Forecast monthly revenue using the same transparent linear-trend method."""
    result = _forecast_rows(_prepare_rows(history, "revenue"), periods, "revenue")
    result["metric"] = "revenue"
    return result


def forecast_product_demand(product_id: str, periods: int = 3) -> Dict[str, Any]:
    """Load product history without exposing customer data to the forecast."""
    from .connection import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT LEFT(s.SALES_DATE, 7) AS period, SUM(sd.QTY) AS quantity
                FROM sales_details sd
                JOIN sales s ON s.SALES_ID = sd.SALES_ID
                WHERE sd.PRODUCT_ID = %s AND s.SALES_DATE IS NOT NULL
                GROUP BY LEFT(s.SALES_DATE, 7)
                ORDER BY period
                """,
                (product_id,),
            )
            result = forecast_demand(cur.fetchall(), periods)
    result["product_id"] = product_id
    return result
