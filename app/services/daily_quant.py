from __future__ import annotations

import pandas as pd

from app.analytics.daily_quant import calculate_daily_quant
from app.config import Settings
from app.db import Repository
from app.services.ibkr import IBKRService


class DailyQuantService:
    BENCHMARKS = ("SPY", "QQQ", "SOXX")

    def __init__(self, settings: Settings, ibkr: IBKRService, repo: Repository):
        self.settings, self.ibkr, self.repo = settings, ibkr, repo

    def sync(self, symbol: str, progress=None) -> pd.DataFrame:
        symbols = tuple(dict.fromkeys((symbol.upper(), *self.BENCHMARKS)))
        return self._sync_bars(symbols, progress)

    def sync_watchlist(self, symbols, progress=None) -> pd.DataFrame:
        targets = tuple(dict.fromkeys(
            str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()
        ))
        if not targets:
            raise ValueError("VOLATILITY_WATCHLIST contains no stock symbols.")
        request_symbols = tuple(dict.fromkeys((*targets, *self.BENCHMARKS)))
        fetched = self._sync_bars(request_symbols, progress)
        fetched_counts = fetched.groupby("symbol").size().to_dict()

        rows = []
        for index, symbol in enumerate(targets, start=1):
            if progress:
                progress(
                    f"Calculating {symbol} ({index}/{len(targets)}) / "
                    f"正在计算 {symbol}（{index}/{len(targets)}）"
                )
            try:
                snapshot, _ = self.report(symbol)
                rows.append({
                    "symbol": symbol,
                    "status": "SUCCESS",
                    "bar_count": int(fetched_counts.get(symbol, 0)),
                    "data_date": snapshot["bar_date"],
                    "overall_score": snapshot["overall_score"],
                    "regime": snapshot["regime"],
                    "message": "Daily bars saved and analysis calculated.",
                })
            except Exception as exc:
                rows.append({
                    "symbol": symbol,
                    "status": "FAILED",
                    "bar_count": int(fetched_counts.get(symbol, 0)),
                    "data_date": None,
                    "overall_score": None,
                    "regime": None,
                    "message": f"{type(exc).__name__}: {exc}",
                })
        return pd.DataFrame(rows)

    def _sync_bars(self, symbols, progress=None) -> pd.DataFrame:
        results = self.ibkr.historical_daily_bars_batch(
            symbols, self.settings.daily_quant_lookback_years, progress
        )
        frames, errors = [], []
        for current, result in results.items():
            if isinstance(result, Exception):
                errors.append(f"{current}: {type(result).__name__}: {result}")
            elif not result.empty:
                enriched = result.copy()
                enriched["asset_name"] = current
                enriched["asset_name_cn"] = current
                enriched["market_role"] = "Daily quant"
                enriched["market_role_cn"] = "日线量化"
                frames.append(enriched[[
                    "symbol", "asset_name", "asset_name_cn", "market_role",
                    "market_role_cn", "bar_date", "open", "high", "low",
                    "close", "volume", "source", "fetched_at",
                ]])
        if not frames:
            raise ValueError("IBKR returned no daily bars. " + "; ".join(errors[:3]))
        frame = pd.concat(frames, ignore_index=True)
        self.repo.save_market_confirmation_bars(frame)
        return frame

    def report(self, symbol: str) -> tuple[dict, pd.DataFrame]:
        symbols = tuple(dict.fromkeys((symbol.upper(), *self.BENCHMARKS)))
        bars = self.repo.market_confirmation_bars(symbols)
        bars = bars.loc[bars["source"].astype(str).str.lower().eq("ibkr")].copy()
        return calculate_daily_quant(bars, symbol, self.BENCHMARKS)
