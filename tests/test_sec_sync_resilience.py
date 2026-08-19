from datetime import date
from types import SimpleNamespace

from app.clients.sec import SECClient
from app.errors import ApplicationError
from app.mock_sec import MOCK_INFORMATION_TABLE
from app.services.institutions import InstitutionService


COVER_XML = """<?xml version="1.0"?><edgarSubmission><formData/></edgarSubmission>"""


class CaptureRepo:
    def __init__(self):
        self.filings = []
        self.runs = []

    def save_sec_filing(self, filing, holdings):
        self.filings.append((filing, holdings))

    def save_sec_sync_run(self, run):
        self.runs.append(run)


class CandidateClient:
    def filing_index(self, cik, accession):
        return {
            "directory": {"item": [
                {"name": "primary_doc.xml", "size": "4000"},
                {"name": "InfoMetadata.xml", "size": "100"},
                {"name": "SubmissionFile.xml", "size": "7000000"},
            ]}
        }

    information_table_names = staticmethod(SECClient.information_table_names)
    archive_url = staticmethod(SECClient.archive_url)

    def get_text(self, url):
        return MOCK_INFORMATION_TABLE if url.endswith("SubmissionFile.xml") else COVER_XML


def test_sync_filing_validates_candidates_until_holdings_are_found():
    service = object.__new__(InstitutionService)
    service.client = CandidateClient()
    service.repo = CaptureRepo()
    period = service._sync_filing(
        "goldman", {"cik": "0000886982"},
        {
            "accessionNumber": "0000886982-26-000093",
            "primaryDocument": "xslForm13F_X02/primary_doc.xml",
            "filingDate": "2026-03-25", "reportDate": "2025-12-31",
            "form": "13F-HR/A",
        },
    )
    filing, holdings = service.repo.filings[0]
    assert period == date(2025, 12, 31)
    assert filing["information_table_url"].endswith("SubmissionFile.xml")
    assert not holdings.empty


def test_recent_sync_continues_after_one_quarter_fails():
    service = object.__new__(InstitutionService)
    service.settings = SimpleNamespace(sec_mode="online")
    service.repo = CaptureRepo()
    service._institution = lambda institution_id: {"cik": "0000000001"}
    service.client = SimpleNamespace(submissions=lambda cik: {
        "filings": {"recent": {
            "accessionNumber": ["bad", "good"],
            "form": ["13F-HR", "13F-HR"],
            "filingDate": ["2026-08-14", "2026-05-15"],
            "reportDate": ["2026-06-30", "2026-03-31"],
            "primaryDocument": ["primary_doc.xml", "primary_doc.xml"],
        }}
    })

    def sync_one(institution_id, institution, row):
        if row["accessionNumber"] == "bad":
            raise ApplicationError("bad attachment")
        return date.fromisoformat(row["reportDate"])

    service._sync_filing = sync_one
    periods = service.sync_recent("test", quarter_count=2)
    assert periods == [date(2026, 3, 31)]
    run = service.repo.runs[-1]
    assert run["success"] is True
    assert run["filings_saved"] == 1
    assert "skipped 1 failed quarter" in run["message"]
