from pathlib import Path

from app.config import Settings
from app.db import Repository
from app.services.institutions import InstitutionService


def test_mock_holdings_persist_by_report_period(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "test.duckdb",
        sec_cache_dir=tmp_path / "cache",
        sec_mode="mock",
    )
    repo = Repository(settings.database_path)
    service = InstitutionService(settings, repo)

    assert len(service.institutions()) == 8
    period = service.load_mock("berkshire")
    periods = service.periods("berkshire")
    assert periods[0] == period
    assert len(periods) == 2
    holdings = service.holdings("berkshire", period)
    assert not holdings.empty
    assert "SEC MOCK" in holdings.iloc[0]["source"]
    changes = service.changes("berkshire", periods[0], periods[1])
    assert {"NEW", "INCREASED", "DECREASED"}.issubset(set(changes["status"]))
