from __future__ import annotations

import math

import altair as alt
import pandas as pd
import streamlit as st

from app.config import Settings
from app.services.trend_lines import TrendLineService


def _daily_slope_percent(slope: float) -> float:
    return math.expm1(slope)


def render_trend_lines(
    service: TrendLineService,
    settings: Settings,
    symbol: str,
) -> None:
    st.divider()
    st.subheader(f"{symbol.upper()} — Optimized trend channel / 最优趋势通道")
    st.caption(
        "V2 fits the prior Lookback window, then projects into two independent "
        "confirmation days with a 0.25×ATR14 breakout buffer. Recalculation reads "
        "DuckDB only. / V2使用此前Lookback窗口拟合，再投影到两个独立确认日，"
        "并采用0.25×ATR14突破缓冲；重新计算只读取DuckDB。"
    )
    algorithm = st.segmented_control(
        "Algorithm / 算法",
        ["V2 Strict / 严格", "V2 Robust / 稳健", "V1 Strict / 第一版"],
        default="V2 Strict / 严格",
        key=f"trend_algorithm_{symbol}",
    )
    standard = [20, 60, 120, 252]
    default = settings.trend_line_default_lookback
    if default not in standard:
        standard.append(default)
        standard.sort()
    custom = st.toggle(
        "Custom lookback / 自定义窗口",
        key=f"trend_custom_{symbol}",
    )
    if custom:
        lookback = int(st.number_input(
            "Lookback (trading days) / 回看窗口（交易日）",
            min_value=20, max_value=504, value=default, step=1,
            key=f"trend_custom_value_{symbol}",
        ))
    else:
        lookback = int(st.segmented_control(
            "Lookback (trading days) / 回看窗口（交易日）",
            standard,
            default=default,
            key=f"trend_standard_{symbol}",
        ))
    try:
        if algorithm == "V1 Strict / 第一版":
            result, chart_data = service.calculate(symbol, lookback)
            v2_mode = None
        else:
            v2_mode = "robust" if algorithm.startswith("V2 Robust") else "strict"
            result, chart_data = service.calculate_v2(symbol, lookback, v2_mode)
    except ValueError as exc:
        st.info(f"Trend channel unavailable: {exc} / 趋势通道暂不可用。")
        return

    with st.container(horizontal=True):
        st.metric("Stock / 股票", symbol.upper(), border=True)
        st.metric("Channel status / 通道状态", result["status"], border=True)
        st.metric(
            "Channel position / 通道位置",
            "N/A" if result["channel_position"] is None
            else f"{result['channel_position']:.1%}",
            border=True,
        )
        st.metric(
            "Distance above support / 高于支撑",
            f"{result['distance_to_support']:+.2%}", border=True,
        )
    if v2_mode is not None:
        with st.container(horizontal=True):
            st.metric(
                "ATR14 buffer / ATR14缓冲",
                f"${result['atr_buffer']:,.2f}",
                "0.25×ATR14", border=True,
            )
            st.metric(
                "Support touches / 支撑触点",
                int(result["support_touches"]), border=True,
            )
            st.metric(
                "Resistance touches / 阻力触点",
                int(result["resistance_touches"]), border=True,
            )
            st.metric(
                "Confirmation / 确认",
                f"{int(result['confirmation_days'])} closes / 个收盘日",
                border=True,
            )
    channel_width_ratio = result["channel_width"] / result["latest_close"]
    with st.container(horizontal=True):
        st.metric(
            "Channel width / 通道宽度",
            f"${result['channel_width']:,.2f}",
            f"{channel_width_ratio:.1%} of Close / 相对收盘价",
            border=True,
        )
        st.metric(
            "Distance below resistance / 低于阻力",
            f"{result['distance_to_resistance']:+.2%}", border=True,
        )
    with st.container(horizontal=True):
        st.metric(
            "Support now / 当前支撑", f"${result['support_current']:,.2f}",
            f"{_daily_slope_percent(result['support_slope']):+.3%}/day",
            border=True,
        )
        st.metric(
            "Resistance now / 当前阻力", f"${result['resistance_current']:,.2f}",
            f"{_daily_slope_percent(result['resistance_slope']):+.3%}/day",
            border=True,
        )
        st.metric(
            "Support pivot / 支撑支点",
            f"${result['support_pivot_price']:,.2f}",
            str(result["support_pivot_date"]), border=True,
        )
        st.metric(
            "Resistance pivot / 阻力支点",
            f"${result['resistance_pivot_price']:,.2f}",
            str(result["resistance_pivot_date"]), border=True,
        )
    if result["data_warning"]:
        st.warning(result["data_warning"], icon=":material/warning:")

    plot = chart_data.copy()
    plot["bar_date"] = pd.to_datetime(plot["bar_date"])
    close_line = alt.Chart(plot).mark_line(color="#4C78A8", strokeWidth=2).encode(
        x=alt.X("bar_date:T", title="Market date / 交易日期"),
        y=alt.Y(
            "close:Q", title="Price (USD, log scale) / 价格（美元，对数轴）",
            scale=alt.Scale(type="log", zero=False),
        ),
        tooltip=[
            alt.Tooltip("bar_date:T", title="Date / 日期"),
            alt.Tooltip("close:Q", title="Close / 收盘", format=",.2f"),
            alt.Tooltip("support:Q", title="Support / 支撑", format=",.2f"),
            alt.Tooltip("resistance:Q", title="Resistance / 阻力", format=",.2f"),
        ],
    )
    channel = plot.melt(
        id_vars=["bar_date"], value_vars=["support", "resistance"],
        var_name="line", value_name="price",
    )
    channel_lines = alt.Chart(channel).mark_line(strokeWidth=2).encode(
        x="bar_date:T",
        y=alt.Y("price:Q", scale=alt.Scale(type="log", zero=False)),
        color=alt.Color(
            "line:N", title="Trend line / 趋势线",
            scale=alt.Scale(
                domain=["support", "resistance"],
                range=["#2E8B57", "#C44E52"],
            ),
        ),
    )
    pivots = pd.DataFrame([
        {"bar_date": pd.Timestamp(result["support_pivot_date"]),
         "price": result["support_pivot_price"], "pivot": "Support pivot / 支撑支点"},
        {"bar_date": pd.Timestamp(result["resistance_pivot_date"]),
         "price": result["resistance_pivot_price"], "pivot": "Resistance pivot / 阻力支点"},
    ])
    pivot_points = alt.Chart(pivots).mark_point(filled=True, size=110).encode(
        x="bar_date:T", y=alt.Y("price:Q", scale=alt.Scale(type="log", zero=False)),
        color=alt.Color(
            "pivot:N", title="Pivot / 支点",
            scale=alt.Scale(
                domain=["Support pivot / 支撑支点", "Resistance pivot / 阻力支点"],
                range=["#2E8B57", "#C44E52"],
            ),
        ),
        tooltip=["pivot:N", alt.Tooltip("bar_date:T"), alt.Tooltip("price:Q", format=",.2f")],
    )
    st.altair_chart(
        (close_line + channel_lines + pivot_points).properties(
            height=430,
            title=f"{symbol.upper()} — Optimized support and resistance / 最优支撑阻力",
        ),
        width="stretch",
    )
    st.caption(
        f"Window / 窗口: {result['window_start']} → {result['window_end']} · "
        f"Algorithm / 算法: {result['algorithm_version']} · "
        f"Natural-log prices · {result['constraint_mode'].title()} mode / "
        f"自然对数价格·{result['constraint_mode']}模式。"
    )
    if v2_mode is not None:
        comparison = service.compare_v2(symbol, v2_mode)
        if not comparison.empty:
            st.subheader("Lookback comparison / 多窗口对比")
            comparison_display = comparison.assign(
                channel_width_ratio=(
                    comparison["channel_width"] / comparison["latest_close"]
                )
            )[[
                "lookback", "breakout_status", "support_current",
                "resistance_current", "channel_position", "channel_width_ratio",
                "support_touches", "resistance_touches",
            ]]
            st.dataframe(
                comparison_display, hide_index=True, width="stretch",
                column_config={
                    "lookback": "Lookback / 窗口",
                    "breakout_status": "Breakout status / 突破状态",
                    "support_current": st.column_config.NumberColumn(
                        "Support / 支撑", format="$%,.2f"
                    ),
                    "resistance_current": st.column_config.NumberColumn(
                        "Resistance / 阻力", format="$%,.2f"
                    ),
                    "channel_position": st.column_config.NumberColumn(
                        "Channel position / 通道位置", format="percent"
                    ),
                    "channel_width_ratio": st.column_config.NumberColumn(
                        "Width / Close / 宽度占股价", format="percent"
                    ),
                    "support_touches": "Support touches / 支撑触点",
                    "resistance_touches": "Resistance touches / 阻力触点",
                },
            )

        with st.expander("Historical breakout backtest / 历史突破回测"):
            st.caption(
                "Walk-forward test: each signal uses only information available on "
                "its date. Returns exclude costs and are research-only. / 滚动前推测试："
                "每个信号只使用当时可得数据；收益未计成本，仅供研究。"
            )
            forward_days = int(st.segmented_control(
                "Forward return horizon / 前瞻收益周期",
                [5, 20, 60], default=20,
                key=f"trend_backtest_horizon_{symbol}_{v2_mode}_{lookback}",
            ))
            if st.button(
                "Run and save backtest / 运行并保存回测",
                icon=":material/science:",
                key=f"trend_backtest_run_{symbol}_{v2_mode}_{lookback}",
            ):
                with st.spinner("Running walk-forward backtest..."):
                    summary, signals = service.backtest_v2(
                        symbol, lookback, v2_mode, forward_days
                    )
                st.session_state[f"trend_backtest_result_{symbol}"] = (summary, signals)
            saved_result = st.session_state.get(f"trend_backtest_result_{symbol}")
            if saved_result:
                summary, signals = saved_result
                with st.container(horizontal=True):
                    st.metric("Signals / 信号数", summary["signal_count"], border=True)
                    st.metric(
                        "Win rate / 胜率",
                        "N/A" if summary["win_rate"] is None else f"{summary['win_rate']:.1%}",
                        border=True,
                    )
                    st.metric(
                        "Average directional return / 平均方向收益",
                        "N/A" if summary["average_directional_return"] is None
                        else f"{summary['average_directional_return']:+.2%}",
                        border=True,
                    )
                    st.metric(
                        "Median directional return / 中位方向收益",
                        "N/A" if summary["median_directional_return"] is None
                        else f"{summary['median_directional_return']:+.2%}",
                        border=True,
                    )
                if not signals.empty:
                    st.dataframe(
                        signals.sort_values("signal_date", ascending=False),
                        hide_index=True, width="stretch",
                        column_config={
                            "signal_date": st.column_config.DateColumn("Signal date / 信号日期"),
                            "direction": "Direction / 方向",
                            "entry_close": st.column_config.NumberColumn("Entry close / 信号收盘", format="$%,.2f"),
                            "forward_close": st.column_config.NumberColumn("Forward close / 前瞻收盘", format="$%,.2f"),
                            "forward_return": st.column_config.NumberColumn("Raw return / 原始收益", format="percent"),
                            "directional_return": st.column_config.NumberColumn("Directional return / 方向收益", format="percent"),
                            "win": "Win / 是否正确",
                        },
                    )
    with st.expander("Calculation details / 计算明细"):
        details = pd.DataFrame([
            {"Metric / 指标": "OLS daily slope / OLS日斜率", "Value / 数值": _daily_slope_percent(result["ols_slope"])},
            {"Metric / 指标": "Support daily slope / 支撑日斜率", "Value / 数值": _daily_slope_percent(result["support_slope"])},
            {"Metric / 指标": "Resistance daily slope / 阻力日斜率", "Value / 数值": _daily_slope_percent(result["resistance_slope"])},
            {"Metric / 指标": "Channel width / 当前通道宽度", "Value / 数值": result["channel_width"]},
        ])
        st.dataframe(details, hide_index=True, width="stretch")
        st.caption(
            "A position below 0% or above 100% means the latest Close is outside "
            "the strict channel; version 1 does not label it a confirmed breakout. / "
            "位置低于0%或高于100%表示最新收盘价位于严格通道之外；第一版不将其称为确认突破。"
        )
