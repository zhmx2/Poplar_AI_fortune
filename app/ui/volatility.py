from __future__ import annotations

from time import monotonic

import pandas as pd
import streamlit as st

from app.config import Settings
from app.services.volatility import VolatilityService
from app.ui.volatility_dashboard import render_watchlist_dashboard


def _percent(value: float | None) -> str:
    return "N/A" if value is None or pd.isna(value) else f"{value:.1%}"


def _number(value: float | None, prefix: str = "") -> str:
    return (
        "N/A"
        if value is None or pd.isna(value)
        else f"{prefix}{value:,.2f}"
    )


def _render_snapshot(snapshot: dict) -> None:
    with st.container(horizontal=True):
        st.metric("Spot / 股价", _number(snapshot.get("spot_price"), "$"), border=True)
        st.metric("Underlying IV / 标的IV", _percent(snapshot.get("underlying_iv")), border=True)
        st.metric("HV30 / 30日历史波动率", _percent(snapshot.get("hv30")), border=True)
        ratio = snapshot.get("iv_hv_ratio")
        st.metric("IV/HV", "N/A" if ratio is None else f"{ratio:.2f}", border=True)
        st.metric("IVR 52W", _percent(snapshot.get("ivr_52w")), border=True)
        st.metric("IVP 52W", _percent(snapshot.get("ivp_52w")), border=True)
    st.caption(
        f"Data: {snapshot.get('market_data_type', 'unknown')} · "
        f"{snapshot.get('data_quality', '')}"
    )


def render_volatility(service: VolatilityService, settings: Settings) -> None:
    st.subheader("IBKR volatility research / IBKR波动率研究")
    st.caption(
        "Read-only IV, HV30, option chain, Greeks and locally accumulated "
        "IVR/IVP. No order functions are implemented."
    )
    if settings.ibkr_volatility_mode == "mock":
        st.info(
            "Mock mode is active. Values are illustrative and must not be used "
            "for investment decisions. Set IBKR_VOLATILITY_MODE=tws only after "
            "TWS read-only API is configured."
        )
    else:
        st.warning(
            "TWS mode is active. Delayed IV/Greeks availability depends on your "
            "IBKR market-data permissions; missing values are not replaced."
        )

    symbol = st.text_input(
        "US stock symbol / 美股代码",
        value=settings.default_symbol,
        key="volatility_symbol",
    ).strip().upper()
    with st.container(horizontal=True):
        snapshot_clicked = st.button(
            "Load and save daily IV snapshot",
            icon=":material/candlestick_chart:",
            disabled=not bool(symbol),
        )
        expiries_clicked = st.button(
            "Load option expirations",
            icon=":material/calendar_month:",
            disabled=not bool(symbol),
        )
        st.metric("Mode / 模式", settings.ibkr_volatility_mode.upper())

    if snapshot_clicked:
        started_at = monotonic()
        status = st.status(
            f"Loading {symbol} volatility snapshot...",
            expanded=True,
        )

        def show_progress(message: str) -> None:
            status.write(f"{monotonic() - started_at:5.1f}s — {message}")

        try:
            snapshot = service.snapshot(
                symbol,
                progress=show_progress,
            ).to_dict()
            st.session_state["volatility_snapshot"] = snapshot
            st.session_state["volatility_snapshot_symbol"] = symbol
            status.update(
                label=(
                    f"{symbol} snapshot completed in "
                    f"{monotonic() - started_at:.1f} seconds"
                ),
                state="complete",
                expanded=True,
            )
        except Exception as exc:
            status.update(
                label=(
                    f"{symbol} snapshot failed after "
                    f"{monotonic() - started_at:.1f} seconds"
                ),
                state="error",
                expanded=True,
            )
            st.error(f"Volatility snapshot failed: {type(exc).__name__}: {exc}")

    snapshot = st.session_state.get("volatility_snapshot")
    if snapshot and st.session_state.get("volatility_snapshot_symbol") == symbol:
        _render_snapshot(snapshot)
        history = service.history(symbol)
        if not history.empty:
            chart = history[["market_date", "underlying_iv", "hv30"]].copy()
            st.line_chart(
                chart,
                x="market_date",
                y=["underlying_iv", "hv30"],
                x_label="Date",
                y_label="Annualized volatility",
            )
            with st.expander("Local IV history / 本地IV历史"):
                st.dataframe(
                    history,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "market_date": st.column_config.DateColumn("Date / 日期"),
                        "spot_price": st.column_config.NumberColumn(
                            "Spot / 股价", format="$%.2f"
                        ),
                        "underlying_iv": st.column_config.NumberColumn(
                            "IV", format="percent"
                        ),
                        "hv30": st.column_config.NumberColumn(
                            "HV30", format="percent"
                        ),
                        "ivr_52w": st.column_config.NumberColumn(
                            "IVR", format="percent"
                        ),
                        "ivp_52w": st.column_config.NumberColumn(
                            "IVP", format="percent"
                        ),
                    },
                )

    if expiries_clicked:
        expiry_started_at = monotonic()
        expiry_status = st.status(
            f"Loading {symbol} option expirations...",
            expanded=True,
        )

        def show_expiry_progress(message: str) -> None:
            expiry_status.write(
                f"{monotonic() - expiry_started_at:5.1f}s — {message}"
            )

        try:
            loaded_expirations = service.expirations(
                symbol,
                progress=show_expiry_progress,
            )
            st.session_state["option_expirations"] = loaded_expirations
            st.session_state["option_expiration_symbol"] = symbol
            expiry_status.update(
                label=(
                    f"{symbol}: loaded {len(loaded_expirations)} expirations "
                    f"in {monotonic() - expiry_started_at:.1f} seconds"
                ),
                state="complete",
                expanded=True,
            )
        except Exception as exc:
            expiry_status.update(
                label=(
                    f"{symbol} expiration request failed after "
                    f"{monotonic() - expiry_started_at:.1f} seconds"
                ),
                state="error",
                expanded=True,
            )
            st.error(f"Option expiration request failed: {type(exc).__name__}: {exc}")

    expirations = (
        st.session_state.get("option_expirations", [])
        if st.session_state.get("option_expiration_symbol") == symbol
        else []
    )
    if expirations:
        expiry = st.selectbox(
            "Option expiry / 期权到期日",
            expirations,
            key=f"option_expiry_{symbol}",
        )
        if st.button(
            "Load option chain and Greeks",
            icon=":material/table_view:",
            key=f"load_chain_{symbol}",
        ):
            chain_started_at = monotonic()
            chain_status = st.status(
                f"Loading {symbol} {expiry} option chain...",
                expanded=True,
            )

            def show_chain_progress(message: str) -> None:
                chain_status.write(
                    f"{monotonic() - chain_started_at:5.1f}s — {message}"
                )

            try:
                chain = service.option_chain(
                    symbol,
                    expiry,
                    progress=show_chain_progress,
                )
                st.session_state["option_chain"] = chain
                st.session_state["option_chain_key"] = (symbol, expiry)
                chain_status.update(
                    label=(
                        f"{symbol} {expiry}: loaded {len(chain)} contracts "
                        f"in {monotonic() - chain_started_at:.1f} seconds"
                    ),
                    state="complete",
                    expanded=True,
                )
            except Exception as exc:
                chain_status.update(
                    label=(
                        f"{symbol} {expiry} option chain failed after "
                        f"{monotonic() - chain_started_at:.1f} seconds"
                    ),
                    state="error",
                    expanded=True,
                )
                st.error(f"Option chain failed: {type(exc).__name__}: {exc}")

        chain = st.session_state.get("option_chain")
        if (
            isinstance(chain, pd.DataFrame)
            and st.session_state.get("option_chain_key") == (symbol, expiry)
            and not chain.empty
        ):
            choices = list(range(len(chain)))
            selected = st.selectbox(
                "Single contract / 单张期权",
                choices,
                format_func=lambda index: (
                    f"{chain.iloc[index]['option_right']} "
                    f"{chain.iloc[index]['strike']:g} · {expiry}"
                ),
                key=f"single_option_{symbol}_{expiry}",
            )
            contract = chain.iloc[selected]
            with st.container(horizontal=True):
                st.metric("Midpoint", _number(contract["midpoint"], "$"), border=True)
                st.metric("Option IV", _percent(contract["implied_vol"]), border=True)
                st.metric("Delta", _number(contract["delta"]), border=True)
                st.metric("Gamma", _number(contract["gamma"]), border=True)
                st.metric("Vega", _number(contract["vega"]), border=True)
                st.metric("Theta", _number(contract["theta"]), border=True)
            st.dataframe(
                chain.sort_values(["strike", "option_right"]),
                width="stretch",
                hide_index=True,
                column_config={
                    "expiry": st.column_config.DateColumn("Expiry / 到期日"),
                    "strike": st.column_config.NumberColumn("Strike / 行权价", format="$%.2f"),
                    "option_right": "Call/Put",
                    "bid": st.column_config.NumberColumn("Bid", format="$%.2f"),
                    "ask": st.column_config.NumberColumn("Ask", format="$%.2f"),
                    "midpoint": st.column_config.NumberColumn("Mid", format="$%.2f"),
                    "implied_vol": st.column_config.NumberColumn("IV", format="percent"),
                    "delta": st.column_config.NumberColumn("Delta", format="%.4f"),
                    "gamma": st.column_config.NumberColumn("Gamma", format="%.4f"),
                    "vega": st.column_config.NumberColumn("Vega", format="%.4f"),
                    "theta": st.column_config.NumberColumn("Theta", format="%.4f"),
                },
            )

    render_watchlist_dashboard(service, settings)
    return

    st.divider()
    st.subheader("Watchlist scan / 自选股扫描")
    if st.button("Scan watchlist", icon=":material/radar:"):
        scan_started_at = monotonic()
        scan_status = st.status(
            "Starting watchlist scan...",
            expanded=True,
        )

        def show_scan_progress(message: str) -> None:
            scan_status.write(
                f"{monotonic() - scan_started_at:5.1f}s — {message}"
            )

        try:
            scan = service.scan(
                settings.volatility_watchlist,
                progress=show_scan_progress,
            )
            st.session_state["volatility_scan"] = scan
            failed = (
                scan.get("data_quality", pd.Series(dtype=str))
                .fillna("")
                .str.startswith("Unavailable:")
                .sum()
            )
            scan_status.update(
                label=(
                    f"Watchlist scan completed in "
                    f"{monotonic() - scan_started_at:.1f} seconds "
                    f"({len(scan) - failed} succeeded, {failed} failed)"
                ),
                state="complete" if failed == 0 else "error",
                expanded=failed > 0,
            )
        except Exception as exc:
            scan_status.update(
                label=(
                    f"Watchlist scan failed after "
                    f"{monotonic() - scan_started_at:.1f} seconds"
                ),
                state="error",
                expanded=True,
            )
            st.error(
                f"Watchlist scan failed: {type(exc).__name__}: {exc}"
            )
    scan = st.session_state.get("volatility_scan")
    if isinstance(scan, pd.DataFrame) and not scan.empty:
        st.dataframe(
            scan,
            width="stretch",
            hide_index=True,
            column_config={
                "spot_price": st.column_config.NumberColumn("Spot", format="$%.2f"),
                "underlying_iv": st.column_config.NumberColumn("IV", format="percent"),
                "hv30": st.column_config.NumberColumn("HV30", format="percent"),
                "ivr_52w": st.column_config.NumberColumn("IVR", format="percent"),
                "ivp_52w": st.column_config.NumberColumn("IVP", format="percent"),
            },
        )
