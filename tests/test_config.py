from pathlib import Path

import pytest

from app.config import Settings


def test_safe_defaults_are_local_and_delayed():
    settings = Settings()
    assert settings.ibkr_host in {"127.0.0.1", "localhost", "::1"}
    assert settings.ibkr_market_data_type in {3, 4}
    assert settings.openbb_enabled is False


def test_rejects_remote_ibkr_host():
    with pytest.raises(ValueError, match="loopback"):
        Settings(ibkr_host="192.168.1.10")


def test_database_path_is_a_path():
    assert isinstance(Settings().database_path, Path)


def test_phase_e_defaults_are_network_safe():
    settings = Settings(
        macro_mode="mock",
        phase_e_companies=("MSFT", "AMZN", "GOOGL", "META"),
    )
    assert settings.macro_mode == "mock"
    assert settings.phase_e_companies == ("MSFT", "AMZN", "GOOGL", "META")


def test_phase_f_defaults_are_network_safe():
    settings = Settings(liquidity_mode="mock", liquidity_lookback_years=10)
    assert settings.liquidity_mode == "mock"
    assert settings.liquidity_lookback_years == 10


def test_rejects_invalid_liquidity_lookback():
    with pytest.raises(ValueError, match="LIQUIDITY_LOOKBACK_YEARS"):
        Settings(liquidity_lookback_years=0)


def test_phase_fb_defaults_are_bounded_and_network_safe():
    settings = Settings(
        market_confirmation_mode="mock",
        market_confirmation_lookback_years=3,
    )
    assert settings.market_confirmation_mode == "mock"
    assert settings.market_confirmation_lookback_years == 3
    assert len(settings.market_confirmation_basket) <= 20


def test_rejects_too_many_confirmation_symbols():
    with pytest.raises(ValueError, match="at most 20"):
        Settings(market_confirmation_basket=tuple(f"S{i}" for i in range(21)))
