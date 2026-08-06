import pandas as pd

from app.analytics.holdings_changes import aggregate_holdings, compare_holdings


def _frame(rows):
    frame = pd.DataFrame(rows)
    frame["title_of_class"] = "COM"
    frame["security_type"] = "STOCK"
    frame["put_call"] = None
    total = frame["value_usd"].sum()
    frame["portfolio_weight"] = frame["value_usd"] / total
    return frame


def test_quarterly_change_status_and_rates():
    current = _frame(
        [
            {"cusip": "AAA", "issuer_name": "Alpha", "shares": 120, "value_usd": 1200},
            {"cusip": "BBB", "issuer_name": "Beta", "shares": 50, "value_usd": 500},
        ]
    )
    previous = _frame(
        [
            {"cusip": "AAA", "issuer_name": "Alpha", "shares": 100, "value_usd": 900},
            {"cusip": "CCC", "issuer_name": "Closed", "shares": 40, "value_usd": 400},
        ]
    )

    changes = compare_holdings(current, previous).set_index("cusip")
    assert changes.loc["AAA", "status"] == "INCREASED"
    assert changes.loc["AAA", "change_rate"] == 0.2
    assert changes.loc["BBB", "status"] == "NEW"
    assert pd.isna(changes.loc["BBB", "change_rate"])
    assert changes.loc["CCC", "status"] == "CLOSED"
    assert changes.loc["CCC", "change_rate"] == -1.0


def test_stock_and_option_with_same_cusip_are_not_merged():
    current = _frame(
        [{"cusip": "AAA", "issuer_name": "Alpha", "shares": 10, "value_usd": 100}]
    )
    option = current.copy()
    option["put_call"] = "PUT"
    option["security_type"] = "OPTION"
    combined = pd.concat([current, option], ignore_index=True)

    changes = compare_holdings(combined, combined)
    assert len(changes) == 2


def test_other_manager_rows_combine_but_put_and_call_remain_separate():
    rows = pd.DataFrame(
        [
            {
                "issuer_name": "APPLE INC", "title_of_class": "COM",
                "cusip": "037833100", "put_call": "CALL",
                "security_type": "OPTION", "other_manager": "1",
                "shares": 8_727_100, "value_usd": 2_214_850_709,
                "portfolio_weight": 0.002543,
            },
            {
                "issuer_name": "APPLE INC", "title_of_class": "COM",
                "cusip": "037833100", "put_call": "CALL",
                "security_type": "OPTION", "other_manager": "3",
                "shares": 163_100, "value_usd": 41_393_149,
                "portfolio_weight": 0.000048,
            },
            {
                "issuer_name": "APPLE INC", "title_of_class": "COM",
                "cusip": "037833100", "put_call": "PUT",
                "security_type": "OPTION", "other_manager": "1",
                "shares": 7_108_200, "value_usd": 1_803_990_078,
                "portfolio_weight": 0.002071,
            },
        ]
    )

    result = aggregate_holdings(rows).set_index("put_call")
    assert len(result) == 2
    assert result.loc["CALL", "manager_row_count"] == 2
    assert result.loc["CALL", "other_managers"] == "1, 3"
    assert result.loc["CALL", "shares"] == 8_890_200
    assert result.loc["CALL", "value_usd"] == 2_256_243_858
    assert result.loc["PUT", "manager_row_count"] == 1
