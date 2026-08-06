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

Future macro and company-financial modules will use this same
DuckDB file.

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
