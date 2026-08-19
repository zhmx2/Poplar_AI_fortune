from __future__ import annotations

from time import monotonic

import pandas as pd
import streamlit as st

from app.config import Settings
from app.services.daily_quant import DailyQuantService
from app.services.trend_lines import TrendLineService
from app.ui.components import date_range_inputs
from app.ui.trend_lines import render_trend_lines


def render_daily_quant(
    service: DailyQuantService,
    settings: Settings,
    trend_lines: TrendLineService | None = None,
) -> None:
    st.subheader("Daily Quant Engine / 日线量化引擎")
    st.caption(
        "Read-only daily analysis using IBKR OHLCV bars. Scores describe market "
        "state; they are not forecasts or trading instructions. / 使用IBKR日线OHLCV进行"
        "只读分析；评分描述市场状态，不是价格预测或交易指令。"
    )
    watchlist = tuple(dict.fromkeys(settings.volatility_watchlist))
    st.info(
        "Batch universe from VOLATILITY_WATCHLIST / 批量股票来自环境配置："
        + ", ".join(watchlist),
        icon=":material/list_alt:",
    )
    if st.button(
        "Sync watchlist daily bars and calculate / 批量同步自选股日线并计算",
        icon=":material/query_stats:",
        key="daily_quant_sync",
        type="primary",
    ):
        started = monotonic()
        status = st.status(
            "Loading watchlist daily bars... / 正在加载自选股日线……",
            expanded=True,
        )
        try:
            batch = service.sync_watchlist(
                watchlist,
                lambda message: status.write(f"{monotonic() - started:5.1f}s — {message}"),
            )
            succeeded = int(batch["status"].eq("SUCCESS").sum())
            failed = len(batch) - succeeded
            status.update(
                label=(
                    f"Batch complete: {succeeded} succeeded, {failed} failed / "
                    f"批量完成：{succeeded}成功，{failed}失败"
                ),
                state="complete" if succeeded else "error",
                expanded=bool(failed),
            )
            st.dataframe(
                batch,
                hide_index=True,
                width="stretch",
                column_config={
                    "symbol": "Symbol / 股票代码",
                    "status": "Status / 状态",
                    "bar_count": st.column_config.NumberColumn(
                        "Bars received / 获取日线数", format="localized"
                    ),
                    "data_date": st.column_config.DateColumn("Data date / 数据日期"),
                    "overall_score": st.column_config.NumberColumn(
                        "Quant score / 综合评分", format="%.1f"
                    ),
                    "regime": "Regime / 市场状态",
                    "message": "Message / 信息",
                },
            )
        except Exception as exc:
            status.update(label="Daily Quant sync failed", state="error", expanded=True)
            st.error(f"Daily Quant sync failed: {type(exc).__name__}: {exc}")

    st.markdown("### Stock dashboard / 个股分析面板")
    symbol = st.selectbox(
        "Select stock to view saved dashboard / 选择个股查看已保存Dashboard",
        sorted(set(watchlist)),
        index=0,
        key="daily_quant_symbol",
    )

    try:
        snapshot, history = service.report(symbol)
    except ValueError as exc:
        st.info(
            f"No complete saved analysis is available yet: {exc} / "
            "尚无完整的本地分析数据，请先同步。"
        )
        return

    with st.container(horizontal=True):
        st.metric("Quant score / 综合评分", f"{snapshot['overall_score']:.1f}/100", border=True)
        st.metric("Regime / 市场状态", f"{snapshot['regime']} / {snapshot['regime_cn']}", border=True)
        st.metric("Close / 收盘价", f"${snapshot['close']:,.2f}", border=True)
        st.metric("RSI14", f"{snapshot['rsi14']:.1f}", border=True)

    score_frame = pd.DataFrame({
        "Factor / 因子": ["Trend / 趋势", "Momentum / 动量", "Relative strength / 相对强弱", "Volume / 成交量"],
        "Score / 评分": [snapshot["trend_score"], snapshot["momentum_score"], snapshot["relative_score"], snapshot["volume_score"]],
    })
    st.bar_chart(
        score_frame,
        x="Factor / 因子",
        y="Score / 评分",
        y_label="Score (0–100) / 评分（0–100）",
    )

    history["bar_date"] = pd.to_datetime(history["bar_date"]).dt.date
    start_date, end_date = date_range_inputs(
        history["bar_date"].min(),
        history["bar_date"].max(),
        key_prefix=f"daily_quant_{symbol}",
    )
    visible = history.loc[history["bar_date"].between(start_date, end_date)].copy()
    st.line_chart(
        visible,
        x="bar_date",
        y=["close", "sma20", "sma50", "sma200"],
        x_label="Market date / 交易日期",
        y_label="Price (USD) / 价格（美元）",
    )
    if trend_lines is not None:
        render_trend_lines(trend_lines, settings, symbol)

    with st.container(horizontal=True):
        st.metric("20D return / 20日收益", f"{snapshot['return_20d']:+.2%}", border=True)
        st.metric("60D return / 60日收益", f"{snapshot['return_60d']:+.2%}", border=True)
        st.metric("HV20 / 20日历史波动", f"{snapshot['hv20']:.2%}", border=True)
        st.metric("HV30 / 30日历史波动", f"{snapshot['hv30']:.2%}", border=True)
    with st.container(horizontal=True):
        st.metric("ATR14 / Close", f"{snapshot['atr14_pct']:.2%}", border=True)
        st.metric("Volume / 20D average / 成交量比", f"{snapshot['volume_ratio_20d']:.2f}×", border=True)
        st.metric("Data date / 数据日期", str(snapshot["bar_date"]), border=True)

    st.caption("Relative strength details / 相对强弱明细: " + snapshot["benchmark_detail"])
    st.info(
        "Interpretation / 解读：70–100 Bullish；55–70 Constructive；45–55 Neutral；"
        "30–45 Defensive；0–30 Bearish。Volume is a confirmation factor and does not "
        "identify buying versus selling by itself. / 成交量只是确认因子，不能单独区分买入或卖出资金。"
    )
    st.dataframe(
        visible[["bar_date", "close", "sma20", "sma50", "sma200", "rsi14", "return_20d", "return_60d", "hv20", "hv30", "atr14_pct", "volume_ratio_20d"]].sort_values("bar_date", ascending=False),
        hide_index=True,
        width="stretch",
        column_config={
            "bar_date": st.column_config.DateColumn("Date / 日期"),
            "close": st.column_config.NumberColumn("Close / 收盘", format="$%,.2f"),
            "sma20": st.column_config.NumberColumn("SMA20", format="$%,.2f"),
            "sma50": st.column_config.NumberColumn("SMA50", format="$%,.2f"),
            "sma200": st.column_config.NumberColumn("SMA200", format="$%,.2f"),
            "rsi14": st.column_config.NumberColumn("RSI14", format="%.1f"),
            "return_20d": st.column_config.NumberColumn("20D return / 20日收益", format="percent"),
            "return_60d": st.column_config.NumberColumn("60D return / 60日收益", format="percent"),
            "hv20": st.column_config.NumberColumn("HV20", format="percent"),
            "hv30": st.column_config.NumberColumn("HV30", format="percent"),
            "atr14_pct": st.column_config.NumberColumn("ATR14 / Close", format="percent"),
            "volume_ratio_20d": st.column_config.NumberColumn("Volume ratio / 成交量比", format="%.2f×"),
        },
    )
