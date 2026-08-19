import numpy as np
import pandas as pd
import pytest

from app.analytics.trend_lines import ALGORITHM_VERSION, optimize_trend_channel


def _bars(count=260, daily_growth=0.001):
    x = np.arange(count, dtype=float)
    center = 100 * np.exp(daily_growth * x)
    return pd.DataFrame({
        "symbol": "TEST", "bar_date": pd.bdate_range("2025-01-01", periods=count),
        "open": center * .995, "high": center * (1.02 + .005 * np.sin(x / 7)),
        "low": center * (.98 - .005 * np.cos(x / 9)), "close": center,
        "volume": 1_000_000,
    })


@pytest.mark.parametrize("growth", [0.001, -0.001, 0.0])
def test_strict_channel_encloses_all_prices(growth):
    result, chart = optimize_trend_channel(_bars(daily_growth=growth), "TEST", 120)
    assert (chart["support"] <= chart["low"] + 1e-8).all()
    assert (chart["resistance"] >= chart["high"] - 1e-8).all()
    assert result["algorithm_version"] == ALGORITHM_VERSION
    assert result["window_start"] < result["window_end"]


def test_result_is_deterministic_and_uses_requested_lookback():
    first, first_chart = optimize_trend_channel(_bars(), "TEST", 60)
    second, second_chart = optimize_trend_channel(_bars(), "TEST", 60)
    assert len(first_chart) == 60
    assert first["support_slope"] == second["support_slope"]
    assert first["resistance_slope"] == second["resistance_slope"]
    pd.testing.assert_series_equal(first_chart["support"], second_chart["support"])


def test_duplicate_dates_are_deduplicated():
    bars = pd.concat([_bars(), _bars().tail(1)], ignore_index=True)
    _, chart = optimize_trend_channel(bars, "TEST", 252)
    assert len(chart) == 252
    assert chart["bar_date"].is_unique


def test_rejects_insufficient_or_non_positive_prices():
    with pytest.raises(ValueError, match="only 30 are saved"):
        optimize_trend_channel(_bars(30), "TEST", 60)
    invalid = _bars()
    invalid.loc[invalid.index[-1], "low"] = 0
    with pytest.raises(ValueError, match="strictly positive"):
        optimize_trend_channel(invalid, "TEST", 120)


def test_very_wide_channel_is_flagged_without_changing_constraints():
    bars = _bars(120)
    bars.loc[60, ["open", "high", "low", "close"]] = [390, 410, 380, 400]
    result, chart = optimize_trend_channel(bars, "TEST", 120)
    assert "wide strict channel" in result["data_warning"].lower()
    assert (chart["support"] <= chart["low"] + 1e-8).all()
    assert (chart["resistance"] >= chart["high"] - 1e-8).all()
