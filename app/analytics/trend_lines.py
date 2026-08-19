from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

import numpy as np
import pandas as pd


ALGORITHM_VERSION = "constrained_log_channel_v1"


@dataclass(frozen=True)
class _LineSolution:
    pivot_index: int
    pivot_log_price: float
    slope: float
    intercept: float
    lower_bound: float
    upper_bound: float


def _bounded_line(
    target: np.ndarray,
    pivot_index: int,
    *,
    side: str,
) -> _LineSolution:
    x = np.arange(len(target), dtype=float)
    dx = x - float(pivot_index)
    anchor = float(target[pivot_index])
    differences = target - anchor
    lower, upper = -math.inf, math.inf
    for delta_x, difference in zip(dx, differences, strict=True):
        if delta_x == 0:
            continue
        bound = float(difference / delta_x)
        if side == "support":
            if delta_x > 0:
                upper = min(upper, bound)
            else:
                lower = max(lower, bound)
        else:
            if delta_x > 0:
                lower = max(lower, bound)
            else:
                upper = min(upper, bound)
    if lower > upper + 1e-12:
        raise ValueError(f"No feasible {side} slope exists for the selected pivot.")
    denominator = float(np.dot(dx, dx))
    unconstrained = (
        float(np.dot(dx, differences) / denominator) if denominator else 0.0
    )
    slope = min(max(unconstrained, lower), upper)
    intercept = anchor - slope * pivot_index
    fitted = intercept + slope * x
    tolerance = 1e-10
    if side == "support" and np.any(fitted > target + tolerance):
        raise ValueError("Support-line constraint validation failed.")
    if side == "resistance" and np.any(fitted < target - tolerance):
        raise ValueError("Resistance-line constraint validation failed.")
    return _LineSolution(
        pivot_index, anchor, slope, intercept, lower, upper
    )


def optimize_trend_channel(
    bars: pd.DataFrame,
    symbol: str,
    lookback: int,
) -> tuple[dict, pd.DataFrame]:
    """Return a strict log-price support/resistance channel and chart rows."""
    if not 20 <= int(lookback) <= 504:
        raise ValueError("Lookback must be between 20 and 504 trading days.")
    required = ["bar_date", "open", "high", "low", "close"]
    missing = [column for column in required if column not in bars.columns]
    if missing:
        raise ValueError("Missing OHLC columns: " + ", ".join(missing))
    clean = bars.copy()
    if "symbol" in clean.columns:
        clean = clean.loc[clean["symbol"].astype(str).str.upper().eq(symbol.upper())]
    clean["bar_date"] = pd.to_datetime(clean["bar_date"], errors="coerce")
    clean = clean.dropna(subset=required).sort_values("bar_date")
    clean = clean.drop_duplicates("bar_date", keep="last")
    for column in ("open", "high", "low", "close"):
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    clean = clean.dropna(subset=["open", "high", "low", "close"])
    if len(clean) < lookback:
        raise ValueError(
            f"{symbol.upper()} needs {lookback} valid daily bars; only {len(clean)} are saved."
        )
    window = clean.tail(lookback).reset_index(drop=True).copy()
    if (window[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Log-price trend lines require strictly positive OHLC values.")
    if (window["high"] < window["low"]).any():
        raise ValueError("At least one daily bar has High below Low.")
    if (
        (window["close"] < window["low"]) | (window["close"] > window["high"])
        | (window["open"] < window["low"]) | (window["open"] > window["high"])
    ).any():
        raise ValueError("At least one daily bar has Open/Close outside its High-Low range.")

    x = np.arange(lookback, dtype=float)
    log_close = np.log(window["close"].to_numpy(dtype=float))
    log_low = np.log(window["low"].to_numpy(dtype=float))
    log_high = np.log(window["high"].to_numpy(dtype=float))
    ols_slope, ols_intercept = np.polyfit(x, log_close, 1)
    ols = ols_intercept + ols_slope * x
    support_pivot = int(np.argmin(log_low - ols))
    resistance_pivot = int(np.argmax(log_high - ols))
    support = _bounded_line(log_low, support_pivot, side="support")
    resistance = _bounded_line(log_high, resistance_pivot, side="resistance")

    support_log = support.intercept + support.slope * x
    resistance_log = resistance.intercept + resistance.slope * x
    window["support"] = np.exp(support_log)
    window["resistance"] = np.exp(resistance_log)
    window["ols_close"] = np.exp(ols)
    latest_close = float(window.iloc[-1]["close"])
    support_current = float(window.iloc[-1]["support"])
    resistance_current = float(window.iloc[-1]["resistance"])
    channel_width = resistance_current - support_current
    channel_position = (
        (latest_close - support_current) / channel_width
        if channel_width > 0 else None
    )
    distance_to_support = latest_close / support_current - 1
    distance_to_resistance = resistance_current / latest_close - 1
    if latest_close > resistance_current * (1 + 1e-10):
        status = "Above resistance / 阻力线上方"
    elif latest_close < support_current * (1 - 1e-10):
        status = "Below support / 支撑线下方"
    elif channel_position is not None and channel_position >= 0.8:
        status = "Testing resistance / 接近阻力"
    elif channel_position is not None and channel_position <= 0.2:
        status = "Testing support / 接近支撑"
    else:
        status = "Inside channel / 通道内部"
    daily_change = window["close"].pct_change().abs()
    warnings: list[str] = []
    if bool((daily_change > 0.5).any()):
        warnings.append(
            "Price jump above 50% detected; verify split adjustment. / "
            "发现超过50%的单日价格跳变，请核实拆股复权。"
        )
    channel_width_ratio = channel_width / latest_close
    if channel_width_ratio > 0.75:
        warnings.append(
            f"Very wide strict channel ({channel_width_ratio:.1%} of latest Close); "
            "the window likely spans multiple price regimes or an influential pivot. "
            "Compare a shorter Lookback before using the levels. / "
            f"严格通道非常宽（相当于最新收盘价的{channel_width_ratio:.1%}）；窗口可能跨越"
            "多个价格状态或受到关键支点显著影响，请对比更短Lookback后再使用。"
        )
    elif channel_width_ratio > 0.40:
        warnings.append(
            f"Wide strict channel ({channel_width_ratio:.1%} of latest Close); "
            "interpret the levels cautiously. / "
            f"严格通道较宽（相当于最新收盘价的{channel_width_ratio:.1%}），请谨慎解读。"
        )
    warning = " ".join(warnings)
    calculated_at = datetime.now(timezone.utc)
    result = {
        "symbol": symbol.upper(),
        "calculation_date": window.iloc[-1]["bar_date"].date(),
        "lookback": int(lookback), "algorithm_version": ALGORITHM_VERSION,
        "price_transform": "natural_log", "constraint_mode": "strict",
        "window_start": window.iloc[0]["bar_date"].date(),
        "window_end": window.iloc[-1]["bar_date"].date(),
        "ols_slope": float(ols_slope), "ols_intercept": float(ols_intercept),
        "support_pivot_date": window.iloc[support_pivot]["bar_date"].date(),
        "support_pivot_price": float(window.iloc[support_pivot]["low"]),
        "support_slope": support.slope, "support_intercept": support.intercept,
        "support_current": support_current,
        "resistance_pivot_date": window.iloc[resistance_pivot]["bar_date"].date(),
        "resistance_pivot_price": float(window.iloc[resistance_pivot]["high"]),
        "resistance_slope": resistance.slope,
        "resistance_intercept": resistance.intercept,
        "resistance_current": resistance_current,
        "latest_close": latest_close, "channel_width": channel_width,
        "channel_position": channel_position,
        "distance_to_support": distance_to_support,
        "distance_to_resistance": distance_to_resistance,
        "status": status, "data_warning": warning,
        "calculated_at": calculated_at,
    }
    return result, window
