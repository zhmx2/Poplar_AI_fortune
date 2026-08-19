from __future__ import annotations

import pandas as pd


USD_BN_CONVERSION = {
    "WALCL": 1 / 1_000,  # FRED unit: USD millions
    "WTREGEN": 1 / 1_000,  # FRED unit: USD millions
    "RRPONTSYD": 1.0,  # FRED unit: USD billions
    "WRBWFRBL": 1 / 1_000,
    "WRESBAL": 1 / 1_000,
    "TREAST": 1 / 1_000,
    "WSHOMCB": 1 / 1_000,
    "WSHOFADSL": 1 / 1_000,
    "WLCFLL": 1 / 1_000,
}


def canonicalize_liquidity_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Prefer official FRED rows and keep one observation per series/date."""
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    result["source"] = result["source"].fillna("unknown").astype(str)
    official_series = set(
        result.loc[result["source"].str.upper().eq("FRED"), "series_id"]
    )
    result = result.loc[
        ~(
            result["series_id"].isin(official_series)
            & result["source"].str.lower().eq("mock")
        )
    ].copy()
    result["_source_priority"] = result["source"].str.upper().map(
        {"FRED": 3, "UNKNOWN": 1, "MOCK": 0}
    ).fillna(2)
    result["_retrieved_sort"] = pd.to_datetime(
        result.get("retrieved_at"), errors="coerce", utc=True
    )
    result = result.sort_values(
        ["series_id", "observation_date", "_source_priority", "_retrieved_sort"]
    ).drop_duplicates(["series_id", "observation_date"], keep="last")
    return result.drop(columns=["_source_priority", "_retrieved_sort"])


def standardize_liquidity_units(frame: pd.DataFrame) -> pd.DataFrame:
    """Add comparable display values without changing the saved raw values."""
    result = frame.copy()
    result["standardized_value"] = result["value"].astype(float)
    result["standardized_unit"] = result["unit"]
    for series_id, factor in USD_BN_CONVERSION.items():
        mask = result["series_id"].eq(series_id)
        result.loc[mask, "standardized_value"] = (
            result.loc[mask, "value"].astype(float) * factor
        )
        result.loc[mask, "standardized_unit"] = "USD billions"
    return result


def build_net_liquidity_proxy(frame: pd.DataFrame) -> pd.DataFrame:
    """Calculate Fed assets minus TGA minus ON RRP on observable dates.

    Weekly Fed assets and TGA observations are forward-filled across the daily
    ON RRP dates. This is a research proxy, not an official FRED series and not
    a measurement of equity-fund flows.
    """
    standardized = standardize_liquidity_units(frame)
    components = standardized.loc[
        standardized["series_id"].isin(USD_BN_CONVERSION)
    ].copy()
    if components.empty:
        return pd.DataFrame(
            columns=[
                "observation_date",
                "fed_assets_usd_bn",
                "tga_usd_bn",
                "rrp_usd_bn",
                "net_liquidity_usd_bn",
            ]
        )
    components["observation_date"] = pd.to_datetime(
        components["observation_date"]
    )
    pivot = components.pivot_table(
        index="observation_date",
        columns="series_id",
        values="standardized_value",
        aggfunc="last",
    ).sort_index()
    pivot = pivot.reindex(columns=["WALCL", "WTREGEN", "RRPONTSYD"]).ffill()
    pivot = pivot.dropna(subset=["WALCL", "WTREGEN", "RRPONTSYD"])
    if pivot.empty:
        return pd.DataFrame(
            columns=[
                "observation_date",
                "fed_assets_usd_bn",
                "tga_usd_bn",
                "rrp_usd_bn",
                "net_liquidity_usd_bn",
            ]
        )
    result = pivot.rename(
        columns={
            "WALCL": "fed_assets_usd_bn",
            "WTREGEN": "tga_usd_bn",
            "RRPONTSYD": "rrp_usd_bn",
        }
    ).reset_index()
    result["net_liquidity_usd_bn"] = (
        result["fed_assets_usd_bn"]
        - result["tga_usd_bn"]
        - result["rrp_usd_bn"]
    )
    return result
