from pathlib import Path

import pytest

from app.config import Settings
from app.db import Repository
from app.errors import ApplicationError
from app.services.institutions import InstitutionService


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "management.duckdb",
        sec_cache_dir=tmp_path / "cache",
        sec_mode="online",
        sec_user_agent="TestResearchApp tests@local.test",
    )


def _submissions():
    return {
        "name": "TEST VERIFIED MANAGER LLC",
        "filings": {
            "recent": {
                "accessionNumber": ["0001234567-26-000001"],
                "form": ["13F-HR"],
                "filingDate": ["2026-05-15"],
                "reportDate": ["2026-03-31"],
                "primaryDocument": ["primary_doc.xml"],
            }
        },
    }


def test_add_verified_institution_and_prevent_duplicate(tmp_path: Path):
    service = InstitutionService(_settings(tmp_path), Repository(tmp_path / "management.duckdb"))
    service.client.submissions = lambda cik: _submissions()

    added = service.add_institution("1234567", "测试机构")
    assert added["cik"] == "0001234567"
    assert added["name"] == "TEST VERIFIED MANAGER LLC"
    saved = service.institutions(active_only=False)
    assert "0001234567" in saved["cik"].tolist()

    with pytest.raises(ApplicationError, match="already saved"):
        service.add_institution("0001234567")


def test_disable_and_rename_institution_persist(tmp_path: Path):
    settings = _settings(tmp_path)
    repo = Repository(settings.database_path)
    service = InstitutionService(settings, repo)
    service.client.submissions = lambda cik: _submissions()
    added = service.add_institution("1234567")

    service.update_preferences(added["institution_id"], "自定义显示名", False)
    assert "0001234567" not in service.institutions()["cik"].tolist()

    restarted = InstitutionService(settings, Repository(settings.database_path))
    row = restarted.institutions(active_only=False)
    row = row[row["cik"] == "0001234567"].iloc[0]
    assert row["name_cn"] == "自定义显示名"
    assert not bool(row["enabled"])


def test_cik_without_13f_is_rejected(tmp_path: Path):
    service = InstitutionService(_settings(tmp_path), Repository(tmp_path / "management.duckdb"))
    service.client.submissions = lambda cik: {
        "name": "NON 13F COMPANY",
        "filings": {"recent": {}},
    }
    with pytest.raises(ApplicationError, match="no recent 13F-HR"):
        service.add_institution("1234567")
