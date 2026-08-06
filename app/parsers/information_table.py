from __future__ import annotations

from datetime import date
import xml.etree.ElementTree as ET

import pandas as pd

from app.analytics.security_classification import classify_security
from app.errors import ApplicationError


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((node for node in element if _local(node.tag) == name), None)


def _text(element: ET.Element | None, name: str, default: str = "") -> str:
    node = _child(element, name) if element is not None else None
    return (node.text or "").strip() if node is not None else default


def _number(value: str) -> float:
    try:
        return float(value.replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def value_scale_for_filing(filing_date: date) -> float:
    # Form 13F XML filed on/after 2023-01-03 reports value in dollars.
    return 1.0 if filing_date >= date(2023, 1, 3) else 1000.0


def parse_information_table(xml: str, filing_date: date) -> pd.DataFrame:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ApplicationError("The SEC Information Table XML is invalid.") from exc

    rows: list[dict] = []
    scale = value_scale_for_filing(filing_date)
    for item in root.iter():
        if _local(item.tag) != "infoTable":
            continue
        issuer = _text(item, "nameOfIssuer")
        title = _text(item, "titleOfClass")
        put_call = _text(item, "putCall").upper() or None
        shares_node = _child(item, "shrsOrPrnAmt")
        voting_node = _child(item, "votingAuthority")
        raw_value = _number(_text(item, "value"))
        security_type, method = classify_security(issuer, title, put_call)
        rows.append(
            {
                "issuer_name": issuer,
                "title_of_class": title,
                "cusip": _text(item, "cusip"),
                "figi": _text(item, "figi") or None,
                "security_type": security_type,
                "classification_method": method,
                "raw_value": raw_value,
                "value_scale": scale,
                "value_usd": raw_value * scale,
                "shares": _number(_text(shares_node, "sshPrnamt")),
                "share_type": _text(shares_node, "sshPrnamtType"),
                "put_call": put_call,
                "investment_discretion": _text(item, "investmentDiscretion"),
                "other_manager": _text(item, "otherManager") or None,
                "voting_sole": _number(_text(voting_node, "Sole")),
                "voting_shared": _number(_text(voting_node, "Shared")),
                "voting_none": _number(_text(voting_node, "None")),
            }
        )
    if not rows:
        raise ApplicationError("The filing contains no 13F holdings rows.")
    frame = pd.DataFrame(rows)
    total = frame["value_usd"].sum()
    frame["portfolio_weight"] = frame["value_usd"] / total if total else 0.0
    return frame
