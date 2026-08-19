from __future__ import annotations

from time import monotonic

import streamlit as st

from app.config import Settings
from app.services.stock_turnover import StockTurnoverService
from app.services.daily_quant import DailyQuantService
from app.services.trend_lines import TrendLineService
from app.ui.components import date_range_inputs
from app.ui.daily_quant import render_daily_quant


def render_stock_turnover(
    service: StockTurnoverService,
    settings: Settings,
    daily_quant: DailyQuantService | None = None,
    trend_lines: TrendLineService | None = None,
) -> None:
    view = st.segmented_control(
        "Research view / 研究视图",
        ["Stock turnover / 成交金额", "Daily Quant Engine / 日线量化"],
        default="Stock turnover / 成交金额",
        key="stock_research_view",
    )
    if view == "Daily Quant Engine / 日线量化":
        if daily_quant is None:
            st.warning("Daily Quant Engine is unavailable. / 日线量化引擎不可用。")
        else:
            render_daily_quant(daily_quant, settings, trend_lines)
        return
    st.subheader("Stock turnover estimate / 股票当日成交金额估算")
    st.caption(
        "Stock-only IBKR daily-bar query. Estimate = current session volume × "
        "daily WAP; it is not an official consolidated exchange turnover figure. "
        "/ 仅查询股票日线；估算值=当日累计成交量×当日WAP，并非交易所官方汇总成交额。"
    )
    st.info(
        "Symbols come from VOLATILITY_WATCHLIST. No option contracts, IV, Greeks "
        "or option-chain requests are made. / 股票列表来自 VOLATILITY_WATCHLIST，"
        "本模块不会请求期权、IV或Greeks。"
    )
    st.caption(
        "Historical daily volume is returned in shares; no streaming-volume scale "
        "conversion is applied. / 历史日线成交量按股返回，不再使用流式成交量尺度换算。"
    )
    if st.button("Load and save turnover estimates / 获取并保存成交金额估算", icon=":material/query_stats:"):
        started = monotonic()
        status = st.status("Loading stock turnover estimates...", expanded=True)
        try:
            frame = service.scan(
                lambda message: status.write(f"{monotonic() - started:5.1f}s — {message}")
            )
            status.update(
                label=f"Completed: {int(frame['success'].sum())}/{len(frame)} symbols",
                state="complete" if bool(frame["success"].all()) else "error",
                expanded=not bool(frame["success"].all()),
            )
        except Exception as exc:
            status.update(label="Turnover scan failed", state="error", expanded=True)
            st.error(f"Turnover scan failed: {type(exc).__name__}: {exc}")

    runs = service.runs()
    if runs.empty:
        st.info("No saved turnover batch yet. / 尚无已保存的成交金额批次。")
        return
    selected = st.selectbox(
        "Saved batch / 已保存批次", runs["run_id"].tolist(),
        format_func=lambda run_id: str(
            runs.loc[runs["run_id"] == run_id, "completed_at"].iloc[0]
        ),
    )
    report = service.report(selected)
    if report["reference_daily_volume"].isna().all():
        st.warning(
            "This is a legacy batch collected before per-symbol volume-scale "
            "validation was added. Its 10,000× encoding error has been corrected, "
            "but rerun the scan to create a fully reference-validated batch. / "
            "这是加入逐股成交量尺度校验之前的历史批次；10,000倍编码错误已修正，"
            "建议重新查询以生成经日线基准完整验证的新批次。"
        )
    display_report = report.copy()
    display_report["estimated_volume_thousand_shares"] = (
        display_report["estimated_share_volume"] / 1_000
    )
    display_report["estimated_turnover_million_usd"] = (
        display_report["estimated_turnover_usd"] / 1_000_000
    )
    valid = report.loc[report["success"]].copy()
    run = runs.loc[runs["run_id"] == selected].iloc[0]
    with st.container(horizontal=True):
        st.metric("Requested / 请求", int(run["requested_count"]), border=True)
        st.metric("Succeeded / 成功", int(run["success_count"]), border=True)
        st.metric("Failed / 失败", int(run["failed_count"]), border=True)
        total = valid["estimated_turnover_usd"].sum() if not valid.empty else None
        st.metric(
            "Basket estimate / 股票篮子估算",
            "N/A" if total is None else f"${total / 1e6:,.2f}mn",
            border=True,
        )
    st.caption(
        "Basket estimate is the sum of the configured watchlist only; it is not "
        "total US stock-market turnover. / 股票篮子估算只是自选股合计，并非美国"
        "股市整体成交金额。"
    )
    if not valid.empty:
        chart = valid.sort_values("estimated_turnover_usd", ascending=False)
        chart = chart.assign(
            estimated_turnover_million_usd=(
                chart["estimated_turnover_usd"] / 1_000_000
            )
        )
        st.bar_chart(
            chart,
            x="symbol",
            y="estimated_turnover_million_usd",
            x_label="Symbol / 股票",
            y_label="Estimated turnover (USD million) / 估算成交金额（百万美元）",
        )
    st.dataframe(
        display_report, hide_index=True, width="stretch",
        column_order=("symbol", "success", "estimated_turnover_million_usd", "estimated_volume_thousand_shares", "price_used", "price_basis", "reference_daily_volume", "raw_volume", "volume_scale_divisor", "volume_multiplier", "market_data_type", "session_scope", "observed_at", "data_quality"),
        column_config={
            "symbol": "Symbol / 股票",
            "success": "Available / 可用",
            "estimated_turnover_million_usd": st.column_config.NumberColumn(
                "Estimated turnover (USD mn) / 估算成交金额（百万美元）",
                format="$%,.2f",
            ),
            "estimated_volume_thousand_shares": st.column_config.NumberColumn(
                "Estimated volume (k shares) / 估算成交量（千股）",
                format="%,.2f",
            ),
            "price_used": st.column_config.NumberColumn(
                "Price used / 采用价格", format="$%,.2f"
            ),
            "price_basis": "Price basis / 价格口径",
            "raw_volume": st.column_config.NumberColumn(
                "IBKR raw wire volume / IBKR原始线路值", format="%,.0f"
            ),
            "reference_daily_volume": st.column_config.NumberColumn(
                "Reference daily volume / 参考日成交量", format="%,.0f"
            ),
            "volume_scale_divisor": st.column_config.NumberColumn(
                "Scale divisor / 尺度除数", format="%,.0f"
            ),
            "volume_multiplier": st.column_config.NumberColumn(
                "Multiplier / 换算倍数", format="%,.0f"
            ),
            "market_data_type": "Data type / 行情类型",
            "session_scope": "Session / 数据时段",
            "observed_at": st.column_config.DatetimeColumn("Observed / 获取时间"),
            "data_quality": st.column_config.TextColumn("Data quality / 数据说明", width="large"),
        },
    )

    st.divider()
    st.subheader("Single-stock turnover history / 单股成交金额历史")
    st.caption(
        "Each point is the latest successful estimate saved for that market date. "
        "The chart reads DuckDB only and does not send a new IBKR request. / "
        "每个数据点采用该交易日最后一次成功保存的估算值；本图只读取DuckDB，不会重新请求IBKR。"
    )
    symbols = service.history_symbols()
    if not symbols:
        st.info("No saved stock history is available. / 暂无已保存的股票历史数据。")
        return
    history_symbol = st.selectbox(
        "Stock / 股票", symbols, key="turnover_history_symbol"
    )
    complete_history = service.history(history_symbol)
    if complete_history.empty:
        st.info(
            "No successful saved estimate is available for this stock. / "
            "该股票暂无成功保存的估算数据。"
        )
        return

    complete_history["market_date"] = complete_history["market_date"].dt.date
    min_date = complete_history["market_date"].min()
    max_date = complete_history["market_date"].max()
    start_date, end_date = date_range_inputs(
        min_date,
        max_date,
        key_prefix=f"turnover_history_{history_symbol}",
    )
    history = service.history(history_symbol, start_date, end_date)
    if history.empty:
        st.info("No data in the selected date range. / 所选日期范围内没有数据。")
        return

    history["market_date"] = history["market_date"].dt.date
    history["estimated_turnover_million_usd"] = (
        history["estimated_turnover_usd"] / 1_000_000
    )
    history["estimated_volume_thousand_shares"] = (
        history["estimated_share_volume"] / 1_000
    )
    first = float(history.iloc[0]["estimated_turnover_million_usd"])
    latest = float(history.iloc[-1]["estimated_turnover_million_usd"])
    change = None if first == 0 else (latest / first - 1) * 100
    with st.container(horizontal=True):
        st.metric(
            "Latest estimate / 最新估算",
            f"${latest:,.2f}mn",
            "N/A" if change is None else f"{change:+,.2f}% vs range start / 较区间起点",
            border=True,
        )
        st.metric(
            "Range high / 区间最高",
            f"${history['estimated_turnover_million_usd'].max():,.2f}mn",
            border=True,
        )
        st.metric(
            "Range low / 区间最低",
            f"${history['estimated_turnover_million_usd'].min():,.2f}mn",
            border=True,
        )
        st.metric("Trading days / 交易日", len(history), border=True)

    st.line_chart(
        history,
        x="market_date",
        y="estimated_turnover_million_usd",
        x_label="Market date / 交易日期",
        y_label="Estimated turnover (USD million) / 估算成交金额（百万美元）",
    )
    st.caption(
        "Higher turnover means more trading activity, but does not by itself mean "
        "capital inflow or price appreciation. / 成交金额上升表示交易活跃度提高，"
        "但不能单独解释为资金净流入或股价上涨。"
    )
    st.dataframe(
        history,
        hide_index=True,
        width="stretch",
        column_order=(
            "market_date", "estimated_turnover_million_usd",
            "estimated_volume_thousand_shares", "price_used", "price_basis",
            "market_data_type", "observed_at",
        ),
        column_config={
            "market_date": st.column_config.DateColumn("Market date / 交易日期"),
            "estimated_turnover_million_usd": st.column_config.NumberColumn(
                "Estimated turnover (USD mn) / 估算成交金额（百万美元）",
                format="$%,.2f",
            ),
            "estimated_volume_thousand_shares": st.column_config.NumberColumn(
                "Estimated volume (k shares) / 估算成交量（千股）",
                format="%,.2f",
            ),
            "price_used": st.column_config.NumberColumn(
                "Price used / 采用价格", format="$%,.2f"
            ),
            "price_basis": "Price basis / 价格口径",
            "market_data_type": "Data type / 行情类型",
            "observed_at": st.column_config.DatetimeColumn("Observed / 获取时间"),
        },
    )
