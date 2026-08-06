# Third-party software and data notices

Poplar AI Fortune integrates with third-party software and data services. This
file is informational and does not replace the authoritative license or terms
published by each provider.

## OpenBB

OpenBB is an optional Python dependency. This repository is not an OpenBB fork,
does not vendor OpenBB source code, and interacts with the separately installed
package through `app/services/openbb.py`. OpenBB access is disabled by default.

- Project: https://github.com/OpenBB-finance/OpenBB
- License: GNU Affero General Public License v3.0
- Copyright and trademarks remain with their respective owners.

Enabling an OpenBB provider also subjects the user to that provider's API,
market-data, caching, and redistribution terms.

## Interactive Brokers

The application connects to a locally running Trader Workstation API session
for read-only account and market-data research. No IBKR credentials are stored
by the application and no order methods are implemented. Market-data access,
delays, storage, and redistribution remain subject to Interactive Brokers and
exchange terms.

## SEC EDGAR

SEC filings are retrieved from SEC EDGAR using a declared User-Agent, request
throttling, retry, and local caching. Users must follow the SEC's current fair
access guidance. Filing content remains attributable to its original filer.

## BLS and FRED

Macroeconomic observations may be retrieved from the U.S. Bureau of Labor
Statistics and the Federal Reserve Bank of St. Louis FRED service. Individual
series can carry source-specific copyright and attribution requirements. Check
each series page before redistributing data.

## Python dependencies

Python packages listed in `requirements.txt` and `requirements-dev.txt` are
distributed under their own licenses. Installing this project downloads those
packages from their respective distribution channels; this repository does not
relicense them.
