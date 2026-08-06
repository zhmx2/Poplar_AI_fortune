from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import Settings
from app.services.institutions import InstitutionService


STYLER_SAFE_CELL_LIMIT = 250_000


def _can_style(frame: pd.DataFrame) -> bool:
    return frame.shape[0] * frame.shape[1] <= STYLER_SAFE_CELL_LIMIT


def _apply_column_preferences(
    service: InstitutionService,
    table_key: str,
    frame: pd.DataFrame,
    labels: dict[str, str],
) -> pd.DataFrame:
    available = frame.columns.tolist()
    preference = service.table_preference(table_key) or {}
    saved_order = [
        column
        for column in preference.get("column_order", [])
        if column in available
    ]
    order = saved_order + [column for column in available if column not in saved_order]
    saved_visible = [
        column
        for column in preference.get("visible_columns", order)
        if column in available
    ]
    visible = saved_visible or order

    with st.popover(
        "Configure columns / 配置列",
        icon=":material/view_column:",
    ):
        config = pd.DataFrame(
            {
                "column": order,
                "label": [labels.get(column, column) for column in order],
                "visible": [column in visible for column in order],
                "order": list(range(1, len(order) + 1)),
            }
        )
        edited = st.data_editor(
            config,
            width="stretch",
            hide_index=True,
            key=f"column_editor_{table_key}",
            disabled=["column", "label"],
            column_config={
                "column": None,
                "label": "Column / 列",
                "visible": st.column_config.CheckboxColumn("Visible / 显示"),
                "order": st.column_config.NumberColumn(
                    "Order / 顺序", min_value=1, step=1
                ),
            },
        )
        if st.button(
            "Save column configuration",
            icon=":material/save:",
            key=f"save_columns_{table_key}",
        ):
            configured = edited.sort_values(
                ["order", "column"], kind="stable"
            )
            new_order = configured["column"].tolist()
            new_visible = configured.loc[
                configured["visible"], "column"
            ].tolist()
            if not new_visible:
                st.warning("At least one column must remain visible.")
            else:
                service.save_table_preference(
                    table_key, new_visible, new_order
                )
                st.success("Column configuration saved to DuckDB.")
                order, visible = new_order, new_visible
    selected = [column for column in order if column in visible]
    return frame[selected]


def _render_institution_management(
    service: InstitutionService, settings: Settings
) -> None:
    manager = st.expander(
        "Institution management / 机构管理",
        icon=":material/domain_add:",
    )
    with manager:
        st.write(
            "Add a manager by SEC CIK. The official name and recent 13F filing "
            "history are verified with SEC before the record is saved."
        )
        with st.form("add_sec_institution", border=True):
            cik_input = st.text_input(
                "SEC CIK",
                placeholder="Example: 0001067983",
                help="Enter 1–10 digits. Leading zeroes are added automatically.",
            )
            name_cn = st.text_input(
                "Chinese display name / 中文显示名称（可选）"
            )
            add_clicked = st.form_submit_button(
                "Verify with SEC and save",
                icon=":material/verified:",
                disabled=settings.sec_mode != "online",
            )
        if settings.sec_mode != "online":
            st.info("Set SEC_MODE=online to verify and add an institution.")
        if add_clicked:
            try:
                added = service.add_institution(cik_input, name_cn)
                st.success(
                    f"Verified and saved: {added['name']} "
                    f"(CIK {added['cik']}); latest report "
                    f"{added['latest_report_date']}."
                )
            except Exception as exc:
                st.error(
                    f"Institution verification failed: "
                    f"{type(exc).__name__}: {exc}"
                )

        st.markdown("**Saved institutions / 已保存机构**")
        all_institutions = service.institutions(active_only=False).copy()
        editor_frame = all_institutions[
            [
                "institution_id", "name", "name_cn", "cik", "enabled",
                "user_added", "verified_at",
            ]
        ]
        edited = st.data_editor(
            editor_frame,
            width="stretch",
            hide_index=True,
            key="institution_preferences_editor",
            disabled=[
                "institution_id", "name", "cik", "user_added", "verified_at"
            ],
            column_config={
                "institution_id": None,
                "name": st.column_config.TextColumn(
                    "SEC official name / SEC官方名称", pinned=True
                ),
                "name_cn": "Display name / 显示名称",
                "cik": "CIK",
                "enabled": st.column_config.CheckboxColumn(
                    "Enabled / 启用"
                ),
                "user_added": st.column_config.CheckboxColumn(
                    "User added / 用户新增"
                ),
                "verified_at": st.column_config.DatetimeColumn(
                    "Verified / 验证时间", format="YYYY-MM-DD HH:mm"
                ),
            },
        )
        if st.button(
            "Save institution preferences",
            icon=":material/save:",
            key="save_institution_preferences",
        ):
            for row in edited.itertuples():
                service.update_preferences(
                    row.institution_id, row.name_cn, bool(row.enabled)
                )
            st.success("Institution display names and enabled status were saved.")


def _highlight_options(row: pd.Series) -> list[str]:
    is_option = row.get("security_type") == "OPTION"
    color = "background-color: rgba(255, 165, 0, 0.20)" if is_option else ""
    return [color] * len(row)


def _holdings_column_config() -> dict:
    return {
        "issuer_name": st.column_config.TextColumn(
            "Issuer / 发行人", pinned=True
        ),
        "title_of_class": "Class title / 证券类别",
        "security_type": "Type / 类型",
        "put_call": "Option / 期权",
        "cusip": "CUSIP",
        "value_usd_mn": st.column_config.NumberColumn(
            "Value / 市值 (USD million)", format="$%.2f"
        ),
        "portfolio_weight": st.column_config.NumberColumn(
            "Weight / 权重", format="percent"
        ),
        "shares": st.column_config.NumberColumn(
            "Shares / 股数", format="localized"
        ),
        "classification_method": "Classification / 分类方法",
        "manager_row_count": st.column_config.NumberColumn(
            "SEC rows / SEC明细行数", format="localized"
        ),
        "other_managers": "Other managers / 其他管理人",
        "investment_discretion": "Discretion / 投资权限",
        "other_manager": "Other manager / 其他管理人",
        "voting_sole": st.column_config.NumberColumn(
            "Voting sole / 单独表决权", format="localized"
        ),
        "voting_shared": st.column_config.NumberColumn(
            "Voting shared / 共享表决权", format="localized"
        ),
        "voting_none": st.column_config.NumberColumn(
            "Voting none / 无表决权", format="localized"
        ),
        "source": "Source / 来源",
    }


HOLDINGS_LABELS = {
    "issuer_name": "Issuer / 发行人",
    "title_of_class": "Class title / 证券类别",
    "security_type": "Type / 类型",
    "put_call": "Option / 期权",
    "cusip": "CUSIP",
    "value_usd_mn": "Value / 市值 (USD million)",
    "portfolio_weight": "Weight / 权重",
    "shares": "Shares / 股数",
    "classification_method": "Classification / 分类方法",
    "manager_row_count": "SEC rows / SEC明细行数",
    "other_managers": "Other managers / 其他管理人",
    "investment_discretion": "Discretion / 投资权限",
    "other_manager": "Other manager / 其他管理人",
    "voting_sole": "Voting sole / 单独表决权",
    "voting_shared": "Voting shared / 共享表决权",
    "voting_none": "Voting none / 无表决权",
    "source": "Source / 来源",
}


CHANGES_LABELS = {
    "issuer_name": "Issuer / 发行人",
    "title_of_class": "Class title / 证券类别",
    "security_type": "Type / 类型",
    "put_call": "Option / 期权",
    "cusip": "CUSIP",
    "status": "Change / 变化",
    "current_value_usd_mn": "Current value / 当前市值 (USD million)",
    "previous_value_usd_mn": "Previous value / 上期市值 (USD million)",
    "value_change_usd_mn": "Value change / 市值变化 (USD million)",
    "portfolio_weight_current": "Current weight / 当前权重",
    "portfolio_weight_previous": "Previous weight / 上期权重",
    "weight_change": "Weight change / 权重变化",
    "shares_current": "Current shares / 当前数量",
    "shares_previous": "Previous shares / 上期数量",
    "shares_change": "Shares change / 数量变化",
    "change_rate": "Change rate / 变化率",
}


def _render_changes(
    service: InstitutionService,
    institution_id: str,
    periods: list,
) -> None:
    st.subheader("Quarterly holdings changes / 季度持仓变化")
    if len(periods) < 2:
        st.info(
            "At least two saved report quarters are required. "
            "Use the SEC sync button to retrieve recent quarters."
        )
        return
    current_col, previous_col = st.columns(2)
    current_period = current_col.selectbox(
        "Current quarter / 当前季度",
        periods,
        index=0,
        key=f"change_current_{institution_id}",
    )
    previous_options = [period for period in periods if period != current_period]
    previous_period = previous_col.selectbox(
        "Previous quarter / 对比季度",
        previous_options,
        index=0,
        key=f"change_previous_{institution_id}_{current_period}",
    )
    changes = service.changes(institution_id, current_period, previous_period)

    counts = changes["status"].value_counts()
    with st.container(horizontal=True):
        st.metric("New / 新增", int(counts.get("NEW", 0)), border=True)
        st.metric("Increased / 增持", int(counts.get("INCREASED", 0)), border=True)
        st.metric("Decreased / 减持", int(counts.get("DECREASED", 0)), border=True)
        st.metric("Closed / 清仓", int(counts.get("CLOSED", 0)), border=True)

    status_filter = st.pills(
        "Change type / 变化类型",
        ["NEW", "INCREASED", "DECREASED", "CLOSED", "UNCHANGED"],
        selection_mode="multi",
        default=["NEW", "INCREASED", "DECREASED", "CLOSED"],
        key=f"change_status_{institution_id}",
    )
    if status_filter:
        changes = changes[changes["status"].isin(status_filter)]
    display = changes.copy()
    for source, target in (
        ("value_usd_current", "current_value_usd_mn"),
        ("value_usd_previous", "previous_value_usd_mn"),
        ("value_change_usd", "value_change_usd_mn"),
    ):
        display[target] = display[source] / 1e6
    display = display[
        [
            "issuer_name", "title_of_class", "security_type", "put_call",
            "cusip", "status", "current_value_usd_mn",
            "previous_value_usd_mn", "value_change_usd_mn",
            "portfolio_weight_current", "portfolio_weight_previous",
            "weight_change", "shares_current", "shares_previous",
            "shares_change", "change_rate",
        ]
    ]
    display = _apply_column_preferences(
        service, "sec_quarterly_changes", display, CHANGES_LABELS
    )
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        key=f"changes_table_{institution_id}_{current_period}_{previous_period}",
        column_config={
            "issuer_name": st.column_config.TextColumn(
                "Issuer / 发行人", pinned=True
            ),
            "title_of_class": "Class title / 证券类别",
            "security_type": "Type / 类型",
            "put_call": "Option / 期权",
            "cusip": "CUSIP",
            "status": "Change / 变化",
            "current_value_usd_mn": st.column_config.NumberColumn(
                "Current value / 当前市值 (USD million)", format="$%.2f"
            ),
            "previous_value_usd_mn": st.column_config.NumberColumn(
                "Previous value / 上期市值 (USD million)", format="$%.2f"
            ),
            "value_change_usd_mn": st.column_config.NumberColumn(
                "Value change / 市值变化 (USD million)", format="$%.2f"
            ),
            "portfolio_weight_current": st.column_config.NumberColumn(
                "Current weight / 当前权重", format="percent"
            ),
            "portfolio_weight_previous": st.column_config.NumberColumn(
                "Previous weight / 上期权重", format="percent"
            ),
            "weight_change": st.column_config.NumberColumn(
                "Weight change / 权重变化", format="percent"
            ),
            "shares_current": st.column_config.NumberColumn(
                "Current shares / 当前数量", format="localized"
            ),
            "shares_previous": st.column_config.NumberColumn(
                "Previous shares / 上期数量", format="localized"
            ),
            "shares_change": st.column_config.NumberColumn(
                "Shares change / 数量变化", format="localized"
            ),
            "change_rate": st.column_config.NumberColumn(
                "Change rate / 变化率", format="percent"
            ),
        },
    )
    st.caption(
        "Change rate is based on reported shares. NEW positions have no prior "
        "denominator, so their change rate is blank; CLOSED positions show -100%."
    )


def _render_reverse_lookup(service: InstitutionService) -> None:
    st.divider()
    st.subheader("Security reverse lookup / 证券反向查询")
    st.caption(
        "Search all enabled institutions using locally saved SEC quarters."
    )
    with st.form("security_reverse_lookup", border=False):
        with st.container(horizontal=True):
            query = st.text_input(
                "Issuer or CUSIP / 发行人或CUSIP",
                placeholder="Example: NVIDIA or 67066G104",
            )
            submitted = st.form_submit_button(
                "Search institutions",
                icon=":material/manage_search:",
            )
    if submitted:
        try:
            st.session_state["security_reverse_results"] = service.reverse_lookup(
                query
            )
            st.session_state["security_reverse_query"] = query.strip()
        except Exception as exc:
            st.error(f"Reverse lookup failed: {type(exc).__name__}: {exc}")
            st.session_state.pop("security_reverse_results", None)

    results = st.session_state.get("security_reverse_results")
    if results is None:
        return
    if results.empty:
        st.info(
            f"No saved institutional holdings matched "
            f"“{st.session_state.get('security_reverse_query', '')}”."
        )
        return

    current_holders = results[results["current_value_usd"] > 0]
    with st.container(horizontal=True):
        st.metric(
            "Current institutions / 当前持有机构",
            current_holders["institution_name"].nunique(),
            border=True,
        )
        st.metric(
            "Matched records / 匹配记录", len(results), border=True
        )
        st.metric(
            "Combined current value / 当前合计市值",
            f"${current_holders['current_value_usd'].sum() / 1e9:,.2f} bn",
            border=True,
        )

    chart = current_holders.nlargest(20, "current_value_usd").copy()
    chart["current_value_usd_mn"] = chart["current_value_usd"] / 1e6
    if not chart.empty:
        st.bar_chart(
            chart,
            x="name_cn",
            y="current_value_usd_mn",
            x_label="Institution / 机构",
            y_label="Current reported value (USD million)",
            horizontal=True,
        )

    display = results.copy()
    for source, target in (
        ("current_value_usd", "current_value_usd_mn"),
        ("previous_value_usd", "previous_value_usd_mn"),
        ("value_change_usd", "value_change_usd_mn"),
    ):
        display[target] = display[source] / 1e6
    display = display[
        [
            "institution_name", "name_cn", "current_period",
            "previous_period", "issuer_name", "title_of_class",
            "security_type", "put_call", "cusip", "status",
            "current_value_usd_mn", "previous_value_usd_mn",
            "value_change_usd_mn", "current_weight", "previous_weight",
            "weight_change", "current_shares", "previous_shares",
            "shares_change", "change_rate",
        ]
    ]
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        key="security_reverse_results_table",
        column_config={
            "institution_name": st.column_config.TextColumn(
                "SEC institution / SEC机构", pinned=True
            ),
            "name_cn": "Display name / 显示名称",
            "current_period": st.column_config.DateColumn(
                "Current quarter / 当前季度"
            ),
            "previous_period": st.column_config.DateColumn(
                "Previous quarter / 上期季度"
            ),
            "issuer_name": "Issuer / 发行人",
            "title_of_class": "Class title / 证券类别",
            "security_type": "Type / 类型",
            "put_call": "Option / 期权",
            "cusip": "CUSIP",
            "status": "Change / 变化",
            "current_value_usd_mn": st.column_config.NumberColumn(
                "Current value / 当前市值 (USD million)", format="$%.2f"
            ),
            "previous_value_usd_mn": st.column_config.NumberColumn(
                "Previous value / 上期市值 (USD million)", format="$%.2f"
            ),
            "value_change_usd_mn": st.column_config.NumberColumn(
                "Value change / 市值变化 (USD million)", format="$%.2f"
            ),
            "current_weight": st.column_config.NumberColumn(
                "Current weight / 当前权重", format="percent"
            ),
            "previous_weight": st.column_config.NumberColumn(
                "Previous weight / 上期权重", format="percent"
            ),
            "weight_change": st.column_config.NumberColumn(
                "Weight change / 权重变化", format="percent"
            ),
            "current_shares": st.column_config.NumberColumn(
                "Current shares / 当前数量", format="localized"
            ),
            "previous_shares": st.column_config.NumberColumn(
                "Previous shares / 上期数量", format="localized"
            ),
            "shares_change": st.column_config.NumberColumn(
                "Shares change / 数量变化", format="localized"
            ),
            "change_rate": st.column_config.NumberColumn(
                "Change rate / 变化率", format="percent"
            ),
        },
    )
    st.info(
        "Results use each institution’s latest two effective quarters stored "
        "locally. Institutions with only one saved quarter are classified "
        "relative to an empty prior quarter."
    )


def render_sec_holdings(service: InstitutionService, settings: Settings) -> None:
    st.subheader("SEC 13F institutional holdings")
    st.caption(
        "Form 13F-HR / 13F-HR/A holdings, persisted by report quarter in DuckDB."
    )
    _render_institution_management(service, settings)
    institutions = service.institutions()
    if institutions.empty:
        st.warning(
            "No institutions are enabled. Re-enable one in Institution management."
        )
        return
    labels = {
        row.institution_id: f"{row.name_cn} · {row.name} (CIK {row.cik})"
        for row in institutions.itertuples()
    }
    institution_id = st.selectbox(
        "Institution / 机构",
        labels,
        format_func=lambda value: labels[value],
    )

    left, right = st.columns([2, 1])
    with left:
        if settings.sec_mode == "mock":
            clicked = st.button(
                "Load illustrative SEC mock data",
                icon=":material/science:",
                width="stretch",
            )
        elif settings.sec_mode == "online":
            clicked = st.button(
                "Sync latest four 13F quarters from SEC",
                icon=":material/cloud_download:",
                width="stretch",
            )
        else:
            clicked = False
            st.info("Offline mode reads previously saved DuckDB holdings.")
    with right:
        st.metric("SEC mode", settings.sec_mode.upper())

    if clicked:
        try:
            if settings.sec_mode == "mock":
                period = service.load_mock(institution_id)
                saved_message = f"Saved mock quarters through {period} to DuckDB."
            else:
                periods_saved = service.sync_recent(institution_id, quarter_count=4)
                period = periods_saved[0]
                saved_message = (
                    f"Saved {len(periods_saved)} SEC report quarter(s) through "
                    f"{period} to DuckDB."
                )
            st.success(saved_message)
        except Exception as exc:
            st.error(f"SEC data load failed: {type(exc).__name__}: {exc}")

    periods = service.periods(institution_id)
    if not periods:
        st.info(
            "No local holdings are available for this institution. "
            "Load mock data or sync in online mode."
        )
        _render_reverse_lookup(service)
        return
    report_period = st.selectbox(
        "Report quarter / 报告季度",
        periods,
        format_func=lambda value: str(value),
    )
    frame = service.holdings(institution_id, report_period)
    if frame.empty:
        st.info("This report contains no locally stored holdings.")
        _render_reverse_lookup(service)
        return
    aggregated_frame = service.aggregated_holdings(institution_id, report_period)

    total_usd = frame["value_usd"].sum()
    stock_value = frame.loc[frame["security_type"] == "STOCK", "value_usd"].sum()
    etf_value = frame.loc[frame["security_type"] == "ETF", "value_usd"].sum()
    with st.container(horizontal=True):
        st.metric(
            "Total value / 总市值", f"${total_usd / 1e9:,.2f} bn", border=True
        )
        st.metric(
            "Positions / 汇总持仓数",
            f"{len(aggregated_frame):,}",
            border=True,
            help=f"Aggregated from {len(frame):,} SEC raw rows.",
        )
        st.metric(
            "Stock / 股票", f"${stock_value / 1e6:,.1f} mn", border=True
        )
        st.metric("ETF / ETF", f"${etf_value / 1e6:,.1f} mn", border=True)

    st.subheader("Top holdings by reported value")
    security_type = st.segmented_control(
        "Security type",
        ["ALL", "STOCK", "ETF", "OPTION"],
        default="ALL",
    )
    chart = aggregated_frame if security_type == "ALL" else aggregated_frame[
        aggregated_frame["security_type"] == security_type
    ]
    chart = chart.nlargest(20, "value_usd").copy()
    chart["value_usd_mn"] = chart["value_usd"] / 1e6
    if chart.empty:
        st.caption(f"No {security_type} rows in this report.")
    else:
        st.bar_chart(
            chart,
            x="issuer_name",
            y="value_usd_mn",
            x_label="Security / 证券",
            y_label="Reported value (USD million)",
            horizontal=True,
        )

    st.subheader("Current holdings / 当前持仓")
    holdings_view = st.segmented_control(
        "Display view / 显示视图",
        ["AGGREGATED", "SEC RAW ROWS"],
        default="AGGREGATED",
        key=f"holdings_view_{institution_id}_{report_period}",
        help=(
            "Aggregated combines Other Manager rows by CUSIP and Stock/Put/Call. "
            "SEC raw rows preserve the filing exactly."
        ),
    )
    with st.container(horizontal=True):
        holdings_type = st.segmented_control(
            "Holdings type / 持仓类型",
            ["ALL", "STOCK", "ETF", "OPTION"],
            default="ALL",
            key=f"holdings_type_{institution_id}_{report_period}",
        )
        holdings_search = st.text_input(
            "Search issuer or CUSIP / 搜索发行人或CUSIP",
            key=f"holdings_search_{institution_id}_{report_period}",
            placeholder="Issuer name or CUSIP",
        )
    display = (
        aggregated_frame.copy()
        if holdings_view == "AGGREGATED"
        else frame.copy()
    )
    if holdings_type != "ALL":
        display = display[display["security_type"] == holdings_type]
    if holdings_search.strip():
        needle = holdings_search.strip()
        display = display[
            display["issuer_name"].str.contains(needle, case=False, na=False)
            | display["cusip"].str.contains(needle, case=False, na=False)
        ]
    display["value_usd_mn"] = display["value_usd"] / 1e6
    if holdings_view == "AGGREGATED":
        display = display[
            [
                "issuer_name", "title_of_class", "security_type", "put_call",
                "cusip", "value_usd_mn", "portfolio_weight", "shares",
                "manager_row_count", "other_managers",
                "classification_method", "source",
            ]
        ]
        preference_key = "sec_current_holdings_aggregated"
    else:
        display = display[
            [
                "issuer_name", "title_of_class", "security_type", "put_call",
                "cusip", "value_usd_mn", "portfolio_weight", "shares",
                "investment_discretion", "other_manager", "voting_sole",
                "voting_shared", "voting_none", "classification_method",
                "source",
            ]
        ]
        preference_key = "sec_current_holdings_raw"
    option_count = int((display["security_type"] == "OPTION").sum())
    display = _apply_column_preferences(
        service, preference_key, display, HOLDINGS_LABELS
    )
    table_data = (
        display.style.apply(_highlight_options, axis=1)
        if _can_style(display) and "security_type" in display.columns
        else display
    )
    st.dataframe(
        table_data,
        width="stretch",
        hide_index=True,
        key=(
            f"holdings_table_{holdings_view}_{institution_id}_{report_period}"
        ),
        column_config=_holdings_column_config(),
    )
    if _can_style(display):
        st.caption(
            f"{holdings_view}: {len(display):,} rows shown; "
            f"{option_count:,} option rows. Option rows are highlighted when "
            "the Type column is visible."
        )
    else:
        st.info(
            f"This large table contains {len(display):,} rows and "
            f"{display.size:,} cells. Native rendering is used to avoid the "
            "Pandas Styler limit. Select OPTION or use search to reduce the "
            "table and restore orange option highlighting."
        )
    if holdings_view == "AGGREGATED":
        st.info(
            "Default view: rows are combined by CUSIP + Stock/Put/Call. "
            "SEC rows shows how many original filing lines were combined; "
            "Other managers lists their SEC manager identifiers."
        )
    else:
        st.info(
            "Audit view: each row is preserved from the SEC Information Table. "
            "Repeated CUSIP and Put/Call values may belong to different Other "
            "Manager identifiers and are not duplicate parser records."
        )
    st.info(
        "Stock/ETF labels are inferred from the 13F put/call field and a "
        "maintainable name heuristic. CUSIP alone does not reliably identify "
        "every ETF, so classifications should be reviewed before advanced analysis."
    )
    _render_changes(service, institution_id, periods)
    _render_reverse_lookup(service)
