from datetime import date

from app.mock_sec import MOCK_INFORMATION_TABLE
from app.parsers.information_table import parse_information_table


def test_parser_classifies_and_weights_current_dollar_values():
    frame = parse_information_table(MOCK_INFORMATION_TABLE, date(2026, 2, 14))

    assert set(frame["security_type"]) == {"STOCK", "ETF", "OPTION"}
    assert frame["value_scale"].unique().tolist() == [1.0]
    assert abs(frame["portfolio_weight"].sum() - 1.0) < 1e-9
    assert frame.iloc[0]["value_usd"] == 5_400_000_000


def test_pre_2023_filing_values_are_thousands():
    xml = MOCK_INFORMATION_TABLE.replace(
        "<value>5400000000</value>", "<value>5400</value>", 1
    )
    frame = parse_information_table(xml, date(2022, 11, 14))
    assert frame.iloc[0]["value_scale"] == 1000.0
    assert frame.iloc[0]["value_usd"] == 5_400_000
