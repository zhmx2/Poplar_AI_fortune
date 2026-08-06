from app.db import Repository
from app.models import Quote, utc_now


def test_quote_round_trip(tmp_path):
    repo = Repository(tmp_path / "test.duckdb")
    quote = Quote("NVDA", 100.0, 100.2, 100.1, 99.0, "USD", "delayed", "ibkr", utc_now())
    repo.save_quote(quote)
    frame = repo.recent_quotes()
    assert len(frame) == 1
    assert frame.iloc[0]["symbol"] == "NVDA"
    assert frame.iloc[0]["observed_at"].tzinfo is not None
