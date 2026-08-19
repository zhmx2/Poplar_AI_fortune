import numpy as np
import pandas as pd

from app.analytics.trend_lines_v2 import (
    analyze_trend_channel_v2, backtest_breakouts, compare_lookbacks,
)


def bars(count=320):
    x = np.arange(count, dtype=float)
    close = 100 * np.exp(.001 * x + .04 * np.sin(x / 13))
    return pd.DataFrame({
        "symbol": "TEST", "bar_date": pd.bdate_range("2025-01-01", periods=count),
        "open": close * .995, "high": close * 1.015, "low": close * .985,
        "close": close, "volume": 1_000_000,
    })


def test_v2_projects_two_confirmation_days_and_calculates_atr_touches():
    result, chart = analyze_trend_channel_v2(bars(), "TEST", 120, "strict")
    assert len(chart) == 122
    assert result["confirmation_days"] == 2
    assert result["atr_buffer"] > 0
    assert result["support_touches"] >= 1
    assert result["resistance_touches"] >= 1
    assert "breakout" in result["breakout_status"].lower()


def test_robust_mode_reduces_single_wick_influence():
    frame = bars()
    frame.loc[250, "high"] = frame.loc[250, "close"] * 3
    strict, _ = analyze_trend_channel_v2(frame, "TEST", 60, "strict")
    robust, _ = analyze_trend_channel_v2(frame, "TEST", 60, "robust")
    assert robust["constraint_mode"] == "robust"
    assert robust["resistance_current"] < strict["resistance_current"]


def test_comparison_and_backtest_return_auditable_frames():
    comparison = compare_lookbacks(bars(), "TEST", (20, 60, 120), "strict")
    summary, signals = backtest_breakouts(bars(), "TEST", 20, "strict", 5)
    assert set(comparison["lookback"]) == {20, 60, 120}
    assert summary["forward_days"] == 5
    assert isinstance(signals, pd.DataFrame)
