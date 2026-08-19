from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analytics.liquidity import (
    build_net_liquidity_proxy,
    canonicalize_liquidity_observations,
)


@dataclass(frozen=True)
class PressureComponent:
    key: str
    name: str
    name_cn: str
    weight: float
    explanation: str
    explanation_cn: str


COMPONENTS = (
    PressureComponent("liquidity_contraction", "Net liquidity contraction", "净流动性收缩", 0.20,
                      "A falling net-liquidity proxy increases funding pressure.", "净流动性代理指标下降，表示资金环境趋紧。"),
    PressureComponent("nfci", "Financial conditions", "金融条件", 0.15,
                      "A higher NFCI indicates tighter-than-average financial conditions.", "NFCI上升表示金融条件相对历史平均水平收紧。"),
    PressureComponent("real_yield_shock", "Real-yield shock", "实际收益率冲击", 0.15,
                      "A rising 10-year real yield raises the discount rate for risk assets.", "10年期实际收益率上升会提高风险资产折现率。"),
    PressureComponent("credit_widening", "Credit-spread widening", "信用利差扩大", 0.15,
                      "A wider high-yield spread signals greater credit stress.", "高收益债利差扩大表示信用压力上升。"),
    PressureComponent("equity_weakness", "Broad-equity weakness", "大盘走弱", 0.15,
                      "A negative SPY 20-day return confirms weaker risk appetite.", "SPY的20日回报走弱，确认风险偏好下降。"),
    PressureComponent("smallcap_weakness", "Small-cap relative weakness", "小盘股相对走弱", 0.10,
                      "IWM underperformance versus SPY often accompanies tighter funding.", "IWM相对SPY走弱，通常与融资环境趋紧同时出现。"),
    PressureComponent("hyg_weakness", "High-yield market weakness", "高收益债市场走弱", 0.05,
                      "A falling HYG price confirms stress in traded credit markets.", "HYG价格下跌，确认交易型信用市场承压。"),
    PressureComponent("dollar_strength", "US-dollar strength", "美元走强", 0.05,
                      "A stronger dollar can tighten global financial conditions.", "美元走强可能收紧全球金融条件。"),
)

COMPONENT_BY_KEY = {item.key: item for item in COMPONENTS}
TOTAL_WEIGHT = sum(item.weight for item in COMPONENTS)


def rolling_pressure_score(
    values: pd.Series, window: int = 252, min_periods: int = 60
) -> pd.Series:
    """Convert a pressure-oriented raw series into a bounded 0-100 score."""
    numeric = pd.to_numeric(values, errors="coerce")
    rolling = numeric.rolling(window=window, min_periods=min_periods)
    mean = rolling.mean()
    std = rolling.std(ddof=0).replace(0, np.nan)
    z_score = (numeric - mean) / std
    return (50 + 15 * z_score).clip(lower=0, upper=100)


def pressure_status(score: float) -> tuple[str, str, str, str]:
    if score < 30:
        return ("Supportive", "流动性支持", "Funding and market confirmation are broadly supportive.", "资金环境与市场确认整体偏支持。")
    if score < 45:
        return ("Mild pressure", "轻度压力", "Some pressure is visible, but conditions remain below neutral stress.", "部分压力已出现，但整体仍低于中性压力区间。")
    if score < 55:
        return ("Neutral", "中性", "Supportive and restrictive signals are broadly balanced.", "支持性与收紧信号大致平衡。")
    if score < 70:
        return ("Elevated pressure", "压力上升", "Multiple liquidity or market indicators are showing above-normal pressure.", "多项流动性或市场指标显示压力高于正常水平。")
    return ("High pressure", "高压力", "Broad stress signals are unusually strong versus their rolling history.", "广泛压力信号相对滚动历史处于异常高位。")


def build_market_pressure_history(
    liquidity_frame: pd.DataFrame,
    market_frame: pd.DataFrame,
    *,
    window: int = 252,
    min_periods: int = 60,
    minimum_components: int = 5,
) -> pd.DataFrame:
    """Build an auditable daily pressure history from saved FRED and IBKR data."""
    if liquidity_frame.empty or market_frame.empty:
        return pd.DataFrame()

    market = market_frame.copy()
    market["bar_date"] = pd.to_datetime(market["bar_date"])
    prices = market.pivot_table(
        index="bar_date", columns="symbol", values="close", aggfunc="last"
    ).sort_index()
    if prices.empty:
        return pd.DataFrame()

    liquidity = canonicalize_liquidity_observations(liquidity_frame)
    liquidity["observation_date"] = pd.to_datetime(liquidity["observation_date"])
    macro = liquidity.pivot_table(
        index="observation_date", columns="series_id", values="value", aggfunc="last"
    ).sort_index().reindex(prices.index).ffill()

    proxy = build_net_liquidity_proxy(liquidity)
    net_liquidity = pd.Series(index=prices.index, dtype=float)
    if not proxy.empty:
        proxy = proxy.set_index(pd.to_datetime(proxy["observation_date"]))
        net_liquidity = proxy["net_liquidity_usd_bn"].reindex(prices.index).ffill()

    raw = pd.DataFrame(index=prices.index)
    raw["liquidity_contraction"] = -net_liquidity.pct_change(20, fill_method=None)
    raw["nfci"] = macro.get("NFCI")
    raw["real_yield_shock"] = macro.get("DFII10", pd.Series(index=prices.index, dtype=float)).diff(20)
    raw["credit_widening"] = macro.get("BAMLH0A0HYM2", pd.Series(index=prices.index, dtype=float)).diff(20)

    returns_20d = prices.pct_change(20, fill_method=None)
    raw["equity_weakness"] = -returns_20d.get("SPY", pd.Series(index=prices.index, dtype=float))
    raw["smallcap_weakness"] = -(
        returns_20d.get("IWM", pd.Series(index=prices.index, dtype=float))
        - returns_20d.get("SPY", pd.Series(index=prices.index, dtype=float))
    )
    raw["hyg_weakness"] = -returns_20d.get("HYG", pd.Series(index=prices.index, dtype=float))
    raw["dollar_strength"] = returns_20d.get("UUP", pd.Series(index=prices.index, dtype=float))

    result = pd.DataFrame(index=prices.index)
    weighted_sum = pd.Series(0.0, index=prices.index)
    available_weight = pd.Series(0.0, index=prices.index)
    available_count = pd.Series(0, index=prices.index, dtype=int)
    for component in COMPONENTS:
        result[f"{component.key}_value"] = raw[component.key]
        score = rolling_pressure_score(raw[component.key], window, min_periods)
        result[f"{component.key}_score"] = score
        valid = score.notna()
        weighted_sum = weighted_sum.add(score.fillna(0) * component.weight)
        available_weight = available_weight.add(valid.astype(float) * component.weight)
        available_count = available_count.add(valid.astype(int))

    result["available_components"] = available_count
    result["coverage_ratio"] = available_weight / TOTAL_WEIGHT
    result["composite_score"] = weighted_sum.div(available_weight.replace(0, np.nan))
    result.loc[available_count < minimum_components, "composite_score"] = np.nan
    result = result.loc[result["composite_score"].notna()].copy()
    if result.empty:
        return result.reset_index(names="score_date")

    statuses = result["composite_score"].map(pressure_status)
    result["status_label"] = statuses.map(lambda item: item[0])
    result["status_label_cn"] = statuses.map(lambda item: item[1])
    result["status_explanation"] = statuses.map(lambda item: item[2])
    result["status_explanation_cn"] = statuses.map(lambda item: item[3])
    result["calculated_at"] = pd.Timestamp.now(tz="UTC")
    return result.reset_index(names="score_date")


def latest_component_table(row: pd.Series) -> pd.DataFrame:
    rows = []
    for component in COMPONENTS:
        rows.append({
            "component": component.name,
            "component_cn": component.name_cn,
            "weight": component.weight,
            "raw_value": row.get(f"{component.key}_value"),
            "score": row.get(f"{component.key}_score"),
            "explanation": component.explanation,
            "explanation_cn": component.explanation_cn,
        })
    return pd.DataFrame(rows)
