from __future__ import annotations

import pandas as pd

from app.analytics.market_pressure import build_market_pressure_history
from app.db import Repository
from app.models import HealthStatus, utc_now
from app.services.phase_f import PhaseFService
from app.services.phase_fb import PhaseFBService


class PhaseFCService:
    """Offline calculation layer over saved Phase F-A and F-B observations."""

    def __init__(
        self,
        phase_f: PhaseFService,
        phase_fb: PhaseFBService,
        repo: Repository,
    ):
        self.phase_f = phase_f
        self.phase_fb = phase_fb
        self.repo = repo

    def health(self) -> HealthStatus:
        saved = self.data()
        message = (
            f"Ready; {len(saved):,} saved daily pressure scores"
            if not saved.empty
            else "Ready; recalculate after Phase F-A and F-B data are available"
        )
        return HealthStatus(
            "Phase F-C pressure dashboard", True, message, utc_now(), state="healthy"
        )

    def recalculate(self) -> pd.DataFrame:
        liquidity = self.phase_f.data()
        market = self.phase_fb.data()
        if liquidity.empty:
            raise ValueError("No source-isolated Phase F-A observations are available.")
        if market.empty:
            raise ValueError("No source-isolated Phase F-B market bars are available.")
        result = build_market_pressure_history(liquidity, market)
        if result.empty:
            raise ValueError(
                "The aligned history is too short or fewer than five pressure "
                "components are available. Sync the standard FRED and market basket first."
            )
        result["liquidity_source"] = ", ".join(
            sorted(liquidity["source"].dropna().astype(str).unique())
        )
        result["market_source"] = ", ".join(
            sorted(market["source"].dropna().astype(str).unique())
        )
        self.repo.save_market_pressure_scores(result)
        return result

    def data(self) -> pd.DataFrame:
        return self.repo.market_pressure_scores()
