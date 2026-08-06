from __future__ import annotations

from datetime import date
from typing import Any

import requests

from app.config import Settings
from app.errors import ApplicationError


class MacroClient:
    """Read-only clients for official BLS and FRED endpoints."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = requests.Session()

    def close(self) -> None:
        self._client.close()

    def bls_series(
        self, series_ids: list[str], start_year: int, end_year: int
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if self.settings.bls_registration_key:
            payload["registrationkey"] = self.settings.bls_registration_key
        try:
            response = self._client.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json=payload,
                timeout=self.settings.sec_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ApplicationError(f"BLS request failed: {exc}") from exc
        if data.get("status") != "REQUEST_SUCCEEDED":
            raise ApplicationError(
                "BLS rejected the request: " + "; ".join(data.get("message", []))
            )
        return data

    def fred_series(self, series_id: str, observation_start: date) -> dict[str, Any]:
        if not self.settings.fred_api_key:
            raise ApplicationError(
                "FRED_API_KEY is not configured. CPI can still be loaded from BLS."
            )
        try:
            response = self._client.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id": series_id,
                    "api_key": self.settings.fred_api_key,
                    "file_type": "json",
                    "observation_start": observation_start.isoformat(),
                },
                timeout=self.settings.sec_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ApplicationError(f"FRED request failed: {exc}") from exc
