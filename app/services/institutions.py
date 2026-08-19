from __future__ import annotations

from datetime import date
import hashlib
import json
import uuid

import pandas as pd

from app.clients.sec import SECClient
from app.config import ROOT, Settings
from app.db import Repository
from app.errors import ApplicationError
from app.mock_sec import MOCK_INFORMATION_TABLE
from app.models import HealthStatus, utc_now
from app.parsers.information_table import parse_information_table
from app.analytics.holdings_changes import aggregate_holdings, compare_holdings


class InstitutionService:
    def __init__(self, settings: Settings, repo: Repository):
        self.settings = settings
        self.repo = repo
        self.client = SECClient(settings)
        self._bootstrap()

    def _bootstrap(self) -> None:
        records = json.loads((ROOT / "config/institutions.json").read_text("utf-8"))
        frame = pd.DataFrame(records)
        frame["updated_at"] = utc_now()
        frame["enabled"] = True
        frame["user_added"] = False
        frame["verified_at"] = utc_now()
        self.repo.upsert_institutions(frame)

    def institutions(self, active_only: bool = True) -> pd.DataFrame:
        return self.repo.institutions(active_only=active_only)

    @staticmethod
    def normalize_cik(value: str) -> str:
        digits = "".join(character for character in value if character.isdigit())
        if not digits or len(digits) > 10:
            raise ApplicationError("CIK must contain 1 to 10 digits.")
        return digits.zfill(10)

    def verify_cik(self, cik_input: str) -> dict:
        if self.settings.sec_mode != "online":
            raise ApplicationError(
                "New institutions can be verified only when SEC_MODE=online."
            )
        cik = self.normalize_cik(cik_input)
        submissions = self.client.submissions(cik)
        official_name = str(submissions.get("name", "")).strip()
        if not official_name:
            raise ApplicationError("SEC did not return an official name for this CIK.")
        filings = self._recent_filings(submissions)
        if not filings:
            raise ApplicationError(
                "This CIK was found, but no recent 13F-HR filing is available."
            )
        return {
            "cik": cik,
            "name": official_name,
            "latest_form": filings[0]["form"],
            "latest_filing_date": filings[0]["filingDate"],
            "latest_report_date": filings[0]["reportDate"],
            "recent_13f_count": len(filings),
            "verified_source": f"https://data.sec.gov/submissions/CIK{cik}.json",
        }

    def add_institution(self, cik_input: str, name_cn: str = "") -> dict:
        verification = self.verify_cik(cik_input)
        existing = self.repo.institution_by_cik(verification["cik"])
        if existing:
            raise ApplicationError(
                f"CIK {verification['cik']} is already saved as {existing['name']}."
            )
        now = utc_now()
        record = {
            "institution_id": f"custom_{verification['cik']}",
            "name": verification["name"],
            "name_cn": name_cn.strip() or verification["name"],
            "cik": verification["cik"],
            "verified_source": verification["verified_source"],
            "updated_at": now,
            "enabled": True,
            "user_added": True,
            "verified_at": now,
        }
        self.repo.save_verified_institution(record)
        return {**verification, **record}

    def update_preferences(
        self, institution_id: str, name_cn: str, enabled: bool
    ) -> None:
        self.repo.update_institution_preferences(
            institution_id, name_cn, enabled
        )

    def health(self) -> HealthStatus:
        labels = {
            "mock": "Mock mode: no SEC network requests",
            "offline": "Offline mode: cached DuckDB/SEC files only",
            "online": "Online mode configured; no completed SEC sync is recorded",
        }
        activity = self.repo.latest_sec_activity()
        if activity:
            outcome = "SUCCESS" if activity["success"] else "FAILED"
            stamp = activity["completed_at"].strftime("%Y-%m-%d %H:%M:%S")
            institution = activity["institution_name"] or "Unknown institution"
            detail = (
                f"Last sync {outcome}: {stamp}; {institution}; "
                f"report {activity['report_period'] or 'N/A'}; "
                f"{activity['message']}"
            )
            ok = bool(activity["success"])
            return HealthStatus(
                "SEC 13F", ok, detail, utc_now(),
                state="healthy" if ok else "unavailable",
            )
        return HealthStatus(
            "SEC 13F", True, labels[self.settings.sec_mode], utc_now(),
            state="healthy",
        )

    @staticmethod
    def _recent_filings(submissions: dict) -> list[dict]:
        recent = submissions.get("filings", {}).get("recent", {})
        keys = (
            "accessionNumber", "form", "filingDate", "reportDate",
            "primaryDocument",
        )
        count = len(recent.get("accessionNumber", []))
        rows = []
        for index in range(count):
            row = {key: recent.get(key, [""] * count)[index] for key in keys}
            if row["form"] in {"13F-HR", "13F-HR/A"}:
                rows.append(row)
        return rows

    def load_mock(self, institution_id: str) -> date:
        institution = self._institution(institution_id)
        report_period = date(2025, 12, 31)
        accession = f"MOCK-{institution_id}-2025Q4"
        holdings = parse_information_table(
            MOCK_INFORMATION_TABLE, date(2026, 2, 14)
        )
        now = utc_now()
        filing = {
            "accession_number": accession,
            "institution_id": institution_id,
            "cik": institution["cik"],
            "form_type": "13F-HR",
            "filing_date": date(2026, 2, 14),
            "report_period": report_period,
            "primary_document": "mock-primary.xml",
            "information_table_url": "mock://information-table.xml",
            "is_amendment": False,
            "source_url": "mock://sec-edgar",
            "retrieved_at": now,
            "content_hash": hashlib.sha256(
                MOCK_INFORMATION_TABLE.encode()
            ).hexdigest(),
            "source": "SEC MOCK — illustrative, not an actual filing",
        }
        self.repo.save_sec_filing(filing, holdings)
        previous = holdings.copy()
        previous.loc[
            previous["issuer_name"] == "APPLE INC", ["value_usd", "raw_value", "shares"]
        ] *= 0.8
        previous.loc[
            previous["issuer_name"] == "BANK OF AMERICA CORP",
            ["value_usd", "raw_value", "shares"],
        ] *= 1.2
        previous = previous[previous["issuer_name"] != "CHEVRON CORP NEW"].copy()
        previous_total = previous["value_usd"].sum()
        previous["portfolio_weight"] = previous["value_usd"] / previous_total
        prior_period = date(2025, 9, 30)
        prior_filing = {
            **filing,
            "accession_number": f"MOCK-{institution_id}-2025Q3",
            "filing_date": date(2025, 11, 14),
            "report_period": prior_period,
        }
        self.repo.save_sec_filing(prior_filing, previous)
        return report_period

    def sync_latest(self, institution_id: str) -> date:
        periods = self.sync_recent(institution_id, quarter_count=1)
        return periods[0]

    def sync_recent(self, institution_id: str, quarter_count: int = 4) -> list[date]:
        if self.settings.sec_mode != "online":
            raise ApplicationError("SEC sync is available only in online mode.")
        institution = self._institution(institution_id)
        started = utc_now()
        run_id = str(uuid.uuid4())
        saved_periods: list[date] = []
        failures: list[str] = []
        try:
            submissions = self.client.submissions(institution["cik"])
            filings = self._recent_filings(submissions)
            if not filings:
                raise ApplicationError("No recent 13F-HR filing was found.")
            selected: list[dict] = []
            seen_periods: set[str] = set()
            for row in filings:
                period = row["reportDate"]
                if not period or period in seen_periods:
                    continue
                selected.append(row)
                seen_periods.add(period)
                if len(selected) >= quarter_count:
                    break
            for row in selected:
                try:
                    saved_periods.append(
                        self._sync_filing(institution_id, institution, row)
                    )
                except Exception as exc:
                    failures.append(
                        f"{row.get('reportDate') or 'unknown period'} "
                        f"{row.get('accessionNumber') or 'unknown accession'}: "
                        f"{type(exc).__name__}: {exc}"
                    )
            if not saved_periods:
                detail = "; ".join(failures[:3])
                raise ApplicationError(
                    "No usable 13F report periods were found. " + detail
                )
            message = f"Saved {len(saved_periods)} report quarter(s)"
            if failures:
                message += (
                    f"; skipped {len(failures)} failed quarter(s): "
                    + "; ".join(failures[:2])
                )
            self.repo.save_sec_sync_run(
                {
                    "run_id": run_id,
                    "institution_id": institution_id,
                    "started_at": started,
                    "completed_at": utc_now(),
                    "success": True,
                    "message": message,
                    "report_period": saved_periods[0],
                    "filings_saved": len(saved_periods),
                }
            )
            return saved_periods
        except Exception as exc:
            self.repo.save_sec_sync_run(
                {
                    "run_id": run_id,
                    "institution_id": institution_id,
                    "started_at": started,
                    "completed_at": utc_now(),
                    "success": False,
                    "message": f"{type(exc).__name__}: {exc}",
                    "report_period": None,
                    "filings_saved": 0,
                }
            )
            raise

    def _sync_filing(
        self, institution_id: str, institution: dict, row: dict
    ) -> date:
        accession = row["accessionNumber"]
        index = self.client.filing_index(institution["cik"], accession)
        candidates = self.client.information_table_names(
            index, row["primaryDocument"]
        )
        filing_date = date.fromisoformat(row["filingDate"])
        report_period = date.fromisoformat(row["reportDate"])
        candidate_errors: list[str] = []
        info_name = ""
        info_url = ""
        xml = ""
        holdings = pd.DataFrame()
        for candidate in candidates:
            candidate_url = self.client.archive_url(
                institution["cik"], accession, candidate
            )
            try:
                candidate_xml = self.client.get_text(candidate_url)
                candidate_holdings = parse_information_table(
                    candidate_xml, filing_date
                )
            except Exception as exc:
                candidate_errors.append(
                    f"{candidate}: {type(exc).__name__}: {exc}"
                )
                continue
            info_name = candidate
            info_url = candidate_url
            xml = candidate_xml
            holdings = candidate_holdings
            break
        if holdings.empty:
            raise ApplicationError(
                f"No usable 13F Information Table for report {report_period}, "
                f"accession {accession}. Candidates tried: "
                + "; ".join(candidate_errors[:5])
            )
        now = utc_now()
        compact = accession.replace("-", "")
        source_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(institution['cik'])}/"
            f"{compact}/{row['primaryDocument']}"
        )
        filing = {
            "accession_number": accession,
            "institution_id": institution_id,
            "cik": institution["cik"],
            "form_type": row["form"],
            "filing_date": filing_date,
            "report_period": report_period,
            "primary_document": row["primaryDocument"],
            "information_table_url": info_url,
            "is_amendment": row["form"].endswith("/A"),
            "source_url": source_url,
            "retrieved_at": now,
            "content_hash": hashlib.sha256(xml.encode()).hexdigest(),
            "source": "SEC EDGAR",
        }
        self.repo.save_sec_filing(filing, holdings)
        return report_period

    def periods(self, institution_id: str) -> list:
        return self.repo.sec_periods(institution_id)

    def holdings(self, institution_id: str, report_period) -> pd.DataFrame:
        return self.repo.institution_holdings(institution_id, report_period)

    def aggregated_holdings(
        self, institution_id: str, report_period
    ) -> pd.DataFrame:
        return aggregate_holdings(self.holdings(institution_id, report_period))

    def changes(
        self, institution_id: str, current_period, previous_period
    ) -> pd.DataFrame:
        return compare_holdings(
            self.holdings(institution_id, current_period),
            self.holdings(institution_id, previous_period),
        )

    def save_table_preference(
        self, table_key: str, visible_columns: list[str], column_order: list[str]
    ) -> None:
        self.repo.save_table_preference(
            table_key, visible_columns, column_order
        )

    def table_preference(self, table_key: str) -> dict | None:
        return self.repo.table_preference(table_key)

    def reverse_lookup(self, query: str) -> pd.DataFrame:
        value = query.strip()
        if len(value) < 2:
            raise ApplicationError(
                "Enter at least two characters of an issuer name or CUSIP."
            )
        return self.repo.reverse_security_lookup(value)

    def _institution(self, institution_id: str) -> dict:
        rows = self.institutions(active_only=False)
        match = rows[rows["institution_id"] == institution_id]
        if match.empty:
            raise ApplicationError("Unknown institution.")
        return match.iloc[0].to_dict()
