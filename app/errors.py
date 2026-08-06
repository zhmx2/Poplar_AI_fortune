from __future__ import annotations


class ApplicationError(RuntimeError):
    """Base class for errors safe to show in the local UI."""


class DataSourceUnavailableError(ApplicationError):
    """A configured external data source cannot currently be reached."""


class FeatureDisabledError(ApplicationError):
    """A feature is intentionally disabled by configuration."""


def friendly_ibkr_error(exc: Exception, host: str, port: int) -> str:
    detail = str(exc).lower()
    if isinstance(exc, (ConnectionRefusedError, TimeoutError, OSError)) or any(
        marker in detail
        for marker in (
            "refused",
            "timed out",
            "timeout",
            "winerror 1225",
            "winerror 10061",
        )
    ):
        return (
            f"TWS is not connected at {host}:{port}. Start and sign in to TWS, "
            "enable ActiveX and Socket Clients, keep Read-Only API enabled, and "
            "confirm the socket port. SEC and offline DuckDB features remain available."
        )
    return f"IBKR is currently unavailable: {type(exc).__name__}: {exc}"
