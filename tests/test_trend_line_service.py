from pathlib import Path

import numpy as np
import pandas as pd

from app.db import Repository
from app.services.trend_lines import TrendLineService


def _saved_bars(count=300):
    dates = pd.bdate_range("2025-01-01", periods=count)
    center = 100 * np.exp(np.arange(count) * 0.0008)
    return pd.DataFrame({
        "symbol": "NVDA", "asset_name": "NVDA", "asset_name_cn": "NVDA",
        "market_role": "Daily quant", "market_role_cn": "日线量化",
        "bar_date": dates.date, "open": center * .995, "high": center * 1.02,
        "low": center * .98, "close": center, "volume": 1_000_000.0,
        "source": "ibkr", "fetched_at": pd.Timestamp("2026-08-15T00:00:00Z"),
    })


def test_service_calculates_and_upserts_by_version_and_lookback(tmp_path: Path):
    repo = Repository(tmp_path / "trend.duckdb")
    repo.save_market_confirmation_bars(_saved_bars())
    service = TrendLineService(repo)

    first, _ = service.calculate("NVDA", 60)
    second, _ = service.calculate("NVDA", 60)
    service.calculate("NVDA", 120)
    saved = service.saved("NVDA")

    assert first["support_slope"] == second["support_slope"]
    assert len(saved) == 2
    assert set(saved["lookback"]) == {60, 120}


def test_service_excludes_mock_rows(tmp_path: Path):
    repo = Repository(tmp_path / "mock.duckdb")
    frame = _saved_bars()
    frame["source"] = "mock"
    repo.save_market_confirmation_bars(frame)
    service = TrendLineService(repo)
    try:
        service.calculate("NVDA", 60)
        assert False, "expected mock exclusion error"
    except ValueError as exc:
        assert "mock rows are excluded" in str(exc)


def test_v2_results_and_backtest_are_persisted(tmp_path: Path):
    repo = Repository(tmp_path / "v2.duckdb")
    repo.save_market_confirmation_bars(_saved_bars())
    service = TrendLineService(repo)

    result, chart = service.calculate_v2("NVDA", 60, "robust")
    summary, signals = service.backtest_v2("NVDA", 20, "strict", 5)

    saved = service.saved("NVDA", 60)
    assert result["algorithm_version"] == "projected_atr_channel_v2"
    assert result["constraint_mode"] == "robust"
    assert len(chart) == 62
    assert saved.iloc[0]["atr_buffer"] > 0
    with repo.connect() as con:
        stored_summary = con.execute(
            "SELECT * FROM trend_line_backtests WHERE run_id = ?",
            [summary["run_id"]],
        ).fetchdf()
        stored_signals = con.execute(
            "SELECT * FROM trend_line_backtest_signals WHERE run_id = ?",
            [summary["run_id"]],
        ).fetchdf()
    assert len(stored_summary) == 1
    assert len(stored_signals) == len(signals)
