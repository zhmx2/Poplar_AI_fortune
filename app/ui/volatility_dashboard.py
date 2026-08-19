from __future__ import annotations

from time import monotonic

import pandas as pd
import streamlit as st

from app.analytics.volatility import volatility_status_guide
from app.config import Settings
from app.services.volatility import VolatilityService


def _run_label(row: pd.Series) -> str:
    completed = pd.Timestamp(row["completed_at"]).strftime("%Y-%m-%d %H:%M:%S")
    return f"{completed} | {row['success_count']}/{row['requested_count']} succeeded | {row['source']}"


def _median_display(frame: pd.DataFrame, column: str, fmt: str) -> str:
    values = pd.to_numeric(frame.get(column), errors="coerce").dropna()
    return "N/A" if values.empty else format(float(values.median()), fmt)


def render_watchlist_dashboard(service: VolatilityService, settings: Settings) -> None:
    st.divider()
    st.subheader("Watchlist volatility dashboard / 自选股波动率分析")
    st.caption(
        "Each scan is saved as a DuckDB batch and remains available offline. "
        "HV30 is calculated from IBKR daily closes; IV remains permission-dependent. "
        "Watchlist: " + ", ".join(settings.volatility_watchlist)
    )

    if st.button("Scan and save watchlist", icon=":material/radar:"):
        started = monotonic()
        status = st.status("Starting watchlist scan...", expanded=True)

        def progress(message: str) -> None:
            status.write(f"{monotonic() - started:5.1f}s — {message}")

        try:
            scan = service.scan(settings.volatility_watchlist, progress=progress)
            failed = int((~scan["success"]).sum()) if not scan.empty else 0
            status.update(
                label=f"Scan saved in {monotonic() - started:.1f}s: {len(scan) - failed} succeeded, {failed} failed",
                state="complete" if failed == 0 else "error",
                expanded=failed > 0,
            )
            if failed:
                st.warning(
                    "A symbol counts as successful only when IBKR returns IV or HV. "
                    "Rows containing only empty fields are now reported as failed. "
                    "/ 只有IBKR返回IV或HV时才计为成功；全部字段为空的记录现在会明确计为失败。"
                )
        except Exception as exc:
            status.update(label="Watchlist scan could not be saved", state="error", expanded=True)
            st.error(f"Watchlist scan failed: {type(exc).__name__}: {exc}")

    runs = service.scan_runs()
    if runs.empty:
        st.info("No saved scan batch yet. Run the watchlist once to create the first report.")
        return

    run_ids = runs["run_id"].tolist()
    selected_run = st.selectbox(
        "Saved scan batch / 已保存扫描批次", run_ids,
        format_func=lambda value: _run_label(runs.loc[runs["run_id"] == value].iloc[0]),
    )
    report = service.scan_report(selected_run)
    run = runs.loc[runs["run_id"] == selected_run].iloc[0]
    successful = report.loc[report["success"]].copy()

    with st.container(horizontal=True):
        st.metric("Requested / 请求", int(run["requested_count"]), border=True)
        st.metric("Succeeded / 成功", int(run["success_count"]), border=True)
        st.metric("Failed / 失败", int(run["failed_count"]), border=True)
        st.metric("Median IV / IV中位数", _median_display(successful, "underlying_iv", ".1%"), border=True)
        st.metric("Median HV30 / HV30中位数", _median_display(successful, "hv30", ".1%"), border=True)
        st.metric("Median IV/HV", _median_display(successful, "iv_hv_ratio", ".2f"), border=True)
        st.metric("IV premium / 溢价数", int((successful["status_label"] == "IV premium").sum()), border=True)

    labels = sorted(report["status_label"].dropna().unique().tolist())
    with st.container(horizontal=True):
        outcome = st.selectbox("Result / 结果", ["All", "Succeeded", "Failed"])
        selected_labels = st.multiselect("Status / 状态", labels, default=labels)
        minimum_ratio = st.number_input("Minimum IV/HV", min_value=0.0, value=0.0, step=0.1)
        sort_by = st.selectbox("Sort by / 排序", ["iv_hv_ratio", "underlying_iv", "ivp_52w", "spot_price", "symbol"])

    filtered = report.copy()
    if outcome == "Succeeded":
        filtered = filtered.loc[filtered["success"]]
    elif outcome == "Failed":
        filtered = filtered.loc[~filtered["success"]]
    if selected_labels:
        filtered = filtered.loc[filtered["status_label"].isin(selected_labels)]
    if minimum_ratio > 0:
        filtered = filtered.loc[filtered["iv_hv_ratio"] >= minimum_ratio]
    filtered = filtered.sort_values(sort_by, ascending=sort_by == "symbol", na_position="last")

    st.dataframe(
        filtered, width="stretch", hide_index=True,
        column_order=("symbol", "status_label_cn", "spot_price", "underlying_iv", "hv30", "iv_hv_ratio", "ivr_52w", "ivp_52w", "observation_count", "market_data_type", "data_quality", "status_explanation"),
        column_config={
            "symbol": "Symbol / 代码",
            "status_label_cn": "Status / 状态",
            "spot_price": st.column_config.NumberColumn("Spot / 股价", format="$%.2f"),
            "underlying_iv": st.column_config.NumberColumn("IV", format="percent"),
            "hv30": st.column_config.NumberColumn("HV30", format="percent"),
            "iv_hv_ratio": st.column_config.NumberColumn("IV/HV", format="%.2f"),
            "ivr_52w": st.column_config.NumberColumn("IVR 52W", format="percent"),
            "ivp_52w": st.column_config.NumberColumn("IVP 52W", format="percent"),
            "observation_count": "History / 历史样本",
            "market_data_type": "Data type / 行情类型",
            "data_quality": "Data quality / 数据质量",
            "status_explanation": st.column_config.TextColumn("Detailed meaning / 详细说明", width="large"),
        },
    )
    st.download_button(
        "Download current report CSV / 下载当前报表",
        data=filtered.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"volatility_watchlist_{selected_run[:8]}.csv",
        mime="text/csv", icon=":material/download:",
    )

    if not successful.empty:
        st.subheader("IV versus HV30 / 隐含与历史波动率")
        st.bar_chart(successful.set_index("symbol")[["underlying_iv", "hv30"]], x_label="Symbol", y_label="Annualized volatility")
        st.subheader("IV/HV ranking / 波动率溢价排序")
        st.bar_chart(successful.sort_values("iv_hv_ratio", ascending=False), x="symbol", y="iv_hv_ratio", x_label="Symbol", y_label="IV/HV")
        selected_symbol = st.selectbox("Symbol history / 个股历史", sorted(successful["symbol"].unique().tolist()))
        history = service.history(selected_symbol)
        if not history.empty:
            st.line_chart(history.sort_values("market_date"), x="market_date", y=["underlying_iv", "hv30"], x_label="Date", y_label="Annualized volatility")

    aggregate_history = service.watchlist_history()
    if not aggregate_history.empty:
        st.subheader("Watchlist median trend / 自选股中位趋势")
        st.line_chart(aggregate_history, x="market_date", y=["median_iv", "median_hv30"], x_label="Date", y_label="Annualized volatility")

    with st.expander("Status-label guide / 状态标签详细说明", expanded=True):
        st.warning(
            "These labels describe volatility pricing, not price direction. IV premium does not mean overbought or bearish; IV discount does not mean undervalued or bullish."
        )
        st.dataframe(volatility_status_guide(), width="stretch", hide_index=True)
