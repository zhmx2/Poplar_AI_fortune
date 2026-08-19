from __future__ import annotations

from datetime import datetime, timezone
import math

import numpy as np
import pandas as pd

from app.analytics.trend_lines import optimize_trend_channel


V2_ALGORITHM_VERSION = "projected_atr_channel_v2"
ATR_MULTIPLIER = 0.25
CONFIRMATION_DAYS = 2
ROBUST_TAIL_FRACTION = 0.02


def _clean(bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    frame = bars.copy()
    if "symbol" in frame:
        frame = frame.loc[frame["symbol"].astype(str).str.upper().eq(symbol.upper())]
    frame["bar_date"] = pd.to_datetime(frame["bar_date"], errors="coerce")
    columns = ["bar_date", "open", "high", "low", "close"]
    frame = frame.dropna(subset=columns).sort_values("bar_date")
    frame = frame.drop_duplicates("bar_date", keep="last").reset_index(drop=True)
    return frame


def _atr(frame: pd.DataFrame, window: int = 14) -> pd.Series:
    prior = frame["close"].shift(1)
    tr = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - prior).abs(),
        (frame["low"] - prior).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def _robust_training(training: pd.DataFrame) -> pd.DataFrame:
    result = training.copy().reset_index(drop=True)
    x = np.arange(len(result), dtype=float)
    log_close = np.log(result["close"].to_numpy(float))
    slope, intercept = np.polyfit(x, log_close, 1)
    ols = intercept + slope * x
    log_low = np.log(result["low"].to_numpy(float))
    log_high = np.log(result["high"].to_numpy(float))
    low_floor = float(np.quantile(log_low - ols, ROBUST_TAIL_FRACTION))
    high_ceiling = float(np.quantile(log_high - ols, 1 - ROBUST_TAIL_FRACTION))
    adjusted_low = np.exp(np.maximum(log_low, ols + low_floor))
    adjusted_high = np.exp(np.minimum(log_high, ols + high_ceiling))
    result["low"] = np.minimum(adjusted_low, np.minimum(result["open"], result["close"]))
    result["high"] = np.maximum(adjusted_high, np.maximum(result["open"], result["close"]))
    return result


def analyze_trend_channel_v2(
    bars: pd.DataFrame,
    symbol: str,
    lookback: int,
    mode: str = "strict",
) -> tuple[dict, pd.DataFrame]:
    if mode not in {"strict", "robust"}:
        raise ValueError("Mode must be strict or robust.")
    full = _clean(bars, symbol)
    needed = lookback + CONFIRMATION_DAYS
    if len(full) < needed:
        raise ValueError(
            f"{symbol.upper()} needs {needed} valid daily bars for V2; only {len(full)} are saved."
        )
    sample = full.tail(needed).reset_index(drop=True)
    training_original = sample.iloc[:-CONFIRMATION_DAYS].copy().reset_index(drop=True)
    training_fit = (
        _robust_training(training_original) if mode == "robust"
        else training_original.copy()
    )
    base, fitted = optimize_trend_channel(training_fit, symbol, lookback)
    fitted[["open", "high", "low", "close"]] = training_original[
        ["open", "high", "low", "close"]
    ].to_numpy()
    x_future = np.arange(lookback, needed, dtype=float)
    confirmation = sample.iloc[-CONFIRMATION_DAYS:].copy().reset_index(drop=True)
    confirmation["support"] = np.exp(
        base["support_intercept"] + base["support_slope"] * x_future
    )
    confirmation["resistance"] = np.exp(
        base["resistance_intercept"] + base["resistance_slope"] * x_future
    )
    confirmation["ols_close"] = np.exp(
        base["ols_intercept"] + base["ols_slope"] * x_future
    )
    chart = pd.concat([fitted, confirmation], ignore_index=True)
    chart["atr14"] = _atr(chart)
    latest_atr = float(chart.iloc[-1]["atr14"])
    if not math.isfinite(latest_atr):
        raise ValueError("ATR14 is unavailable for the selected window.")
    buffer_value = ATR_MULTIPLIER * latest_atr
    above = confirmation["close"] > confirmation["resistance"] + buffer_value
    below = confirmation["close"] < confirmation["support"] - buffer_value
    if bool(above.all()):
        breakout = "Confirmed upside breakout / 确认向上突破"
    elif bool(below.all()):
        breakout = "Confirmed downside breakdown / 确认向下跌破"
    elif bool(above.iloc[-1]):
        breakout = "Potential upside breakout (1/2) / 潜在向上突破（1/2）"
    elif bool(below.iloc[-1]):
        breakout = "Potential downside breakdown (1/2) / 潜在向下跌破（1/2）"
    else:
        breakout = "No confirmed breakout / 无确认突破"
    touch_tolerance = ATR_MULTIPLIER * chart["atr14"]
    train_rows = chart.iloc[:lookback]
    tolerance_rows = touch_tolerance.iloc[:lookback]
    support_touches = int(
        ((train_rows["low"] - train_rows["support"]).abs() <= tolerance_rows).sum()
    )
    resistance_touches = int(
        ((train_rows["high"] - train_rows["resistance"]).abs() <= tolerance_rows).sum()
    )
    latest = chart.iloc[-1]
    support_now, resistance_now = float(latest["support"]), float(latest["resistance"])
    close_now = float(latest["close"])
    width = resistance_now - support_now
    position = (close_now - support_now) / width if width > 0 else None
    warnings: list[str] = []
    if bool((sample["close"].pct_change().abs() > 0.5).any()):
        warnings.append(
            "Price jump above 50% detected; verify split adjustment. / "
            "发现超过50%的单日价格跳变，请核实拆股复权。"
        )
    width_ratio = width / close_now
    if width_ratio > 0.75:
        warnings.append(
            f"Very wide {mode} channel ({width_ratio:.1%} of latest Close); "
            "compare shorter Lookbacks. / "
            f"{mode}通道非常宽（相当于最新收盘价的{width_ratio:.1%}），请对比更短窗口。"
        )
    elif width_ratio > 0.40:
        warnings.append(
            f"Wide {mode} channel ({width_ratio:.1%} of latest Close); "
            "interpret cautiously. / "
            f"{mode}通道较宽（相当于最新收盘价的{width_ratio:.1%}），请谨慎解读。"
        )
    result = dict(base)
    result.update({
        "calculation_date": latest["bar_date"].date(),
        "algorithm_version": V2_ALGORITHM_VERSION,
        "constraint_mode": mode,
        "window_start": training_original.iloc[0]["bar_date"].date(),
        "window_end": latest["bar_date"].date(),
        "support_current": support_now, "resistance_current": resistance_now,
        "latest_close": close_now, "channel_width": width,
        "channel_position": position,
        "distance_to_support": close_now / support_now - 1,
        "distance_to_resistance": resistance_now / close_now - 1,
        "status": breakout, "atr14": latest_atr,
        "atr_buffer": buffer_value, "support_touches": support_touches,
        "resistance_touches": resistance_touches,
        "confirmation_days": CONFIRMATION_DAYS,
        "breakout_status": breakout,
        "robust_outlier_fraction": ROBUST_TAIL_FRACTION if mode == "robust" else 0.0,
        "data_warning": " ".join(warnings),
        "calculated_at": datetime.now(timezone.utc),
    })
    return result, chart


def compare_lookbacks(
    bars: pd.DataFrame, symbol: str, lookbacks=(20, 60, 120, 252), mode="strict"
) -> pd.DataFrame:
    rows = []
    for lookback in lookbacks:
        try:
            result, _ = analyze_trend_channel_v2(bars, symbol, lookback, mode)
            rows.append(result)
        except ValueError:
            continue
    return pd.DataFrame(rows)


def backtest_breakouts(
    bars: pd.DataFrame,
    symbol: str,
    lookback: int,
    mode: str = "strict",
    forward_days: int = 20,
) -> tuple[dict, pd.DataFrame]:
    full = _clean(bars, symbol)
    rows = []
    start = lookback + CONFIRMATION_DAYS
    for end in range(start, len(full) - forward_days + 1):
        result, _ = analyze_trend_channel_v2(full.iloc[:end], symbol, lookback, mode)
        status = result["breakout_status"]
        direction = 1 if status.startswith("Confirmed upside") else -1 if status.startswith("Confirmed downside") else 0
        if direction == 0:
            continue
        entry = float(full.iloc[end - 1]["close"])
        future = float(full.iloc[end + forward_days - 1]["close"])
        raw_return = future / entry - 1
        rows.append({
            "signal_date": full.iloc[end - 1]["bar_date"],
            "direction": "Upside / 向上" if direction == 1 else "Downside / 向下",
            "entry_close": entry, "forward_close": future,
            "forward_return": raw_return,
            "directional_return": raw_return * direction,
            "win": raw_return * direction > 0,
        })
    signals = pd.DataFrame(rows)
    summary = {
        "symbol": symbol.upper(), "lookback": lookback, "mode": mode,
        "forward_days": forward_days, "signal_count": len(signals),
        "win_rate": float(signals["win"].mean()) if not signals.empty else None,
        "average_directional_return": float(signals["directional_return"].mean()) if not signals.empty else None,
        "median_directional_return": float(signals["directional_return"].median()) if not signals.empty else None,
        "calculated_at": datetime.now(timezone.utc),
    }
    return summary, signals
