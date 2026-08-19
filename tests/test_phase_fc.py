from pathlib import Path

import numpy as np
import pandas as pd

from app.analytics.market_pressure import (
    build_market_pressure_history,
    pressure_status,
    rolling_pressure_score,
)
from app.config import Settings
from app.db import Repository
from app.services.phase_f import PhaseFService
from app.services.phase_fb import PhaseFBService
from app.services.phase_fc import PhaseFCService


class StubIBKR:
    def historical_daily_bars_batch(self, *args, **kwargs):
        raise AssertionError("IBKR must not be contacted in mock tests")


def _services(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "phase_fc.duckdb",
        sec_cache_dir=tmp_path / "cache",
        liquidity_mode="mock",
        market_confirmation_mode="mock",
        market_confirmation_lookback_years=2,
        market_confirmation_basket=("SPY", "IWM", "HYG", "UUP"),
    )
    repo = Repository(settings.database_path)
    phase_f = PhaseFService(settings, repo)
    phase_fb = PhaseFBService(settings, StubIBKR(), repo)
    return phase_f, phase_fb, PhaseFCService(phase_f, phase_fb, repo)


def test_rolling_score_is_bounded_and_has_no_future_dependency():
    series = pd.Series(np.sin(np.arange(300) / 13) + np.arange(300) / 500)
    full = rolling_pressure_score(series)
    prefix = rolling_pressure_score(series.iloc[:220])
    pd.testing.assert_series_equal(full.iloc[:220], prefix)
    assert full.dropna().between(0, 100).all()


def test_pressure_status_bands():
    assert pressure_status(29)[0] == "Supportive"
    assert pressure_status(40)[0] == "Mild pressure"
    assert pressure_status(50)[0] == "Neutral"
    assert pressure_status(60)[0] == "Elevated pressure"
    assert pressure_status(80)[0] == "High pressure"


def test_mock_sources_calculate_and_persist_pressure_history(tmp_path: Path):
    phase_f, phase_fb, phase_fc = _services(tmp_path)
    phase_f.sync()
    phase_fb.sync()
    calculated = phase_fc.recalculate()
    saved = phase_fc.data()

    assert not calculated.empty
    assert len(saved) == len(calculated)
    assert saved["composite_score"].between(0, 100).all()
    assert saved["coverage_ratio"].between(0, 1).all()
    assert (saved["available_components"] >= 5).all()
    assert set(saved["liquidity_source"]) == {"mock"}
    assert set(saved["market_source"]) == {"mock"}


def test_calculation_requires_at_least_five_available_components(tmp_path: Path):
    phase_f, phase_fb, _ = _services(tmp_path)
    liquidity, _ = phase_f.sync()
    market, _ = phase_fb.sync()
    market = market.loc[market["symbol"].isin(["SPY", "IWM"])]
    result = build_market_pressure_history(liquidity, market, minimum_components=8)
    assert result.empty
