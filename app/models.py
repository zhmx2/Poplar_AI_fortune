from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class HealthStatus:
    service: str
    ok: bool
    message: str
    checked_at: datetime
    state: str = "healthy"


@dataclass
class Quote:
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    close: float | None
    currency: str
    market_data_type: str
    source: str
    observed_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VolatilitySnapshot:
    symbol: str
    market_date: Any
    spot_price: float | None
    underlying_iv: float | None
    hv30: float | None
    iv_hv_ratio: float | None
    ivr_52w: float | None
    ivp_52w: float | None
    observation_count: int
    market_data_type: str
    source: str
    observed_at: datetime
    data_quality: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
