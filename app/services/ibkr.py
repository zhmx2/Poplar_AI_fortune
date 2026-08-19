from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd

from app.analytics.volatility import historical_volatility
from app.config import Settings
from app.errors import DataSourceUnavailableError, friendly_ibkr_error
from app.models import HealthStatus, Quote, utc_now


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


IB_ASYNC_VOLUME_DECIMAL_SCALE = 10_000.0


def _ibkr_share_volume(
    value: Any,
    lot_multiplier: float = 1.0,
    reference_daily_volume: float | None = None,
) -> tuple[float | None, float]:
    """Normalize mixed native/fixed-4-decimal IBKR stock volume encodings."""
    raw = _number(value)
    if raw is None or raw < 0:
        return None, 1.0
    divisor = (
        IB_ASYNC_VOLUME_DECIMAL_SCALE
        if reference_daily_volume is not None
        and reference_daily_volume > 0
        and raw > reference_daily_volume * 100
        else 1.0
    )
    return raw / divisor * lot_multiplier, divisor


class IBKRService:
    """Read-only IBKR adapter. This module intentionally has no order methods."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._ib = None
        self._snapshot_client_offset = 0

    def connect(self, client_id: int | None = None) -> None:
        if self._ib and self._ib.isConnected():
            return
        from ib_async import IB

        self._ib = IB()
        selected_client_id = (
            self.settings.ibkr_client_id
            if client_id is None
            else client_id
        )
        try:
            self._ib.connect(
                self.settings.ibkr_host,
                self.settings.ibkr_port,
                clientId=selected_client_id,
                timeout=self.settings.ibkr_timeout_seconds,
                readonly=True,
                account=self.settings.ibkr_account or "",
            )
            self._ib.reqMarketDataType(self.settings.ibkr_market_data_type)
        except Exception as exc:
            self.disconnect()
            raise DataSourceUnavailableError(
                friendly_ibkr_error(
                    exc, self.settings.ibkr_host, self.settings.ibkr_port
                )
            ) from exc

    def disconnect(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()

    def health(self) -> HealthStatus:
        try:
            self._connect_readonly_session(lambda message: None)
            accounts = self._ib.managedAccounts()
            detail = f"Connected read-only; {len(accounts)} account(s) visible."
            return HealthStatus("IBKR TWS", True, detail, utc_now())
        except Exception as exc:
            return HealthStatus(
                "IBKR TWS", False, str(exc), utc_now(), state="unavailable"
            )
        finally:
            self.disconnect()

    def accounts(self) -> pd.DataFrame:
        try:
            self._connect_readonly_session(lambda message: None)
            rows = []
            for item in self._ib.accountSummary(
                self.settings.ibkr_account or ""
            ):
                rows.append(
                    {
                        "account": item.account,
                        "tag": item.tag,
                        "value": item.value,
                        "currency": item.currency,
                        "source": "ibkr",
                        "observed_at": utc_now(),
                    }
                )
            return pd.DataFrame(rows)
        finally:
            self.disconnect()

    def positions(self) -> pd.DataFrame:
        try:
            self._connect_readonly_session(lambda message: None)
            rows = []
            for item in self._ib.portfolio(
                self.settings.ibkr_account or ""
            ):
                contract = item.contract
                rows.append(
                    {
                        "account": item.account,
                        "symbol": contract.symbol,
                        "con_id": contract.conId,
                        "security_type": contract.secType,
                        "currency": contract.currency,
                        "position": _number(item.position),
                        "average_cost": _number(item.averageCost),
                        "market_price": _number(item.marketPrice),
                        "market_value": _number(item.marketValue),
                        "unrealized_pnl": _number(item.unrealizedPNL),
                        "realized_pnl": _number(item.realizedPNL),
                        "source": "ibkr",
                        "observed_at": utc_now(),
                    }
                )
            return pd.DataFrame(rows)
        finally:
            self.disconnect()

    def quote(self, symbol: str) -> Quote:
        from ib_async import Stock

        try:
            self._connect_readonly_session(lambda message: None)
            contract = Stock(symbol.upper(), "SMART", "USD")
            qualified = self._ib.qualifyContracts(contract)
            if not qualified:
                raise ValueError(
                    f"IBKR could not qualify symbol {symbol!r}."
                )
            ticker = self._ib.reqMktData(qualified[0], snapshot=True)
            self._ib.sleep(2)
            market_type = {
                1: "live",
                2: "frozen",
                3: "delayed",
                4: "delayed-frozen",
            }.get(getattr(ticker, "marketDataType", None), "unknown")
            return Quote(
                symbol=symbol.upper(),
                bid=_number(ticker.bid),
                ask=_number(ticker.ask),
                last=_number(ticker.last),
                close=_number(ticker.close),
                currency=qualified[0].currency or "USD",
                market_data_type=market_type,
                source="ibkr",
                observed_at=utc_now(),
            )
        finally:
            self.disconnect()

    def _stock_contract(self, symbol: str):
        from ib_async import Stock

        contract = Stock(symbol.upper(), "SMART", "USD")
        qualified = self._ib.qualifyContracts(contract)
        if not qualified:
            raise ValueError(f"IBKR could not qualify symbol {symbol!r}.")
        return qualified[0]

    def _connect_readonly_session(
        self,
        progress: Callable[[str], None],
    ) -> None:
        last_connection_error: Exception | None = None
        for attempt in range(2):
            client_offset = (
                getattr(self, "_snapshot_client_offset", 0) + attempt
            )
            client_id = self.settings.ibkr_client_id + client_offset
            progress(
                f"Connecting read-only to TWS at "
                f"{self.settings.ibkr_host}:{self.settings.ibkr_port} "
                f"(Client ID {client_id}, attempt {attempt + 1}/2)"
            )
            try:
                self.connect(client_id=client_id)
                self._snapshot_client_offset = client_offset + 1
                return
            except DataSourceUnavailableError as exc:
                last_connection_error = exc
                self.disconnect()
                if attempt == 0:
                    progress(
                        f"Client ID {client_id} did not connect; "
                        "retrying with a fresh read-only Client ID"
                    )
        assert last_connection_error is not None
        raise last_connection_error

    def _volatility_fields_on_connected(
        self,
        symbol: str,
        progress: Callable[[str], None],
    ) -> dict:
        contract = None
        ticker = None
        try:
            progress(f"Qualifying the {symbol.upper()} stock contract")
            contract = self._stock_contract(symbol)
            progress(
                f"Loading daily closing prices to calculate HV30 for "
                f"{symbol.upper()}"
            )
            bars = self._ib.reqHistoricalData(
                contract, endDateTime="", durationStr="60 D",
                barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
                formatDate=1, keepUpToDate=False,
                timeout=max(25, int(self.settings.ibkr_timeout_seconds * 3)),
            )
            closes = [
                value for value in (_number(bar.close) for bar in bars)
                if value is not None and value > 0
            ]
            latest_bar = bars[-1] if bars else None
            spot = _number(getattr(latest_bar, "close", None))
            hv30 = historical_volatility(closes, 30)
            market_date = getattr(latest_bar, "date", date.today())
            progress(
                f"Requesting delayed underlying IV for {symbol.upper()}; "
                "HV30 is calculated locally"
            )
            self._ib.reqMarketDataType(self.settings.ibkr_market_data_type)
            ticker = self._ib.reqMktData(
                contract, genericTickList="106", snapshot=False
            )
            progress(
                f"Waiting up to "
                f"{self.settings.ibkr_volatility_wait_seconds:g} seconds "
                f"for {symbol.upper()} market-data fields"
            )
            self._ib.sleep(self.settings.ibkr_volatility_wait_seconds)
            market_type = {
                1: "live", 2: "frozen", 3: "delayed", 4: "delayed-frozen"
            }.get(getattr(ticker, "marketDataType", None), "unknown")
            result = {
                "symbol": symbol.upper(),
                "market_date": pd.Timestamp(market_date).date(),
                "spot_price": spot or _number(ticker.marketPrice()),
                "underlying_iv": _number(ticker.impliedVolatility),
                "hv30": hv30,
                "market_data_type": (
                    f"historical-daily + {market_type} IV"
                    if _number(ticker.impliedVolatility) is not None
                    else "historical-daily; IV unavailable"
                ),
            }
            progress(
                f"{symbol.upper()} HV30 calculated; IV received"
                if result["underlying_iv"] is not None
                else f"{symbol.upper()} HV30 calculated; IV unavailable from permissions"
            )
            return result
        finally:
            if ticker is not None and contract is not None:
                try:
                    self._ib.cancelMktData(contract)
                except Exception:
                    pass

    def volatility_snapshot_raw(
        self,
        symbol: str,
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        def report(message: str) -> None:
            if progress is not None:
                progress(message)

        # Streamlit reruns execute in changing script threads. An ib_async
        # connection retained by st.cache_resource can otherwise remain bound
        # to the previous rerun's event loop and wait indefinitely.
        report("Closing any connection retained by an earlier page run")
        self.disconnect()
        try:
            self._connect_readonly_session(report)
            return self._volatility_fields_on_connected(symbol, report)
        finally:
            self.disconnect()
            report("TWS request session closed")

    def volatility_snapshots_raw(
        self,
        symbols: tuple[str, ...] | list[str],
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, dict | Exception]:
        def report(message: str) -> None:
            if progress is not None:
                progress(message)

        report("Closing any connection retained by an earlier page run")
        self.disconnect()
        results: dict[str, dict | Exception] = {}
        try:
            self._connect_readonly_session(report)
            total = len(symbols)
            for index, raw_symbol in enumerate(symbols, start=1):
                symbol = raw_symbol.strip().upper()
                report(f"Scanning {symbol} ({index}/{total})")
                try:
                    results[symbol] = self._volatility_fields_on_connected(
                        symbol, report
                    )
                except Exception as exc:
                    results[symbol] = exc
                    report(
                        f"{symbol} failed: {type(exc).__name__}: {exc}"
                    )
            return results
        finally:
            self.disconnect()
            report("Shared TWS watchlist session closed")

    def _stock_turnover_on_connected(
        self, symbol: str, progress: Callable[[str], None]
    ) -> dict:
        contract = None
        try:
            progress(f"Qualifying {symbol.upper()} stock contract")
            contract = self._stock_contract(symbol)
            progress(
                f"Loading current daily volume and WAP for {symbol.upper()}"
            )
            bars = self._ib.reqHistoricalData(
                contract, endDateTime="", durationStr="10 D",
                barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
                formatDate=1, keepUpToDate=False,
                timeout=max(20, int(self.settings.ibkr_timeout_seconds * 2)),
            )
            if not bars:
                raise ValueError(
                    f"IBKR returned no daily bars for {symbol.upper()}."
                )
            latest = bars[-1]
            reference_values = [
                value for value in (_number(bar.volume) for bar in bars[:-1])
                if value is not None and value > 0
            ]
            reference_volume = (
                float(pd.Series(reference_values).median())
                if reference_values else None
            )
            volume = _number(latest.volume)
            wap = _number(latest.average)
            close = _number(latest.close)
            price_used = wap or close
            price_basis = "Daily WAP" if wap is not None else "Daily close"
            turnover = (
                volume * price_used
                if volume is not None and price_used is not None else None
            )
            return {
                "symbol": symbol.upper(), "raw_volume": volume,
                "volume_multiplier": 1.0, "volume_scale_divisor": 1.0,
                "reference_daily_volume": reference_volume,
                "estimated_share_volume": volume,
                "price_used": price_used, "price_basis": price_basis,
                "estimated_turnover_usd": turnover,
                "currency": contract.currency or "USD",
                "market_data_type": "historical-daily",
                "session_scope": str(pd.Timestamp(latest.date).date()),
            }
        finally:
            pass

    def stock_turnover_estimates_raw(
        self, symbols: tuple[str, ...] | list[str],
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, dict | Exception]:
        report = progress or (lambda message: None)
        self.disconnect()
        results: dict[str, dict | Exception] = {}
        try:
            self._connect_readonly_session(report)
            for index, raw_symbol in enumerate(symbols, start=1):
                symbol = raw_symbol.strip().upper()
                report(f"Loading {symbol} ({index}/{len(symbols)})")
                try:
                    results[symbol] = self._stock_turnover_on_connected(symbol, report)
                except Exception as exc:
                    results[symbol] = exc
            return results
        finally:
            self.disconnect()
            report("Shared read-only TWS turnover session closed")

    def _historical_daily_bars_on_connected(
        self,
        symbol: str,
        lookback_years: int,
        progress: Callable[[str], None],
    ) -> pd.DataFrame:
        progress(f"Qualifying the {symbol.upper()} historical-data contract")
        contract = self._stock_contract(symbol)
        progress(
            f"Requesting {lookback_years} year(s) of daily bars for "
            f"{symbol.upper()}"
        )
        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=f"{lookback_years} Y",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
            keepUpToDate=False,
            timeout=max(30, int(self.settings.ibkr_timeout_seconds * 3)),
        )
        now = utc_now()
        rows = []
        for bar in bars:
            bar_date = pd.Timestamp(bar.date).date()
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "bar_date": bar_date,
                    "open": _number(bar.open),
                    "high": _number(bar.high),
                    "low": _number(bar.low),
                    "close": _number(bar.close),
                    "volume": _number(bar.volume),
                    "source": "ibkr",
                    "fetched_at": now,
                }
            )
        progress(f"Received {len(rows):,} daily bars for {symbol.upper()}")
        return pd.DataFrame(rows)

    def historical_daily_bars_batch(
        self,
        symbols: tuple[str, ...] | list[str],
        lookback_years: int,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, pd.DataFrame | Exception]:
        def report(message: str) -> None:
            if progress is not None:
                progress(message)

        report("Closing any connection retained by an earlier page run")
        self.disconnect()
        results: dict[str, pd.DataFrame | Exception] = {}
        try:
            self._connect_readonly_session(report)
            total = len(symbols)
            for index, raw_symbol in enumerate(symbols, start=1):
                symbol = raw_symbol.strip().upper()
                report(f"Loading {symbol} ({index}/{total})")
                try:
                    results[symbol] = self._historical_daily_bars_on_connected(
                        symbol, lookback_years, report
                    )
                except Exception as exc:
                    results[symbol] = exc
                    report(f"{symbol} failed: {type(exc).__name__}: {exc}")
            return results
        finally:
            self.disconnect()
            report("Shared TWS historical-data session closed")

    def option_expirations(
        self,
        symbol: str,
        progress: Callable[[str], None] | None = None,
    ) -> list[str]:
        def report(message: str) -> None:
            if progress is not None:
                progress(message)

        report("Closing any connection retained by an earlier page run")
        self.disconnect()
        try:
            self._connect_readonly_session(report)
            report(f"Qualifying the {symbol.upper()} stock contract")
            contract = self._stock_contract(symbol)
            report(
                f"Requesting option definitions and expirations for "
                f"{symbol.upper()}"
            )
            chains = self._ib.reqSecDefOptParams(
                contract.symbol, "", contract.secType, contract.conId
            )
            if not chains:
                report("IBKR returned no option definitions")
                return []
            chain = next(
                (item for item in chains if item.exchange == "SMART"),
                max(chains, key=lambda item: len(item.expirations)),
            )
            today = date.today().strftime("%Y%m%d")
            expirations = sorted(
                expiry for expiry in chain.expirations if expiry >= today
            )
            report(f"Received {len(expirations)} available expirations")
            return expirations
        finally:
            self.disconnect()
            report("TWS expiration request session closed")

    def option_chain(
        self,
        symbol: str,
        expiry: str,
        strike_count: int,
        progress: Callable[[str], None] | None = None,
    ) -> pd.DataFrame:
        def report(message: str) -> None:
            if progress is not None:
                progress(message)

        from ib_async import Option

        report("Closing any connection retained by an earlier page run")
        self.disconnect()
        underlying = None
        stock_ticker = None
        option_tickers = []
        try:
            self._connect_readonly_session(report)
            report(f"Qualifying the {symbol.upper()} stock contract")
            underlying = self._stock_contract(symbol)
            report("Requesting the delayed underlying price")
            stock_ticker = self._ib.reqMktData(
                underlying, snapshot=False
            )
            self._ib.sleep(self.settings.ibkr_volatility_wait_seconds)
            spot = _number(stock_ticker.marketPrice())
            self._ib.cancelMktData(underlying)
            stock_ticker = None

            report(
                f"Loading option definitions for expiry {expiry}"
            )
            chains = self._ib.reqSecDefOptParams(
                underlying.symbol, "", underlying.secType, underlying.conId
            )
            candidates = [
                item for item in chains
                if expiry in item.expirations and item.exchange == "SMART"
            ] or [item for item in chains if expiry in item.expirations]
            if not candidates:
                raise ValueError(
                    f"No IBKR option chain found for expiry {expiry}."
                )
            chain = max(candidates, key=lambda item: len(item.strikes))
            strikes = sorted(
                float(value) for value in chain.strikes if value > 0
            )
            if not strikes:
                raise ValueError(
                    f"IBKR returned no strikes for expiry {expiry}."
                )
            center = spot if spot is not None else strikes[len(strikes) // 2]
            nearest = sorted(
                strikes, key=lambda value: abs(value - center)
            )[:strike_count]
            selected_strikes = sorted(nearest)
            contracts = [
                Option(
                    symbol.upper(), expiry, strike, right, "SMART",
                    multiplier=chain.multiplier or "100", currency="USD",
                    tradingClass=chain.tradingClass,
                )
                for strike in selected_strikes
                for right in ("C", "P")
            ]
            report(
                f"Qualifying {len(contracts)} Call/Put contracts around spot"
            )
            qualification_results = self._ib.qualifyContracts(*contracts)
            qualified = [
                contract
                for contract in qualification_results
                if contract is not None
            ]
            skipped = len(contracts) - len(qualified)
            if skipped:
                report(
                    f"Skipped {skipped} contract combinations that IBKR "
                    f"does not define for expiry {expiry}"
                )
            if not qualified:
                raise ValueError(
                    f"IBKR could not qualify any selected options for "
                    f"{symbol.upper()} expiry {expiry}."
                )
            report(
                f"Requesting delayed prices, IV and Greeks for "
                f"{len(qualified)} contracts"
            )
            option_tickers = [
                self._ib.reqMktData(contract, snapshot=False)
                for contract in qualified
            ]
            report(
                f"Waiting up to "
                f"{self.settings.ibkr_volatility_wait_seconds:g} seconds "
                "for option computations"
            )
            self._ib.sleep(self.settings.ibkr_volatility_wait_seconds)
            now = utc_now()
            rows = []
            for ticker in option_tickers:
                contract = ticker.contract
                greeks = (
                    ticker.modelGreeks or ticker.lastGreeks
                    or ticker.bidGreeks or ticker.askGreeks
                )
                bid, ask, last = (
                    _number(ticker.bid),
                    _number(ticker.ask),
                    _number(ticker.last),
                )
                midpoint = (
                    (bid + ask) / 2
                    if bid is not None and ask is not None
                    else None
                )
                rows.append(
                    {
                        "symbol": symbol.upper(),
                        "con_id": contract.conId,
                        "expiry": date(
                            int(expiry[:4]),
                            int(expiry[4:6]),
                            int(expiry[6:8]),
                        ),
                        "strike": float(contract.strike),
                        "option_right": contract.right,
                        "bid": bid,
                        "ask": ask,
                        "last": last,
                        "midpoint": midpoint,
                        "implied_vol": _number(
                            getattr(greeks, "impliedVol", None)
                        ),
                        "delta": _number(getattr(greeks, "delta", None)),
                        "gamma": _number(getattr(greeks, "gamma", None)),
                        "vega": _number(getattr(greeks, "vega", None)),
                        "theta": _number(getattr(greeks, "theta", None)),
                        "option_price": _number(
                            getattr(greeks, "optPrice", None)
                        ),
                        "underlying_price": _number(
                            getattr(greeks, "undPrice", None)
                        ) or spot,
                        "market_data_type": {
                            1: "live",
                            2: "frozen",
                            3: "delayed",
                            4: "delayed-frozen",
                        }.get(
                            getattr(ticker, "marketDataType", None),
                            "unknown",
                        ),
                        "source": "ibkr",
                        "observed_at": now,
                    }
                )
            report(f"Received {len(rows)} option contract rows")
            return pd.DataFrame(rows)
        finally:
            if stock_ticker is not None and underlying is not None:
                try:
                    self._ib.cancelMktData(underlying)
                except Exception:
                    pass
            for ticker in option_tickers:
                try:
                    self._ib.cancelMktData(ticker.contract)
                except Exception:
                    pass
            self.disconnect()
            report("TWS option-chain request session closed")
