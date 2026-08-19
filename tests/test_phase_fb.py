from pathlib import Path

import pandas as pd

from app.analytics.market_confirmation import (
    market_return_summary,
    normalize_market_prices,
)
from app.config import Settings
from app.db import Repository
from app.services.phase_fb import PhaseFBService


class StubIBKR:
    def historical_daily_bars_batch(self, *args, **kwargs):
        raise AssertionError("IBKR must not be contacted in mock/offline tests")


def _service(tmp_path: Path, mode: str = "mock") -> PhaseFBService:
    settings = Settings(
        database_path=tmp_path / "phase_fb.duckdb",
        sec_cache_dir=tmp_path / "cache",
        market_confirmation_mode=mode,
        market_confirmation_lookback_years=1,
        market_confirmation_basket=("SPY", "TLT"),
    )
    return PhaseFBService(settings, StubIBKR(), Repository(settings.database_path))


def test_mock_market_bars_persist_and_offline_reads_them(tmp_path: Path):
    service = _service(tmp_path)
    loaded, errors = service.sync()
    assert not errors
    assert set(loaded["symbol"]) == {"SPY", "TLT"}
    assert set(loaded["source"]) == {"mock"}

    offline = _service(tmp_path, "offline")
    saved = offline.data()
    assert len(saved) == len(loaded)
    assert set(saved["source"]) == {"mock"}


def test_tws_mode_excludes_mock_rows(tmp_path: Path):
    _service(tmp_path, "mock").sync()
    assert _service(tmp_path, "tws").data().empty


def test_market_bars_are_upserted_without_duplicates(tmp_path: Path):
    service = _service(tmp_path)
    first, _ = service.sync()
    second, _ = service.sync()
    saved = service.data()
    assert len(saved) == len(first) == len(second)


def test_normalized_prices_start_at_100():
    frame = pd.DataFrame(
        {
            "symbol": ["SPY", "SPY", "TLT", "TLT"],
            "bar_date": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-02"]
            ),
            "close": [100.0, 105.0, 80.0, 76.0],
        }
    )
    result = normalize_market_prices(frame)
    starts = result.groupby("symbol").first()["normalized_close"]
    assert starts.to_dict() == {"SPY": 100.0, "TLT": 100.0}


def test_return_summary_uses_trading_observations():
    dates = pd.bdate_range("2026-01-01", periods=64)
    frame = pd.DataFrame(
        {
            "symbol": "SPY",
            "asset_name": "S&P 500 ETF",
            "asset_name_cn": "标普500 ETF",
            "market_role": "Broad equities",
            "market_role_cn": "美国大盘",
            "bar_date": dates,
            "close": [100.0 + index for index in range(64)],
            "source": "ibkr",
        }
    )
    summary = market_return_summary(frame).iloc[0]
    assert summary["return_1d"] == 163 / 162 - 1
    assert summary["return_20d"] == 163 / 143 - 1
    assert summary["return_63d"] == 163 / 100 - 1
