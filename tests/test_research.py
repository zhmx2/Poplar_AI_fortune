from datetime import date

import pandas as pd

from app.models import HealthStatus, Quote, utc_now
from app.services.research import ResearchService


class FakeRepo:
    def __init__(self):
        self.saved = []

    def save_frame(self, table, frame):
        self.saved.append((table, len(frame)))

    def save_quote(self, quote):
        self.saved.append(("quotes", quote.symbol))

    def health(self):
        return HealthStatus("DuckDB", True, "ok", utc_now())


class FakeIBKR:
    def health(self):
        return HealthStatus("IBKR", True, "ok", utc_now())

    def accounts(self):
        return pd.DataFrame([{"account": "masked"}])

    def positions(self):
        return pd.DataFrame([{"symbol": "NVDA"}])

    def quote(self, symbol):
        return Quote(symbol, 1, 2, 1.5, 1.4, "USD", "delayed", "ibkr", utc_now())


class FakeOpenBB:
    def health(self):
        return HealthStatus("OpenBB", True, "ok", utc_now())

    def history(self, symbol, start, end):
        return pd.DataFrame([{"symbol": symbol, "close": 1.0}])


def test_unified_service_routes_and_persists():
    repo = FakeRepo()
    service = ResearchService(FakeIBKR(), FakeOpenBB(), repo)
    assert service.quote("NVDA").market_data_type == "delayed"
    assert len(service.positions()) == 1
    assert len(service.history("NVDA", date(2025, 1, 1), date(2025, 2, 1))) == 1
    assert ("quotes", "NVDA") in repo.saved


def test_health_checks_are_independent():
    class BrokenIBKR(FakeIBKR):
        def health(self):
            raise RuntimeError("TWS unavailable")

    service = ResearchService(BrokenIBKR(), FakeOpenBB(), FakeRepo())
    statuses = service.health()

    assert [status.service for status in statuses] == ["IBKR TWS", "OpenBB", "DuckDB"]
    assert statuses[0].state == "unavailable"
    assert statuses[1].ok
    assert statuses[2].ok
