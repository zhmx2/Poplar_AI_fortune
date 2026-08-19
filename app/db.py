from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Iterator

import duckdb
import pandas as pd

from app.models import HealthStatus, Quote, utc_now


class Repository:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = duckdb.connect(str(self.path))
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS quotes (
                    symbol VARCHAR, bid DOUBLE, ask DOUBLE, last DOUBLE,
                    close DOUBLE, currency VARCHAR, market_data_type VARCHAR,
                    source VARCHAR, observed_at TIMESTAMPTZ
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    account VARCHAR, symbol VARCHAR, con_id BIGINT,
                    security_type VARCHAR, currency VARCHAR, position DOUBLE,
                    average_cost DOUBLE, market_price DOUBLE, market_value DOUBLE,
                    unrealized_pnl DOUBLE, realized_pnl DOUBLE,
                    source VARCHAR, observed_at TIMESTAMPTZ
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS account_snapshots (
                    account VARCHAR, tag VARCHAR, value VARCHAR, currency VARCHAR,
                    source VARCHAR, observed_at TIMESTAMPTZ
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS historical_bars (
                    symbol VARCHAR, bar_time TIMESTAMP, open DOUBLE, high DOUBLE,
                    low DOUBLE, close DOUBLE, volume DOUBLE, source VARCHAR,
                    fetched_at TIMESTAMPTZ
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS institutions (
                    institution_id VARCHAR PRIMARY KEY, name VARCHAR, name_cn VARCHAR,
                    cik VARCHAR, verified_source VARCHAR, updated_at TIMESTAMPTZ
                )
            """)
            con.execute(
                "ALTER TABLE institutions ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE"
            )
            con.execute(
                "ALTER TABLE institutions ADD COLUMN IF NOT EXISTS user_added BOOLEAN DEFAULT FALSE"
            )
            con.execute(
                "ALTER TABLE institutions ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ"
            )
            con.execute("""
                CREATE TABLE IF NOT EXISTS sec_filings (
                    accession_number VARCHAR PRIMARY KEY, institution_id VARCHAR,
                    cik VARCHAR, form_type VARCHAR, filing_date DATE,
                    report_period DATE, primary_document VARCHAR,
                    information_table_url VARCHAR, is_amendment BOOLEAN,
                    source_url VARCHAR, retrieved_at TIMESTAMPTZ,
                    content_hash VARCHAR, source VARCHAR
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS institution_holdings (
                    institution_id VARCHAR, report_period DATE,
                    accession_number VARCHAR, cusip VARCHAR, issuer_name VARCHAR,
                    title_of_class VARCHAR, figi VARCHAR, security_type VARCHAR,
                    classification_method VARCHAR, raw_value DOUBLE,
                    value_scale DOUBLE, value_usd DOUBLE, shares DOUBLE,
                    share_type VARCHAR, put_call VARCHAR,
                    investment_discretion VARCHAR, other_manager VARCHAR,
                    voting_sole DOUBLE, voting_shared DOUBLE, voting_none DOUBLE,
                    portfolio_weight DOUBLE, source VARCHAR,
                    retrieved_at TIMESTAMPTZ
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS sec_sync_runs (
                    run_id VARCHAR PRIMARY KEY, institution_id VARCHAR,
                    started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
                    success BOOLEAN, message VARCHAR, report_period DATE,
                    filings_saved INTEGER
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS volatility_snapshots (
                    symbol VARCHAR, market_date DATE, spot_price DOUBLE,
                    underlying_iv DOUBLE, hv30 DOUBLE, iv_hv_ratio DOUBLE,
                    ivr_52w DOUBLE, ivp_52w DOUBLE, observation_count INTEGER,
                    market_data_type VARCHAR, source VARCHAR,
                    observed_at TIMESTAMPTZ, data_quality VARCHAR,
                    PRIMARY KEY (symbol, market_date, source)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS option_quotes (
                    symbol VARCHAR, con_id BIGINT, expiry DATE, strike DOUBLE,
                    option_right VARCHAR, bid DOUBLE, ask DOUBLE, last DOUBLE,
                    midpoint DOUBLE, implied_vol DOUBLE, delta DOUBLE,
                    gamma DOUBLE, vega DOUBLE, theta DOUBLE,
                    option_price DOUBLE, underlying_price DOUBLE,
                    market_data_type VARCHAR, source VARCHAR,
                    observed_at TIMESTAMPTZ
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS watchlist_scan_runs (
                    run_id VARCHAR PRIMARY KEY, started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ, source VARCHAR,
                    requested_count INTEGER, success_count INTEGER,
                    failed_count INTEGER, duration_seconds DOUBLE,
                    symbols_json VARCHAR
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS watchlist_scan_results (
                    run_id VARCHAR, symbol VARCHAR, success BOOLEAN,
                    error_message VARCHAR, market_date DATE,
                    spot_price DOUBLE, underlying_iv DOUBLE, hv30 DOUBLE,
                    iv_hv_ratio DOUBLE, ivr_52w DOUBLE, ivp_52w DOUBLE,
                    observation_count INTEGER, market_data_type VARCHAR,
                    source VARCHAR, observed_at TIMESTAMPTZ,
                    data_quality VARCHAR, status_label VARCHAR,
                    status_label_cn VARCHAR, status_explanation VARCHAR,
                    PRIMARY KEY (run_id, symbol)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS stock_turnover_runs (
                    run_id VARCHAR PRIMARY KEY, started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ, source VARCHAR,
                    requested_count INTEGER, success_count INTEGER,
                    failed_count INTEGER, symbols_json VARCHAR
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS stock_turnover_estimates (
                    run_id VARCHAR, symbol VARCHAR, success BOOLEAN,
                    error_message VARCHAR, raw_volume DOUBLE,
                    volume_multiplier DOUBLE, estimated_share_volume DOUBLE,
                    price_used DOUBLE, price_basis VARCHAR,
                    estimated_turnover_usd DOUBLE, currency VARCHAR,
                    market_data_type VARCHAR, session_scope VARCHAR,
                    source VARCHAR, observed_at TIMESTAMPTZ,
                    data_quality VARCHAR,
                    PRIMARY KEY (run_id, symbol)
                )
            """)
            con.execute(
                "ALTER TABLE stock_turnover_estimates ADD COLUMN IF NOT EXISTS "
                "volume_scale_divisor DOUBLE DEFAULT 1"
            )
            con.execute(
                "ALTER TABLE stock_turnover_estimates ADD COLUMN IF NOT EXISTS "
                "reference_daily_volume DOUBLE"
            )
            # ib_async 2.x exposes TWS decimal stock sizes at a fixed 4-decimal
            # integer scale. Early turnover batches stored that wire value as
            # shares. Correct those legacy rows once, identified by their old
            # data-quality text so subsequent initializations remain idempotent.
            con.execute("""
                UPDATE stock_turnover_estimates
                SET estimated_share_volume = estimated_share_volume / 10000.0,
                    estimated_turnover_usd = estimated_turnover_usd / 10000.0,
                    data_quality = data_quality ||
                        '; corrected ib_async fixed-decimal volume scale'
                WHERE source = 'ibkr'
                  AND data_quality =
                    'Estimate = cumulative volume × price basis; not official exchange turnover'
            """)
            con.execute("""
                UPDATE stock_turnover_estimates
                SET estimated_share_volume = estimated_share_volume * 10000.0,
                    estimated_turnover_usd = estimated_turnover_usd * 10000.0,
                    volume_scale_divisor = 1,
                    data_quality = replace(
                        data_quality,
                        '; corrected ib_async fixed-decimal volume scale',
                        '; retained native volume scale after plausibility check'
                    )
                WHERE source = 'ibkr'
                  AND raw_volume < 100000000
                  AND data_quality LIKE
                    '%corrected ib_async fixed-decimal volume scale%'
            """)
            con.execute("""
                UPDATE stock_turnover_estimates
                SET volume_scale_divisor = 10000
                WHERE source = 'ibkr'
                  AND data_quality LIKE
                    '%corrected ib_async fixed-decimal volume scale%'
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS macro_observations (
                    series_id VARCHAR, observation_date DATE, value DOUBLE,
                    series_name VARCHAR, unit VARCHAR, frequency VARCHAR,
                    source VARCHAR, retrieved_at TIMESTAMPTZ,
                    PRIMARY KEY (series_id, observation_date, source)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS market_confirmation_bars (
                    symbol VARCHAR, asset_name VARCHAR, asset_name_cn VARCHAR,
                    market_role VARCHAR, market_role_cn VARCHAR, bar_date DATE,
                    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
                    volume DOUBLE, source VARCHAR, fetched_at TIMESTAMPTZ,
                    PRIMARY KEY (symbol, bar_date, source)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS optimized_trend_lines (
                    symbol VARCHAR, calculation_date DATE, lookback INTEGER,
                    algorithm_version VARCHAR, price_transform VARCHAR,
                    constraint_mode VARCHAR, window_start DATE, window_end DATE,
                    ols_slope DOUBLE, ols_intercept DOUBLE,
                    support_pivot_date DATE, support_pivot_price DOUBLE,
                    support_slope DOUBLE, support_intercept DOUBLE,
                    support_current DOUBLE, resistance_pivot_date DATE,
                    resistance_pivot_price DOUBLE, resistance_slope DOUBLE,
                    resistance_intercept DOUBLE, resistance_current DOUBLE,
                    latest_close DOUBLE, channel_width DOUBLE,
                    channel_position DOUBLE, distance_to_support DOUBLE,
                    distance_to_resistance DOUBLE, status VARCHAR,
                    data_warning VARCHAR, calculated_at TIMESTAMPTZ,
                    PRIMARY KEY (
                        symbol, calculation_date, lookback, algorithm_version
                    )
                )
            """)
            for definition in (
                "atr14 DOUBLE", "atr_buffer DOUBLE", "support_touches INTEGER",
                "resistance_touches INTEGER", "confirmation_days INTEGER",
                "breakout_status VARCHAR", "robust_outlier_fraction DOUBLE",
            ):
                con.execute(
                    "ALTER TABLE optimized_trend_lines ADD COLUMN IF NOT EXISTS "
                    + definition
                )
            con.execute("""
                CREATE TABLE IF NOT EXISTS trend_line_backtests (
                    run_id VARCHAR PRIMARY KEY, symbol VARCHAR, lookback INTEGER,
                    mode VARCHAR, forward_days INTEGER, signal_count INTEGER,
                    win_rate DOUBLE, average_directional_return DOUBLE,
                    median_directional_return DOUBLE, calculated_at TIMESTAMPTZ
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS trend_line_backtest_signals (
                    run_id VARCHAR, signal_date DATE, direction VARCHAR,
                    entry_close DOUBLE, forward_close DOUBLE,
                    forward_return DOUBLE, directional_return DOUBLE, win BOOLEAN,
                    PRIMARY KEY (run_id, signal_date, direction)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS market_pressure_scores (
                    score_date DATE PRIMARY KEY,
                    composite_score DOUBLE, coverage_ratio DOUBLE,
                    available_components INTEGER,
                    status_label VARCHAR, status_label_cn VARCHAR,
                    status_explanation VARCHAR, status_explanation_cn VARCHAR,
                    liquidity_source VARCHAR, market_source VARCHAR,
                    liquidity_contraction_value DOUBLE,
                    liquidity_contraction_score DOUBLE,
                    nfci_value DOUBLE, nfci_score DOUBLE,
                    real_yield_shock_value DOUBLE,
                    real_yield_shock_score DOUBLE,
                    credit_widening_value DOUBLE,
                    credit_widening_score DOUBLE,
                    equity_weakness_value DOUBLE,
                    equity_weakness_score DOUBLE,
                    smallcap_weakness_value DOUBLE,
                    smallcap_weakness_score DOUBLE,
                    hyg_weakness_value DOUBLE, hyg_weakness_score DOUBLE,
                    dollar_strength_value DOUBLE, dollar_strength_score DOUBLE,
                    calculated_at TIMESTAMPTZ
                )
            """)
            con.execute(
                "ALTER TABLE market_pressure_scores ADD COLUMN IF NOT EXISTS liquidity_source VARCHAR"
            )
            con.execute(
                "ALTER TABLE market_pressure_scores ADD COLUMN IF NOT EXISTS market_source VARCHAR"
            )
            con.execute("""
                CREATE TABLE IF NOT EXISTS company_financials (
                    symbol VARCHAR, cik VARCHAR, company_name VARCHAR,
                    fiscal_year INTEGER, period_end DATE, metric VARCHAR,
                    value DOUBLE, unit VARCHAR, xbrl_tag VARCHAR,
                    form_type VARCHAR, filed_date DATE, accession_number VARCHAR,
                    source_url VARCHAR, source VARCHAR, retrieved_at TIMESTAMPTZ,
                    PRIMARY KEY (symbol, period_end, metric, source)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS table_preferences (
                    table_key VARCHAR PRIMARY KEY,
                    visible_columns_json VARCHAR,
                    column_order_json VARCHAR,
                    updated_at TIMESTAMPTZ
                )
            """)

    def save_quote(self, quote: Quote) -> None:
        values = list(quote.to_dict().values())
        with self.connect() as con:
            con.execute("INSERT INTO quotes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values)

    def save_frame(self, table: str, frame: pd.DataFrame) -> None:
        allowed = {"positions", "account_snapshots", "historical_bars"}
        if table not in allowed or frame.empty:
            return
        with self.connect() as con:
            con.register("_incoming", frame)
            con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM _incoming")

    def recent_quotes(self, limit: int = 100) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM quotes ORDER BY observed_at DESC LIMIT ?", [limit]
            ).df()

    def health(self) -> HealthStatus:
        try:
            with self.connect() as con:
                con.execute("SELECT 1").fetchone()
            return HealthStatus(
                "DuckDB", True, f"Ready: {self.path}", utc_now(), state="healthy"
            )
        except Exception as exc:
            return HealthStatus(
                "DuckDB",
                False,
                f"Unavailable: {type(exc).__name__}: {exc}",
                utc_now(),
                state="unavailable",
            )

    def historical_symbols(self) -> list[str]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT DISTINCT symbol FROM historical_bars ORDER BY symbol"
            ).fetchall()
        return [row[0] for row in rows]

    def historical_bars(self, symbol: str, limit: int = 1000) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(
                """
                SELECT symbol, bar_time, open, high, low, close, volume, source,
                       fetched_at
                FROM historical_bars
                WHERE symbol = ?
                ORDER BY bar_time DESC
                LIMIT ?
                """,
                [symbol.upper(), limit],
            ).df()

    def upsert_institutions(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        with self.connect() as con:
            con.register("_institutions", frame)
            con.execute("""
                INSERT INTO institutions (
                    institution_id, name, name_cn, cik, verified_source,
                    updated_at, enabled, user_added, verified_at
                )
                SELECT institution_id, name, name_cn, cik, verified_source,
                       updated_at, enabled, user_added, verified_at
                FROM _institutions
                ON CONFLICT (institution_id) DO UPDATE SET
                    name = excluded.name,
                    name_cn = institutions.name_cn,
                    cik = excluded.cik,
                    verified_source = excluded.verified_source,
                    updated_at = excluded.updated_at,
                    verified_at = COALESCE(
                        institutions.verified_at, excluded.verified_at
                    )
            """)

    def institutions(self, active_only: bool = True) -> pd.DataFrame:
        with self.connect() as con:
            where = "WHERE enabled" if active_only else ""
            return con.execute(
                f"SELECT * FROM institutions {where} ORDER BY name"
            ).df()

    def institution_by_cik(self, cik: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM institutions WHERE cik = ? LIMIT 1", [cik]
            ).fetchone()
            columns = [item[0] for item in con.description] if row else []
        return dict(zip(columns, row)) if row else None

    def save_verified_institution(self, record: dict) -> None:
        frame = pd.DataFrame([record])
        self.upsert_institutions(frame)

    def update_institution_preferences(
        self, institution_id: str, name_cn: str, enabled: bool
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                UPDATE institutions
                SET name_cn = COALESCE(NULLIF(TRIM(?), ''), name),
                    enabled = ?, updated_at = ?
                WHERE institution_id = ?
                """,
                [str(name_cn or ""), enabled, utc_now(), institution_id],
            )

    def save_sec_filing(self, filing: dict, holdings: pd.DataFrame) -> None:
        accession = filing["accession_number"]
        enriched = holdings.copy()
        for column in (
            "institution_id",
            "report_period",
            "accession_number",
            "source",
            "retrieved_at",
        ):
            enriched[column] = filing[column]
        with self.connect() as con:
            con.execute("BEGIN")
            try:
                con.execute(
                    """
                    INSERT OR REPLACE INTO sec_filings VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    [
                        filing[name]
                        for name in (
                            "accession_number", "institution_id", "cik",
                            "form_type", "filing_date", "report_period",
                            "primary_document", "information_table_url",
                            "is_amendment", "source_url", "retrieved_at",
                            "content_hash", "source",
                        )
                    ],
                )
                con.execute(
                    "DELETE FROM institution_holdings WHERE accession_number = ?",
                    [accession],
                )
                con.register("_holdings", enriched)
                con.execute("""
                    INSERT INTO institution_holdings BY NAME
                    SELECT * FROM _holdings
                """)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

    def sec_periods(self, institution_id: str) -> list:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT DISTINCT report_period
                FROM institution_holdings
                WHERE institution_id = ?
                ORDER BY report_period DESC
                """,
                [institution_id],
            ).fetchall()
        return [row[0] for row in rows]

    def institution_holdings(self, institution_id: str, report_period) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(
                """
                WITH effective_filing AS (
                    SELECT accession_number
                    FROM sec_filings
                    WHERE institution_id = ? AND report_period = ?
                    ORDER BY filing_date DESC, is_amendment DESC,
                             retrieved_at DESC
                    LIMIT 1
                )
                SELECT issuer_name, title_of_class, cusip, security_type,
                       classification_method, value_usd, shares, share_type,
                       put_call, investment_discretion, other_manager,
                       voting_sole, voting_shared, voting_none,
                       portfolio_weight, source, retrieved_at
                FROM institution_holdings
                WHERE accession_number = (
                    SELECT accession_number FROM effective_filing
                )
                ORDER BY value_usd DESC
                """,
                [institution_id, report_period],
            ).df()

    def save_sec_sync_run(self, run: dict) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO sec_sync_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run[name]
                    for name in (
                        "run_id", "institution_id", "started_at", "completed_at",
                        "success", "message", "report_period", "filings_saved",
                    )
                ],
            )

    def latest_sec_activity(self) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT r.success, r.completed_at, r.message, r.report_period,
                       r.filings_saved, i.name
                FROM sec_sync_runs r
                LEFT JOIN institutions i USING (institution_id)
                ORDER BY r.completed_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row:
                return {
                    "success": row[0], "completed_at": row[1],
                    "message": row[2], "report_period": row[3],
                    "filings_saved": row[4], "institution_name": row[5],
                }
            legacy = con.execute(
                """
                SELECT TRUE, f.retrieved_at, 'Stored SEC filing', f.report_period,
                       1, i.name
                FROM sec_filings f
                LEFT JOIN institutions i USING (institution_id)
                WHERE f.source = 'SEC EDGAR'
                ORDER BY f.retrieved_at DESC
                LIMIT 1
                """
            ).fetchone()
        if not legacy:
            return None
        return {
            "success": legacy[0], "completed_at": legacy[1],
            "message": legacy[2], "report_period": legacy[3],
            "filings_saved": legacy[4], "institution_name": legacy[5],
        }

    def save_volatility_snapshot(self, snapshot) -> None:
        values = snapshot.to_dict()
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        with self.connect() as con:
            con.execute(
                f"""
                INSERT OR REPLACE INTO volatility_snapshots
                ({", ".join(columns)}) VALUES ({placeholders})
                """,
                [values[column] for column in columns],
            )

    def save_volatility_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        with self.connect() as con:
            con.register("_volatility_snapshots", frame)
            con.execute("""
                INSERT OR REPLACE INTO volatility_snapshots BY NAME
                SELECT * FROM _volatility_snapshots
            """)

    def volatility_history(
        self, symbol: str, limit: int = 252, source: str | None = None
    ) -> pd.DataFrame:
        source_filter = " AND source = ?" if source else ""
        parameters: list[object] = [symbol.upper()]
        if source:
            parameters.append(source)
        parameters.append(limit)
        with self.connect() as con:
            return con.execute(
                f"""
                SELECT * FROM volatility_snapshots
                WHERE symbol = ?
                {source_filter}
                ORDER BY market_date DESC
                LIMIT ?
                """,
                parameters,
            ).df()

    def save_option_quotes(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        with self.connect() as con:
            con.register("_option_quotes", frame)
            con.execute(
                "INSERT INTO option_quotes BY NAME SELECT * FROM _option_quotes"
            )

    def save_watchlist_scan(self, run: dict, results: pd.DataFrame) -> None:
        with self.connect() as con:
            con.execute("BEGIN TRANSACTION")
            con.execute(
                """INSERT OR REPLACE INTO watchlist_scan_runs
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [run[key] for key in (
                    "run_id", "started_at", "completed_at", "source",
                    "requested_count", "success_count", "failed_count",
                    "duration_seconds", "symbols_json",
                )],
            )
            if not results.empty:
                con.register("_watchlist_results", results)
                con.execute("""
                    INSERT OR REPLACE INTO watchlist_scan_results BY NAME
                    SELECT * FROM _watchlist_results
                """)
            con.execute("COMMIT")

    def watchlist_scan_runs(self, limit: int = 100) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(
                """SELECT * FROM watchlist_scan_runs
                   ORDER BY completed_at DESC LIMIT ?""", [limit]
            ).df()

    def watchlist_scan_results(self, run_id: str) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(
                """SELECT * FROM watchlist_scan_results
                   WHERE run_id = ? ORDER BY symbol""", [run_id]
            ).df()

    def watchlist_volatility_history(self, source: str) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(
                """SELECT market_date,
                          median(underlying_iv) AS median_iv,
                          median(hv30) AS median_hv30,
                          median(iv_hv_ratio) AS median_iv_hv_ratio,
                          count(*) AS symbol_count
                   FROM volatility_snapshots
                   WHERE source = ?
                   GROUP BY market_date ORDER BY market_date""", [source]
            ).df()

    def save_stock_turnover_scan(self, run: dict, results: pd.DataFrame) -> None:
        with self.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute(
                    """INSERT OR REPLACE INTO stock_turnover_runs
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [run[key] for key in (
                        "run_id", "started_at", "completed_at", "source",
                        "requested_count", "success_count", "failed_count",
                        "symbols_json",
                    )],
                )
                if not results.empty:
                    con.register("_stock_turnover", results)
                    con.execute("""
                        INSERT OR REPLACE INTO stock_turnover_estimates BY NAME
                        SELECT * FROM _stock_turnover
                    """)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

    def stock_turnover_runs(self, limit: int = 100) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(
                """SELECT * FROM stock_turnover_runs
                   ORDER BY completed_at DESC LIMIT ?""", [limit]
            ).df()

    def stock_turnover_report(self, run_id: str) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(
                """SELECT * FROM stock_turnover_estimates
                   WHERE run_id = ?
                   ORDER BY estimated_turnover_usd DESC NULLS LAST, symbol""",
                [run_id],
            ).df()

    def stock_turnover_symbols(self) -> pd.DataFrame:
        """Return symbols that have at least one usable saved estimate."""
        with self.connect() as con:
            return con.execute(
                """SELECT DISTINCT symbol
                   FROM stock_turnover_estimates
                   WHERE success = TRUE
                     AND estimated_turnover_usd IS NOT NULL
                   ORDER BY symbol"""
            ).df()

    def stock_turnover_history(
        self, symbol: str, start_date=None, end_date=None
    ) -> pd.DataFrame:
        """Return one (latest) successful observation per symbol and market day."""
        filters = ["symbol = ?", "success = TRUE", "estimated_turnover_usd IS NOT NULL"]
        params: list = [symbol.upper().strip()]
        if start_date is not None:
            filters.append("market_date >= ?")
            params.append(start_date)
        if end_date is not None:
            filters.append("market_date <= ?")
            params.append(end_date)
        where_clause = " AND ".join(filters)
        with self.connect() as con:
            return con.execute(
                f"""WITH normalized AS (
                       SELECT *, COALESCE(
                           TRY_CAST(session_scope AS DATE),
                           CAST(observed_at AS DATE)
                       ) AS market_date
                       FROM stock_turnover_estimates
                   ), ranked AS (
                       SELECT *, ROW_NUMBER() OVER (
                           PARTITION BY symbol, market_date
                           ORDER BY observed_at DESC, run_id DESC
                       ) AS recency_rank
                       FROM normalized
                       WHERE {where_clause}
                   )
                   SELECT market_date, symbol, estimated_share_volume,
                          price_used, price_basis, estimated_turnover_usd,
                          currency, market_data_type, session_scope,
                          observed_at, data_quality
                   FROM ranked
                   WHERE recency_rank = 1
                   ORDER BY market_date""",
                params,
            ).df()

    def save_macro_observations(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        with self.connect() as con:
            con.register("_macro", frame)
            con.execute("""INSERT OR REPLACE INTO macro_observations BY NAME
                           SELECT * FROM _macro""")

    def macro_observations(self, series_ids: list[str] | None = None) -> pd.DataFrame:
        with self.connect() as con:
            if not series_ids:
                return con.execute(
                    "SELECT * FROM macro_observations ORDER BY observation_date"
                ).df()
            placeholders = ",".join("?" for _ in series_ids)
            return con.execute(
                f"""SELECT * FROM macro_observations
                    WHERE series_id IN ({placeholders})
                    ORDER BY observation_date""", series_ids
            ).df()

    def save_market_confirmation_bars(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        with self.connect() as con:
            con.register("_market_bars", frame)
            con.execute(
                """INSERT OR REPLACE INTO market_confirmation_bars BY NAME
                   SELECT * FROM _market_bars"""
            )

    def market_confirmation_bars(
        self,
        symbols: list[str] | tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        with self.connect() as con:
            if not symbols:
                return con.execute(
                    """SELECT * FROM market_confirmation_bars
                       ORDER BY bar_date, symbol"""
                ).df()
            normalized = [symbol.upper() for symbol in symbols]
            placeholders = ",".join("?" for _ in normalized)
            return con.execute(
                f"""SELECT * FROM market_confirmation_bars
                    WHERE symbol IN ({placeholders})
                    ORDER BY bar_date, symbol""",
                normalized,
            ).df()

    def save_optimized_trend_line(self, result: dict) -> None:
        frame = pd.DataFrame([result])
        with self.connect() as con:
            con.register("_trend_line", frame)
            con.execute(
                """INSERT OR REPLACE INTO optimized_trend_lines BY NAME
                   SELECT * FROM _trend_line"""
            )

    def optimized_trend_lines(
        self, symbol: str | None = None, lookback: int | None = None
    ) -> pd.DataFrame:
        filters, params = [], []
        if symbol:
            filters.append("symbol = ?")
            params.append(symbol.upper())
        if lookback is not None:
            filters.append("lookback = ?")
            params.append(int(lookback))
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with self.connect() as con:
            return con.execute(
                f"""SELECT * FROM optimized_trend_lines{where}
                    ORDER BY calculation_date DESC, calculated_at DESC""",
                params,
            ).df()

    def save_trend_line_backtest(
        self, summary: dict, signals: pd.DataFrame
    ) -> None:
        summary_frame = pd.DataFrame([summary])
        with self.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                con.register("_backtest_summary", summary_frame)
                con.execute(
                    """INSERT INTO trend_line_backtests BY NAME
                       SELECT * FROM _backtest_summary"""
                )
                if not signals.empty:
                    con.register("_backtest_signals", signals)
                    con.execute(
                        """INSERT INTO trend_line_backtest_signals BY NAME
                           SELECT * FROM _backtest_signals"""
                    )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

    def save_market_pressure_scores(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        with self.connect() as con:
            con.register("_pressure_scores", frame)
            con.execute("BEGIN TRANSACTION")
            con.execute("DELETE FROM market_pressure_scores")
            con.execute(
                """INSERT OR REPLACE INTO market_pressure_scores BY NAME
                   SELECT * FROM _pressure_scores"""
            )
            con.execute("COMMIT")

    def market_pressure_scores(self) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM market_pressure_scores ORDER BY score_date"
            ).df()

    def save_company_financials(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        with self.connect() as con:
            con.register("_financials", frame)
            con.execute("""INSERT OR REPLACE INTO company_financials BY NAME
                           SELECT * FROM _financials""")

    def company_financials(self, symbols: list[str] | None = None) -> pd.DataFrame:
        with self.connect() as con:
            if not symbols:
                return con.execute(
                    "SELECT * FROM company_financials ORDER BY period_end"
                ).df()
            placeholders = ",".join("?" for _ in symbols)
            return con.execute(
                f"""SELECT * FROM company_financials
                    WHERE symbol IN ({placeholders})
                    ORDER BY period_end""", [s.upper() for s in symbols]
            ).df()

    def save_table_preference(
        self, table_key: str, visible_columns: list[str], column_order: list[str]
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO table_preferences VALUES (?, ?, ?, ?)
                """,
                [
                    table_key,
                    json.dumps(visible_columns),
                    json.dumps(column_order),
                    utc_now(),
                ],
            )

    def table_preference(self, table_key: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT visible_columns_json, column_order_json
                FROM table_preferences WHERE table_key = ?
                """,
                [table_key],
            ).fetchone()
        if not row:
            return None
        return {
            "visible_columns": json.loads(row[0]),
            "column_order": json.loads(row[1]),
        }

    def reverse_security_lookup(self, query: str, limit: int = 2000) -> pd.DataFrame:
        pattern = f"%{query.strip().lower()}%"
        with self.connect() as con:
            return con.execute(
                """
                WITH filing_rank AS (
                    SELECT f.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY institution_id, report_period
                               ORDER BY filing_date DESC, is_amendment DESC,
                                        retrieved_at DESC
                           ) AS effective_rank
                    FROM sec_filings f
                ),
                period_rank AS (
                    SELECT *,
                           DENSE_RANK() OVER (
                               PARTITION BY institution_id
                               ORDER BY report_period DESC
                           ) AS quarter_rank
                    FROM filing_rank
                    WHERE effective_rank = 1
                ),
                positions AS (
                    SELECT h.institution_id, p.quarter_rank, h.report_period,
                           h.cusip, COALESCE(h.put_call, '') AS put_call,
                           MIN(h.issuer_name) AS issuer_name,
                           MIN(h.title_of_class) AS title_of_class,
                           MIN(h.security_type) AS security_type,
                           SUM(h.value_usd) AS value_usd,
                           SUM(h.shares) AS shares,
                           SUM(h.portfolio_weight) AS portfolio_weight
                    FROM institution_holdings h
                    JOIN period_rank p
                      ON h.institution_id = p.institution_id
                     AND h.report_period = p.report_period
                     AND h.accession_number = p.accession_number
                    WHERE p.quarter_rank <= 2
                    GROUP BY h.institution_id, p.quarter_rank, h.report_period,
                             h.cusip, COALESCE(h.put_call, '')
                ),
                current_positions AS (
                    SELECT * FROM positions WHERE quarter_rank = 1
                ),
                previous_positions AS (
                    SELECT * FROM positions WHERE quarter_rank = 2
                ),
                compared AS (
                    SELECT COALESCE(c.institution_id, p.institution_id)
                               AS institution_id,
                           c.report_period AS current_period,
                           p.report_period AS previous_period,
                           COALESCE(c.issuer_name, p.issuer_name) AS issuer_name,
                           COALESCE(c.title_of_class, p.title_of_class)
                               AS title_of_class,
                           COALESCE(c.security_type, p.security_type)
                               AS security_type,
                           COALESCE(c.cusip, p.cusip) AS cusip,
                           COALESCE(c.put_call, p.put_call) AS put_call,
                           COALESCE(c.value_usd, 0) AS current_value_usd,
                           COALESCE(p.value_usd, 0) AS previous_value_usd,
                           COALESCE(c.shares, 0) AS current_shares,
                           COALESCE(p.shares, 0) AS previous_shares,
                           COALESCE(c.portfolio_weight, 0) AS current_weight,
                           COALESCE(p.portfolio_weight, 0) AS previous_weight,
                           CASE
                               WHEN p.institution_id IS NULL THEN 'NEW'
                               WHEN c.institution_id IS NULL THEN 'CLOSED'
                               WHEN c.shares > p.shares THEN 'INCREASED'
                               WHEN c.shares < p.shares THEN 'DECREASED'
                               ELSE 'UNCHANGED'
                           END AS status
                    FROM current_positions c
                    FULL OUTER JOIN previous_positions p
                      ON c.institution_id = p.institution_id
                     AND c.cusip = p.cusip
                     AND c.put_call = p.put_call
                )
                SELECT i.name AS institution_name, i.name_cn,
                       c.current_period, c.previous_period, c.issuer_name,
                       c.title_of_class, c.security_type,
                       NULLIF(c.put_call, '') AS put_call, c.cusip, c.status,
                       c.current_value_usd, c.previous_value_usd,
                       c.current_value_usd - c.previous_value_usd
                           AS value_change_usd,
                       c.current_weight, c.previous_weight,
                       c.current_weight - c.previous_weight AS weight_change,
                       c.current_shares, c.previous_shares,
                       c.current_shares - c.previous_shares AS shares_change,
                       CASE WHEN c.previous_shares != 0
                            THEN (c.current_shares - c.previous_shares)
                                 / c.previous_shares
                            ELSE NULL END AS change_rate
                FROM compared c
                JOIN institutions i USING (institution_id)
                WHERE i.enabled
                  AND (
                      LOWER(c.issuer_name) LIKE ?
                      OR LOWER(c.cusip) LIKE ?
                  )
                ORDER BY c.current_value_usd DESC, i.name
                LIMIT ?
                """,
                [pattern, pattern, limit],
            ).df()
