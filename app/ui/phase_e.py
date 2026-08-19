from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from app.config import Settings
from app.services.phase_e import PhaseEService
from app.ui.components import date_range_inputs


def filter_macro_date_range(
    frame: pd.DataFrame, start_date, end_date
) -> pd.DataFrame:
    dates = pd.to_datetime(frame["observation_date"])
    return frame.loc[
        dates.between(pd.Timestamp(start_date), pd.Timestamp(end_date), inclusive="both")
    ].copy()


def canonicalize_macro_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Prefer official observations and return one value per series/month."""
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    result["source"] = result["source"].fillna("unknown").astype(str)
    official_series = set(
        result.loc[result["source"].str.lower() != "mock", "series_id"]
    )
    result = result.loc[
        ~(
            result["series_id"].isin(official_series)
            & result["source"].str.lower().eq("mock")
        )
    ].copy()
    result["_source_priority"] = result["source"].str.upper().map(
        {"FRED": 3, "BLS": 3, "UNKNOWN": 1, "MOCK": 0}
    ).fillna(2)
    result["_retrieved_sort"] = pd.to_datetime(
        result.get("retrieved_at"), errors="coerce", utc=True
    )
    result = result.sort_values(
        ["series_id", "observation_date", "_source_priority", "_retrieved_sort"]
    ).drop_duplicates(["series_id", "observation_date"], keep="last")
    return result.drop(columns=["_source_priority", "_retrieved_sort"])


def filter_financial_date_range(
    frame: pd.DataFrame, start_date, end_date
) -> pd.DataFrame:
    dates = pd.to_datetime(frame["period_end"])
    return frame.loc[
        dates.between(pd.Timestamp(start_date), pd.Timestamp(end_date), inclusive="both")
    ].copy()


def build_cpi_yoy_chart(cpi: pd.DataFrame) -> alt.Chart:
    chart_data = cpi.dropna(subset=["YoY"]).copy()
    chart_data["observation_date"] = pd.to_datetime(chart_data["observation_date"])
    colors = alt.Scale(
        domain=["US CPI, all items", "US core CPI"],
        range=["#2563EB", "#DC2626"],
    )
    return alt.Chart(chart_data).mark_line(
        point=alt.OverlayMarkDef(size=45)
    ).encode(
        x=alt.X(
            "observation_date:T",
            title="Observation month / 观察月份",
            axis=alt.Axis(format="%Y-%m", labelAngle=-35),
        ),
        y=alt.Y(
            "YoY:Q",
            title="Year-over-year change / 同比变化",
            axis=alt.Axis(format=".1%"),
            scale=alt.Scale(zero=False),
        ),
        color=alt.Color(
            "series_name:N", title="Series / 指标", scale=colors,
            legend=alt.Legend(orient="top"),
        ),
        tooltip=[
            alt.Tooltip("observation_date:T", title="Month", format="%Y-%m"),
            alt.Tooltip("series_name:N", title="Series"),
            alt.Tooltip("YoY:Q", title="YoY", format=".2%"),
        ],
    ).properties(height=420)


def _latest_macro(frame: pd.DataFrame, series_id: str) -> tuple[str, str]:
    series = frame.loc[frame["series_id"] == series_id].sort_values("observation_date")
    if series.empty:
        return "N/A", ""
    latest = series.iloc[-1]
    if series_id in {"CUUR0000SA0", "CUUR0000SA0L1E"} and "YoY" in series:
        valid_yoy = series["YoY"].dropna()
        if not valid_yoy.empty:
            return (
                f"{valid_yoy.iloc[-1]:.1%} YoY",
                pd.Timestamp(latest["observation_date"]).strftime("%Y-%m"),
            )
    if series_id in {"CUUR0000SA0", "CUUR0000SA0L1E"} and len(series) >= 13:
        delta = latest["value"] / series.iloc[-13]["value"] - 1
        return f"{delta:.1%} YoY", pd.Timestamp(latest["observation_date"]).strftime("%Y-%m")
    return f"{latest['value']:.1f}", pd.Timestamp(latest["observation_date"]).strftime("%Y-%m")


def render_phase_e(service: PhaseEService, settings: Settings) -> None:
    st.subheader("Macro and company financial research / 宏观与公司财务")
    st.caption(
        "Official BLS/FRED macro series and SEC Company Facts are saved to the "
        "existing DuckDB. OpenBB is not used."
    )
    if settings.macro_mode == "mock":
        st.info("Mock mode is active. Values are illustrative and clearly marked as mock.")
    elif settings.macro_mode == "offline":
        st.info("Offline mode is active. This page reads DuckDB only.")
    else:
        st.success("Online macro mode is active. Network requests occur only when Sync is clicked.")

    macro_tab, financial_tab, cross_tab = st.tabs(
        ["Macro dashboard", "CAPEX and financials", "Cross-source research"]
    )
    with macro_tab:
        if st.button("Sync CPI and consumer sentiment", icon=":material/sync:"):
            with st.status("Loading official macro series...", expanded=True) as status:
                try:
                    loaded = service.sync_macro()
                    status.write(f"Saved {len(loaded):,} observations to DuckDB")
                    if settings.macro_mode == "online" and not settings.fred_api_key:
                        status.write("FRED key absent: CPI loaded from BLS; UMCSENT was skipped.")
                    status.update(label="Macro sync completed", state="complete")
                except Exception as exc:
                    status.update(label="Macro sync failed", state="error")
                    st.error(f"Macro sync failed: {type(exc).__name__}: {exc}")

        macro = service.macro_data()
        if macro.empty:
            st.info("No saved macro observations yet.")
        else:
            macro = canonicalize_macro_observations(macro)
            macro = macro.sort_values(["series_id", "observation_date"]).copy()
            macro["YoY"] = macro.groupby("series_id")["value"].pct_change(12)
            min_date = pd.Timestamp(macro["observation_date"].min()).date()
            max_date = pd.Timestamp(macro["observation_date"].max()).date()
            start_date, end_date = date_range_inputs(
                min_date,
                max_date,
                key_prefix="phase_e_macro_date_range",
            )
            filtered_macro = filter_macro_date_range(macro, start_date, end_date)
            st.caption(
                f"Showing {start_date:%Y-%m-%d} to {end_date:%Y-%m-%d} "
                f"({len(filtered_macro):,} observations)"
            )
            headline, headline_date = _latest_macro(filtered_macro, "CUUR0000SA0")
            core, core_date = _latest_macro(filtered_macro, "CUUR0000SA0L1E")
            sentiment, sentiment_date = _latest_macro(filtered_macro, "UMCSENT")
            with st.container(horizontal=True):
                st.metric("Headline CPI / 总体CPI", headline, headline_date, delta_color="off", border=True)
                st.metric("Core CPI / 核心CPI", core, core_date, delta_color="off", border=True)
                st.metric("Consumer sentiment / 消费者情绪", sentiment, sentiment_date, delta_color="off", border=True)

            cpi = filtered_macro.loc[
                filtered_macro["series_id"].isin(
                    ["CUUR0000SA0", "CUUR0000SA0L1E"]
                )
            ].copy()
            st.subheader("CPI year-over-year / CPI同比")
            cpi_chart_data = cpi.dropna(subset=["YoY"])
            if cpi_chart_data.empty:
                st.info("The selected range has no CPI year-over-year observations.")
            else:
                st.altair_chart(build_cpi_yoy_chart(cpi_chart_data), width="stretch")
                st.caption(
                    "Blue: headline CPI. Red: core CPI. Hover over a point for "
                    "the exact month and percentage. Official observations are "
                    "used instead of overlapping Mock records."
                )
                with st.expander("CPI YoY data / CPI同比数据"):
                    st.dataframe(
                        cpi_chart_data[
                            ["observation_date", "series_name", "YoY", "source"]
                        ].sort_values(
                            ["observation_date", "series_name"], ascending=[False, True]
                        ),
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "observation_date": st.column_config.DateColumn(
                                "Month / 月份", format="YYYY-MM"
                            ),
                            "series_name": "Series / 指标",
                            "YoY": st.column_config.NumberColumn(
                                "YoY / 同比", format="percent"
                            ),
                            "source": "Source / 来源",
                        },
                    )
            sentiment_frame = filtered_macro.loc[
                filtered_macro["series_id"] == "UMCSENT"
            ]
            if not sentiment_frame.empty:
                st.subheader("Consumer sentiment / 消费者情绪")
                st.line_chart(sentiment_frame, x="observation_date", y="value", x_label="Date", y_label="Index")
            with st.expander("Saved macro data / 已保存宏观数据"):
                st.dataframe(
                    filtered_macro.sort_values("observation_date", ascending=False),
                    width="stretch", hide_index=True,
                )

    with financial_tab:
        available = list(settings.phase_e_companies)
        symbol = st.selectbox("Company / 公司", available)
        if st.button("Sync selected company from SEC", icon=":material/cloud_download:"):
            with st.status(f"Loading {symbol} SEC Company Facts...", expanded=True) as status:
                try:
                    loaded = service.sync_company(symbol)
                    status.write(f"Saved {len(loaded):,} annual metric records")
                    status.update(label=f"{symbol} financial sync completed", state="complete")
                except Exception as exc:
                    status.update(label=f"{symbol} financial sync failed", state="error")
                    st.error(f"Company sync failed: {type(exc).__name__}: {exc}")

        financials = service.company_data(available or None)
        if financials.empty:
            st.info("No saved company financial data yet.")
        else:
            financials = financials.copy()
            financials["period_end"] = pd.to_datetime(financials["period_end"])
            financial_min = financials["period_end"].min().date()
            financial_max = financials["period_end"].max().date()
            financial_start, financial_end = date_range_inputs(
                financial_min,
                financial_max,
                key_prefix="phase_e_financial_date_range",
                start_label="Financial start date / 财务开始日期",
                end_label="Financial end date / 财务结束日期",
            )
            financials = filter_financial_date_range(
                financials, financial_start, financial_end
            )
            st.caption(
                f"Showing report periods {financial_start:%Y-%m-%d} to "
                f"{financial_end:%Y-%m-%d} ({len(financials):,} metric records)"
            )
            selected_symbols = st.multiselect(
                "Companies shown / 显示公司",
                sorted(financials["symbol"].unique()),
                default=sorted(financials["symbol"].unique()),
            )
            shown = financials.loc[financials["symbol"].isin(selected_symbols)].copy()
            if shown.empty:
                st.info("No company financial records match the selected filters.")
            else:
                shown["value_billions"] = shown["value"] / 1e9
                capex = shown.loc[shown["metric"] == "capex_cash"]
                st.subheader("Annual cash CAPEX / 年度现金CAPEX")
                st.bar_chart(capex, x="fiscal_year", y="value_billions", color="symbol", x_label="Fiscal year", y_label="USD billions", stack=False)
                st.subheader("Financial trends / 财务趋势")
                st.line_chart(shown, x="fiscal_year", y="value_billions", color="metric", x_label="Fiscal year", y_label="USD billions")
                st.warning(
                    "CAPEX is the SEC cash-flow XBRL concept. It may exclude assets "
                    "obtained through finance leases; compare company disclosures and "
                    "the retained XBRL tag before making peer conclusions."
                )
                st.dataframe(
                    shown.sort_values(["period_end", "symbol", "metric"], ascending=[False, True, True]),
                    width="stretch", hide_index=True,
                    column_order=("symbol", "company_name", "fiscal_year", "period_end", "metric", "value", "unit", "xbrl_tag", "form_type", "filed_date", "source_url", "source"),
                    column_config={
                        "value": st.column_config.NumberColumn("Value / 数值 (USD)", format="$%.0f"),
                        "source_url": st.column_config.LinkColumn("SEC filing / 申报链接", display_text="Open SEC"),
                        "period_end": st.column_config.DateColumn("Period end / 期末"),
                        "filed_date": st.column_config.DateColumn("Filed / 申报日"),
                    },
                )

    with cross_tab:
        macro = service.macro_data()
        financials = service.company_data()
        if macro.empty or financials.empty:
            st.info("Sync at least one macro dataset and one company before using this view.")
        else:
            st.write(
                "This view aligns macro conditions with annual company investment. "
                "It is descriptive and does not establish causation."
            )
            capex = financials.loc[financials["metric"] == "capex_cash"].copy()
            latest = capex.sort_values("period_end").groupby("symbol").tail(2)
            latest["capex_yoy"] = latest.groupby("symbol")["value"].pct_change()
            summary = latest.groupby("symbol").tail(1)[["symbol", "fiscal_year", "value", "capex_yoy", "xbrl_tag"]]
            st.dataframe(
                summary, width="stretch", hide_index=True,
                column_config={
                    "value": st.column_config.NumberColumn("Latest CAPEX / 最新CAPEX", format="$%.0f"),
                    "capex_yoy": st.column_config.NumberColumn("CAPEX YoY", format="percent"),
                },
            )
