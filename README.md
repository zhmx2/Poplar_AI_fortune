# Poplar AI Fortune

A Windows-first, local-only investment research application built with
Streamlit, a unified Python service layer, and DuckDB persistence. The project
is read-only by design: it contains no order placement, modification,
cancellation, or exercise functions.

> Research software only. Nothing in this repository is investment advice,
> and data returned by third-party providers must be independently verified.

Current capabilities:

- Read-only IBKR TWS account summaries, positions, and delayed quotes.
- Offline access to data already stored in DuckDB.
- OpenBB archive access with OpenBB network functionality frozen.
- SEC 13F institutional holdings with online, offline, and illustrative mock modes.

## OpenBB relationship

This repository was initially informed by OpenBB's financial-data integration
approach, but it is **not a fork of OpenBB** and does not copy or modify OpenBB
source code. OpenBB is installed as an optional third-party Python dependency
and is accessed only through `app/services/openbb.py`.

OpenBB network access is frozen by default with `OPENBB_ENABLED=false`. In this
mode the application does not import OpenBB, build its static interfaces, call
Yahoo Finance, or make an OpenBB provider request. Previously cached bars in
DuckDB remain available offline. IBKR, SEC EDGAR, BLS/FRED, and DuckDB operate
through separate clients and services and do not depend on OpenBB.

OpenBB is distributed by its own copyright holders under the GNU Affero
General Public License v3.0. OpenBB and every upstream data provider retain
their own trademarks, licenses, API restrictions, and data redistribution
terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Phase A status

Phase A freezes OpenBB and isolates every data source.

The safe default in `.env` is:

```env
OPENBB_ENABLED=false
```

With this setting, the app:

- Does not import the OpenBB package.
- Does not run an OpenBB connectivity check.
- Does not contact Yahoo Finance.
- Can still display historical bars already stored in DuckDB.
- Reports OpenBB as intentionally disabled instead of failed.

IBKR, OpenBB, and DuckDB health checks run independently. TWS being unavailable
does not prevent DuckDB or future SEC offline features from working.

## Phase B status: SEC 13F holdings

Phase B adds a read-only SEC EDGAR research module:

- Verified CIK configuration for Berkshire Hathaway, Bridgewater, Renaissance
  Technologies, Pershing Square, Appaloosa, Soros Fund Management, Tiger
  Global, and ARK Investment Management.
- Form `13F-HR` and `13F-HR/A` discovery and Information Table XML parsing.
- SEC-compliant User-Agent validation, throttling, retry, and file caching.
- Report-quarter persistence in the existing DuckDB file.
- Top-20 holdings charts and a bilingual current-holdings table.
- Explicit USD million/billion labels.
- Stock, ETF, and option classification with the classification method retained.
- Mock mode for safe offline demonstration.

The safe default is:

```env
SEC_MODE=mock
```

Click **Load illustrative SEC mock data** on the SEC page. The data is clearly
labelled as illustrative and is saved to DuckDB. To use SEC EDGAR, set:

```env
SEC_MODE=online
SEC_USER_AGENT=InvestmentResearchApp/1.0 your.real.email@domain.com
```

SEC requires declared contact information. Do not use the example address.
The app defaults to five requests per second, caches responses, and does not
submit or modify any SEC data.

## Phase C status: quarterly change analysis

Phase C adds:

- Synchronization of the latest four distinct 13F report quarters.
- Effective-filing selection so a later amendment does not duplicate an
  original filing in the same report quarter.
- Quarter-to-quarter `NEW`, `INCREASED`, `DECREASED`, `CLOSED`, and
  `UNCHANGED` classification.
- Share change, change rate, reported-value change, portfolio weight, and
  weight-change calculations.
- Bilingual column titles with USD million and percentage formatting.
- Orange highlighting for option rows in the current-holdings table.
- Interactive status filtering and draggable dataframe columns.
- SEC health information based on the latest recorded sync result. Older
  Phase B databases fall back to the most recently stored real SEC filing.
- Persistent visible-column and column-order configuration for current
  holdings and quarterly-change tables.
- Cross-institution reverse security lookup by issuer name or CUSIP, using
  each enabled institution's latest two effective saved quarters.

The comparison identity is `CUSIP + Put/Call`, so a stock and an option on the
same issuer are not combined. Change rate is based on reported shares; a new
position has no previous denominator and therefore displays a blank rate.

## Phase B/C enhancement: SEC institution management

The SEC module also includes local institution management:

- Add an institution by entering its SEC CIK.
- Normalize CIKs to the official ten-digit representation.
- Verify the official registrant name through SEC submissions data.
- Require at least one recent `13F-HR` or `13F-HR/A` before saving.
- Reject duplicate CIKs.
- Save verified user-added institutions in the existing DuckDB.
- Edit a bilingual display name and enable or disable any saved institution.
- Preserve user preferences across application restarts.
- Make enabled custom institutions available to the existing four-quarter sync,
  holdings dashboard, and quarterly change analysis.

Institution verification is available only in `SEC_MODE=online`. The app never
accepts a freely typed official SEC name as verified data; the name shown in
the database always comes from the SEC submissions response.

## Phase D: IBKR volatility research

The read-only volatility module includes underlying IV, HV30, IV/HV, a bounded
option chain, single-contract IV and Greeks, daily DuckDB snapshots, locally
calculated IVR/IVP, history charts, and watchlist scanning.

### Phase D2: watchlist analysis

Every watchlist scan is stored as an immutable batch in DuckDB, including
per-symbol failures. The Volatility page can reopen prior batches without a
TWS connection and provides KPI summaries, status/ranking filters, IV-versus-
HV charts, watchlist and symbol history, detailed bilingual status meanings,
and UTF-8 CSV export.

The main pricing labels are `IV premium` (`IV/HV >= 1.20`), `IV near HV`,
`IV discount` (`IV/HV <= 0.90`), and `Insufficient data`. These labels describe
the price of expected volatility relative to trailing realized volatility.
They do **not** predict whether the stock price will rise or fall and should
not be interpreted as overbought/oversold signals.

```env
IBKR_VOLATILITY_MODE=mock
IBKR_VOLATILITY_WAIT_SECONDS=3
IBKR_OPTION_STRIKE_COUNT=7
VOLATILITY_WATCHLIST=NVDA,SPY,QQQ,AAPL,MSFT
IBKR_US_STOCK_VOLUME_MULTIPLIER=1
```

Mock values are illustrative. After TWS is configured with Read-Only API, set
`IBKR_VOLATILITY_MODE=tws`. IBKR may return delayed, subscribed live, or
missing values depending on permissions; missing TWS fields are never
fabricated. IVR/IVP use daily observations accumulated by this application
instead of assuming a free historical-IV backfill. Repeated requests on the
same date update the same daily record.

## Phase E: macro and company financials

The **Macro & financials** page adds three DuckDB-backed views:

- BLS headline and core CPI, including locally calculated year-over-year rates.
- FRED University of Michigan consumer sentiment (`UMCSENT`) when an optional
  FRED API key is configured.
- SEC Company Facts annual revenue, operating cash flow, cash CAPEX and derived
  free cash flow for the verified MSFT, AMZN, GOOGL and META CIK mapping.

```env
MACRO_MODE=online
FRED_API_KEY=your_optional_32_character_key
BLS_REGISTRATION_KEY=
PHASE_E_COMPANIES=MSFT,AMZN,GOOGL,META
```

`MACRO_MODE=mock` creates clearly labelled illustrative data. `offline` makes
the page read DuckDB only. In `online` mode, BLS CPI works without a key under
the public API limits. FRED series are skipped until `FRED_API_KEY` is set.
SEC Company Facts uses the existing compliant `SEC_USER_AGENT`, throttling,
retry and cache configuration.

CAPEX is stored as the cash-flow XBRL concept and retains its original tag,
filing date, accession number and SEC link. It may exclude equipment acquired
under finance leases, so peer comparisons should not silently treat it as
total infrastructure investment. Free cash flow is explicitly derived as
operating cash flow minus cash CAPEX.

## Prerequisites

- Windows 11 and 64-bit Python 3.12.
- Trader Workstation only when IBKR pages are used.
- An active IBKR account with TWS API access for account or quote queries.

TWS is optional while using only offline data.

## Safe TWS configuration

In TWS, open **Global Configuration → API → Settings**:

1. Enable **ActiveX and Socket Clients**.
2. Keep **Read-Only API** enabled.
3. Confirm the live TWS socket port, normally `7496`.
4. Allow connections from localhost only.
5. Do not expose the TWS port through Windows Firewall or a router.

The application also passes `readonly=True` and rejects a non-loopback
`IBKR_HOST`.

## Install

Open PowerShell in this directory:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

The script creates `.venv`, installs dependencies, and creates `.env` from the
safe example when it does not already exist.

Important settings:

```env
IBKR_HOST=127.0.0.1
IBKR_PORT=7496
IBKR_CLIENT_ID=41
IBKR_MARKET_DATA_TYPE=3
DATABASE_PATH=data/investment.duckdb
OPENBB_ENABLED=false
```

Do not put an IBKR username, password, or authentication code in `.env`.

## Start

```powershell
.\start.ps1
```

Open:

```text
http://127.0.0.1:8501
```

The server binds only to `127.0.0.1`.

## Pages

- **Health:** independent status for IBKR, OpenBB, DuckDB, and SEC mode.
- **SEC 13F holdings:** institutional selector, report quarter, Top-20 charts,
  and locally persisted current holdings.
- **IBKR volatility:** IV/HV snapshot, IVR/IVP history, option-chain Greeks,
  and watchlist scan.
- **Account:** IBKR account summary; TWS is required.
- **Positions:** current IBKR holdings; TWS is required.
- **Quote:** IBKR delayed or subscribed quote; TWS is required.
- **OpenBB archive:** local DuckDB history only while OpenBB is frozen.
- **Local cache:** locally persisted IBKR quote snapshots.

Sensitive account identifiers are removed from dataframes before they are sent
to the browser. The local DuckDB audit snapshots may retain account identifiers,
so protect the Windows account and disk.

## DuckDB

The database is stored at:

```text
data/investment.duckdb
```

Current tables include:

- `account_snapshots`
- `positions`
- `quotes`
- `historical_bars`
- `institutions`
- `sec_filings`
- `institution_holdings`
- `volatility_snapshots`
- `option_quotes`
- `market_confirmation_bars`

Future macro and company-financial modules will use this same
DuckDB file.

## Phase F-A: market liquidity and funding pressure

The **Market liquidity** page adds a FRED-only, DuckDB-backed research layer.
OpenBB and IBKR are not used by Phase F-A.

Configured series:

- Federal Reserve assets (`WALCL`), Treasury General Account (`WTREGEN`), and
  overnight reverse repos (`RRPONTSYD`).
- National Financial Conditions Index (`NFCI`) and SOFR (`SOFR`).
- 2-year and 10-year Treasury yields (`DGS2`, `DGS10`), 10-year real yield
  (`DFII10`), and the 10y-2y spread (`T10Y2Y`).
- ICE BofA US High Yield option-adjusted spread (`BAMLH0A0HYM2`).

The derived net-liquidity proxy is:

```text
Federal Reserve total assets - Treasury General Account - overnight reverse repos
```

Monetary components are normalized to USD billions for calculation. Weekly Fed
assets and TGA observations are forward-filled across ON RRP observation dates.
The result is a research proxy, not an official FRED series and not a measure of
daily equity-fund flows. Saved raw observations retain their original units,
frequency, source, and retrieval timestamp.

Configuration:

```env
LIQUIDITY_MODE=mock
LIQUIDITY_LOOKBACK_YEARS=10
FRED_API_KEY=
```

Use `online` only after configuring a FRED key. `offline` performs no network
request and reads the existing DuckDB. One failed FRED series does not discard
successfully downloaded series; the UI reports partial-sync warnings.

### H.4.1 selected indicators

The Phase F-A sync also downloads a focused Federal Reserve H.4.1 dataset:

- `WRBWFRBL`: reserve balances with Federal Reserve Banks, Wednesday level
  (primary reserve series).
- `WRESBAL`: reserve balances, weekly average (secondary reference).
- `WALCL`: Federal Reserve total assets.
- `TREAST`: US Treasury securities held outright.
- `WSHOMCB`: mortgage-backed securities held outright.
- `WSHOFADSL`: federal agency debt securities held outright.
- `WLCFLL`: liquidity and credit facility loans.
- `WTREGEN`: Treasury General Account.

The dashboard displays reserve balances, 1-week/4-week/52-week changes,
year-over-year change, reserves as a share of Federal Reserve total assets,
asset composition, 4-week and 13-week securities runoff, facility-loan changes,
and the difference between actual reserve changes and the net-liquidity proxy.
All monetary levels are converted to USD billions for analysis while the raw
FRED observations retain their original units in DuckDB.

The QT runoff measure is the negative change in Treasury + MBS + agency debt
holdings. A positive value means combined holdings decreased; a negative value
means they increased. Neither the reserve metrics nor the net-liquidity proxy
measures equity-fund flows.

## Phase F-B: IBKR market confirmation basket

Phase F-B adds a read-only, daily-price confirmation layer to the **Market
liquidity** page. The default basket is:

- `SPY`: broad US equities.
- `QQQ`: growth equities.
- `IWM`: small-cap equities.
- `TLT`: long-duration US Treasuries.
- `HYG`: high-yield credit.
- `LQD`: investment-grade credit.
- `GLD`: gold.
- `UUP`: US-dollar proxy.

Daily bars are requested in one shared read-only TWS session and saved to the
deduplicated `market_confirmation_bars` table. The primary key is symbol,
trading date, and source. Partial symbol failures are reported without
discarding successful downloads. Mock and IBKR rows are strictly separated in
the dashboard.

Configuration:

```env
MARKET_CONFIRMATION_MODE=mock
MARKET_CONFIRMATION_LOOKBACK_YEARS=3
MARKET_CONFIRMATION_BASKET=SPY,QQQ,IWM,TLT,HYG,LQD,GLD,UUP
```

Modes are `mock`, `tws`, and `offline`. TWS mode requires the existing local,
read-only IBKR configuration. The basket supports up to 20 symbols and the
historical lookback is limited to 1-5 years to keep IBKR requests bounded.
Phase F-B displays trailing returns and normalized cross-asset performance; it
does not calculate the Phase F-C composite pressure score.

## Phase F-C: composite market-pressure dashboard

Phase F-C is an offline calculation and presentation layer over the
source-isolated observations already saved by Phase F-A and Phase F-B. It makes
no FRED or IBKR request. Recalculation writes an auditable daily history to
`market_pressure_scores`, including raw component values, component scores,
weights, coverage, status labels, and calculation timestamps.

The 0-100 score uses eight pressure-oriented components:

| Component | Weight |
|---|---:|
| Net-liquidity contraction (20 trading days) | 20% |
| NFCI financial conditions | 15% |
| 10-year real-yield change (20 trading days) | 15% |
| High-yield OAS change (20 trading days) | 15% |
| SPY weakness (20 trading days) | 15% |
| IWM weakness relative to SPY | 10% |
| HYG weakness | 5% |
| UUP strength | 5% |

Each component is transformed using only its rolling 252-observation history
(minimum 60 observations), then clipped to 0-100. Missing components are not
silently treated as neutral: available weights are renormalized, coverage is
shown, and at least five of eight components are required. Status bands are:
below 30 supportive, 30-45 mild pressure, 45-55 neutral, 55-70 elevated
pressure, and 70 or above high pressure.

This is a transparent research indicator, not an official fund-flow measure,
forecast, trading signal, or investment recommendation.

## Tests

Tests are offline and do not connect to IBKR or Yahoo Finance:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

They verify:

- Localhost-only IBKR configuration.
- Delayed market-data defaults.
- Absence of order methods.
- Friendly TWS connection errors.
- Independent data-source health checks.
- OpenBB disabled without importing the package.
- OpenBB history blocked before a network call.
- DuckDB persistence.

## Restoring OpenBB later

Only restore OpenBB intentionally:

1. Stop Streamlit.
2. Set `OPENBB_ENABLED=true`.
3. Run:

```powershell
.\.venv\Scripts\openbb-build.exe
```

4. Restart the application.

OpenBB and provider availability must be retested before regular use.

## Troubleshooting

- **TWS not connected:** start TWS, enable socket clients, and check the port.
- **Client ID already in use:** select another `IBKR_CLIENT_ID`.
- **No quote values:** confirm delayed data availability and TWS permissions.
- **Database locked:** close other programs directly accessing the DuckDB file.
- **OpenBB disabled:** expected during Phase A; the archive remains available.

This is a research tool, not a trading system or investment recommendation.

## License

Poplar AI Fortune is licensed under the GNU Affero General Public License v3.0
(`AGPL-3.0-only`). See [LICENSE](LICENSE). Third-party packages and market data
are not relicensed by this repository; their original terms continue to apply.

### Stock turnover estimate

The **Stock turnover** page reuses `VOLATILITY_WATCHLIST` and requests IBKR
daily stock bars only—no streaming quote, option contract, IV, Greeks, or
option-chain requests. It estimates each symbol's session dollar turnover as
the current daily-bar volume multiplied by daily WAP, then saves both the batch
and symbol-level results in DuckDB.

The value is an estimate, not an official consolidated exchange turnover.

The same page also contains **Daily Quant Engine / 日线量化引擎**. It downloads
and caches read-only IBKR daily OHLCV bars for the selected watchlist stock plus
SPY, QQQ, and SOXX, then calculates SMA20/50/200, RSI14, 20/60-day returns,
HV20/30, ATR14%, volume ratio, relative strength, factor scores, and a 0–100
market-regime score. Configure the history window with
`DAILY_QUANT_LOOKBACK_YEARS=3` (1–5 years). Scores describe the current daily
market state and are not forecasts, recommendations, or order signals.
Historical daily-bar volume is treated as shares and does not use the streaming
volume multiplier setting.

The engine also includes **Optimized trend channel / 最优趋势通道**. It uses
saved IBKR OHLCV rows only: an OLS log-Close direction identifies extreme
log-Low/log-High pivots, then an exact one-dimensional constrained solution
produces strict support and resistance lines. The user selects the Lookback in
the frontend (20, 60, 120, 252, or a custom 20–504 trading-day value). The
optional `TREND_LINE_DEFAULT_LOOKBACK=120` changes only the initial UI value.
Changing Lookback does not contact TWS. Results are versioned and upserted into
DuckDB table `optimized_trend_lines`; version 1 does not alter the existing
Daily Quant composite score or label channel exits as confirmed breakouts.

Trend-channel version 2 (`projected_atr_channel_v2`) fits the historical
Lookback window and projects the lines into two independent confirmation days.
It adds a fixed `0.25 × ATR14` breakout buffer, support/resistance touch counts,
two-close confirmation, Strict and Robust (2% residual-tail clipping) modes,
20/60/120/252-day comparison, and a saved walk-forward breakout backtest for
5/20/60-day forward returns. These are research diagnostics only; transaction
costs, slippage, taxes, and position sizing are not modeled.
