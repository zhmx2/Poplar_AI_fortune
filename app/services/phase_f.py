from __future__ import annotations

from datetime import date
import math

import pandas as pd

from app.clients.macro import MacroClient
from app.config import Settings
from app.db import Repository
from app.errors import ApplicationError
from app.models import HealthStatus, utc_now


LIQUIDITY_SERIES = {
    "WALCL": (
        "Federal Reserve total assets / 美联储总资产",
        "Millions of USD",
        "Weekly",
    ),
    "WRBWFRBL": (
        "Reserve balances with Federal Reserve Banks: Wednesday level / 美联储银行准备金余额：周三水平",
        "Millions of USD",
        "Weekly",
    ),
    "WRESBAL": (
        "Reserve balances with Federal Reserve Banks: week average / 美联储银行准备金余额：周平均",
        "Millions of USD",
        "Weekly",
    ),
    "TREAST": (
        "US Treasury securities held outright / 美联储直接持有的美国国债",
        "Millions of USD",
        "Weekly",
    ),
    "WSHOMCB": (
        "Mortgage-backed securities held outright / 美联储直接持有的抵押贷款支持证券",
        "Millions of USD",
        "Weekly",
    ),
    "WSHOFADSL": (
        "Federal agency debt securities held outright / 美联储直接持有的联邦机构债券",
        "Millions of USD",
        "Weekly",
    ),
    "WLCFLL": (
        "Liquidity and credit facility loans / 流动性与信贷工具贷款",
        "Millions of USD",
        "Weekly",
    ),
    "WTREGEN": (
        "US Treasury General Account / 美国财政部一般账户",
        "Millions of USD",
        "Weekly",
    ),
    "RRPONTSYD": (
        "Overnight reverse repurchase agreements / 隔夜逆回购",
        "Billions of USD",
        "Daily",
    ),
    "NFCI": (
        "Chicago Fed National Financial Conditions Index / 芝加哥联储全国金融条件指数",
        "Index",
        "Weekly",
    ),
    "SOFR": ("Secured Overnight Financing Rate / 担保隔夜融资利率", "Percent", "Daily"),
    "DGS2": ("2-year US Treasury yield / 2年期美债收益率", "Percent", "Daily"),
    "DGS10": ("10-year US Treasury yield / 10年期美债收益率", "Percent", "Daily"),
    "DFII10": ("10-year real Treasury yield / 10年期实际美债收益率", "Percent", "Daily"),
    "T10Y2Y": ("10Y minus 2Y Treasury spread / 10年期减2年期美债利差", "Percent", "Daily"),
    "BAMLH0A0HYM2": (
        "ICE BofA US High Yield option-adjusted spread / 美国高收益债期权调整利差",
        "Percent",
        "Daily",
    ),
}


class PhaseFService:
    def __init__(self, settings: Settings, repo: Repository):
        self.settings = settings
        self.repo = repo

    def health(self) -> HealthStatus:
        messages = {
            "mock": "Mock mode; illustrative liquidity data",
            "offline": "Offline mode; reading saved liquidity data from DuckDB",
            "online": "Online mode configured; FRED is contacted only during sync",
        }
        return HealthStatus(
            "Phase F-A liquidity",
            True,
            messages[self.settings.liquidity_mode],
            utc_now(),
            state="healthy",
        )

    def sync(self) -> tuple[pd.DataFrame, list[str]]:
        if self.settings.liquidity_mode == "offline":
            return self.data(), []
        if self.settings.liquidity_mode == "mock":
            frame = self._mock_data()
            self.repo.save_macro_observations(frame)
            return frame, []
        if not self.settings.fred_api_key:
            raise ApplicationError(
                "FRED_API_KEY is required when LIQUIDITY_MODE=online. "
                "Use offline mode to read previously saved observations."
            )

        client = MacroClient(self.settings)
        frames: list[pd.DataFrame] = []
        errors: list[str] = []
        start = date(date.today().year - self.settings.liquidity_lookback_years, 1, 1)
        try:
            for series_id in LIQUIDITY_SERIES:
                try:
                    payload = client.fred_series(series_id, start)
                    parsed = self._parse_fred(series_id, payload)
                    if parsed.empty:
                        errors.append(f"{series_id}: no numeric observations returned")
                    else:
                        frames.append(parsed)
                except Exception as exc:
                    errors.append(f"{series_id}: {type(exc).__name__}: {exc}")
        finally:
            client.close()
        if not frames:
            detail = "; ".join(errors[:3])
            raise ApplicationError(f"FRED liquidity sync returned no data. {detail}")
        frame = pd.concat(frames, ignore_index=True)
        self.repo.save_macro_observations(frame)
        return frame, errors

    def data(self) -> pd.DataFrame:
        frame = self.repo.macro_observations(list(LIQUIDITY_SERIES))
        if frame.empty:
            return frame

        source = frame["source"].fillna("unknown").astype(str).str.lower()
        if self.settings.liquidity_mode == "online":
            # Never allow illustrative rows onto an online dashboard, including
            # when a FRED sync is partial or has not been run yet.
            return frame.loc[source.eq("fred")].copy()
        if self.settings.liquidity_mode == "mock":
            return frame.loc[source.eq("mock")].copy()

        # Offline mode prefers the most authoritative saved dataset.  It may
        # fall back to mock only on installations that have never saved FRED.
        official = frame.loc[source.eq("fred")].copy()
        if not official.empty:
            return official
        return frame.loc[source.eq("mock")].copy()

    @staticmethod
    def _parse_fred(series_id: str, payload: dict) -> pd.DataFrame:
        name, unit, frequency = LIQUIDITY_SERIES[series_id]
        rows = []
        now = utc_now()
        for item in payload.get("observations", []):
            try:
                value = float(str(item.get("value", "")).strip())
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "series_id": series_id,
                    "observation_date": pd.Timestamp(item["date"]).date(),
                    "value": value,
                    "series_name": name,
                    "unit": unit,
                    "frequency": frequency,
                    "source": "FRED",
                    "retrieved_at": now,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _mock_data() -> pd.DataFrame:
        end = pd.Timestamp.today().normalize()
        daily_dates = pd.bdate_range(end=end, periods=520)
        weekly_dates = pd.date_range(end=end, periods=104, freq="W-WED")
        rows: list[dict] = []
        now = utc_now()
        for series_id, (name, unit, frequency) in LIQUIDITY_SERIES.items():
            dates = weekly_dates if frequency == "Weekly" else daily_dates
            for i, dt in enumerate(dates):
                if series_id == "WALCL":
                    value = 6_900_000 - i * 1_100 + 18_000 * math.sin(i / 8)
                elif series_id == "WRBWFRBL":
                    value = 3_400_000 - i * 2_100 + 35_000 * math.sin(i / 7)
                elif series_id == "WRESBAL":
                    value = 3_390_000 - i * 2_050 + 30_000 * math.sin(i / 7)
                elif series_id == "TREAST":
                    value = 4_850_000 - i * 3_000 + 9_000 * math.sin(i / 10)
                elif series_id == "WSHOMCB":
                    value = 2_450_000 - i * 2_200 + 8_000 * math.sin(i / 11)
                elif series_id == "WSHOFADSL":
                    value = max(1_000, 2_400 - i * 8)
                elif series_id == "WLCFLL":
                    value = 7_000 + 2_000 * (1 + math.sin(i / 9))
                elif series_id == "WTREGEN":
                    value = 650_000 + 120_000 * math.sin(i / 6)
                elif series_id == "RRPONTSYD":
                    value = max(2.0, 450 - i * 0.8 + 25 * math.sin(i / 18))
                elif series_id == "NFCI":
                    value = -0.45 + 0.12 * math.sin(i / 10)
                elif series_id == "SOFR":
                    value = 4.35 + 0.08 * math.sin(i / 30)
                elif series_id == "DGS2":
                    value = 4.25 + 0.35 * math.sin(i / 45)
                elif series_id == "DGS10":
                    value = 4.40 + 0.30 * math.sin(i / 50)
                elif series_id == "DFII10":
                    value = 2.05 + 0.18 * math.sin(i / 55)
                elif series_id == "T10Y2Y":
                    value = 0.15 + 0.20 * math.sin(i / 38)
                else:
                    value = 3.10 + 0.55 * math.sin(i / 35)
                rows.append(
                    {
                        "series_id": series_id,
                        "observation_date": dt.date(),
                        "value": float(value),
                        "series_name": name,
                        "unit": unit,
                        "frequency": frequency,
                        "source": "mock",
                        "retrieved_at": now,
                    }
                )
        return pd.DataFrame(rows)
