from __future__ import annotations

from datetime import date
import hashlib
import math

import pandas as pd

from app.analytics.company_facts import parse_company_financials
from app.clients.macro import MacroClient
from app.clients.sec import SECClient
from app.config import Settings
from app.db import Repository
from app.errors import ApplicationError
from app.models import HealthStatus, utc_now


COMPANIES = {
    "MSFT": ("0000789019", "Microsoft Corporation"),
    "AMZN": ("0001018724", "Amazon.com, Inc."),
    "GOOGL": ("0001652044", "Alphabet Inc."),
    "META": ("0001326801", "Meta Platforms, Inc."),
}

MACRO_SERIES = {
    "CUUR0000SA0": ("US CPI, all items", "Index 1982-84=100", "Monthly", "BLS"),
    "CUUR0000SA0L1E": ("US core CPI", "Index 1982-84=100", "Monthly", "BLS"),
    "UMCSENT": ("University of Michigan consumer sentiment", "Index 1966Q1=100", "Monthly", "FRED"),
}


class PhaseEService:
    def __init__(self, settings: Settings, repo: Repository):
        self.settings = settings
        self.repo = repo

    def health(self) -> HealthStatus:
        if self.settings.macro_mode == "offline":
            message, state = "Offline mode; reading saved macro and XBRL data", "healthy"
        elif self.settings.macro_mode == "mock":
            message, state = "Mock mode; illustrative macro and financial data", "healthy"
        else:
            message, state = "Online mode configured; sources are checked only during sync", "healthy"
        return HealthStatus("Phase E research", True, message, utc_now(), state=state)

    def sync_macro(self) -> pd.DataFrame:
        if self.settings.macro_mode == "offline":
            return self.macro_data()
        if self.settings.macro_mode == "mock":
            frame = self._mock_macro()
            self.repo.save_macro_observations(frame)
            return frame

        client = MacroClient(self.settings)
        frames: list[pd.DataFrame] = []
        try:
            current_year = date.today().year
            data = client.bls_series(
                ["CUUR0000SA0", "CUUR0000SA0L1E"], current_year - 9, current_year
            )
            frames.append(self._parse_bls(data))
            if self.settings.fred_api_key:
                frames.append(self._parse_fred(
                    "UMCSENT", client.fred_series("UMCSENT", date(current_year - 10, 1, 1))
                ))
        finally:
            client.close()
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        self.repo.save_macro_observations(frame)
        return frame

    def sync_company(self, symbol: str) -> pd.DataFrame:
        symbol = symbol.strip().upper()
        if symbol not in self.settings.phase_e_companies:
            raise ApplicationError(
                f"{symbol} is not configured in PHASE_E_COMPANIES."
            )
        if self.settings.sec_mode == "offline":
            return self.company_data([symbol])
        if self.settings.sec_mode == "mock":
            cik, name = COMPANIES.get(
                symbol, ("0000000000", f"{symbol} illustrative company")
            )
            frame = self._mock_financials(symbol, cik, name)
            self.repo.save_company_financials(frame)
            return frame
        client = SECClient(self.settings)
        try:
            cik, _ = self._resolve_company(symbol, client)
            frame = parse_company_financials(
                client.company_facts(cik), symbol, cik, utc_now()
            )
        finally:
            client.close()
        if frame.empty:
            raise ApplicationError(f"SEC Company Facts returned no supported annual facts for {symbol}.")
        self.repo.save_company_financials(frame)
        return frame

    @staticmethod
    def _resolve_company(symbol: str, client: SECClient) -> tuple[str, str]:
        if symbol in COMPANIES:
            return COMPANIES[symbol]
        mapping = client.company_tickers()
        for company in mapping.values():
            if str(company.get("ticker", "")).strip().upper() == symbol:
                cik = str(company.get("cik_str", "")).zfill(10)
                name = str(company.get("title", symbol)).strip()
                if cik.strip("0"):
                    return cik, name
        raise ApplicationError(
            f"SEC company ticker mapping did not contain {symbol}. "
            "Check that PHASE_E_COMPANIES uses the SEC-listed ticker."
        )

    def macro_data(self) -> pd.DataFrame:
        return self.repo.macro_observations()

    def company_data(self, symbols: list[str] | None = None) -> pd.DataFrame:
        return self.repo.company_financials(symbols)

    @staticmethod
    def _parse_bls(payload: dict) -> pd.DataFrame:
        rows = []
        now = utc_now()
        for series in payload.get("Results", {}).get("series", []):
            series_id = series["seriesID"]
            meta = MACRO_SERIES[series_id]
            for item in series.get("data", []):
                period = item.get("period", "")
                if not period.startswith("M") or period == "M13":
                    continue
                try:
                    value = float(str(item.get("value", "")).strip())
                except (TypeError, ValueError):
                    # BLS can publish placeholders such as "-" for observations
                    # that are unavailable or not yet reported. Keep the valid
                    # observations instead of failing the entire synchronization.
                    continue
                rows.append({
                    "series_id": series_id,
                    "observation_date": date(int(item["year"]), int(period[1:]), 1),
                    "value": value, "series_name": meta[0],
                    "unit": meta[1], "frequency": meta[2], "source": meta[3],
                    "retrieved_at": now,
                })
        return pd.DataFrame(rows)

    @staticmethod
    def _parse_fred(series_id: str, payload: dict) -> pd.DataFrame:
        meta = MACRO_SERIES[series_id]
        rows = []
        now = utc_now()
        for item in payload.get("observations", []):
            try:
                value = float(str(item.get("value", "")).strip())
            except (TypeError, ValueError):
                continue
            rows.append({
                "series_id": series_id,
                "observation_date": pd.Timestamp(item["date"]).date(),
                "value": value, "series_name": meta[0],
                "unit": meta[1], "frequency": meta[2], "source": meta[3],
                "retrieved_at": now,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _mock_macro() -> pd.DataFrame:
        dates = pd.date_range(end=pd.Timestamp.today().normalize(), periods=72, freq="MS")
        rows = []
        now = utc_now()
        for i, dt in enumerate(dates):
            values = {
                "CUUR0000SA0": 255 + i * 0.75 + math.sin(i / 4),
                "CUUR0000SA0L1E": 260 + i * 0.70 + math.sin(i / 5),
                "UMCSENT": 75 + 8 * math.sin(i / 7),
            }
            for series_id, value in values.items():
                meta = MACRO_SERIES[series_id]
                rows.append({
                    "series_id": series_id, "observation_date": dt.date(),
                    "value": value, "series_name": meta[0], "unit": meta[1],
                    "frequency": meta[2], "source": "mock", "retrieved_at": now,
                })
        return pd.DataFrame(rows)

    @staticmethod
    def _mock_financials(
        symbol: str, cik: str | None = None, name: str | None = None
    ) -> pd.DataFrame:
        if cik is None or name is None:
            cik, name = COMPANIES.get(
                symbol, ("0000000000", f"{symbol} illustrative company")
            )
        rows = []
        now = utc_now()
        seed = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)
        base = 75e9 + (seed % 8) * 25e9
        for offset, year in enumerate(range(date.today().year - 5, date.today().year)):
            values = {
                "revenue": base * (1.12**offset),
                "operating_cash_flow": base * 0.35 * (1.10**offset),
                "capex_cash": base * 0.14 * (1.22**offset),
            }
            values["free_cash_flow"] = values["operating_cash_flow"] - values["capex_cash"]
            for metric, value in values.items():
                rows.append({
                    "symbol": symbol, "cik": cik, "company_name": name,
                    "fiscal_year": year, "period_end": date(year, 12, 31),
                    "metric": metric, "value": value, "unit": "USD",
                    "xbrl_tag": "MOCK" if metric != "free_cash_flow" else "DERIVED: mock",
                    "form_type": "MOCK", "filed_date": date(year + 1, 2, 1),
                    "accession_number": "", "source_url": "", "source": "mock",
                    "retrieved_at": now,
                })
        return pd.DataFrame(rows)
