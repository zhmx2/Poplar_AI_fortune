from __future__ import annotations

import pandas as pd

from app.analytics.liquidity import (
    build_net_liquidity_proxy,
    canonicalize_liquidity_observations,
    standardize_liquidity_units,
)


H41_SERIES = (
    "WALCL",
    "WRBWFRBL",
    "WRESBAL",
    "TREAST",
    "WSHOMCB",
    "WSHOFADSL",
    "WLCFLL",
    "WTREGEN",
)


def build_h41_weekly_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Return aligned Wednesday H.4.1 levels and transparent derived metrics."""
    columns = [
        "observation_date", "total_assets_usd_bn", "reserve_balances_usd_bn",
        "reserve_week_average_usd_bn", "treasuries_usd_bn", "mbs_usd_bn",
        "agency_debt_usd_bn", "facility_loans_usd_bn", "tga_usd_bn",
        "reserve_change_1w_usd_bn", "reserve_change_4w_usd_bn",
        "reserve_change_52w_usd_bn", "reserve_yoy_pct",
        "reserve_to_assets_ratio", "securities_usd_bn", "qt_runoff_4w_usd_bn",
        "qt_runoff_13w_usd_bn", "facility_loans_change_1w_usd_bn",
        "facility_loans_change_4w_usd_bn", "net_liquidity_usd_bn",
        "net_liquidity_change_4w_usd_bn", "reserve_vs_net_liquidity_4w_gap_usd_bn",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    canonical = canonicalize_liquidity_observations(frame)
    standardized = standardize_liquidity_units(canonical)
    selected = standardized.loc[standardized["series_id"].isin(H41_SERIES)].copy()
    if selected.empty:
        return pd.DataFrame(columns=columns)
    selected["observation_date"] = pd.to_datetime(selected["observation_date"])
    pivot = selected.pivot_table(
        index="observation_date",
        columns="series_id",
        values="standardized_value",
        aggfunc="last",
    ).sort_index()
    # The primary reserve series defines the weekly observation calendar.
    if "WRBWFRBL" not in pivot:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(index=pivot.index[pivot["WRBWFRBL"].notna()])
    mapping = {
        "WALCL": "total_assets_usd_bn",
        "WRBWFRBL": "reserve_balances_usd_bn",
        "WRESBAL": "reserve_week_average_usd_bn",
        "TREAST": "treasuries_usd_bn",
        "WSHOMCB": "mbs_usd_bn",
        "WSHOFADSL": "agency_debt_usd_bn",
        "WLCFLL": "facility_loans_usd_bn",
        "WTREGEN": "tga_usd_bn",
    }
    for series_id, output in mapping.items():
        result[output] = (
            pivot[series_id].reindex(result.index).ffill()
            if series_id in pivot else pd.NA
        )

    reserves = pd.to_numeric(result["reserve_balances_usd_bn"], errors="coerce")
    assets = pd.to_numeric(result["total_assets_usd_bn"], errors="coerce")
    result["reserve_change_1w_usd_bn"] = reserves.diff(1)
    result["reserve_change_4w_usd_bn"] = reserves.diff(4)
    result["reserve_change_52w_usd_bn"] = reserves.diff(52)
    result["reserve_yoy_pct"] = reserves.pct_change(52, fill_method=None)
    result["reserve_to_assets_ratio"] = reserves / assets.replace(0, pd.NA)

    securities = result[["treasuries_usd_bn", "mbs_usd_bn", "agency_debt_usd_bn"]].apply(
        pd.to_numeric, errors="coerce"
    )
    result["securities_usd_bn"] = securities.sum(axis=1, min_count=1)
    result["qt_runoff_4w_usd_bn"] = -result["securities_usd_bn"].diff(4)
    result["qt_runoff_13w_usd_bn"] = -result["securities_usd_bn"].diff(13)
    loans = pd.to_numeric(result["facility_loans_usd_bn"], errors="coerce")
    result["facility_loans_change_1w_usd_bn"] = loans.diff(1)
    result["facility_loans_change_4w_usd_bn"] = loans.diff(4)

    proxy = build_net_liquidity_proxy(canonical)
    result["net_liquidity_usd_bn"] = pd.NA
    if not proxy.empty:
        proxy = proxy.copy()
        proxy["observation_date"] = pd.to_datetime(proxy["observation_date"])
        proxy = proxy.set_index("observation_date")["net_liquidity_usd_bn"].sort_index()
        result["net_liquidity_usd_bn"] = proxy.reindex(result.index, method="ffill")
    net = pd.to_numeric(result["net_liquidity_usd_bn"], errors="coerce")
    result["net_liquidity_change_4w_usd_bn"] = net.diff(4)
    result["reserve_vs_net_liquidity_4w_gap_usd_bn"] = (
        result["reserve_change_4w_usd_bn"] - result["net_liquidity_change_4w_usd_bn"]
    )
    return result.reset_index(names="observation_date").reindex(columns=columns)
