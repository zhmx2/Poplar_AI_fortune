from types import SimpleNamespace
from pathlib import Path
from datetime import date, timedelta

import pytest

from app.config import Settings
from app.errors import DataSourceUnavailableError
from app.errors import friendly_ibkr_error
from app.services.ibkr import IBKRService, _ibkr_share_volume, _number


def daily_bars(count=40, *, final_volume=1_250_000, final_wap=200.0):
    start = date(2026, 6, 1)
    return [
        SimpleNamespace(
            date=start + timedelta(days=index),
            close=100.0 + index,
            volume=final_volume if index == count - 1 else 1_000_000,
            average=final_wap if index == count - 1 else 150.0,
        )
        for index in range(count)
    ]


def test_number_filters_invalid_market_values():
    assert _number(float("nan")) is None
    assert _number("not-a-number") is None
    assert _number(12.5) == 12.5


def test_ib_async_fixed_decimal_volume_is_normalized_to_shares():
    assert _ibkr_share_volume(973_108_500_000, reference_daily_volume=66_800_753) == (97_310_850, 10_000)
    assert _ibkr_share_volume(10_294, reference_daily_volume=518_332) == (10_294, 1)


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
        reqMarketDataType=lambda value: None,
        reqMktData=lambda *args, **kwargs: ticker,
        sleep=lambda seconds: None,
        cancelMktData=lambda contract: None,
        reqHistoricalData=lambda *args, **kwargs: daily_bars(),
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


def test_missing_iv_keeps_locally_calculated_hv30(monkeypatch):
    service = IBKRService(Settings(sec_mode="mock", ibkr_market_data_type=3))
    empty = SimpleNamespace(
        marketDataType=3, impliedVolatility=float("nan"),
        histVolatility=float("nan"), marketPrice=lambda: float("nan"),
    )
    requested_types = []
    fake_ib = SimpleNamespace(
        reqMarketDataType=lambda value: requested_types.append(value),
        reqMktData=lambda *args, **kwargs: empty,
        sleep=lambda seconds: None,
        cancelMktData=lambda contract: None,
        reqHistoricalData=lambda *args, **kwargs: daily_bars(),
    )
    service._ib = fake_ib
    monkeypatch.setattr(service, "_stock_contract", lambda symbol: object())

    result = service._volatility_fields_on_connected("NVDA", lambda message: None)

    assert requested_types == [3]
    assert result["market_data_type"] == "historical-daily; IV unavailable"
    assert result["underlying_iv"] is None
    assert result["hv30"] is not None


def test_stock_turnover_uses_stock_volume_and_price_only(monkeypatch):
    service = IBKRService(Settings(
        sec_mode="mock", ibkr_us_stock_volume_multiplier=1.0
    ))
    contract = SimpleNamespace(currency="USD")
    fake_ib = SimpleNamespace(
        reqHistoricalData=lambda *args, **kwargs: daily_bars(),
    )
    service._ib = fake_ib
    monkeypatch.setattr(service, "_stock_contract", lambda symbol: contract)

    result = service._stock_turnover_on_connected("NVDA", lambda message: None)

    assert result["estimated_share_volume"] == 1_250_000
    assert result["price_basis"] == "Daily WAP"
    assert result["estimated_turnover_usd"] == 250_000_000
    assert result["market_data_type"] == "historical-daily"


def test_stock_turnover_daily_bars_ignore_streaming_lot_setting(monkeypatch):
    service = IBKRService(Settings(
        sec_mode="mock", ibkr_us_stock_volume_multiplier=100.0
    ))
    contract = SimpleNamespace(currency="USD")
    service._ib = SimpleNamespace(
        reqHistoricalData=lambda *args, **kwargs: daily_bars(
            final_volume=10, final_wap=50.0
        ),
    )
    monkeypatch.setattr(service, "_stock_contract", lambda symbol: contract)

    result = service._stock_turnover_on_connected("MSFT", lambda message: None)

    assert result["estimated_share_volume"] == 10
    assert result["price_basis"] == "Daily WAP"
    assert result["estimated_turnover_usd"] == 500


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
