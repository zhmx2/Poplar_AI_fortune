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
