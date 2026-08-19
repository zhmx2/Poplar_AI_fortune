from __future__ import annotations

from datetime import date

import pandas as pd

from app.db import Repository
from app.models import HealthStatus, Quote, utc_now
from app.services.ibkr import IBKRService
from app.services.openbb import OpenBBService
from app.services.institutions import InstitutionService
from app.services.volatility import VolatilityService
from app.services.phase_e import PhaseEService
from app.services.phase_f import PhaseFService
from app.services.phase_fb import PhaseFBService
from app.services.phase_fc import PhaseFCService
from app.services.stock_turnover import StockTurnoverService
from app.services.daily_quant import DailyQuantService
from app.services.trend_lines import TrendLineService


class ResearchService:
    """Unified facade consumed by the frontend."""

    def __init__(
        self,
        ibkr: IBKRService,
        openbb: OpenBBService,
        repo: Repository,
        institutions: InstitutionService | None = None,
        volatility: VolatilityService | None = None,
        phase_e: PhaseEService | None = None,
        phase_f: PhaseFService | None = None,
        phase_fb: PhaseFBService | None = None,
        phase_fc: PhaseFCService | None = None,
        stock_turnover: StockTurnoverService | None = None,
        daily_quant: DailyQuantService | None = None,
        trend_lines: TrendLineService | None = None,
    ):
        self.ibkr = ibkr
        self.openbb = openbb
        self.repo = repo
        self.institutions = institutions
        self.volatility = volatility
        self.phase_e = phase_e
        self.phase_f = phase_f
        self.phase_fb = phase_fb
        self.phase_fc = phase_fc
        self.stock_turnover = stock_turnover
        self.daily_quant = daily_quant
        self.trend_lines = trend_lines

    def health(self) -> list[HealthStatus]:
        statuses: list[HealthStatus] = []
        for name, checker in (
            ("IBKR TWS", self.ibkr.health),
            ("OpenBB", self.openbb.health),
            ("DuckDB", self.repo.health),
            *(
                (("SEC 13F", self.institutions.health),)
                if self.institutions is not None
                else ()
            ),
            *(
                (("Phase E research", self.phase_e.health),)
                if self.phase_e is not None else ()
            ),
            *(
                (("Phase F-A liquidity", self.phase_f.health),)
                if self.phase_f is not None else ()
            ),
            *(
                (("Phase F-B market confirmation", self.phase_fb.health),)
                if self.phase_fb is not None else ()
            ),
            *(
                (("Phase F-C pressure dashboard", self.phase_fc.health),)
                if self.phase_fc is not None else ()
            ),
            *(
                (("IBKR volatility", self.volatility.health),)
                if self.volatility is not None
                else ()
            ),
        ):
            try:
                statuses.append(checker())
            except Exception as exc:
                statuses.append(
                    HealthStatus(
                        name,
                        False,
                        f"Health check failed: {type(exc).__name__}: {exc}",
                        utc_now(),
                        state="unavailable",
                    )
                )
        return statuses

    def account_summary(self) -> pd.DataFrame:
        frame = self.ibkr.accounts()
        self.repo.save_frame("account_snapshots", frame)
        return frame

    def positions(self) -> pd.DataFrame:
        frame = self.ibkr.positions()
        self.repo.save_frame("positions", frame)
        return frame

    def quote(self, symbol: str) -> Quote:
        quote = self.ibkr.quote(symbol)
        self.repo.save_quote(quote)
        return quote

    def history(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        frame = self.openbb.history(symbol, start, end)
        self.repo.save_frame("historical_bars", frame)
        return frame
