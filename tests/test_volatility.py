from pathlib import Path
from datetime import date

import pandas as pd
import pytest

from app.analytics.volatility import (
    historical_volatility,
    iv_percentile,
    iv_rank,
    safe_ratio,
    volatility_state,
)
from app.config import Settings
from app.db import Repository
from app.models import VolatilitySnapshot, utc_now
from app.services.ibkr import IBKRService
from app.services.volatility import VolatilityService
from app.ui.volatility_dashboard import _median_display


def test_volatility_calculations():
    closes = [100 + index * 0.5 for index in range(40)]
    assert historical_volatility(closes, 30) is not None
    assert iv_rank(0.30, [0.20, 0.30, 0.40]) == pytest.approx(0.5)
    assert iv_percentile(0.30, [0.20, 0.25, 0.35, 0.40]) == 0.5
    assert safe_ratio(0.30, 0.20) == pytest.approx(1.5)
    assert safe_ratio(0.30, 0) is None


def test_dashboard_medians_show_na_for_missing_iv_but_keep_hv():
    frame = pd.DataFrame({"underlying_iv": [None, None], "hv30": [0.2, 0.4]})
    assert _median_display(frame, "underlying_iv", ".1%") == "N/A"
    assert _median_display(frame, "hv30", ".1%") == "30.0%"


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(1.20, "IV premium"), (1.05, "IV near HV"), (0.90, "IV discount")],
)
def test_volatility_state_labels_do_not_claim_price_direction(ratio, expected):
    state = volatility_state(ratio, 0.50, 252)
    assert state["status_label"] == expected
    assert "not" in state["status_explanation"].lower()
    assert "direction" in state["status_explanation"].lower() or "bullish" in state["status_explanation"].lower()


def _service(tmp_path: Path) -> VolatilityService:
    settings = Settings(
        database_path=tmp_path / "volatility.duckdb",
        sec_cache_dir=tmp_path / "cache",
        ibkr_volatility_mode="mock",
        volatility_watchlist=("NVDA", "SPY"),
    )
    repo = Repository(settings.database_path)
    return VolatilityService(settings, IBKRService(settings), repo)


def test_mock_snapshot_builds_and_persists_iv_history(tmp_path: Path):
    service = _service(tmp_path)
    progress: list[str] = []
    snapshot = service.snapshot("NVDA", progress=progress.append)

    assert snapshot.underlying_iv is not None
    assert snapshot.hv30 is not None
    assert snapshot.ivr_52w is not None
    assert snapshot.ivp_52w is not None
    assert snapshot.observation_count == 252
    history = service.history("NVDA")
    assert len(history) >= 252
    assert history.iloc[-1]["source"] == "ibkr-mock"
    assert "Saving the daily snapshot to DuckDB" in progress
    assert progress[-1] == "Snapshot saved successfully"


def test_mock_history_is_isolated_from_tws_observations(tmp_path: Path):
    service = _service(tmp_path)
    service.repo.save_volatility_snapshot(
        VolatilitySnapshot(
            symbol="NVDA",
            market_date=pd.Timestamp("2020-01-02").date(),
            spot_price=100.0,
            underlying_iv=0.99,
            hv30=0.50,
            iv_hv_ratio=1.98,
            ivr_52w=None,
            ivp_52w=None,
            observation_count=1,
            market_data_type="delayed",
            source="ibkr",
            observed_at=utc_now(),
            data_quality="test",
        )
    )

    service.snapshot("NVDA")
    history = service.history("NVDA")

    assert set(history["source"]) == {"ibkr-mock"}
    assert 0.99 not in history["underlying_iv"].tolist()


def test_mock_option_chain_separates_calls_and_puts_and_saves(tmp_path: Path):
    service = _service(tmp_path)
    expiry = service.expirations("NVDA")[0]
    chain = service.option_chain("NVDA", expiry)

    assert set(chain["option_right"]) == {"C", "P"}
    assert chain["implied_vol"].notna().all()
    assert chain["delta"].notna().all()
    with service.repo.connect() as con:
        saved = con.execute("SELECT count(*) FROM option_quotes").fetchone()[0]
    assert saved == len(chain)


def test_mock_watchlist_scan_returns_independent_symbols(tmp_path: Path):
    service = _service(tmp_path)
    scan = service.scan(["NVDA", "SPY"])
    assert scan["symbol"].tolist() == ["NVDA", "SPY"]
    assert pd.notna(scan["underlying_iv"]).all()
    assert scan["success"].all()
    assert scan["status_label"].notna().all()

    runs = service.scan_runs()
    assert len(runs) == 1
    assert runs.iloc[0]["requested_count"] == 2
    saved = service.scan_report(runs.iloc[0]["run_id"])
    assert saved["symbol"].tolist() == ["NVDA", "SPY"]
    assert saved["status_explanation"].str.len().gt(20).all()


def test_watchlist_report_and_history_are_available_without_new_scan(tmp_path: Path):
    service = _service(tmp_path)
    service.scan(["NVDA", "SPY"])
    run_id = service.scan_runs().iloc[0]["run_id"]

    reopened = _service(tmp_path)
    assert len(reopened.scan_report(run_id)) == 2
    history = reopened.watchlist_history()
    assert not history.empty
    assert {"median_iv", "median_hv30", "median_iv_hv_ratio"} <= set(history.columns)


def test_failed_tws_scan_is_saved_for_offline_diagnostics(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "failed.duckdb",
        sec_cache_dir=tmp_path / "cache",
        ibkr_volatility_mode="tws",
    )
    ibkr = IBKRService(settings)

    def unavailable(*args, **kwargs):
        raise ConnectionRefusedError("TWS unavailable")

    ibkr.volatility_snapshots_raw = unavailable
    service = VolatilityService(settings, ibkr, Repository(settings.database_path))
    scan = service.scan(["NVDA", "MSFT"])

    assert not scan["success"].any()
    run = service.scan_runs().iloc[0]
    assert run["failed_count"] == 2
    saved = service.scan_report(run["run_id"])
    assert saved["error_message"].str.contains("TWS unavailable").all()


def test_empty_ibkr_fields_are_failed_instead_of_false_success(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "empty.duckdb",
        sec_cache_dir=tmp_path / "cache",
        ibkr_volatility_mode="tws",
    )
    ibkr = IBKRService(settings)
    ibkr.volatility_snapshots_raw = lambda *args, **kwargs: {
        "NVDA": {
            "symbol": "NVDA", "spot_price": None, "underlying_iv": None,
            "hv30": None, "market_data_type": "delayed-frozen",
        }
    }
    service = VolatilityService(settings, ibkr, Repository(settings.database_path))
    scan = service.scan(["NVDA"])

    assert not bool(scan.iloc[0]["success"])
    assert "neither IV nor calculated HV30" in scan.iloc[0]["error_message"]
    run = service.scan_runs().iloc[0]
    assert run["success_count"] == 0
    assert run["failed_count"] == 1


def test_hv_only_tws_result_is_saved_as_partial_success(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "hv_only.duckdb",
        sec_cache_dir=tmp_path / "cache",
        ibkr_volatility_mode="tws",
    )
    ibkr = IBKRService(settings)
    ibkr.volatility_snapshots_raw = lambda *args, **kwargs: {
        "NVDA": {
            "symbol": "NVDA", "market_date": date.today(),
            "spot_price": 225.0, "underlying_iv": None,
            "hv30": 0.32,
            "market_data_type": "historical-daily; IV unavailable",
        }
    }
    service = VolatilityService(settings, ibkr, Repository(settings.database_path))

    scan = service.scan(["NVDA"])

    assert bool(scan.iloc[0]["success"])
    assert scan.iloc[0]["hv30"] == pytest.approx(0.32)
    assert pd.isna(scan.iloc[0]["underlying_iv"])
    assert "partial" in scan.iloc[0]["data_quality"]
