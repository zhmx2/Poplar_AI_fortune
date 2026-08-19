from __future__ import annotations

import math

import pandas as pd


def _last(series: pd.Series) -> float | None:
    value = series.iloc[-1] if not series.empty else None
    return None if value is None or pd.isna(value) else float(value)


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).rolling(window).mean()
    loss = -change.clip(upper=0).rolling(window).mean()
    rs = gain / loss.replace(0, float("nan"))
    result = 100 - 100 / (1 + rs)
    return result.where(loss.ne(0), 100.0)


def calculate_daily_quant(
    bars: pd.DataFrame,
    symbol: str,
    benchmarks: tuple[str, ...] = ("SPY", "QQQ", "SOXX"),
) -> tuple[dict, pd.DataFrame]:
    """Calculate an auditable daily-factor snapshot and indicator history."""
    stock = bars.loc[bars["symbol"].eq(symbol.upper())].copy()
    stock = stock.sort_values("bar_date").drop_duplicates("bar_date", keep="last")
    stock = stock.dropna(subset=["close"])
    if len(stock) < 201:
        raise ValueError(
            f"{symbol.upper()} needs at least 201 daily bars; only {len(stock)} are saved."
        )
    close = stock["close"].astype(float)
    high = stock["high"].astype(float)
    low = stock["low"].astype(float)
    volume = stock["volume"].astype(float)
    for window in (20, 50, 200):
        stock[f"sma{window}"] = close.rolling(window).mean()
    stock["rsi14"] = _rsi(close)
    stock["return_20d"] = close.pct_change(20)
    stock["return_60d"] = close.pct_change(60)
    log_return = (close / close.shift(1)).apply(
        lambda value: math.log(value) if pd.notna(value) and value > 0 else float("nan")
    )
    stock["hv20"] = log_return.rolling(20).std() * math.sqrt(252)
    stock["hv30"] = log_return.rolling(30).std() * math.sqrt(252)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    stock["atr14_pct"] = true_range.rolling(14).mean() / close
    stock["volume_ratio_20d"] = volume / volume.rolling(20).mean()

    latest = stock.iloc[-1]
    trend_checks = [
        latest["close"] > latest["sma20"],
        latest["close"] > latest["sma50"],
        latest["close"] > latest["sma200"],
        latest["sma20"] > latest["sma50"],
    ]
    trend_score = 25.0 * sum(bool(value) for value in trend_checks)
    rsi = float(latest["rsi14"])
    rsi_score = max(0.0, min(100.0, (rsi - 30.0) / 40.0 * 100.0))
    momentum_score = max(
        0.0,
        min(
            100.0,
            0.4 * rsi_score
            + 0.3 * (50 + float(latest["return_20d"]) * 250)
            + 0.3 * (50 + float(latest["return_60d"]) * 125),
        ),
    )
    volume_ratio = float(latest["volume_ratio_20d"])
    volume_score = max(0.0, min(100.0, 50 + (volume_ratio - 1) * 50))

    relative_values: list[float] = []
    benchmark_details: list[str] = []
    for benchmark in benchmarks:
        peer = bars.loc[bars["symbol"].eq(benchmark)].sort_values("bar_date")
        peer = peer.drop_duplicates("bar_date", keep="last").dropna(subset=["close"])
        if len(peer) < 61:
            continue
        peer_close = peer["close"].astype(float)
        rel20 = float(latest["return_20d"] - peer_close.pct_change(20).iloc[-1])
        rel60 = float(latest["return_60d"] - peer_close.pct_change(60).iloc[-1])
        relative_values.append((rel20 + rel60) / 2)
        benchmark_details.append(f"{benchmark}:20D {rel20:+.1%}, 60D {rel60:+.1%}")
    relative_score = (
        max(0.0, min(100.0, 50 + sum(relative_values) / len(relative_values) * 250))
        if relative_values else 50.0
    )
    overall = (
        trend_score * 0.35 + momentum_score * 0.25
        + relative_score * 0.25 + volume_score * 0.15
    )
    if overall >= 70:
        regime, regime_cn = "Bullish trend", "多头趋势"
    elif overall >= 55:
        regime, regime_cn = "Constructive", "偏强"
    elif overall >= 45:
        regime, regime_cn = "Neutral", "中性"
    elif overall >= 30:
        regime, regime_cn = "Defensive", "偏弱防御"
    else:
        regime, regime_cn = "Bearish", "空头趋势"
    snapshot = {
        "symbol": symbol.upper(), "bar_date": latest["bar_date"],
        "close": float(latest["close"]), "sma20": float(latest["sma20"]),
        "sma50": float(latest["sma50"]), "sma200": float(latest["sma200"]),
        "rsi14": rsi, "return_20d": float(latest["return_20d"]),
        "return_60d": float(latest["return_60d"]),
        "hv20": float(latest["hv20"]), "hv30": float(latest["hv30"]),
        "atr14_pct": float(latest["atr14_pct"]),
        "volume_ratio_20d": volume_ratio, "trend_score": trend_score,
        "momentum_score": momentum_score, "relative_score": relative_score,
        "volume_score": volume_score, "overall_score": overall,
        "regime": regime, "regime_cn": regime_cn,
        "benchmark_detail": "; ".join(benchmark_details) or "Unavailable",
    }
    return snapshot, stock
