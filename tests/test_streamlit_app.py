from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_FILE = Path(__file__).resolve().parents[1] / "app.py"


def test_app_starts_with_openbb_frozen():
    app = AppTest.from_file(APP_FILE, default_timeout=20)
    app.run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Local investment research"]
    assert "OpenBB archive" in [tab.label for tab in app.tabs]
    assert "Macro & financials" in [tab.label for tab in app.tabs]
    assert "Market liquidity" in [tab.label for tab in app.tabs]
    assert "Stock turnover" in [tab.label for tab in app.tabs]
    assert any("OpenBB is frozen" in item.value for item in app.info)


def test_stock_turnover_page_uses_requested_display_units():
    source = APP_FILE.with_name("app").joinpath("ui", "stock_turnover.py").read_text(
        encoding="utf-8"
    )
    assert "estimated_share_volume\"] / 1_000" in source
    assert "estimated_turnover_usd\"] / 1_000_000" in source
    assert "估算成交量（千股）" in source
    assert "估算成交金额（百万美元）" in source
    assert 'format="$%,.2f"' in source
    assert 'format="%,.2f"' in source
