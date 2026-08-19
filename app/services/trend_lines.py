from __future__ import annotations

import pandas as pd
from uuid import uuid4

from app.analytics.trend_lines import optimize_trend_channel
from app.analytics.trend_lines_v2 import (
    analyze_trend_channel_v2, backtest_breakouts, compare_lookbacks,
)
from app.db import Repository


class TrendLineService:
    """Calculate trend channels from saved bars without contacting IBKR."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def calculate(self, symbol: str, lookback: int) -> tuple[dict, pd.DataFrame]:
        bars = self._bars(symbol)
        result, chart = optimize_trend_channel(bars, symbol, lookback)
        self.repo.save_optimized_trend_line(result)
        return result, chart

    def _bars(self, symbol: str) -> pd.DataFrame:
        bars = self.repo.market_confirmation_bars((symbol.upper(),))
        if bars.empty:
            raise ValueError(
                f"No saved daily bars are available for {symbol.upper()}."
            )
        official = bars.loc[
            bars["source"].fillna("").astype(str).str.lower().eq("ibkr")
        ].copy()
        if official.empty:
            raise ValueError(
                f"No saved IBKR daily bars are available for {symbol.upper()}; "
                "mock rows are excluded."
            )
        return official

    def calculate_v2(
        self, symbol: str, lookback: int, mode: str = "strict"
    ) -> tuple[dict, pd.DataFrame]:
        result, chart = analyze_trend_channel_v2(
            self._bars(symbol), symbol, lookback, mode
        )
        self.repo.save_optimized_trend_line(result)
        return result, chart

    def compare_v2(self, symbol: str, mode: str = "strict") -> pd.DataFrame:
        return compare_lookbacks(self._bars(symbol), symbol, mode=mode)

    def backtest_v2(
        self, symbol: str, lookback: int, mode: str, forward_days: int
    ) -> tuple[dict, pd.DataFrame]:
        summary, signals = backtest_breakouts(
            self._bars(symbol), symbol, lookback, mode, forward_days
        )
        run_id = uuid4().hex
        summary = {"run_id": run_id, **summary}
        stored = signals.copy()
        if not stored.empty:
            stored.insert(0, "run_id", run_id)
        self.repo.save_trend_line_backtest(summary, stored)
        return summary, signals

    def saved(self, symbol: str, lookback: int | None = None) -> pd.DataFrame:
        return self.repo.optimized_trend_lines(symbol, lookback)
