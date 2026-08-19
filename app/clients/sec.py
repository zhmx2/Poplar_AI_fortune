from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any

import requests

from app.config import Settings
from app.errors import ApplicationError


class SECClient:
    """Compliant, cached, read-only SEC EDGAR client."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.cache_dir = settings.sec_cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._client = requests.Session()
        self._client.headers.update(
            {
                "User-Agent": settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json, application/xml, text/xml, */*",
            }
        )

    def close(self) -> None:
        self._client.close()

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}.cache"

    def _throttle(self) -> None:
        interval = 1.0 / self.settings.sec_requests_per_second
        with self._lock:
            remaining = interval - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request = time.monotonic()

    def get_text(self, url: str) -> str:
        path = self._cache_path(url)
        if self.settings.sec_mode == "offline":
            if path.exists():
                return path.read_text(encoding="utf-8")
            raise ApplicationError("SEC offline cache does not contain this filing.")
        if self.settings.sec_mode == "mock":
            raise ApplicationError("Network access is disabled in SEC mock mode.")

        last_error: Exception | None = None
        for attempt in range(self.settings.sec_max_retries + 1):
            try:
                self._throttle()
                response = self._client.get(
                    url, timeout=self.settings.sec_timeout_seconds
                )
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2**attempt
                    if attempt < self.settings.sec_max_retries:
                        time.sleep(min(delay, 30))
                        continue
                response.raise_for_status()
                path.write_text(response.text, encoding="utf-8")
                return response.text
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < self.settings.sec_max_retries:
                    time.sleep(min(2**attempt, 10))

        if path.exists():
            return path.read_text(encoding="utf-8")
        raise ApplicationError(
            f"SEC request failed and no cached copy is available: {last_error}"
        )

    def get_json(self, url: str) -> dict[str, Any]:
        try:
            return json.loads(self.get_text(url))
        except json.JSONDecodeError as exc:
            raise ApplicationError(f"SEC returned invalid JSON: {url}") from exc

    def submissions(self, cik: str) -> dict[str, Any]:
        return self.get_json(
            f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        )

    def company_facts(self, cik: str) -> dict[str, Any]:
        return self.get_json(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
        )

    def company_tickers(self) -> dict[str, Any]:
        """Return SEC's official ticker-to-CIK mapping."""
        return self.get_json("https://www.sec.gov/files/company_tickers.json")

    def filing_index(self, cik: str, accession: str) -> dict[str, Any]:
        compact = accession.replace("-", "")
        return self.get_json(
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}/index.json"
        )

    @staticmethod
    def information_table_names(index: dict[str, Any], primary: str) -> list[str]:
        """Return ranked XML candidates, excluding the filing cover document."""
        items = index.get("directory", {}).get("item", [])
        primary_name = Path(primary).name.lower()
        xml_items = []
        for item in items:
            name = str(item.get("name", ""))
            if not name.lower().endswith(".xml"):
                continue
            if Path(name).name.lower() == primary_name:
                continue
            try:
                size = int(item.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            xml_items.append((name, size))
        ranked = sorted(
            xml_items,
            key=lambda pair: (
                not any(
                    token in pair[0].lower()
                    for token in ("info", "table", "13f")
                ),
                -pair[1],
                pair[0].lower(),
            ),
        )
        if not ranked:
            raise ApplicationError("No 13F Information Table XML was found.")
        return [name for name, _ in ranked]

    @staticmethod
    def information_table_name(index: dict[str, Any], primary: str) -> str:
        """Backward-compatible first candidate accessor."""
        return SECClient.information_table_names(index, primary)[0]

    @staticmethod
    def archive_url(cik: str, accession: str, filename: str) -> str:
        compact = accession.replace("-", "")
        return (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{compact}/{filename}"
        )
