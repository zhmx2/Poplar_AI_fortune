from streamlit.testing.v1 import AppTest


def test_app_starts_with_openbb_frozen():
    app = AppTest.from_file("app.py", default_timeout=20)
    app.run()

    assert not app.exception
    assert [title.value for title in app.title] == ["Local investment research"]
    assert "OpenBB archive" in [tab.label for tab in app.tabs]
    assert "Macro & financials" in [tab.label for tab in app.tabs]
    assert any("OpenBB is frozen" in item.value for item in app.info)
