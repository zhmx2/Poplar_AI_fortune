from __future__ import annotations

import pandas as pd
import streamlit as st

from app.analytics.liquidity import (
    build_net_liquidity_proxy,
    canonicalize_liquidity_observations,
    standardize_liquidity_units,
)
from app.analytics.h41 import H41_SERIES, build_h41_weekly_history
from app.analytics.market_confirmation import (
    market_return_summary,
    normalize_market_prices,
)
from app.analytics.market_pressure import latest_component_table
from app.config import Settings
from app.services.phase_f import LIQUIDITY_SERIES, PhaseFService
from app.services.phase_fb import PhaseFBService
from app.services.phase_fc import PhaseFCService
from app.ui.components import date_range_inputs


def filter_liquidity_date_range(
    frame: pd.DataFrame, start_date, end_date
) -> pd.DataFrame:
    dates = pd.to_datetime(frame["observation_date"])
    return frame.loc[
        dates.between(pd.Timestamp(start_date), pd.Timestamp(end_date), inclusive="both")
    ].copy()


def filter_market_date_range(
    frame: pd.DataFrame, start_date, end_date
) -> pd.DataFrame:
    dates = pd.to_datetime(frame["bar_date"])
    return frame.loc[
        dates.between(pd.Timestamp(start_date), pd.Timestamp(end_date), inclusive="both")
    ].copy()


def format_usd_bn(value, *, signed: bool = False) -> str:
    if pd.isna(value):
        return "N/A"
    numeric = float(value)
    if not signed:
        return f"${numeric:,.1f}bn"
    sign = "+" if numeric > 0 else "-" if numeric < 0 else ""
    return f"{sign}${abs(numeric):,.1f}bn"


def format_percent(value, *, signed: bool = False) -> str:
    if pd.isna(value):
        return "N/A"
    sign = "+" if signed else ""
    return f"{float(value):{sign}.1%}"


def trend_label(value) -> str:
    if pd.isna(value):
        return "N/A"
    if float(value) > 0:
        return "Increase / 增加"
    if float(value) < 0:
        return "Decrease / 减少"
    return "Unchanged / 持平"


def pressure_delta_display(value: float | None) -> tuple[str | None, str]:
    """Pressure rises are adverse (red); pressure falls are supportive (green)."""
    if value is None or pd.isna(value):
        return None, "off"
    if value > 0:
        return f"+{value:.1f} · pressure increased / 压力增加", "inverse"
    if value < 0:
        return f"{value:.1f} · pressure eased / 压力缓解", "inverse"
    return "0.0 · unchanged / 持平", "off"


def render_phase_f(
    service: PhaseFService,
    phase_fb: PhaseFBService,
    phase_fc: PhaseFCService,
    settings: Settings,
) -> None:
    st.subheader("Market liquidity and funding pressure / 市场流动性与资金压力")
    st.caption(
        "Phase F-A uses official FRED observations and the existing DuckDB; it "
        "does not use OpenBB or IBKR. / Phase F-A使用FRED官方数据和现有DuckDB，"
        "不使用OpenBB或IBKR。"
    )
    if settings.liquidity_mode == "mock":
        st.info("Mock mode is active; values are illustrative. / 当前为Mock模式，数据仅供演示。")
    elif settings.liquidity_mode == "offline":
        st.info("Offline mode is active; no FRED request will be made. / 当前为离线模式，不会访问FRED。")
    else:
        st.success("Online mode is active; FRED is contacted only during sync. / 当前为在线模式，仅在同步时访问FRED。")

    if st.button("Sync Phase F-A from FRED / 从FRED同步Phase F-A", icon=":material/sync:"):
        with st.status("Loading FRED liquidity series / 正在加载FRED流动性序列…", expanded=True) as status:
            try:
                loaded, errors = service.sync()
                status.write(f"Saved {len(loaded):,} observations to DuckDB / 已保存{len(loaded):,}条数据")
                for error in errors:
                    status.write(f"Skipped / 已跳过：{error}")
                state = "complete" if not errors else "error"
                label = "Phase F-A sync completed / 同步完成" if not errors else "Phase F-A sync completed with warnings / 同步完成但有警告"
                status.update(label=label, state=state)
            except Exception as exc:
                status.update(label="Phase F-A sync failed / 同步失败", state="error")
                st.error(f"Liquidity sync failed / 流动性同步失败：{type(exc).__name__}: {exc}")

    frame = service.data()
    if frame.empty:
        if settings.liquidity_mode == "online":
            st.warning(
                "No saved FRED observations are available; mock rows are excluded. "
                "/ 尚无已保存的FRED数据，Mock数据已从在线报表排除。请点击同步。"
            )
        else:
            st.info("No saved Phase F-A observations yet. / 尚无已保存的Phase F-A数据。")
        st.divider()
        render_phase_fb(phase_fb, settings)
        st.divider()
        render_phase_fc(phase_fc)
        return

    frame = canonicalize_liquidity_observations(frame)
    active_sources = sorted(frame["source"].dropna().astype(str).unique())
    st.caption("Dashboard data source / 报表数据来源：" + ", ".join(active_sources))
    frame["series_name"] = frame["series_id"].map(
        {series_id: definition[0] for series_id, definition in LIQUIDITY_SERIES.items()}
    ).fillna(frame["series_name"])
    frame = standardize_liquidity_units(frame)
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    min_date = frame["observation_date"].min().date()
    max_date = frame["observation_date"].max().date()
    start_date, end_date = date_range_inputs(
        min_date,
        max_date,
        key_prefix="phase_f_liquidity_date_range",
    )
    shown = filter_liquidity_date_range(frame, start_date, end_date)
    st.caption(
        f"Showing / 显示范围：{start_date:%Y-%m-%d} 至 {end_date:%Y-%m-%d} · "
        f"{len(shown):,} observations / 条数据"
    )

    with st.container(border=True):
        st.subheader("System liquidity components / 系统流动性组成")
        system = shown.loc[
            shown["series_id"].isin(["WALCL", "WTREGEN", "RRPONTSYD"])
        ]
        st.line_chart(
            system,
            x="observation_date",
            y="standardized_value",
            color="series_name",
            x_label="Observation date / 观察日期",
            y_label="USD billions / 十亿美元",
        )
        st.caption(
            "Fed assets add system liquidity, while balances held in the Treasury "
            "General Account and overnight reverse repos absorb cash from the system. "
            "/ 美联储资产扩张通常增加系统流动性；财政部一般账户余额和隔夜逆回购"
            "余额上升通常会从金融体系吸收现金。"
        )

    proxy = build_net_liquidity_proxy(frame)
    proxy = filter_liquidity_date_range(proxy, start_date, end_date)
    with st.container(border=True):
        st.subheader("Net liquidity proxy / 净流动性代理")
        if proxy.empty:
            st.info("WALCL, TGA and ON RRP must overlap. / 三项数据日期重叠后才能计算该指标。")
        else:
            st.line_chart(
                proxy,
                x="observation_date",
                y="net_liquidity_usd_bn",
                x_label="Observation date / 观察日期",
                y_label="USD billions / 十亿美元",
            )
        st.caption(
            "Formula: Federal Reserve total assets − Treasury General Account − "
            "overnight reverse repos. Weekly components are forward-filled across "
            "RRP observation dates. This is not official FRED data and is not an "
            "estimate of daily equity fund flows. / 公式：美联储总资产－财政部一般账户－"
            "隔夜逆回购。周度数据会按日向前填充。本指标不是FRED官方序列，也不代表"
            "股票市场每日实际资金流量。"
        )

    with st.container(border=True):
        st.subheader("Rates and real-yield pressure / 利率与实际收益率压力")
        rates = shown.loc[
            shown["series_id"].isin(["SOFR", "DGS2", "DGS10", "DFII10", "T10Y2Y"])
        ]
        st.line_chart(
            rates,
            x="observation_date",
            y="standardized_value",
            color="series_name",
            x_label="Observation date / 观察日期",
            y_label="Percent / 百分比",
        )
        st.caption(
            "Higher policy, nominal and real yields can tighten financing conditions "
            "and raise the discount rate applied to risk assets. / 政策利率、名义收益率"
            "和实际收益率上升，可能收紧融资条件并提高风险资产的折现率。"
        )

    conditions_col, credit_col = st.columns(2)
    with conditions_col:
        with st.container(border=True):
            st.subheader("Financial conditions / 金融条件")
            nfci = shown.loc[shown["series_id"].eq("NFCI")]
            st.line_chart(
                nfci,
                x="observation_date",
                y="standardized_value",
                x_label="Observation date / 观察日期",
                y_label="NFCI index / NFCI指数",
            )
            st.caption("Positive NFCI values indicate tighter-than-average conditions. / NFCI为正表示金融条件严于历史平均水平。")
    with credit_col:
        with st.container(border=True):
            st.subheader("High-yield credit spread / 高收益债信用利差")
            credit = shown.loc[shown["series_id"].eq("BAMLH0A0HYM2")]
            st.line_chart(
                credit,
                x="observation_date",
                y="standardized_value",
                x_label="Observation date / 观察日期",
                y_label="Percent / 百分比",
            )
            st.caption(
                "A widening high-yield spread generally signals rising credit risk and "
                "weaker risk appetite. / 高收益债利差扩大通常表示信用风险上升、"
                "市场风险偏好下降。"
            )

    with st.expander("Saved Phase F-A data / 已保存数据"):
        display = shown.sort_values(
            ["observation_date", "series_id"], ascending=[False, True]
        ).copy()
        display["unit"] = display["unit"].replace(
            {
                "Millions of USD": "Millions of USD / 百万美元",
                "Billions of USD": "Billions of USD / 十亿美元",
                "Percent": "Percent / 百分比",
                "Index": "Index / 指数",
            }
        )
        display["frequency"] = display["frequency"].replace(
            {"Daily": "Daily / 每日", "Weekly": "Weekly / 每周"}
        )
        st.dataframe(
            display[
                [
                    "observation_date",
                    "series_id",
                    "series_name",
                    "value",
                    "unit",
                    "frequency",
                    "source",
                    "retrieved_at",
                ]
            ],
            hide_index=True,
            column_config={
                "observation_date": st.column_config.DateColumn(
                    "Observation date / 观察日期"
                ),
                "series_id": "FRED series / FRED代码",
                "series_name": "Indicator / 指标",
                "value": st.column_config.NumberColumn("Raw value / 原始值", format="%.4f"),
                "unit": "Original unit / 原始单位",
                "frequency": "Frequency / 频率",
                "source": "Source / 来源",
                "retrieved_at": st.column_config.DatetimeColumn(
                    "Retrieved / 获取时间"
                ),
            },
        )
        st.caption("Configured FRED series / 已配置FRED序列：" + ", ".join(LIQUIDITY_SERIES))

    st.divider()
    render_h41_module(frame)

    st.divider()
    render_phase_fb(phase_fb, settings)
    st.divider()
    render_phase_fc(phase_fc)


def render_h41_module(frame: pd.DataFrame) -> None:
    st.subheader("H.4.1 selected indicators / H.4.1精选指标")
    st.caption(
        "Official weekly Federal Reserve balance-sheet observations from FRED. "
        "WRBWFRBL is the primary reserve series; WRESBAL is shown as a smoothing "
        "reference. / 通过FRED获取的美联储官方周度资产负债表数据。WRBWFRBL为"
        "准备金主序列，WRESBAL作为平滑参考。"
    )
    history = build_h41_weekly_history(frame)
    if history.empty:
        st.info(
            "WRBWFRBL has not been saved yet. Run the Phase F-A FRED sync first. "
            "/ 尚未保存WRBWFRBL，请先执行Phase F-A的FRED同步。"
        )
        return

    history["observation_date"] = pd.to_datetime(history["observation_date"])
    latest = history.sort_values("observation_date").iloc[-1]
    with st.container(horizontal=True):
        st.metric(
            "Reserve balances / 准备金余额",
            format_usd_bn(latest["reserve_balances_usd_bn"]),
            f"{format_usd_bn(latest['reserve_change_4w_usd_bn'], signed=True)} over 4W / 4周",
            border=True,
            chart_data=history["reserve_balances_usd_bn"].tail(26).tolist(),
            chart_type="line",
        )
        st.metric(
            "1-week change / 1周变化",
            trend_label(latest["reserve_change_1w_usd_bn"]),
            format_usd_bn(latest["reserve_change_1w_usd_bn"], signed=True),
            delta_color="normal",
            border=True,
        )
        st.metric(
            "Year-over-year / 同比变化",
            format_percent(latest["reserve_yoy_pct"], signed=True),
            format_usd_bn(latest["reserve_change_52w_usd_bn"], signed=True),
            delta_color="normal",
            border=True,
        )
        st.metric(
            "Reserves / total assets / 准备金占总资产",
            format_percent(latest["reserve_to_assets_ratio"]),
            border=True,
        )

    min_date = history["observation_date"].min().date()
    max_date = history["observation_date"].max().date()
    start_date, end_date = date_range_inputs(
        min_date, max_date, key_prefix="phase_f_h41_date_range"
    )
    shown = history.loc[
        history["observation_date"].between(
            pd.Timestamp(start_date), pd.Timestamp(end_date), inclusive="both"
        )
    ].copy()

    with st.container(border=True):
        st.subheader("Reserve levels: Wednesday and weekly average / 准备金：周三水平与周平均")
        reserve_chart = shown[
            ["observation_date", "reserve_balances_usd_bn", "reserve_week_average_usd_bn"]
        ].rename(
            columns={
                "reserve_balances_usd_bn": "WRBWFRBL · Wednesday / 周三水平",
                "reserve_week_average_usd_bn": "WRESBAL · Week average / 周平均",
            }
        ).melt("observation_date", var_name="series", value_name="value")
        st.line_chart(
            reserve_chart,
            x="observation_date",
            y="value",
            color="series",
            x_label="Observation date / 观察日期",
            y_label="USD billions / 十亿美元",
        )
        st.caption(
            "The Wednesday level is used for calculations so that it aligns with other "
            "H.4.1 Wednesday observations. / 计算采用周三水平，以便与其他H.4.1周三"
            "时点数据保持一致。"
        )

    change_col, ratio_col = st.columns(2)
    with change_col:
        with st.container(border=True):
            st.subheader("Reserve changes / 准备金变化")
            changes = shown[
                ["observation_date", "reserve_change_1w_usd_bn", "reserve_change_4w_usd_bn", "reserve_change_52w_usd_bn"]
            ].rename(columns={
                "reserve_change_1w_usd_bn": "1W / 1周",
                "reserve_change_4w_usd_bn": "4W / 4周",
                "reserve_change_52w_usd_bn": "52W / 52周",
            }).melt("observation_date", var_name="period", value_name="change")
            st.line_chart(
                changes, x="observation_date", y="change", color="period",
                x_label="Observation date / 观察日期",
                y_label="Change, USD billions / 变化，十亿美元",
            )
    with ratio_col:
        with st.container(border=True):
            st.subheader("Reserve share of Fed assets / 准备金占美联储总资产比例")
            st.line_chart(
                shown, x="observation_date", y="reserve_to_assets_ratio",
                x_label="Observation date / 观察日期",
                y_label="Ratio / 比例",
            )
            st.caption(
                "This ratio describes balance-sheet composition, not a regulatory "
                "capital or reserve requirement. / 该比例描述资产负债表结构，不是"
                "监管资本率或法定准备金率。"
            )

    with st.container(border=True):
        st.subheader("Federal Reserve asset structure / 美联储资产结构")
        assets = shown[
            ["observation_date", "treasuries_usd_bn", "mbs_usd_bn", "agency_debt_usd_bn", "facility_loans_usd_bn"]
        ].rename(columns={
            "treasuries_usd_bn": "Treasuries / 美国国债",
            "mbs_usd_bn": "MBS / 抵押贷款支持证券",
            "agency_debt_usd_bn": "Agency debt / 机构债",
            "facility_loans_usd_bn": "Facility loans / 信贷工具贷款",
        }).melt("observation_date", var_name="asset", value_name="value")
        st.line_chart(
            assets, x="observation_date", y="value", color="asset",
            x_label="Observation date / 观察日期",
            y_label="USD billions / 十亿美元",
        )

    qt_col, funding_col = st.columns(2)
    with qt_col:
        with st.container(border=True):
            st.subheader("QT runoff pace / QT缩表速度")
            st.metric(
                "Securities holdings: 4W trend / 证券持仓：4周趋势",
                format_usd_bn(latest["securities_usd_bn"]),
                f"{format_usd_bn(-latest['qt_runoff_4w_usd_bn'], signed=True)} over 4W / 4周",
                delta_color="normal",
                border=True,
            )
            st.metric(
                "Securities holdings: 13W trend / 证券持仓：13周趋势",
                format_usd_bn(latest["securities_usd_bn"]),
                f"{format_usd_bn(-latest['qt_runoff_13w_usd_bn'], signed=True)} over 13W / 13周",
                delta_color="normal",
                border=True,
            )
            st.caption(
                "The colored delta is the change in Treasuries + MBS + agency debt: "
                "a red decrease indicates runoff; a green increase indicates expansion. "
                "/ 彩色变化值为国债+MBS+机构债的持仓变化：红色下降表示缩减，"
                "绿色上升表示扩张。"
            )
    with funding_col:
        with st.container(border=True):
            st.subheader("Bank funding pressure / 银行融资压力")
            st.metric(
                "Liquidity facility loans / 流动性工具贷款",
                format_usd_bn(latest["facility_loans_usd_bn"]),
                f"{format_usd_bn(latest['facility_loans_change_4w_usd_bn'], signed=True)} over 4W / 4周",
                delta_color="inverse",
                border=True,
            )
            st.line_chart(
                shown, x="observation_date", y="facility_loans_usd_bn",
                x_label="Observation date / 观察日期",
                y_label="USD billions / 十亿美元",
            )
            st.caption(
                "A sharp rise can indicate greater use of Federal Reserve credit, but "
                "must be interpreted with facility details and market context. / 突然"
                "上升可能表示对美联储信贷工具的使用增加，但需结合工具明细和市场环境。"
            )

    with st.container(border=True):
        st.subheader("Reserves versus net-liquidity proxy / 准备金与净流动性代理对比")
        comparison = shown[
            ["observation_date", "reserve_change_4w_usd_bn", "net_liquidity_change_4w_usd_bn"]
        ].rename(columns={
            "reserve_change_4w_usd_bn": "Reserve 4W change / 准备金4周变化",
            "net_liquidity_change_4w_usd_bn": "Net-liquidity proxy 4W change / 净流动性代理4周变化",
        }).melt("observation_date", var_name="measure", value_name="change")
        st.line_chart(
            comparison, x="observation_date", y="change", color="measure",
            x_label="Observation date / 观察日期",
            y_label="4-week change, USD billions / 4周变化，十亿美元",
        )
        st.metric(
            "Latest 4W difference / 最新4周差异",
            format_usd_bn(latest["reserve_vs_net_liquidity_4w_gap_usd_bn"], signed=True),
            help="Neutral comparison value; it has no automatic good/bad color. / 中性对比值，不自动判断利好或利空。",
            border=True,
        )
        st.caption(
            "The difference helps identify when actual reserve changes diverge from "
            "the WALCL−TGA−ON RRP proxy. It is not an equity-fund-flow estimate. / "
            "该差异用于识别实际准备金变化何时偏离WALCL−TGA−ON RRP代理，"
            "不代表股票基金资金流量。"
        )

    with st.expander("Saved H.4.1 derived history / 已保存H.4.1派生历史"):
        st.dataframe(
            shown.sort_values("observation_date", ascending=False),
            hide_index=True,
            column_config={
                "observation_date": st.column_config.DateColumn("Date / 日期"),
                "reserve_yoy_pct": st.column_config.NumberColumn("Reserve YoY / 准备金同比", format="percent"),
                "reserve_to_assets_ratio": st.column_config.NumberColumn("Reserves/assets / 准备金占总资产", format="percent"),
            },
        )
        st.caption("H.4.1/FRED series / H.4.1的FRED序列：" + ", ".join(H41_SERIES))


def render_phase_fb(service: PhaseFBService, settings: Settings) -> None:
    st.subheader("Phase F-B: market confirmation basket / 市场确认篮子")
    st.caption(
        "Daily IBKR historical prices confirm whether liquidity and funding changes "
        "are reflected across major asset groups. No trading or composite pressure "
        "score is included. / 使用IBKR日线历史价格确认流动性与融资变化是否反映在"
        "主要资产类别中。本阶段不包含交易功能或综合压力评分。"
    )
    mode = settings.market_confirmation_mode
    if mode == "mock":
        st.info("Mock mode is active. / 当前为Mock演示模式。")
    elif mode == "offline":
        st.info("Offline mode reads saved DuckDB bars only. / 离线模式只读取DuckDB。")
    else:
        st.success(
            "TWS mode is active; IBKR is contacted only during sync. / 当前为TWS模式，"
            "仅在同步时访问IBKR。"
        )

    if st.button(
        "Sync market confirmation basket / 同步市场确认篮子",
        icon=":material/sync:",
        key="phase_fb_sync",
    ):
        with st.status(
            "Loading daily market bars / 正在加载日线行情…", expanded=True
        ) as status:
            started = pd.Timestamp.now()

            def progress(message: str) -> None:
                elapsed = (pd.Timestamp.now() - started).total_seconds()
                status.write(f"{elapsed:.1f}s — {message}")

            try:
                loaded, errors = service.sync(progress)
                status.write(
                    f"Saved {len(loaded):,} bars / 已保存{len(loaded):,}条日线"
                )
                for error in errors:
                    status.write(f"Skipped / 已跳过：{error}")
                status.update(
                    label=(
                        "Market basket sync completed / 市场篮子同步完成"
                        if not errors
                        else "Sync completed with warnings / 同步完成但有警告"
                    ),
                    state="complete" if not errors else "error",
                )
            except Exception as exc:
                status.update(label="Market basket sync failed / 同步失败", state="error")
                st.error(
                    f"Market confirmation sync failed / 市场确认同步失败："
                    f"{type(exc).__name__}: {exc}"
                )

    frame = service.data()
    if frame.empty:
        if mode == "tws":
            st.warning(
                "No saved IBKR market bars are available; mock rows are excluded. "
                "/ 尚无IBKR历史行情，Mock数据已从TWS报表排除。"
            )
        else:
            st.info("No saved market-confirmation bars yet. / 尚无市场确认行情。")
        return

    frame = frame.copy()
    frame["bar_date"] = pd.to_datetime(frame["bar_date"])
    sources = ", ".join(sorted(frame["source"].astype(str).unique()))
    st.caption(f"Dashboard data source / 报表数据来源：{sources}")
    min_date = frame["bar_date"].min().date()
    max_date = frame["bar_date"].max().date()
    start_date, end_date = date_range_inputs(
        min_date,
        max_date,
        key_prefix="phase_fb_market_date_range",
    )
    shown = filter_market_date_range(frame, start_date, end_date)
    selected_symbols = st.multiselect(
        "Assets shown / 显示资产",
        options=list(settings.market_confirmation_basket),
        default=list(settings.market_confirmation_basket),
        key="phase_fb_symbols",
    )
    shown = shown.loc[shown["symbol"].isin(selected_symbols)].copy()
    st.caption(
        f"Showing / 显示范围：{start_date:%Y-%m-%d} 至 {end_date:%Y-%m-%d} · "
        f"{len(shown):,} bars / 条日线"
    )
    if shown.empty:
        st.info("No bars match the selected filters. / 没有符合筛选条件的行情。")
        return

    summary = market_return_summary(shown)
    with st.container(border=True):
        st.subheader("Latest market confirmation / 最新市场确认")
        st.dataframe(
            summary,
            hide_index=True,
            column_order=(
                "symbol", "asset_name", "asset_name_cn", "market_role_cn",
                "bar_date", "close", "return_1d", "return_20d",
                "return_63d", "source",
            ),
            column_config={
                "symbol": "Symbol / 代码",
                "asset_name": "Asset / 资产",
                "asset_name_cn": "Chinese name / 中文名称",
                "market_role_cn": "Market role / 市场角色",
                "bar_date": st.column_config.DateColumn("Date / 日期"),
                "close": st.column_config.NumberColumn("Close / 收盘价", format="%.2f"),
                "return_1d": st.column_config.NumberColumn("1D / 1日", format="percent"),
                "return_20d": st.column_config.NumberColumn("20D / 20日", format="percent"),
                "return_63d": st.column_config.NumberColumn("63D / 63日", format="percent"),
                "source": "Source / 来源",
            },
        )

    normalized = normalize_market_prices(shown)
    normalized["asset_label"] = (
        normalized["symbol"] + " · " + normalized["asset_name_cn"]
    )
    with st.container(border=True):
        st.subheader("Normalized performance / 标准化表现")
        st.line_chart(
            normalized,
            x="bar_date",
            y="normalized_close",
            color="asset_label",
            x_label="Trading date / 交易日期",
            y_label="Start = 100 / 起点=100",
        )
        st.caption(
            "Each selected asset is rebased to 100 at its first visible date. This "
            "supports cross-asset confirmation but is not a trading signal. / 每项资产"
            "在当前日期范围首日标准化为100，用于跨资产确认，不构成交易信号。"
        )

    with st.expander("Saved IBKR market bars / 已保存IBKR市场日线"):
        st.dataframe(
            shown.sort_values(["bar_date", "symbol"], ascending=[False, True]),
            hide_index=True,
            column_config={
                "bar_date": st.column_config.DateColumn("Date / 日期"),
                "fetched_at": st.column_config.DatetimeColumn(
                    "Fetched / 获取时间"
                ),
            },
        )


def render_phase_fc(service: PhaseFCService) -> None:
    st.subheader("Phase F-C: composite market pressure / 综合市场压力")
    st.caption(
        "This offline research model combines saved FRED and IBKR observations. "
        "It does not fetch data, estimate actual fund flows, or generate trading "
        "instructions. / 本离线研究模型组合已保存的FRED与IBKR数据，不会联网，"
        "不估算真实基金净流入流出，也不生成交易指令。"
    )

    if st.button(
        "Recalculate pressure history / 重新计算压力历史",
        icon=":material/calculate:",
        key="phase_fc_recalculate",
    ):
        with st.status(
            "Calculating aligned pressure history / 正在计算对齐后的压力历史…",
            expanded=True,
        ) as status:
            try:
                calculated = service.recalculate()
                status.write(
                    f"Saved {len(calculated):,} daily scores to DuckDB / "
                    f"已保存{len(calculated):,}个每日评分到DuckDB"
                )
                status.update(
                    label="Pressure history calculated / 压力历史计算完成",
                    state="complete",
                )
            except Exception as exc:
                status.update(
                    label="Pressure calculation failed / 压力计算失败",
                    state="error",
                )
                st.error(
                    f"Phase F-C failed / Phase F-C失败：{type(exc).__name__}: {exc}"
                )

    frame = service.data()
    if frame.empty:
        st.info(
            "No saved pressure history yet. Sync Phase F-A and F-B, then recalculate. "
            "/ 尚无已保存的压力历史。请先同步F-A和F-B，再重新计算。"
        )
        return

    frame = frame.copy()
    frame["score_date"] = pd.to_datetime(frame["score_date"])
    latest = frame.sort_values("score_date").iloc[-1]
    st.caption(
        f"Derived sources / 派生数据来源：F-A = {latest.get('liquidity_source', 'unknown')} · "
        f"F-B = {latest.get('market_source', 'unknown')}"
    )
    prior_20 = (
        frame.sort_values("score_date").iloc[-21]["composite_score"]
        if len(frame) > 20 else None
    )
    delta_20 = (
        float(latest["composite_score"] - prior_20)
        if prior_20 is not None and pd.notna(prior_20) else None
    )
    pressure_delta, pressure_delta_color = pressure_delta_display(delta_20)
    trend = frame.sort_values("score_date")["composite_score"].tail(30).tolist()

    with st.container(horizontal=True):
        st.metric(
            "Pressure score / 压力评分",
            f"{latest['composite_score']:.1f} / 100",
            pressure_delta,
            delta_color=pressure_delta_color,
            border=True,
            chart_data=trend,
            chart_type="line",
        )
        st.metric(
            "Market state / 市场状态",
            f"{latest['status_label']} / {latest['status_label_cn']}",
            border=True,
        )
        st.metric(
            "Data coverage / 数据覆盖",
            f"{latest['coverage_ratio']:.0%}",
            f"{int(latest['available_components'])} of 8 components / 8项中的"
            f"{int(latest['available_components'])}项",
            delta_color="off",
            border=True,
        )
        st.metric(
            "Score date / 评分日期",
            f"{latest['score_date']:%Y-%m-%d}",
            border=True,
        )

    st.info(
        f"{latest['status_explanation']} / {latest['status_explanation_cn']}"
    )
    st.caption(
        "Color meaning / 颜色含义: pressure increase = red; pressure easing = "
        "green; unchanged = gray. / 压力增加为红色，压力缓解为绿色，持平为灰色。"
    )

    component_table = latest_component_table(latest)
    with st.container(border=True):
        st.subheader("Latest component decomposition / 最新分项拆解")
        st.dataframe(
            component_table,
            hide_index=True,
            column_order=(
                "component", "component_cn", "weight", "raw_value", "score",
                "explanation_cn", "explanation",
            ),
            column_config={
                "component": "Component / 分项",
                "component_cn": "中文名称",
                "weight": st.column_config.NumberColumn("Weight / 权重", format="percent"),
                "raw_value": st.column_config.NumberColumn("Raw value / 原始值", format="%.4f"),
                "score": st.column_config.ProgressColumn(
                    "Pressure score / 压力分数", min_value=0, max_value=100, format="%.1f"
                ),
                "explanation_cn": "中文说明",
                "explanation": "Explanation / 说明",
            },
        )
        st.caption(
            "Each component is standardized only against its preceding rolling history. "
            "Available weights are renormalized; at least five components are required. "
            "/ 每个分项只使用截至当日的滚动历史标准化；缺失分项时对可用权重重新"
            "归一化，至少需要5个分项才生成综合评分。"
        )

    min_date = frame["score_date"].min().date()
    max_date = frame["score_date"].max().date()
    start_date, end_date = date_range_inputs(
        min_date, max_date, key_prefix="phase_fc_pressure_date_range"
    )
    shown = frame.loc[
        frame["score_date"].between(
            pd.Timestamp(start_date), pd.Timestamp(end_date), inclusive="both"
        )
    ].copy()
    with st.container(border=True):
        st.subheader("Historical pressure regime / 历史压力状态")
        st.line_chart(
            shown,
            x="score_date",
            y="composite_score",
            x_label="Score date / 评分日期",
            y_label="Pressure score (0–100) / 压力评分（0–100）",
        )
        st.caption(
            "Bands: below 30 supportive; 30–45 mild pressure; 45–55 neutral; "
            "55–70 elevated pressure; 70 or above high pressure. / 区间：低于30为"
            "流动性支持，30–45为轻度压力，45–55为中性，55–70为压力上升，"
            "70及以上为高压力。"
        )

    with st.expander("Saved pressure history / 已保存的压力历史"):
        st.dataframe(
            shown.sort_values("score_date", ascending=False)[
                [
                    "score_date", "composite_score", "coverage_ratio",
                    "available_components", "status_label", "status_label_cn",
                    "liquidity_source", "market_source", "calculated_at",
                ]
            ],
            hide_index=True,
            column_config={
                "score_date": st.column_config.DateColumn("Date / 日期"),
                "composite_score": st.column_config.NumberColumn("Score / 评分", format="%.1f"),
                "coverage_ratio": st.column_config.NumberColumn("Coverage / 覆盖率", format="percent"),
                "available_components": "Components / 可用分项",
                "status_label": "Status / 状态",
                "status_label_cn": "中文状态",
                "liquidity_source": "F-A source / F-A来源",
                "market_source": "F-B source / F-B来源",
                "calculated_at": st.column_config.DatetimeColumn("Calculated / 计算时间"),
            },
        )
