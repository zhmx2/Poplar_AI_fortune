from pathlib import Path

from app.config import Settings
from app.db import Repository
from app.services.institutions import InstitutionService


def _service(tmp_path: Path) -> InstitutionService:
    settings = Settings(
        database_path=tmp_path / "phase_c.duckdb",
        sec_cache_dir=tmp_path / "cache",
        sec_mode="mock",
    )
    return InstitutionService(settings, Repository(settings.database_path))


def test_table_column_preferences_persist_across_restart(tmp_path: Path):
    service = _service(tmp_path)
    service.save_table_preference(
        "sec_current_holdings",
        ["issuer_name", "value_usd_mn"],
        ["value_usd_mn", "issuer_name", "cusip"],
    )

    restarted = _service(tmp_path)
    preference = restarted.table_preference("sec_current_holdings")
    assert preference == {
        "visible_columns": ["issuer_name", "value_usd_mn"],
        "column_order": ["value_usd_mn", "issuer_name", "cusip"],
    }


def test_reverse_lookup_finds_security_across_institutions(tmp_path: Path):
    service = _service(tmp_path)
    service.load_mock("berkshire")
    service.load_mock("bridgewater")

    by_name = service.reverse_lookup("APPLE")
    by_cusip = service.reverse_lookup("037833100")

    assert set(by_name["institution_name"]) == {
        "Berkshire Hathaway Inc",
        "Bridgewater Associates, LP",
    }
    assert set(by_name["status"]) == {"INCREASED"}
    assert len(by_cusip) == 2
    assert (by_cusip["current_value_usd"] > 0).all()
