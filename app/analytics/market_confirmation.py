from __future__ import annotations

import pandas as pd


def normalize_market_prices(frame: pd.DataFrame) -> pd.DataFrame:
    """Rebase each symbol's close to 100 at its first visible observation."""
    if frame.empty:
        return frame.copy()
    result = frame.sort_values(["symbol", "bar_date"]).copy()
    first_close = result.groupby("symbol")["close"].transform("first")
    result["normalized_close"] = result["close"] / first_close * 100
    return result


def market_return_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Return latest close and trailing changes without creating a score."""
    columns = [
        "symbol", "asset_name", "asset_name_cn", "market_role",
        "market_role_cn", "bar_date", "close", "return_1d",
        "return_20d", "return_63d", "source",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for symbol, group in frame.groupby("symbol", sort=True):
        ordered = group.sort_values("bar_date").reset_index(drop=True)
        latest = ordered.iloc[-1]

        def trailing(periods: int) -> float | None:
            if len(ordered) <= periods:
                return None
            prior = ordered.iloc[-periods - 1]["close"]
            return float(latest["close"] / prior - 1) if prior else None

        rows.append(
            {
                "symbol": symbol,
                "asset_name": latest["asset_name"],
                "asset_name_cn": latest["asset_name_cn"],
                "market_role": latest["market_role"],
                "market_role_cn": latest["market_role_cn"],
                "bar_date": latest["bar_date"],
                "close": latest["close"],
                "return_1d": trailing(1),
                "return_20d": trailing(20),
                "return_63d": trailing(63),
                "source": latest["source"],
            }
        )
    return pd.DataFrame(rows, columns=columns)
