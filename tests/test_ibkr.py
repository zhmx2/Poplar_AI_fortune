from types import SimpleNamespace
from pathlib import Path

import pytest

from app.config import Settings
from app.errors import DataSourceUnavailableError
from app.errors import friendly_ibkr_error
from app.services.ibkr import IBKRService, _number


def test_number_filters_invalid_market_values():
    assert _number(float("nan")) is None
    assert _number("not-a-number") is None
    assert _number(12.5) == 12.5


def test_ibkr_service_exposes_no_order_methods():
    forbidden = {"placeOrder", "place_order", "cancelOrder", "cancel_order"}
    assert forbidden.isdisjoint(set(dir(IBKRService)))


def test_connection_refused_becomes_actionable_message():
    message = friendly_ibkr_error(
        ConnectionRefusedError(1225, "refused"), "127.0.0.1", 7496
    )
    assert "TWS is not connected" in message
    assert "Read-Only API" in message
    assert "SEC and offline DuckDB features remain available" in message


def test_volatility_snapshot_retries_with_fresh_client_id(monkeypatch):
    service = IBKRService(Settings(sec_mode="mock", ibkr_client_id=41))
    attempts = []
    ticker = SimpleNamespace(
        marketDataType=3,
        impliedVolatility=0.40,
        histVolatility=0.30,
        marketPrice=lambda: 100.0,
    )
    fake_ib = SimpleNamespace(
        reqMktData=lambda *args, **kwargs: ticker,
        sleep=lambda seconds: None,
        cancelMktData=lambda contract: None,
    )

    def connect(client_id=None):
        attempts.append(client_id)
        if len(attempts) == 1:
            raise DataSourceUnavailableError("temporary timeout")
        service._ib = fake_ib

    monkeypatch.setattr(service, "connect", connect)
    monkeypatch.setattr(service, "disconnect", lambda: None)
    monkeypatch.setattr(service, "_stock_contract", lambda symbol: object())

    result = service.volatility_snapshot_raw("MSFT")

    assert attempts == [41, 42]
    assert service._snapshot_client_offset == 2
    assert result["underlying_iv"] == 0.40


@pytest.mark.parametrize("operation", ["health", "accounts", "positions"])
def test_read_operations_always_disconnect(monkeypatch, operation):
    service = IBKRService(Settings(sec_mode="mock"))
    fake_ib = SimpleNamespace(
        managedAccounts=lambda: [],
        accountSummary=lambda account: [],
        portfolio=lambda account: [],
    )
    disconnects = []
    monkeypatch.setattr(
        service,
        "_connect_readonly_session",
        lambda progress: setattr(service, "_ib", fake_ib),
    )
    monkeypatch.setattr(
        service, "disconnect", lambda: disconnects.append(True)
    )

    getattr(service, operation)()

    assert disconnects == [True]


def test_quote_always_disconnects(monkeypatch):
    service = IBKRService(Settings(sec_mode="mock"))
    contract = SimpleNamespace(currency="USD")
    ticker = SimpleNamespace(
        marketDataType=3,
        bid=99.0,
        ask=101.0,
        last=100.0,
        close=98.0,
    )
    fake_ib = SimpleNamespace(
        qualifyContracts=lambda requested: [contract],
        reqMktData=lambda requested, snapshot: ticker,
        sleep=lambda seconds: None,
    )
    disconnects = []
    monkeypatch.setattr(
        service,
        "_connect_readonly_session",
        lambda progress: setattr(service, "_ib", fake_ib),
    )
    monkeypatch.setattr(
        service, "disconnect", lambda: disconnects.append(True)
    )

    quote = service.quote("NVDA")

    assert quote.last == 100.0
    assert disconnects == [True]


def test_streamlit_facade_does_not_cache_ibkr_service():
    app_source = (Path(__file__).parents[1] / "app.py").read_text(
        encoding="utf-8"
    )
    assert "@st.cache_resource\ndef services" not in app_source


def test_option_qualification_filters_undefined_contracts():
    qualification_results = [
        SimpleNamespace(secType="OPT", conId=1),
        None,
        SimpleNamespace(secType="OPT", conId=2),
        None,
    ]

    qualified = [
        contract
        for contract in qualification_results
        if contract is not None
    ]

    assert [contract.conId for contract in qualified] == [1, 2]
    assert len(qualification_results) - len(qualified) == 2
