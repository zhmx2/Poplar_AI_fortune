# Security policy

## Supported version

Security fixes are applied to the latest version on the `main` branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature for this
repository. Do not open a public issue containing credentials, account numbers,
private filings, API keys, or reproducible exploit details.

## Credential safety

- Copy `.env.example` to `.env` and keep `.env` local.
- Never commit IBKR credentials, account identifiers, SEC contact details, or
  API keys.
- Keep TWS restricted to localhost and enable Read-Only API.
- Do not expose the Streamlit service or the TWS socket directly to the public
  internet.
- DuckDB files may contain portfolio or research history and are intentionally
  excluded from version control.
