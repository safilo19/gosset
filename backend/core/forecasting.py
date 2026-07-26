"""forecast_timeseries logic (exponential smoothing / ARIMA / auto). Plain Python — no MCP or web-framework code."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

_FREQ_SEASONAL_PERIOD = {
    "D": 7,
    "B": 5,
    "W": 52,
    "M": 12,
    "MS": 12,
    "Q": 4,
    "QS": 4,
    "A": 1,
    "Y": 1,
}


@dataclass
class ForecastSeries:
    values: pd.Series
    dates: pd.DatetimeIndex
    inferred_freq: str | None
    seasonal_period: int | None
    step: pd.Timedelta


def prepare_series(df: pd.DataFrame, date_col: str, value_col: str) -> ForecastSeries:
    if not pd.api.types.is_numeric_dtype(df[value_col]):
        raise ValueError(f"forecast_timeseries needs a numeric value column; '{value_col}' has dtype {df[value_col].dtype}.")

    try:
        dates = pd.to_datetime(df[date_col], errors="raise")
    except (ValueError, TypeError) as e:
        raise ValueError(f"Column '{date_col}' could not be parsed as dates: {e}") from e

    sub = pd.DataFrame({"date": dates, "value": df[value_col]}).dropna().sort_values("date")
    sub = sub.drop_duplicates(subset="date", keep="last")

    if len(sub) < 4:
        raise ValueError(f"Not enough data to forecast: found {len(sub)} point(s) with valid date+value, need at least 4.")

    date_index = pd.DatetimeIndex(sub["date"])
    inferred_freq = pd.infer_freq(date_index)

    seasonal_period = None
    if inferred_freq:
        prefix = inferred_freq.split("-")[0]
        seasonal_period = _FREQ_SEASONAL_PERIOD.get(prefix)

    deltas = date_index.to_series().diff().dropna()
    step = deltas.median() if not deltas.empty else pd.Timedelta(days=1)

    return ForecastSeries(
        values=pd.Series(sub["value"].to_numpy()),
        dates=date_index,
        inferred_freq=inferred_freq,
        seasonal_period=seasonal_period,
        step=step,
    )


def detect_trend(values: pd.Series) -> bool:
    slope_test = scipy_stats.linregress(np.arange(len(values)), values.to_numpy())
    return bool(slope_test.pvalue < 0.05)


def choose_method(series: ForecastSeries, requested: str) -> tuple[str, str, bool, bool]:
    """Returns (method, reason, has_trend, has_seasonality)."""
    n = len(series.values)
    has_trend = detect_trend(series.values)
    m = series.seasonal_period
    has_seasonality = bool(m and m > 1 and n >= 2 * m)

    if requested != "auto":
        reason = f"Using the requested method ({requested})."
        return requested, reason, has_trend, has_seasonality

    if n < 10:
        return (
            "exponential_smoothing",
            f"Series is short (n={n}); exponential smoothing is more robust than an ARIMA order search on little data.",
            has_trend,
            has_seasonality,
        )
    if has_seasonality:
        cycles = n / m
        return (
            "exponential_smoothing",
            f"Detected seasonality (period≈{m}, ~{cycles:.1f} cycles of history); using Holt-Winters "
            f"exponential smoothing to explicitly model the seasonal pattern.",
            has_trend,
            has_seasonality,
        )
    if has_trend:
        return (
            "arima",
            "Detected a trend without clear seasonality; using ARIMA to model the trend and autocorrelation.",
            has_trend,
            has_seasonality,
        )
    return (
        "exponential_smoothing",
        "No strong trend or seasonality detected; using exponential smoothing for a stable forecast.",
        has_trend,
        has_seasonality,
    )


def forecast_exponential_smoothing(
    series: ForecastSeries, periods: int, has_trend: bool, has_seasonality: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    seasonal_periods = series.seasonal_period if has_seasonality else None
    model = ETSModel(
        series.values,
        error="add",
        trend="add" if has_trend else None,
        seasonal="add" if has_seasonality else None,
        seasonal_periods=seasonal_periods,
    ).fit(disp=False)

    n = len(series.values)
    pred = model.get_prediction(start=n, end=n + periods - 1)
    frame = pred.summary_frame(alpha=0.05)
    return frame["mean"].to_numpy(), frame["pi_lower"].to_numpy(), frame["pi_upper"].to_numpy()


def _best_arima_order(values: pd.Series) -> tuple[int, int, int]:
    """Minimal internal grid search (no external auto-arima dependency)."""
    best_order = (1, 1, 1)
    best_aic = np.inf
    with warnings.catch_warnings():
        # Non-convergent candidate orders are expected during the search; only the winning order is used.
        warnings.simplefilter("ignore")
        for p in range(0, 3):
            for d in range(0, 2):
                for q in range(0, 3):
                    if p == 0 and q == 0:
                        continue
                    try:
                        fitted = ARIMA(values, order=(p, d, q)).fit()
                    except Exception:
                        continue
                    if fitted.aic < best_aic:
                        best_aic = fitted.aic
                        best_order = (p, d, q)
    return best_order


def forecast_arima(series: ForecastSeries, periods: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    order = _best_arima_order(series.values)
    model = ARIMA(series.values, order=order).fit()
    fc = model.get_forecast(steps=periods)
    mean = fc.predicted_mean.to_numpy()
    ci = fc.conf_int(alpha=0.05)
    lower = ci.iloc[:, 0].to_numpy()
    upper = ci.iloc[:, 1].to_numpy()
    return mean, lower, upper


def forecast_period_labels(series: ForecastSeries, periods: int) -> list[str]:
    last_date = series.dates[-1]
    is_date_only = series.step >= pd.Timedelta(days=1)

    if series.inferred_freq:
        # Calendar-aware stepping (handles variable month/quarter lengths correctly).
        future_dates = pd.date_range(start=last_date, periods=periods + 1, freq=series.inferred_freq)[1:]
    else:
        future_dates = [last_date + series.step * i for i in range(1, periods + 1)]

    return [d.date().isoformat() if is_date_only else d.isoformat() for d in future_dates]


@dataclass
class ForecastPointResult:
    period: str
    forecast: float
    lower_ci: float
    upper_ci: float


@dataclass
class ForecastOutcome:
    method_used: str
    method_reason: str
    inferred_frequency: str | None
    history_length: int
    confidence_level: float
    points: list[ForecastPointResult]
    summary: str
    content_lines: list[str]


def run_forecast(
    df: pd.DataFrame, date_column: str, value_column: str, periods: int, method: str, dataset_id: str
) -> ForecastOutcome:
    series = prepare_series(df, date_column, value_column)
    method_used, reason, has_trend, has_seasonality = choose_method(series, method)

    if method_used == "arima":
        mean, lower, upper = forecast_arima(series, periods)
    else:
        mean, lower, upper = forecast_exponential_smoothing(series, periods, has_trend, has_seasonality)

    labels = forecast_period_labels(series, periods)
    points = [
        ForecastPointResult(period=label, forecast=float(m), lower_ci=float(lo), upper_ci=float(hi))
        for label, m, lo, hi in zip(labels, mean, lower, upper)
    ]

    next_value_line = f"Next value: {points[0].forecast:.4g} (95% CI [{points[0].lower_ci:.4g}, {points[0].upper_ci:.4g}])."

    summary = (
        f"Forecasted {periods} period(s) of '{value_column}' from dataset '{dataset_id}' "
        f"using {method_used} ({len(series.values)} historical point(s)). {reason} {next_value_line}"
    )
    content_lines = [
        f"Forecasted {periods} period(s) of '{value_column}' using {method_used}.",
        reason,
        next_value_line,
    ]

    return ForecastOutcome(
        method_used=method_used,
        method_reason=reason,
        inferred_frequency=series.inferred_freq,
        history_length=len(series.values),
        confidence_level=0.95,
        points=points,
        summary=summary,
        content_lines=content_lines,
    )
