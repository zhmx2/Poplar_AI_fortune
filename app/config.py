from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    ibkr_host: str = os.getenv("IBKR_HOST", "127.0.0.1")
    ibkr_port: int = _int("IBKR_PORT", 7496)
    ibkr_client_id: int = _int("IBKR_CLIENT_ID", 41)
    ibkr_account: str = os.getenv("IBKR_ACCOUNT", "")
    ibkr_timeout_seconds: float = _float("IBKR_TIMEOUT_SECONDS", 8.0)
    ibkr_market_data_type: int = _int("IBKR_MARKET_DATA_TYPE", 3)
    ibkr_volatility_mode: str = os.getenv(
        "IBKR_VOLATILITY_MODE", "mock"
    ).strip().lower()
    ibkr_volatility_wait_seconds: float = _float(
        "IBKR_VOLATILITY_WAIT_SECONDS", 3.0
    )
    ibkr_us_stock_volume_multiplier: float = _float(
        "IBKR_US_STOCK_VOLUME_MULTIPLIER", 1.0
    )
    ibkr_option_strike_count: int = _int("IBKR_OPTION_STRIKE_COUNT", 7)
    volatility_watchlist: tuple[str, ...] = tuple(
        symbol.strip().upper()
        for symbol in os.getenv(
            "VOLATILITY_WATCHLIST", "NVDA,SPY,QQQ,AAPL,MSFT"
        ).split(",")
        if symbol.strip()
    )
    daily_quant_lookback_years: int = _int("DAILY_QUANT_LOOKBACK_YEARS", 3)
    trend_line_default_lookback: int = _int("TREND_LINE_DEFAULT_LOOKBACK", 120)
    database_path: Path = ROOT / os.getenv("DATABASE_PATH", "data/investment.duckdb")
    openbb_enabled: bool = _bool("OPENBB_ENABLED", False)
    openbb_history_provider: str = os.getenv("OPENBB_HISTORY_PROVIDER", "yfinance")
    default_symbol: str = os.getenv("APP_DEFAULT_SYMBOL", "NVDA")
    sec_mode: str = os.getenv("SEC_MODE", "mock").strip().lower()
    sec_user_agent: str = os.getenv("SEC_USER_AGENT", "").strip()
    sec_requests_per_second: float = _float("SEC_REQUESTS_PER_SECOND", 5.0)
    sec_timeout_seconds: float = _float("SEC_TIMEOUT_SECONDS", 20.0)
    sec_max_retries: int = _int("SEC_MAX_RETRIES", 3)
    sec_cache_dir: Path = ROOT / os.getenv("SEC_CACHE_DIR", "data/sec_cache")
    macro_mode: str = os.getenv("MACRO_MODE", "mock").strip().lower()
    fred_api_key: str = os.getenv("FRED_API_KEY", "").strip()
    bls_registration_key: str = os.getenv("BLS_REGISTRATION_KEY", "").strip()
    phase_e_companies: tuple[str, ...] = tuple(
        symbol.strip().upper()
        for symbol in os.getenv(
            "PHASE_E_COMPANIES", "MSFT,AMZN,GOOGL,META"
        ).split(",") if symbol.strip()
    )
    liquidity_mode: str = os.getenv("LIQUIDITY_MODE", "mock").strip().lower()
    liquidity_lookback_years: int = _int("LIQUIDITY_LOOKBACK_YEARS", 10)
    market_confirmation_mode: str = os.getenv(
        "MARKET_CONFIRMATION_MODE", "mock"
    ).strip().lower()
    market_confirmation_lookback_years: int = _int(
        "MARKET_CONFIRMATION_LOOKBACK_YEARS", 3
    )
    market_confirmation_basket: tuple[str, ...] = tuple(
        symbol.strip().upper()
        for symbol in os.getenv(
            "MARKET_CONFIRMATION_BASKET",
            "SPY,QQQ,IWM,TLT,HYG,LQD,GLD,UUP",
        ).split(",")
        if symbol.strip()
    )

    def __post_init__(self) -> None:
        if self.ibkr_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("IBKR_HOST must be a loopback address for this local-only app.")
        if self.ibkr_market_data_type not in {3, 4}:
            raise ValueError("IBKR_MARKET_DATA_TYPE must be delayed (3) or delayed-frozen (4).")
        if not 1 <= self.ibkr_port <= 65535:
            raise ValueError("IBKR_PORT is invalid.")
        if self.ibkr_volatility_mode not in {"mock", "tws"}:
            raise ValueError("IBKR_VOLATILITY_MODE must be mock or tws.")
        if not 0.5 <= self.ibkr_volatility_wait_seconds <= 15:
            raise ValueError(
                "IBKR_VOLATILITY_WAIT_SECONDS must be between 0.5 and 15."
            )
        if self.ibkr_us_stock_volume_multiplier not in {1.0, 100.0}:
            raise ValueError(
                "IBKR_US_STOCK_VOLUME_MULTIPLIER must be 1 or 100."
            )
        if not 3 <= self.ibkr_option_strike_count <= 21:
            raise ValueError("IBKR_OPTION_STRIKE_COUNT must be between 3 and 21.")
        if self.sec_mode not in {"mock", "online", "offline"}:
            raise ValueError("SEC_MODE must be mock, online, or offline.")
        if not 0.1 <= self.sec_requests_per_second <= 10:
            raise ValueError("SEC_REQUESTS_PER_SECOND must be between 0.1 and 10.")
        if self.sec_mode == "online":
            agent = self.sec_user_agent.lower()
            if "@" not in agent or "example.com" in agent:
                raise ValueError(
                    "SEC_USER_AGENT must contain a real contact email in online mode."
                )
        if self.macro_mode not in {"mock", "online", "offline"}:
            raise ValueError("MACRO_MODE must be mock, online, or offline.")
        if self.liquidity_mode not in {"mock", "online", "offline"}:
            raise ValueError("LIQUIDITY_MODE must be mock, online, or offline.")
        if not 1 <= self.liquidity_lookback_years <= 30:
            raise ValueError("LIQUIDITY_LOOKBACK_YEARS must be between 1 and 30.")
        if self.market_confirmation_mode not in {"mock", "tws", "offline"}:
            raise ValueError(
                "MARKET_CONFIRMATION_MODE must be mock, tws, or offline."
            )
        if not 1 <= self.market_confirmation_lookback_years <= 5:
            raise ValueError(
                "MARKET_CONFIRMATION_LOOKBACK_YEARS must be between 1 and 5."
            )
        if not self.market_confirmation_basket:
            raise ValueError("MARKET_CONFIRMATION_BASKET must not be empty.")
        if len(self.market_confirmation_basket) > 20:
            raise ValueError(
                "MARKET_CONFIRMATION_BASKET supports at most 20 symbols."
            )
        if not 1 <= self.daily_quant_lookback_years <= 5:
            raise ValueError("DAILY_QUANT_LOOKBACK_YEARS must be between 1 and 5.")
        if not 20 <= self.trend_line_default_lookback <= 504:
            raise ValueError("TREND_LINE_DEFAULT_LOOKBACK must be between 20 and 504.")
