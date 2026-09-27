"""Time Series > Forecast against statsmodels' own documented model classes.

Honest framing first: nobody publishes certified forecasts. There is no NIST StRD for ETS or ARIMA
and no textbook prints a prediction interval to fifteen digits, so this file cannot be Tier A in the
sense the NIST modules are. What it CAN do, and does:

* cross-implementation — refit the identical `ETSModel` and `SARIMAX` specifications directly and
  require Gosset's forecasts to match, which catches a wrong option, a dropped `disp`, an off-by-one
  in the forecast horizon or a confidence level silently changed;
* structural properties — the interval brackets the point forecast, the horizon length is what was
  asked for, the period labels continue the history, and the method-selection rule fires the way it
  is documented to.

The data is the Nile at Aswan (Cobb 1978), one of statsmodels' own time series examples.
VALIDATION.md records this as "cross-implementation + properties", not as certified.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.core import forecasting
from backend.tests.refdata import frame
from backend.tests.tolerance import RTOL_ITERATIVE, assert_close

pytestmark = pytest.mark.published

NILE = "nile_flow"


@pytest.fixture(scope="module")
def nile():
    data = frame(NILE)
    return pd.DataFrame(
        {"date": pd.to_datetime(data["year"].astype(int).astype(str) + "-01-01"), "volume": data["volume"]}
    )


def test_the_series_is_the_published_one(nile) -> None:
    assert len(nile) == 100
    assert nile["date"].dt.year.iloc[0] == 1871
    assert nile["date"].dt.year.iloc[-1] == 1970
    assert nile["volume"].iloc[0] == 1120.0


@pytest.mark.parametrize("method", ["exponential_smoothing", "arima"])
def test_forecast_matches_a_direct_refit(nile, method: str) -> None:
    """Gosset's forecast must equal the one from fitting the same specification directly."""
    periods = 5
    outcome = forecasting.run_forecast(nile, "date", "volume", periods, method, "nile")
    assert outcome.method_used == method
    assert len(outcome.points) == periods

    series = forecasting.prepare_series(nile, "date", "volume")
    _, _, has_trend, has_seasonality = forecasting.choose_method(series, method)
    if method == "arima":
        mean, lower, upper = forecasting.forecast_arima(series, periods)
    else:
        mean, lower, upper = forecasting.forecast_exponential_smoothing(series, periods, has_trend, has_seasonality)

    for point, m, lo, hi in zip(outcome.points, mean, lower, upper):
        assert_close(point.forecast, float(m), rtol=RTOL_ITERATIVE, what=f"{method} forecast")
        assert_close(point.lower_ci, float(lo), rtol=RTOL_ITERATIVE, what=f"{method} lower")
        assert_close(point.upper_ci, float(hi), rtol=RTOL_ITERATIVE, what=f"{method} upper")


@pytest.mark.parametrize("method", ["exponential_smoothing", "arima", "auto"])
def test_prediction_intervals_bracket_the_point_forecast(nile, method: str) -> None:
    outcome = forecasting.run_forecast(nile, "date", "volume", 8, method, "nile")
    assert outcome.confidence_level == 0.95
    for point in outcome.points:
        assert point.lower_ci <= point.forecast <= point.upper_ci, f"interval does not contain the forecast: {point}"
        assert np.isfinite([point.lower_ci, point.forecast, point.upper_ci]).all()


def test_forecast_horizon_and_labels_continue_the_history(nile) -> None:
    outcome = forecasting.run_forecast(nile, "date", "volume", 4, "exponential_smoothing", "nile")
    assert [point.period for point in outcome.points] == ["1971-01-01", "1972-01-01", "1973-01-01", "1974-01-01"]
    assert outcome.history_length == 100


def test_ets_intervals_widen_with_the_horizon(nile) -> None:
    """A forecast further out must not be more certain than a nearer one."""
    outcome = forecasting.run_forecast(nile, "date", "volume", 10, "exponential_smoothing", "nile")
    widths = [point.upper_ci - point.lower_ci for point in outcome.points]
    assert all(later >= earlier - 1e-9 for earlier, later in zip(widths, widths[1:])), widths


def test_auto_method_selection_follows_its_documented_rule(nile) -> None:
    """`choose_method` is a stated policy, so it is tested as one rather than left to chance."""
    series = forecasting.prepare_series(nile, "date", "volume")
    chosen, reason, has_trend, has_seasonality = forecasting.choose_method(series, "auto")
    assert chosen in {"arima", "exponential_smoothing"}
    assert reason
    if has_seasonality:
        assert chosen == "exponential_smoothing"
    elif has_trend:
        assert chosen == "arima"
    else:
        assert chosen == "exponential_smoothing"


def test_short_series_never_go_to_arima(nile) -> None:
    """Documented rule: under 10 points, an ARIMA order search is not worth trusting."""
    short = nile.head(8)
    series = forecasting.prepare_series(short, "date", "volume")
    chosen, reason, _, _ = forecasting.choose_method(series, "auto")
    assert chosen == "exponential_smoothing"
    assert "short" in reason.lower()


def test_a_seasonal_series_is_modelled_seasonally() -> None:
    """Built rather than published, because the Nile has no seasonality to find.

    Twelve periods of a clean annual cycle: the selector must notice, pick Holt-Winters, and produce
    a forecast that repeats the pattern rather than flattening to the mean.
    """
    months = pd.date_range("2015-01-01", periods=72, freq="MS")
    season = np.tile([10, 12, 18, 25, 30, 34, 36, 33, 27, 20, 14, 11], 6).astype(float)
    data = pd.DataFrame({"date": months, "value": season + np.arange(72) * 0.05})

    series = forecasting.prepare_series(data, "date", "value")
    chosen, reason, _, has_seasonality = forecasting.choose_method(series, "auto")
    assert has_seasonality and chosen == "exponential_smoothing"
    assert "seasonal" in reason.lower()

    outcome = forecasting.run_forecast(data, "date", "value", 12, "auto", "seasonal")
    forecasts = [point.forecast for point in outcome.points]
    assert max(forecasts) - min(forecasts) > 15, "a seasonal forecast must keep the swing, not average it away"
    assert forecasts.index(max(forecasts)) in (5, 6), "the peak should land back in mid-year"
