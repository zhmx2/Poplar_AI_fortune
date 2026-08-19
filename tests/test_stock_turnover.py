from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from app.config import Settings
from app.db import Repository
from app.services.stock_turnover import StockTurnoverService


def test_scan_persists_success_and_failure(tmp_path: Path):
    settings = Settings(
        sec_mode="mock", database_path=tmp_path / "turnover.duckdb",
        volatility_watchlist=("NVDA", "BAD"),
    )
    repo = Repository(settings.database_path)
    fake_ibkr = SimpleNamespace(
        stock_turnover_estimates_raw=lambda symbols, progress: {
            "NVDA": {
                "symbol": "NVDA", "raw_volume": 1000.0,
                "volume_multiplier": 1.0, "estimated_share_volume": 1000.0,
                "price_used": 200.0, "price_basis": "Last",
                "estimated_turnover_usd": 200000.0, "currency": "USD",
                "market_data_type": "delayed",
                "session_scope": "current market session",
            },
            "BAD": ValueError("unknown symbol"),
        }
    )
    service = StockTurnoverService(settings, fake_ibkr, repo)

    frame = service.scan()

    assert frame["success"].tolist() == [True, False]
    runs = service.runs()
    assert int(runs.iloc[0]["success_count"]) == 1
    saved = service.report(runs.iloc[0]["run_id"])
    assert set(saved["symbol"]) == {"NVDA", "BAD"}


def test_history_deduplicates_by_market_date_and_filters_range(tmp_path: Path):
    settings = Settings(sec_mode="mock", database_path=tmp_path / "history.duckdb")
    repo = Repository(settings.database_path)
    base = {
        "symbol": "NVDA", "success": True, "error_message": None,
        "raw_volume": 1_000.0, "volume_multiplier": 1.0,
        "volume_scale_divisor": 1.0, "reference_daily_volume": 1_000.0,
        "estimated_share_volume": 1_000.0, "price_used": 100.0,
        "price_basis": "Daily WAP", "currency": "USD",
        "market_data_type": "historical-daily", "source": "ibkr",
        "data_quality": "test",
    }
    rows = pd.DataFrame([
        {**base, "run_id": "r1", "session_scope": "2026-08-12",
         "estimated_turnover_usd": 100_000.0,
         "observed_at": pd.Timestamp("2026-08-12T20:00:00Z")},
        {**base, "run_id": "r2", "session_scope": "2026-08-12",
         "estimated_turnover_usd": 120_000.0,
         "observed_at": pd.Timestamp("2026-08-12T21:00:00Z")},
        {**base, "run_id": "r3", "session_scope": "2026-08-13",
         "estimated_turnover_usd": 130_000.0,
         "observed_at": pd.Timestamp("2026-08-13T21:00:00Z")},
    ])
    for run_id in rows["run_id"]:
        row = rows.loc[rows["run_id"] == run_id]
        repo.save_stock_turnover_scan({
            "run_id": run_id, "started_at": row.iloc[0]["observed_at"],
            "completed_at": row.iloc[0]["observed_at"], "source": "ibkr",
            "requested_count": 1, "success_count": 1, "failed_count": 0,
            "symbols_json": '["NVDA"]',
        }, row)

    history = repo.stock_turnover_history(
        "nvda", pd.Timestamp("2026-08-12").date(), pd.Timestamp("2026-08-12").date()
    )

    assert len(history) == 1
    assert history.iloc[0]["estimated_turnover_usd"] == 120_000.0
    assert repo.stock_turnover_symbols()["symbol"].tolist() == ["NVDA"]
