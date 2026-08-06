from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.analytics.company_facts import parse_company_financials
from app.config import Settings
from app.db import Repository
from app.services.phase_e import PhaseEService
from app.ui.phase_e import (
    build_cpi_yoy_chart,
    canonicalize_macro_observations,
    filter_financial_date_range,
    filter_macro_date_range,
)


def _fact(value, tag, end="2024-06-30", filed="2024-07-30"):
    return {
        "start": "2023-07-01", "end": end, "val": value,
        "form": "10-K", "filed": filed, "accn": "0000789019-24-000001",
    }


def test_company_facts_extracts_capex_and_derives_free_cash_flow():
    facts = {
        "entityName": "Microsoft Corporation",
        "facts": {"us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {"USD": [_fact(200e9, "revenue")]}
            },
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {"USD": [_fact(90e9, "ocf")]}
            },
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {"USD": [_fact(40e9, "capex")]}
            },
        }},
    }
    frame = parse_company_financials(
        facts, "MSFT", "0000789019", datetime.now(timezone.utc)
    )
    values = frame.set_index("metric")["value"].to_dict()
    assert values["capex_cash"] == 40e9
    assert values["free_cash_flow"] == 50e9
    assert frame.loc[frame["metric"] == "capex_cash", "xbrl_tag"].iloc[0] == "PaymentsToAcquirePropertyPlantAndEquipment"


def _service(tmp_path: Path, macro_mode="mock") -> PhaseEService:
    settings = Settings(
        database_path=tmp_path / "phase_e.duckdb",
        sec_cache_dir=tmp_path / "cache",
        macro_mode=macro_mode,
        sec_mode="mock",
    )
    return PhaseEService(settings, Repository(settings.database_path))


def test_mock_macro_and_financials_persist_for_offline_reading(tmp_path: Path):
    service = _service(tmp_path)
    service.sync_macro()
    service.sync_company("MSFT")

    reopened = _service(tmp_path, macro_mode="offline")
    macro = reopened.macro_data()
    financials = reopened.company_data(["MSFT"])
    assert {"CUUR0000SA0", "CUUR0000SA0L1E", "UMCSENT"} <= set(macro["series_id"])
    assert {"revenue", "operating_cash_flow", "capex_cash", "free_cash_flow"} <= set(financials["metric"])


def test_bls_parser_skips_annual_average_period():
    payload = {"Results": {"series": [{
        "seriesID": "CUUR0000SA0",
        "data": [
            {"year": "2025", "period": "M01", "value": "317.7"},
            {"year": "2025", "period": "M02", "value": "-"},
            {"year": "2025", "period": "M13", "value": "319.0"},
        ],
    }]}}
    frame = PhaseEService._parse_bls(payload)
    assert len(frame) == 1
    assert frame.iloc[0]["observation_date"] == pd.Timestamp("2025-01-01").date()


def test_macro_date_range_filter_is_inclusive():
    frame = pd.DataFrame({
        "observation_date": pd.to_datetime(
            ["2024-01-01", "2024-02-01", "2024-03-01"]
        ),
        "value": [1.0, 2.0, 3.0],
    })
    filtered = filter_macro_date_range(
        frame,
        pd.Timestamp("2024-02-01").date(),
        pd.Timestamp("2024-03-01").date(),
    )
    assert filtered["value"].tolist() == [2.0, 3.0]


def test_financial_date_range_filter_is_inclusive():
    frame = pd.DataFrame({
        "period_end": pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31"]),
        "value": [1.0, 2.0, 3.0],
    })
    filtered = filter_financial_date_range(
        frame,
        pd.Timestamp("2023-01-01").date(),
        pd.Timestamp("2024-12-31").date(),
    )
    assert filtered["value"].tolist() == [2.0, 3.0]


def test_cpi_chart_has_percentage_axis_and_tooltips():
    frame = pd.DataFrame({
        "observation_date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
        "series_name": ["US CPI, all items", "US core CPI"],
        "YoY": [0.031, 0.039],
    })
    spec = build_cpi_yoy_chart(frame).to_dict()
    assert "layer" not in spec
    assert spec["encoding"]["y"]["axis"]["format"] == ".1%"
    assert len(spec["encoding"]["tooltip"]) == 3


def test_macro_display_prefers_official_data_and_has_one_row_per_month():
    frame = pd.DataFrame({
        "series_id": ["UMCSENT", "UMCSENT", "UMCSENT", "CUUR0000SA0"],
        "observation_date": pd.to_datetime(
            ["2025-01-01", "2025-01-01", "2025-02-01", "2025-01-01"]
        ),
        "value": [70.0, 64.7, 65.1, 320.0],
        "source": ["mock", "FRED", "FRED", "mock"],
        "retrieved_at": pd.to_datetime(
            ["2025-01-02", "2025-01-03", "2025-02-03", "2025-01-02"], utc=True
        ),
    })
    result = canonicalize_macro_observations(frame)
    sentiment = result.loc[result["series_id"] == "UMCSENT"]
    assert sentiment["value"].tolist() == [64.7, 65.1]
    assert set(sentiment["source"]) == {"FRED"}
    assert not result.duplicated(["series_id", "observation_date"]).any()


def test_resolve_new_company_from_sec_ticker_mapping():
    class StubSEC:
        @staticmethod
        def company_tickers():
            return {
                "0": {
                    "cik_str": 1045810,
                    "ticker": "NVDA",
                    "title": "NVIDIA CORP",
                }
            }

    assert PhaseEService._resolve_company("NVDA", StubSEC()) == (
        "0001045810", "NVIDIA CORP"
    )


def test_mock_mode_accepts_company_added_in_env(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "dynamic.duckdb",
        sec_cache_dir=tmp_path / "cache",
        macro_mode="mock",
        sec_mode="mock",
        phase_e_companies=("MSFT", "NVDA"),
    )
    service = PhaseEService(settings, Repository(settings.database_path))
    frame = service.sync_company("NVDA")
    assert not frame.empty
    assert set(frame["symbol"]) == {"NVDA"}
