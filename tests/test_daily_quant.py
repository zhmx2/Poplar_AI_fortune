from pathlib import Path

import pandas as pd

from app.analytics.daily_quant import calculate_daily_quant
from app.services.daily_quant import DailyQuantService


def test_daily_quant_calculates_scores_and_indicators():
    dates = pd.bdate_range("2025-01-01", periods=260)
    rows = []
    for symbol, growth in (("NVDA", 0.002), ("SPY", 0.0005), ("QQQ", 0.0008), ("SOXX", 0.001)):
        for index, bar_date in enumerate(dates):
            close = 100 * (1 + growth) ** index
            rows.append({
                "symbol": symbol, "bar_date": bar_date.date(), "open": close * .99,
                "high": close * 1.01, "low": close * .98, "close": close,
                "volume": 1_000_000 + index * 1_000,
            })
    snapshot, history = calculate_daily_quant(pd.DataFrame(rows), "NVDA")
    assert len(history) == 260
    assert snapshot["trend_score"] == 100
    assert 0 <= snapshot["overall_score"] <= 100
    assert snapshot["relative_score"] > 50
    assert snapshot["hv30"] >= 0


def test_daily_quant_requires_sufficient_history():
    frame = pd.DataFrame({
        "symbol": ["NVDA"] * 20,
        "bar_date": pd.bdate_range("2026-01-01", periods=20).date,
        "open": [100.0] * 20, "high": [101.0] * 20,
        "low": [99.0] * 20, "close": [100.0] * 20,
        "volume": [1_000_000.0] * 20,
    })
    try:
        calculate_daily_quant(frame, "NVDA")
        assert False, "expected insufficient-history error"
    except ValueError as exc:
        assert "at least 201" in str(exc)


def test_watchlist_sync_fetches_benchmarks_once_and_calculates_each_symbol():
    dates = pd.bdate_range("2025-01-01", periods=260)

    class StubIBKR:
        calls = []

        def historical_daily_bars_batch(self, symbols, years, progress=None):
            self.calls.append(tuple(symbols))
            output = {}
            for offset, symbol in enumerate(symbols, start=1):
                close = pd.Series(range(100 + offset, 360 + offset), dtype=float)
                output[symbol] = pd.DataFrame({
                    "symbol": symbol,
                    "bar_date": dates.date,
                    "open": close * .99,
                    "high": close * 1.01,
                    "low": close * .98,
                    "close": close,
                    "volume": 1_000_000 + close * 1_000,
                    "source": "ibkr",
                    "fetched_at": pd.Timestamp("2026-08-18", tz="UTC"),
                })
            return output

    class StubRepo:
        saved = pd.DataFrame()

        def save_market_confirmation_bars(self, frame):
            self.saved = frame.copy()

        def market_confirmation_bars(self, symbols=None):
            return self.saved[self.saved["symbol"].isin(symbols)].copy()

    settings = type("Settings", (), {"daily_quant_lookback_years": 3})()
    ibkr, repo = StubIBKR(), StubRepo()
    service = DailyQuantService(settings, ibkr, repo)

    summary = service.sync_watchlist(("NVDA", "MSFT"))

    assert ibkr.calls == [("NVDA", "MSFT", "SPY", "QQQ", "SOXX")]
    assert summary["symbol"].tolist() == ["NVDA", "MSFT"]
    assert summary["status"].tolist() == ["SUCCESS", "SUCCESS"]
    assert set(repo.saved["symbol"]) == {"NVDA", "MSFT", "SPY", "QQQ", "SOXX"}
