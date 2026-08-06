from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import math
from time import monotonic
from uuid import uuid4
from collections.abc import Callable

import numpy as np
import pandas as pd

from app.analytics.volatility import (
    iv_percentile, iv_rank, safe_ratio, volatility_state,
)
from app.config import Settings
from app.db import Repository
from app.errors import ApplicationError
from app.models import VolatilitySnapshot, utc_now
from app.models import HealthStatus
from app.services.ibkr import IBKRService


class VolatilityService:
    def __init__(
        self, settings: Settings, ibkr: IBKRService, repo: Repository
    ):
        self.settings = settings
        self.ibkr = ibkr
        self.repo = repo

    def health(self) -> HealthStatus:
        if self.settings.ibkr_volatility_mode == "mock":
            return HealthStatus(
                "IBKR volatility",
                True,
                "Mock mode: illustrative IV, Greeks and seeded history",
                utc_now(),
                state="healthy",
            )
        return HealthStatus(
            "IBKR volatility",
            True,
            "TWS mode configured; fields are verified when a snapshot is requested",
            utc_now(),
            state="healthy",
        )

    @staticmethod
    def _seed(symbol: str) -> int:
        return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)

    def _mock_base(self, symbol: str) -> tuple[float, float, float]:
        seed = self._seed(symbol)
        spot = 80.0 + seed % 220
        iv = 0.20 + (seed % 35) / 100
        hv = iv * (0.68 + (seed % 18) / 100)
        return spot, iv, hv

    def _ensure_mock_history(self, symbol: str) -> None:
        if len(
            self.repo.volatility_history(symbol, 400, source="ibkr-mock")
        ) >= 252:
            return
        spot, base_iv, hv = self._mock_base(symbol)
        rng = np.random.default_rng(self._seed(symbol))
        dates = pd.bdate_range(end=date.today() - timedelta(days=1), periods=252)
        iv_values = np.clip(
            base_iv + np.cumsum(rng.normal(0, 0.006, len(dates))),
            0.08,
            1.5,
        )
        price_values = spot * np.exp(
            np.cumsum(rng.normal(0, hv / math.sqrt(252), len(dates)))
        )
        frame = pd.DataFrame(
            {
                "symbol": symbol,
                "market_date": dates.date,
                "spot_price": price_values,
                "underlying_iv": iv_values,
                "hv30": hv,
                "iv_hv_ratio": iv_values / hv,
                "ivr_52w": np.nan,
                "ivp_52w": np.nan,
                "observation_count": range(1, len(dates) + 1),
                "market_data_type": "mock",
                "source": "ibkr-mock",
                "observed_at": pd.Timestamp.now(tz="UTC"),
                "data_quality": "illustrative mock history",
            }
        )
        self.repo.save_volatility_frame(frame)

    def snapshot(
        self,
        symbol: str,
        progress: Callable[[str], None] | None = None,
    ) -> VolatilitySnapshot:
        def report(message: str) -> None:
            if progress is not None:
                progress(message)

        symbol = symbol.strip().upper()
        if not symbol:
            raise ApplicationError("Enter a stock symbol.")
        if self.settings.ibkr_volatility_mode == "mock":
            report("Preparing illustrative Mock history")
            self._ensure_mock_history(symbol)
            spot, current_iv, hv30 = self._mock_base(symbol)
            raw = {
                "spot_price": spot,
                "underlying_iv": current_iv,
                "hv30": hv30,
                "market_data_type": "mock",
            }
            source = "ibkr-mock"
        else:
            raw = self.ibkr.volatility_snapshot_raw(symbol, progress=report)
            source = "ibkr"

        return self._calculate_and_save(symbol, raw, source, report)

    def _calculate_and_save(
        self,
        symbol: str,
        raw: dict,
        source: str,
        report: Callable[[str], None],
    ) -> VolatilitySnapshot:
        current_iv, hv30 = raw["underlying_iv"], raw["hv30"]
        report("Calculating IV/HV, IV Rank and IV Percentile")
        history = self.repo.volatility_history(
            symbol, 252, source=source
        ).sort_values("market_date")
        previous = history.loc[
            history["market_date"] != pd.Timestamp(date.today()),
            "underlying_iv",
        ].dropna().tolist()
        ranking_values = previous[-251:] + (
            [current_iv] if current_iv is not None else []
        )
        count = len(ranking_values)
        quality = (
            "ready: 252 observations"
            if count >= 252
            else f"building history: {count}/252 observations"
        )
        if current_iv is None:
            quality = "underlying IV unavailable from current data permissions"
        snapshot = VolatilitySnapshot(
            symbol=symbol,
            market_date=date.today(),
            spot_price=raw["spot_price"],
            underlying_iv=current_iv,
            hv30=hv30,
            iv_hv_ratio=safe_ratio(current_iv, hv30),
            ivr_52w=iv_rank(current_iv, ranking_values),
            ivp_52w=iv_percentile(current_iv, ranking_values),
            observation_count=count,
            market_data_type=raw["market_data_type"],
            source=source,
            observed_at=utc_now(),
            data_quality=quality,
        )
        report("Saving the daily snapshot to DuckDB")
        self.repo.save_volatility_snapshot(snapshot)
        report("Snapshot saved successfully")
        return snapshot

    def history(self, symbol: str) -> pd.DataFrame:
        source = (
            "ibkr-mock"
            if self.settings.ibkr_volatility_mode == "mock"
            else "ibkr"
        )
        return self.repo.volatility_history(
            symbol, 400, source=source
        ).sort_values("market_date")

    def expirations(
        self,
        symbol: str,
        progress: Callable[[str], None] | None = None,
    ) -> list[str]:
        if self.settings.ibkr_volatility_mode == "mock":
            today = date.today()
            return [
                (today + timedelta(days=days)).strftime("%Y%m%d")
                for days in (30, 60, 90)
            ]
        return self.ibkr.option_expirations(
            symbol.strip().upper(), progress=progress
        )

    def option_chain(
        self,
        symbol: str,
        expiry: str,
        progress: Callable[[str], None] | None = None,
    ) -> pd.DataFrame:
        symbol = symbol.strip().upper()
        if self.settings.ibkr_volatility_mode == "mock":
            frame = self._mock_chain(symbol, expiry)
        else:
            frame = self.ibkr.option_chain(
                symbol,
                expiry,
                self.settings.ibkr_option_strike_count,
                progress=progress,
            )
        if progress is not None:
            progress("Saving option-chain rows to DuckDB")
        self.repo.save_option_quotes(frame)
        if progress is not None:
            progress("Option-chain rows saved successfully")
        return frame

    def _mock_chain(self, symbol: str, expiry: str) -> pd.DataFrame:
        spot, base_iv, _ = self._mock_base(symbol)
        step = max(2.5, round(spot * 0.025 / 2.5) * 2.5)
        half = self.settings.ibkr_option_strike_count // 2
        center = round(spot / step) * step
        strikes = [center + step * offset for offset in range(-half, half + 1)]
        expiry_date = date(int(expiry[:4]), int(expiry[4:6]), int(expiry[6:8]))
        rows = []
        now = utc_now()
        for strike in strikes:
            moneyness = (strike - spot) / spot
            iv = base_iv + abs(moneyness) * 0.35
            for right in ("C", "P"):
                delta = (
                    0.5 - moneyness * 4
                    if right == "C"
                    else -0.5 - moneyness * 4
                )
                delta = max(0.05, min(0.95, delta)) if right == "C" else max(
                    -0.95, min(-0.05, delta)
                )
                intrinsic = max(spot - strike, 0) if right == "C" else max(
                    strike - spot, 0
                )
                midpoint = intrinsic + spot * iv * 0.04
                rows.append(
                    {
                        "symbol": symbol, "con_id": 0, "expiry": expiry_date,
                        "strike": strike, "option_right": right,
                        "bid": midpoint * 0.97, "ask": midpoint * 1.03,
                        "last": midpoint, "midpoint": midpoint,
                        "implied_vol": iv, "delta": delta,
                        "gamma": 0.015, "vega": spot * 0.0012,
                        "theta": -spot * 0.0004,
                        "option_price": midpoint,
                        "underlying_price": spot,
                        "market_data_type": "mock", "source": "ibkr-mock",
                        "observed_at": now,
                    }
                )
        return pd.DataFrame(rows)

    def scan(
        self,
        symbols: tuple[str, ...] | list[str],
        progress: Callable[[str], None] | None = None,
    ) -> pd.DataFrame:
        def report(message: str) -> None:
            if progress is not None:
                progress(message)

        normalized = tuple(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
        started_at = utc_now()
        timer = monotonic()
        rows: list[dict] = []
        if self.settings.ibkr_volatility_mode == "mock":
            for symbol in normalized:
                try:
                    rows.append(
                        self.snapshot(symbol, progress=report).to_dict()
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "symbol": symbol,
                            "data_quality":
                            f"Unavailable: {type(exc).__name__}: {exc}",
                        }
                    )
        else:
            try:
                raw_results = self.ibkr.volatility_snapshots_raw(
                    normalized, progress=report
                )
            except Exception as exc:
                raw_results = {symbol: exc for symbol in normalized}
            for symbol in normalized:
                raw = raw_results.get(symbol)
                if isinstance(raw, Exception):
                    rows.append({
                        "symbol": symbol,
                        "data_quality": f"Unavailable: {type(raw).__name__}: {raw}",
                    })
                    continue
                if raw is None:
                    rows.append({
                        "symbol": symbol,
                        "data_quality": "Unavailable: no result returned",
                    })
                    continue
                try:
                    rows.append(
                        self._calculate_and_save(symbol, raw, "ibkr", report).to_dict()
                    )
                except Exception as exc:
                    rows.append({
                        "symbol": symbol,
                        "data_quality": f"Unavailable: {type(exc).__name__}: {exc}",
                    })

        completed_at = utc_now()
        run_id = uuid4().hex
        result_rows = []
        for row in rows:
            quality = str(row.get("data_quality", ""))
            success = not quality.startswith("Unavailable:")
            state = volatility_state(
                row.get("iv_hv_ratio"), row.get("ivp_52w"),
                int(row.get("observation_count") or 0),
            )
            result_rows.append({
                "run_id": run_id,
                "symbol": row.get("symbol"),
                "success": success,
                "error_message": None if success else quality,
                "market_date": row.get("market_date"),
                "spot_price": row.get("spot_price"),
                "underlying_iv": row.get("underlying_iv"),
                "hv30": row.get("hv30"),
                "iv_hv_ratio": row.get("iv_hv_ratio"),
                "ivr_52w": row.get("ivr_52w"),
                "ivp_52w": row.get("ivp_52w"),
                "observation_count": row.get("observation_count", 0),
                "market_data_type": row.get("market_data_type"),
                "source": row.get("source"),
                "observed_at": row.get("observed_at"),
                "data_quality": quality,
                **state,
            })
        frame = pd.DataFrame(result_rows)
        successes = int(frame["success"].sum()) if not frame.empty else 0
        source = "ibkr-mock" if self.settings.ibkr_volatility_mode == "mock" else "ibkr"
        self.repo.save_watchlist_scan(
            {
                "run_id": run_id,
                "started_at": started_at,
                "completed_at": completed_at,
                "source": source,
                "requested_count": len(normalized),
                "success_count": successes,
                "failed_count": len(normalized) - successes,
                "duration_seconds": monotonic() - timer,
                "symbols_json": json.dumps(normalized),
            },
            frame,
        )
        return frame

    def scan_runs(self, limit: int = 100) -> pd.DataFrame:
        return self.repo.watchlist_scan_runs(limit)

    def scan_report(self, run_id: str) -> pd.DataFrame:
        return self.repo.watchlist_scan_results(run_id)

    def watchlist_history(self) -> pd.DataFrame:
        source = "ibkr-mock" if self.settings.ibkr_volatility_mode == "mock" else "ibkr"
        return self.repo.watchlist_volatility_history(source)
