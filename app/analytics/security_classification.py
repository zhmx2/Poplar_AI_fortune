from __future__ import annotations


ETF_TOKENS = (
    " ETF",
    "ETF ",
    "SPDR",
    "ISHARES",
    "INVESCO QQQ",
    "VANGUARD INDEX",
    "SELECT SECTOR",
    "TRUST UNIT",
)


def classify_security(
    issuer_name: str, title_of_class: str, put_call: str | None
) -> tuple[str, str]:
    if put_call:
        return "OPTION", "13F putCall field"
    combined = f"{issuer_name} {title_of_class}".upper()
    if any(token in combined for token in ETF_TOKENS):
        return "ETF", "maintained name heuristic"
    return "STOCK", "default 13F equity classification"
