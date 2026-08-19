from __future__ import annotations

import math

import pandas as pd

from app.config import Settings
from app.db import Repository
from app.models import HealthStatus, utc_now
from app.services.ibkr import IBKRService


MARKET_BASKET = {
    "SPY": ("S&P 500 ETF", "标普500 ETF", "Broad equities", "美国大盘"),
    "QQQ": ("Nasdaq-100 ETF", "纳斯达克100 ETF", "Growth equities", "成长股"),
    "IWM": ("Russell 2000 ETF", "罗素2000 ETF", "Small caps", "小盘股"),
    "TLT": ("20+ Year Treasury ETF", "20年以上美债ETF", "Treasury duration", "长期美债"),
    "HYG": ("High Yield Bond ETF", "高收益债ETF", "Credit risk", "信用风险"),
    "LQD": ("Investment Grade Bond ETF", "投资级公司债ETF", "Investment-grade credit", "投资级信用"),
    "GLD": ("Gold Shares ETF", "黄金ETF", "Defensive real asset", "防御性实物资产"),
    "UUP": ("US Dollar Index ETF", "美元指数ETF", "US dollar", "美元"),
}


def basket_definition(symbol: str) -> tuple[str, str, str, str]:
    return MARKET_BASKET.get(
        symbol.upper(),
        (symbol.upper(), symbol.upper(), "Custom confirmation asset", "自定义确认资产"),
    )


class PhaseFBService:
    def __init__(
        self,
        settings: Settings,
        ibkr: IBKRService,
        repo: Repository,
    ):
        self.settings = settings
        self.ibkr = ibkr
        self.repo = repo

    def health(self) -> HealthStatus:
        messages = {
            "mock": "Mock mode; illustrative market-confirmation bars",
            "offline": "Offline mode; reading saved market bars from DuckDB",
            "tws": "TWS mode configured; IBKR is contacted only during sync",
        }
        return HealthStatus(
            "Phase F-B market confirmation",
            True,
            messages[self.settings.market_confirmation_mode],
            utc_now(),
        )

    def sync(self, progress=None) -> tuple[pd.DataFrame, list[str]]:
        mode = self.settings.market_confirmation_mode
        if mode == "offline":
            return self.data(), []
        if mode == "mock":
            frame = self._mock_data()
            self.repo.save_market_confirmation_bars(frame)
            return frame, []

        results = self.ibkr.historical_daily_bars_batch(
            self.settings.market_confirmation_basket,
            self.settings.market_confirmation_lookback_years,
            progress,
        )
        frames: list[pd.DataFrame] = []
        errors: list[str] = []
        for symbol, result in results.items():
            if isinstance(result, Exception):
                errors.append(f"{symbol}: {type(result).__name__}: {result}")
                continue
            if result.empty:
                errors.append(f"{symbol}: no historical bars returned")
                continue
            frames.append(self._add_basket_metadata(result, symbol))
        if not frames:
            detail = "; ".join(errors[:3])
            raise ValueError(f"IBKR market basket returned no data. {detail}")
        frame = pd.concat(frames, ignore_index=True)
        self.repo.save_market_confirmation_bars(frame)
        return frame, errors

    def data(self) -> pd.DataFrame:
        frame = self.repo.market_confirmation_bars(
            self.settings.market_confirmation_basket
        )
        if frame.empty:
            return frame
        source = frame["source"].fillna("unknown").astype(str).str.lower()
        mode = self.settings.market_confirmation_mode
        if mode == "tws":
            return frame.loc[source.eq("ibkr")].copy()
        if mode == "mock":
            return frame.loc[source.eq("mock")].copy()
        official = frame.loc[source.eq("ibkr")].copy()
        return official if not official.empty else frame.loc[source.eq("mock")].copy()

    @staticmethod
    def _add_basket_metadata(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
        name, name_cn, role, role_cn = basket_definition(symbol)
        result = frame.copy()
        result["asset_name"] = name
        result["asset_name_cn"] = name_cn
        result["market_role"] = role
        result["market_role_cn"] = role_cn
        return result[
            [
                "symbol", "asset_name", "asset_name_cn", "market_role",
                "market_role_cn", "bar_date", "open", "high", "low",
                "close", "volume", "source", "fetched_at",
            ]
        ]

    def _mock_data(self) -> pd.DataFrame:
        dates = pd.bdate_range(
            end=pd.Timestamp.today().normalize(),
            periods=252 * self.settings.market_confirmation_lookback_years,
        )
        base_prices = {
            "SPY": 450, "QQQ": 390, "IWM": 200, "TLT": 95,
            "HYG": 76, "LQD": 108, "GLD": 185, "UUP": 28,
        }
        rows: list[dict] = []
        now = utc_now()
        for symbol_index, symbol in enumerate(
            self.settings.market_confirmation_basket
        ):
            name, name_cn, role, role_cn = basket_definition(symbol)
            base = base_prices.get(symbol, 100.0)
            for index, bar_date in enumerate(dates):
                trend = 1 + (0.00025 + symbol_index * 0.00001) * index
                cycle = 1 + 0.025 * math.sin(index / (22 + symbol_index))
                close = base * trend * cycle
                rows.append(
                    {
                        "symbol": symbol,
                        "asset_name": name,
                        "asset_name_cn": name_cn,
                        "market_role": role,
                        "market_role_cn": role_cn,
                        "bar_date": bar_date.date(),
                        "open": close * 0.998,
                        "high": close * 1.006,
                        "low": close * 0.994,
                        "close": close,
                        "volume": 1_000_000 + index * 750 + symbol_index * 20_000,
                        "source": "mock",
                        "fetched_at": now,
                    }
                )
        return pd.DataFrame(rows)
