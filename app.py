from __future__ import annotations

import pandas as pd
import streamlit as st

from app.config import Settings
from app.db import Repository
from app.errors import ApplicationError
from app.services.ibkr import IBKRService
from app.services.openbb import OpenBBService
from app.services.research import ResearchService
from app.services.institutions import InstitutionService
from app.ui.sec_holdings import render_sec_holdings
from app.services.volatility import VolatilityService
from app.ui.volatility import render_volatility
from app.services.phase_e import PhaseEService
from app.ui.phase_e import render_phase_e
from app.services.phase_f import PhaseFService
from app.services.phase_fb import PhaseFBService
from app.services.phase_fc import PhaseFCService
from app.ui.phase_f import render_phase_f
from app.services.stock_turnover import StockTurnoverService
from app.ui.stock_turnover import render_stock_turnover
from app.services.daily_quant import DailyQuantService
from app.services.trend_lines import TrendLineService


st.set_page_config(
    page_title="Local investment research",
    page_icon=":material/monitoring:",
    layout="wide",
)


def services() -> ResearchService:
    # ib_async connections are event-loop/thread bound. Streamlit reruns may
    # execute on a different script thread, so a facade containing IBKRService
    # must never be retained with st.cache_resource across reruns.
    settings = Settings()
    repo = Repository(settings.database_path)
    ibkr = IBKRService(settings)
    volatility = VolatilityService(settings, ibkr, repo)
    phase_e = PhaseEService(settings, repo)
    phase_f = PhaseFService(settings, repo)
    phase_fb = PhaseFBService(settings, ibkr, repo)
    phase_fc = PhaseFCService(phase_f, phase_fb, repo)
    stock_turnover = StockTurnoverService(settings, ibkr, repo)
    daily_quant = DailyQuantService(settings, ibkr, repo)
    trend_lines = TrendLineService(repo)
    return ResearchService(
        ibkr,
        OpenBBService(settings),
        repo,
        InstitutionService(settings, repo),
        volatility,
        phase_e,
        phase_f,
        phase_fb,
        phase_fc,
        stock_turnover,
        daily_quant,
        trend_lines,
    )


svc = services()
settings = Settings()
st.session_state.setdefault("health", [])

st.title("Local investment research")
st.caption("Read-only IBKR research and offline DuckDB data")


def show_health(status) -> None:
    message = f"{status.service}: {status.message}"
    if status.state == "disabled":
        st.info(message, icon=":material/pause_circle:")
    elif status.ok:
        st.success(message, icon=":material/check_circle:")
    else:
        st.warning(message, icon=":material/warning:")


def show_error(action: str, exc: Exception) -> None:
    if isinstance(exc, ApplicationError):
        st.warning(str(exc), icon=":material/info:")
    else:
        st.error(
            f"{action} failed: {type(exc).__name__}: {exc}",
            icon=":material/error:",
        )


with st.sidebar:
    st.subheader("Safety")
    st.success("IBKR adapter is read-only. No order API is implemented.")
    st.caption(
        f"TWS: {settings.ibkr_host}:{settings.ibkr_port} · "
        f"client {settings.ibkr_client_id}"
    )
    if settings.openbb_enabled:
        st.warning("OpenBB network access is enabled.")
    else:
        st.info("OpenBB is frozen; no Yahoo Finance requests will be made.")
    if st.button(
        "Run connection checks",
        icon=":material/health_and_safety:",
        width="stretch",
    ):
        st.session_state["health"] = svc.health()
    for status in st.session_state["health"]:
        show_health(status)


health_tab, sec_tab, volatility_tab, turnover_tab, phase_e_tab, phase_f_tab, account_tab, positions_tab, quote_tab, archive_tab, cache_tab = st.tabs(
    [
        "Health",
        "SEC 13F holdings",
        "IBKR volatility",
        "Stock turnover",
        "Macro & financials",
        "Market liquidity",
        "Account",
        "Positions",
        "Quote",
        "OpenBB archive",
        "Local cache",
    ]
)

with sec_tab:
    render_sec_holdings(svc.institutions, settings)

with volatility_tab:
    render_volatility(svc.volatility, settings)

with turnover_tab:
    render_stock_turnover(
        svc.stock_turnover, settings, svc.daily_quant, svc.trend_lines
    )

with phase_e_tab:
    render_phase_e(svc.phase_e, settings)

with phase_f_tab:
    render_phase_f(svc.phase_f, svc.phase_fb, svc.phase_fc, settings)

with health_tab:
    st.subheader("Independent data-source status")
    st.write(
        "TWS is optional during the current phase. If it is unavailable, DuckDB "
        "and future SEC offline features continue to work."
    )
    if st.button("Check now", icon=":material/refresh:", key="health_check_main"):
        statuses = svc.health()
        st.session_state["health"] = statuses
        health_frame = pd.DataFrame([vars(item) for item in statuses])
        st.dataframe(health_frame, width="stretch", hide_index=True)

with account_tab:
    st.warning("Account values are sensitive and are shown only in this local browser session.")
    if st.button("Load account summary", icon=":material/account_balance:"):
        try:
            frame = svc.account_summary()
            preferred = frame[
                frame["tag"].isin(
                    [
                        "NetLiquidation",
                        "TotalCashValue",
                        "BuyingPower",
                        "AvailableFunds",
                        "ExcessLiquidity",
                    ]
                )
            ]
            safe_frame = (preferred if not preferred.empty else frame).drop(
                columns=["account"], errors="ignore"
            )
            st.dataframe(safe_frame, width="stretch", hide_index=True)
        except Exception as exc:
            show_error("Account summary", exc)

with positions_tab:
    if st.button("Load current positions", icon=":material/pie_chart:"):
        try:
            frame = svc.positions()
            safe_frame = frame.drop(columns=["account"], errors="ignore")
            st.dataframe(safe_frame, width="stretch", hide_index=True)
        except Exception as exc:
            show_error("Positions", exc)

with quote_tab:
    quote_symbol = (
        st.text_input("US stock symbol", settings.default_symbol, key="quote_symbol")
        .strip()
        .upper()
    )
    if st.button(
        "Request IBKR delayed quote",
        icon=":material/query_stats:",
        disabled=not bool(quote_symbol),
    ):
        try:
            quote = svc.quote(quote_symbol)
            st.json(quote.to_dict())
            if quote.market_data_type == "unknown":
                st.info(
                    "IBKR did not label the snapshot. Check data permissions "
                    "and TWS messages."
                )
        except Exception as exc:
            show_error("Quote", exc)

with archive_tab:
    st.subheader("OpenBB archive")
    if settings.openbb_enabled:
        st.warning("OpenBB is enabled in .env. Phase A expects OPENBB_ENABLED=false.")
    else:
        st.info(
            "OpenBB is frozen. This page reads only existing DuckDB history and "
            "does not import OpenBB or contact Yahoo Finance."
        )
    try:
        symbols = svc.repo.historical_symbols()
        if symbols:
            history_symbol = st.selectbox("Cached symbol", symbols)
            cached = svc.repo.historical_bars(history_symbol).sort_values("bar_time")
            if not cached.empty:
                st.line_chart(cached, x="bar_time", y="close")
                st.dataframe(cached, width="stretch", hide_index=True)
        else:
            st.caption("No OpenBB historical bars are currently cached.")
    except Exception as exc:
        show_error("OpenBB archive", exc)

with cache_tab:
    st.caption(f"DuckDB file: {settings.database_path}")
    st.dataframe(svc.repo.recent_quotes(), width="stretch", hide_index=True)
