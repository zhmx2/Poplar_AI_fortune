from __future__ import annotations

from datetime import date

import pandas as pd

from app.config import Settings
from app.errors import FeatureDisabledError
from app.models import HealthStatus, utc_now


class OpenBBService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def health(self) -> HealthStatus:
        if not self.settings.openbb_enabled:
            return HealthStatus(
                "OpenBB",
                True,
                "Frozen by configuration. No OpenBB import or network request was made.",
                utc_now(),
                state="disabled",
            )
        try:
            from openbb import obb  # noqa: F401

            return HealthStatus(
                "OpenBB", True, "Python package loaded; static interfaces are ready.", utc_now()
            )
        except ValueError as exc:
            if "signal only works in main thread" in str(exc):
                return HealthStatus(
                    "OpenBB",
                    False,
                    "Static interfaces are not built. Stop the app, run "
                    r".\.venv\Scripts\openbb-build.exe once, then restart it.",
                    utc_now(),
                )
            return HealthStatus(
                "OpenBB", False, f"Unavailable: ValueError: {exc}", utc_now()
            )
        except Exception as exc:
            return HealthStatus(
                "OpenBB", False, f"Unavailable: {type(exc).__name__}: {exc}", utc_now()
            )

    def history(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        if not self.settings.openbb_enabled:
            raise FeatureDisabledError(
                "OpenBB is frozen. Set OPENBB_ENABLED=true and restart the app "
                "only when you intentionally want to restore network access."
            )
        from openbb import obb

        result = obb.equity.price.historical(
            symbol=symbol.upper(),
            start_date=start_date,
            end_date=end_date,
            provider=self.settings.openbb_history_provider,
        )
        frame = result.to_dataframe().reset_index()
        date_column = "date" if "date" in frame.columns else frame.columns[0]
        frame = frame.rename(columns={date_column: "bar_time"})
        wanted = ["bar_time", "open", "high", "low", "close", "volume"]
        frame = frame[[column for column in wanted if column in frame.columns]].copy()
        frame["symbol"] = symbol.upper()
        frame["source"] = f"openbb:{self.settings.openbb_history_provider}"
        frame["fetched_at"] = utc_now()
        return frame
