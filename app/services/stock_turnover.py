from __future__ import annotations

import json
from collections.abc import Callable
from uuid import uuid4

import pandas as pd

from app.config import Settings
from app.db import Repository
from app.models import utc_now
from app.services.ibkr import IBKRService


class StockTurnoverService:
    """Estimate stock dollar turnover; never requests option contracts."""

    def __init__(self, settings: Settings, ibkr: IBKRService, repo: Repository):
        self.settings, self.ibkr, self.repo = settings, ibkr, repo

    def scan(self, progress: Callable[[str], None] | None = None) -> pd.DataFrame:
        symbols = tuple(dict.fromkeys(self.settings.volatility_watchlist))
        started_at = utc_now()
        try:
            raw = self.ibkr.stock_turnover_estimates_raw(symbols, progress)
        except Exception as exc:
            raw = {symbol: exc for symbol in symbols}
        run_id = uuid4().hex
        rows = []
        for symbol in symbols:
            value = raw.get(symbol)
            if isinstance(value, Exception) or value is None:
                message = (
                    f"{type(value).__name__}: {value}" if isinstance(value, Exception)
                    else "No result returned"
                )
                rows.append({
                    "run_id": run_id, "symbol": symbol, "success": False,
                    "error_message": message, "raw_volume": None,
                    "volume_multiplier": self.settings.ibkr_us_stock_volume_multiplier,
                    "volume_scale_divisor": 1.0,
                    "reference_daily_volume": None,
                    "estimated_share_volume": None, "price_used": None,
                    "price_basis": "Unavailable", "estimated_turnover_usd": None,
                    "currency": "USD", "market_data_type": "unknown",
                    "session_scope": "unavailable", "source": "ibkr",
                    "observed_at": utc_now(), "data_quality": "Unavailable: " + message,
                })
                continue
            success = value.get("estimated_turnover_usd") is not None
            quality = (
                "Estimate = IBKR current daily-bar volume × daily WAP; "
                "not official consolidated exchange turnover"
                if success else "Unavailable: IBKR returned no complete price/volume pair"
            )
            rows.append({
                "run_id": run_id, **value, "success": success,
                "error_message": None if success else quality,
                "source": "ibkr", "observed_at": utc_now(), "data_quality": quality,
            })
        frame = pd.DataFrame(rows)
        success_count = int(frame["success"].sum()) if not frame.empty else 0
        self.repo.save_stock_turnover_scan({
            "run_id": run_id, "started_at": started_at,
            "completed_at": utc_now(), "source": "ibkr",
            "requested_count": len(symbols), "success_count": success_count,
            "failed_count": len(symbols) - success_count,
            "symbols_json": json.dumps(symbols),
        }, frame)
        return frame

    def runs(self) -> pd.DataFrame:
        return self.repo.stock_turnover_runs()

    def report(self, run_id: str) -> pd.DataFrame:
        return self.repo.stock_turnover_report(run_id)

    def history_symbols(self) -> list[str]:
        saved = self.repo.stock_turnover_symbols()
        symbols = set(saved["symbol"].tolist()) if not saved.empty else set()
        symbols.update(self.settings.volatility_watchlist)
        return sorted(str(symbol).upper() for symbol in symbols)

    def history(self, symbol: str, start_date=None, end_date=None) -> pd.DataFrame:
        return self.repo.stock_turnover_history(symbol, start_date, end_date)
