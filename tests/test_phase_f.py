from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from app.analytics.liquidity import (
    build_net_liquidity_proxy,
    canonicalize_liquidity_observations,
    standardize_liquidity_units,
)
from app.config import Settings
from app.db import Repository
from app.errors import ApplicationError
from app.services.phase_f import LIQUIDITY_SERIES, PhaseFService
from app.ui.phase_f import (
    filter_liquidity_date_range,
    format_usd_bn,
    pressure_delta_display,
    trend_label,
)


def _frame(rows: list[tuple[str, str, float, str]]) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    return pd.DataFrame(
        [
            {
                "series_id": series_id,
                "observation_date": pd.Timestamp(observation_date),
                "value": value,
                "series_name": series_id,
                "unit": unit,
                "frequency": "Daily",
                "source": "FRED",
                "retrieved_at": now,
            }
            for series_id, observation_date, value, unit in rows
        ]
    )


def _service(tmp_path: Path, mode: str = "mock") -> PhaseFService:
    settings = Settings(
        database_path=tmp_path / "phase_f.duckdb",
        sec_cache_dir=tmp_path / "cache",
        liquidity_mode=mode,
    )
    return PhaseFService(settings, Repository(settings.database_path))


def test_phase_f_mock_data_persists_for_offline_reading(tmp_path: Path):
    service = _service(tmp_path)
    loaded, errors = service.sync()
    assert not errors
    assert set(loaded["series_id"]) == set(LIQUIDITY_SERIES)

    offline = _service(tmp_path, "offline")
    saved = offline.data()
    assert set(saved["series_id"]) == set(LIQUIDITY_SERIES)
    assert set(saved["source"]) == {"mock"}


def test_fred_parser_skips_missing_observations():
    payload = {
        "observations": [
            {"date": "2026-01-01", "value": "."},
            {"date": "2026-01-02", "value": "4.25"},
        ]
    }
    frame = PhaseFService._parse_fred("DGS10", payload)
    assert len(frame) == 1
    assert frame.iloc[0]["value"] == 4.25
    assert frame.iloc[0]["source"] == "FRED"


def test_system_liquidity_units_are_normalized_to_usd_billions():
    frame = _frame(
        [
            ("WALCL", "2026-01-07", 6_800_000, "Millions of USD"),
            ("WTREGEN", "2026-01-07", 800_000, "Millions of USD"),
            ("RRPONTSYD", "2026-01-07", 25, "Billions of USD"),
        ]
    )
    result = standardize_liquidity_units(frame).set_index("series_id")
    assert result.loc["WALCL", "standardized_value"] == 6_800
    assert result.loc["WTREGEN", "standardized_value"] == 800
    assert result.loc["RRPONTSYD", "standardized_value"] == 25
    assert set(result["standardized_unit"]) == {"USD billions"}


def test_net_liquidity_proxy_forward_fills_weekly_components():
    frame = _frame(
        [
            ("WALCL", "2026-01-07", 6_800_000, "Millions of USD"),
            ("WTREGEN", "2026-01-07", 800_000, "Millions of USD"),
            ("RRPONTSYD", "2026-01-07", 25, "Billions of USD"),
            ("RRPONTSYD", "2026-01-08", 20, "Billions of USD"),
        ]
    )
    result = build_net_liquidity_proxy(frame)
    assert result["net_liquidity_usd_bn"].tolist() == [5_975, 5_980]
    assert result["fed_assets_usd_bn"].tolist() == [6_800, 6_800]


def test_official_rows_replace_mock_rows_for_same_series_and_date():
    frame = _frame(
        [
            ("DGS10", "2026-01-02", 4.2, "Percent"),
            ("DGS10", "2026-01-03", 4.3, "Percent"),
        ]
    )
    mock = frame.iloc[[0]].copy()
    mock["source"] = "mock"
    mock["value"] = 9.9
    result = canonicalize_liquidity_observations(pd.concat([mock, frame]))
    assert result["value"].tolist() == [4.2, 4.3]
    assert set(result["source"]) == {"FRED"}


def test_liquidity_date_filter_is_inclusive():
    frame = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03"]
            ),
            "value": [1, 2, 3],
        }
    )
    result = filter_liquidity_date_range(
        frame, pd.Timestamp("2026-01-02").date(), pd.Timestamp("2026-01-03").date()
    )
    assert result["value"].tolist() == [2, 3]


def test_signed_currency_puts_sign_before_currency_symbol():
    assert format_usd_bn(-134.646, signed=True) == "-$134.6bn"
    assert format_usd_bn(58.19, signed=True) == "+$58.2bn"
    assert format_usd_bn(0, signed=True) == "$0.0bn"


def test_trend_labels_match_numeric_direction():
    assert trend_label(1) == "Increase / 增加"
    assert trend_label(-1) == "Decrease / 减少"
    assert trend_label(0) == "Unchanged / 持平"


def test_pressure_delta_uses_inverse_risk_color_semantics():
    rising, rising_color = pressure_delta_display(4.2)
    falling, falling_color = pressure_delta_display(-3.1)
    unchanged, unchanged_color = pressure_delta_display(0)

    assert rising.startswith("+4.2") and "压力增加" in rising
    assert rising_color == "inverse"
    assert falling.startswith("-3.1") and "压力缓解" in falling
    assert falling_color == "inverse"
    assert unchanged_color == "off"


def test_online_mode_requires_fred_key(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "online.duckdb",
        sec_cache_dir=tmp_path / "cache",
        liquidity_mode="online",
        fred_api_key="",
    )
    service = PhaseFService(settings, Repository(settings.database_path))
    with pytest.raises(ApplicationError, match="FRED_API_KEY"):
        service.sync()


def test_online_dashboard_excludes_all_mock_rows(tmp_path: Path):
    mock_service = _service(tmp_path, "mock")
    mock_service.sync()

    online_service = _service(tmp_path, "online")
    assert online_service.data().empty


def test_online_dashboard_returns_only_fred_when_sources_coexist(tmp_path: Path):
    mock_service = _service(tmp_path, "mock")
    mock_service.sync()
    official = _frame([("DGS10", "2026-01-02", 4.25, "Percent")])
    mock_service.repo.save_macro_observations(official)

    online_service = _service(tmp_path, "online")
    result = online_service.data()
    assert len(result) == 1
    assert set(result["source"]) == {"FRED"}


def test_offline_dashboard_prefers_fred_without_mixing_mock(tmp_path: Path):
    mock_service = _service(tmp_path, "mock")
    mock_service.sync()
    official = _frame([("DGS10", "2026-01-02", 4.25, "Percent")])
    mock_service.repo.save_macro_observations(official)

    offline_service = _service(tmp_path, "offline")
    result = offline_service.data()
    assert len(result) == 1
    assert set(result["source"]) == {"FRED"}
