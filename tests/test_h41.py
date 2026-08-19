from datetime import datetime, timezone

import pandas as pd
import pytest

from app.analytics.h41 import build_h41_weekly_history


def _h41_frame(periods: int = 60) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=periods, freq="W-WED")
    rows = []
    now = datetime.now(timezone.utc)
    definitions = {
        "WALCL": lambda i: 7_000_000 - i * 1_000,
        "WRBWFRBL": lambda i: 3_000_000 - i * 2_000,
        "WRESBAL": lambda i: 2_995_000 - i * 2_000,
        "TREAST": lambda i: 4_500_000 - i * 1_000,
        "WSHOMCB": lambda i: 2_300_000 - i * 500,
        "WSHOFADSL": lambda i: 2_000 - i * 5,
        "WLCFLL": lambda i: 5_000 + i * 100,
        "WTREGEN": lambda i: 700_000,
        "RRPONTSYD": lambda i: 100,
    }
    for series_id, value_fn in definitions.items():
        unit = "Billions of USD" if series_id == "RRPONTSYD" else "Millions of USD"
        for index, observation_date in enumerate(dates):
            rows.append({
                "series_id": series_id,
                "observation_date": observation_date,
                "value": value_fn(index),
                "series_name": series_id,
                "unit": unit,
                "frequency": "Weekly",
                "source": "FRED",
                "retrieved_at": now,
            })
    return pd.DataFrame(rows)


def test_h41_reserve_changes_ratios_and_qt_are_calculated():
    result = build_h41_weekly_history(_h41_frame())
    latest = result.iloc[-1]
    assert latest["reserve_change_1w_usd_bn"] == -2
    assert latest["reserve_change_4w_usd_bn"] == -8
    assert latest["reserve_change_52w_usd_bn"] == -104
    expected_ratio = (3_000 - 59 * 2) / (7_000 - 59)
    assert latest["reserve_to_assets_ratio"] == expected_ratio
    # 4-week runoff: Treasury 4 + MBS 2 + agency debt 0.02 USD bn.
    assert latest["qt_runoff_4w_usd_bn"] == pytest.approx(6.02)
    assert latest["facility_loans_change_4w_usd_bn"] == pytest.approx(0.4)


def test_h41_uses_wednesday_reserves_as_primary_calendar():
    frame = _h41_frame(10)
    removed_date = frame.loc[frame["series_id"].eq("WRBWFRBL"), "observation_date"].iloc[3]
    frame = frame.loc[
        ~(
            frame["series_id"].eq("WRBWFRBL")
            & frame["observation_date"].eq(removed_date)
        )
    ]
    result = build_h41_weekly_history(frame)
    assert len(result) == 9
    assert removed_date not in set(result["observation_date"])


def test_h41_requires_primary_reserve_series():
    frame = _h41_frame(10)
    result = build_h41_weekly_history(frame.loc[~frame["series_id"].eq("WRBWFRBL")])
    assert result.empty
