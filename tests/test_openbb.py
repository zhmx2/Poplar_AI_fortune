from datetime import date

import pytest

from app.config import Settings
from app.errors import FeatureDisabledError
from app.services.openbb import OpenBBService


def test_health_explains_unbuilt_static_interfaces(monkeypatch):
    service = OpenBBService(Settings(openbb_enabled=True))
    original_import = __import__

    def fail_import(name, *args, **kwargs):
        if name == "openbb":
            raise ValueError("signal only works in main thread of the main interpreter")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fail_import)
    status = service.health()

    assert not status.ok
    assert "openbb-build.exe" in status.message


def test_disabled_openbb_does_not_import_package(monkeypatch):
    service = OpenBBService(Settings(openbb_enabled=False))
    original_import = __import__
    attempted = []

    def track_import(name, *args, **kwargs):
        if name == "openbb":
            attempted.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", track_import)
    status = service.health()

    assert status.ok
    assert status.state == "disabled"
    assert attempted == []


def test_disabled_openbb_blocks_history_before_import():
    service = OpenBBService(Settings(openbb_enabled=False))
    with pytest.raises(FeatureDisabledError, match="frozen"):
        service.history("NVDA", date(2025, 1, 1), date(2025, 2, 1))
