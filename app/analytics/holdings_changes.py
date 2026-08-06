from __future__ import annotations

import numpy as np
import pandas as pd


KEY_COLUMNS = ["cusip", "put_call"]


def aggregate_holdings(frame: pd.DataFrame) -> pd.DataFrame:
    """Combine SEC manager rows while preserving stock/put/call identity."""
    if frame.empty:
        return frame.copy()
    data = frame.copy()
    data["put_call"] = data["put_call"].fillna("")
    optional_defaults = {
        "other_manager": "",
        "classification_method": "",
        "share_type": "",
        "source": "",
        "retrieved_at": pd.NaT,
    }
    for column, default in optional_defaults.items():
        if column not in data:
            data[column] = default
    data["other_manager"] = data["other_manager"].fillna("")

    def manager_list(values: pd.Series) -> str:
        managers = sorted(
            {str(value).strip() for value in values if str(value).strip()},
            key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value),
        )
        return ", ".join(managers)

    aggregated = (
        data.groupby(KEY_COLUMNS, dropna=False, as_index=False)
        .agg(
            issuer_name=("issuer_name", "first"),
            title_of_class=("title_of_class", "first"),
            security_type=("security_type", "first"),
            classification_method=("classification_method", "first"),
            value_usd=("value_usd", "sum"),
            shares=("shares", "sum"),
            share_type=("share_type", "first"),
            portfolio_weight=("portfolio_weight", "sum"),
            manager_row_count=("cusip", "size"),
            other_managers=("other_manager", manager_list),
            source=("source", "first"),
            retrieved_at=("retrieved_at", "max"),
        )
    )
    aggregated["put_call"] = aggregated["put_call"].replace("", None)
    return aggregated.sort_values(
        "value_usd", ascending=False, ignore_index=True
    )


def _aggregate(frame: pd.DataFrame, suffix: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    grouped = aggregate_holdings(frame)
    grouped["put_call"] = grouped["put_call"].fillna("")
    return grouped.rename(
        columns={
            "issuer_name": f"issuer_name_{suffix}",
            "title_of_class": f"title_of_class_{suffix}",
            "security_type": f"security_type_{suffix}",
            "value_usd": f"value_usd_{suffix}",
            "shares": f"shares_{suffix}",
            "portfolio_weight": f"portfolio_weight_{suffix}",
        }
    )


def compare_holdings(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """Compare two effective 13F quarters using CUSIP plus put/call identity."""
    current_agg = _aggregate(current, "current")
    previous_agg = _aggregate(previous, "previous")
    merged = current_agg.merge(previous_agg, on=KEY_COLUMNS, how="outer")

    for stem in ("issuer_name", "title_of_class", "security_type"):
        merged[stem] = merged[f"{stem}_current"].combine_first(
            merged[f"{stem}_previous"]
        )
    for column in (
        "value_usd_current", "value_usd_previous", "shares_current",
        "shares_previous", "portfolio_weight_current",
        "portfolio_weight_previous",
    ):
        merged[column] = merged[column].fillna(0.0)

    has_current = merged["issuer_name_current"].notna()
    has_previous = merged["issuer_name_previous"].notna()
    share_change = merged["shares_current"] - merged["shares_previous"]
    merged["status"] = np.select(
        [
            has_current & ~has_previous,
            ~has_current & has_previous,
            share_change > 0,
            share_change < 0,
        ],
        ["NEW", "CLOSED", "INCREASED", "DECREASED"],
        default="UNCHANGED",
    )
    merged["shares_change"] = share_change
    merged["change_rate"] = np.where(
        merged["shares_previous"] != 0,
        share_change / merged["shares_previous"],
        np.nan,
    )
    merged["value_change_usd"] = (
        merged["value_usd_current"] - merged["value_usd_previous"]
    )
    merged["weight_change"] = (
        merged["portfolio_weight_current"]
        - merged["portfolio_weight_previous"]
    )
    return merged[
        [
            "issuer_name", "title_of_class", "security_type", "put_call",
            "cusip", "status", "value_usd_current", "value_usd_previous",
            "value_change_usd", "portfolio_weight_current",
            "portfolio_weight_previous", "weight_change", "shares_current",
            "shares_previous", "shares_change", "change_rate",
        ]
    ].sort_values("value_usd_current", ascending=False, ignore_index=True)
