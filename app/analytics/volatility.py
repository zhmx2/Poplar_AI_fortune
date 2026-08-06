from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def historical_volatility(closes: Iterable[float], window: int = 30) -> float | None:
    values = np.asarray(
        [float(value) for value in closes if value is not None], dtype=float
    )
    values = values[np.isfinite(values) & (values > 0)]
    if len(values) < window + 1:
        return None
    returns = np.diff(np.log(values[-(window + 1) :]))
    if len(returns) < 2:
        return None
    return float(np.std(returns, ddof=1) * math.sqrt(252))


def iv_rank(current_iv: float | None, history: Iterable[float]) -> float | None:
    if current_iv is None or not math.isfinite(current_iv):
        return None
    values = np.asarray(list(history), dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return None
    low, high = float(values.min()), float(values.max())
    if high == low:
        return 0.0
    return max(0.0, min(1.0, (current_iv - low) / (high - low)))


def iv_percentile(current_iv: float | None, history: Iterable[float]) -> float | None:
    if current_iv is None or not math.isfinite(current_iv):
        return None
    values = np.asarray(list(history), dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return None
    return float(np.count_nonzero(values < current_iv) / len(values))


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def volatility_state(
    iv_hv_ratio: float | None,
    ivp_52w: float | None,
    observation_count: int = 0,
) -> dict[str, str]:
    """Describe volatility pricing without implying a price direction."""
    if iv_hv_ratio is None or not math.isfinite(iv_hv_ratio):
        return {
            "status_label": "Insufficient data",
            "status_label_cn": "数据不足",
            "status_explanation": (
                "IV or HV30 is unavailable, so the current volatility-pricing "
                "state cannot be assessed. This is not a directional signal."
            ),
        }

    if iv_hv_ratio >= 1.20:
        label, label_cn = "IV premium", "隐含波动溢价"
        explanation = (
            "Options imply at least 20% more future volatility than the stock "
            "realized over the trailing 30 days, so option premiums are "
            "relatively expensive versus recent movement. This signals priced "
            "uncertainty, not a price-direction signal for whether the stock "
            "will rise or fall."
        )
    elif iv_hv_ratio <= 0.90:
        label, label_cn = "IV discount", "隐含波动折价"
        explanation = (
            "Options imply no more than 90% of the stock's trailing 30-day "
            "realized volatility, so option premiums are relatively cheap "
            "versus recent movement. This is not a bullish or bearish signal."
        )
    else:
        label, label_cn = "IV near HV", "隐含与历史波动接近"
        explanation = (
            "Implied volatility is broadly aligned with trailing 30-day "
            "realized volatility. Options are not showing a large volatility "
            "premium or discount; this does not predict price direction."
        )

    if observation_count < 60:
        explanation += " Local IV history is still too short for a robust IVP reading."
    elif ivp_52w is not None and math.isfinite(ivp_52w):
        if ivp_52w >= 0.80:
            explanation += " Current IV is also high versus the stored history."
        elif ivp_52w <= 0.20:
            explanation += " Current IV is also low versus the stored history."

    return {
        "status_label": label,
        "status_label_cn": label_cn,
        "status_explanation": explanation,
    }


def volatility_status_guide() -> list[dict[str, str]]:
    return [
        {
            "Rule / 条件": "IV/HV ≥ 1.20",
            "Status / 状态": "IV premium / 隐含波动溢价",
            "Meaning / 说明": "期权定价的未来波动明显高于过去30日实际波动；期权相对偏贵，但不代表股价方向。",
        },
        {
            "Rule / 条件": "0.90 < IV/HV < 1.20",
            "Status / 状态": "IV near HV / 隐含与历史波动接近",
            "Meaning / 说明": "期权预期与近期实际波动大致一致；没有明显波动率溢价或折价，也不预测涨跌。",
        },
        {
            "Rule / 条件": "IV/HV ≤ 0.90",
            "Status / 状态": "IV discount / 隐含波动折价",
            "Meaning / 说明": "期权定价的未来波动低于近期实际波动；期权相对偏便宜，但不等同于看涨或看跌。",
        },
        {
            "Rule / 条件": "IV/HV unavailable",
            "Status / 状态": "Insufficient data / 数据不足",
            "Meaning / 说明": "IBKR未返回IV或HV30，无法判断波动率定价状态。",
        },
    ]
