from __future__ import annotations

from datetime import datetime

import pandas as pd


METRIC_TAGS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex_cash": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForProceedsFromProductiveAssets",
    ),
}


def _annual_facts(company_facts: dict, tags: tuple[str, ...]) -> list[dict]:
    concepts = company_facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        concept = concepts.get(tag)
        if not concept:
            continue
        units = concept.get("units", {}).get("USD", [])
        annual = [
            item for item in units
            if item.get("form") in {"10-K", "10-K/A"}
            and item.get("start") and item.get("end")
            and (pd.Timestamp(item["end"]) - pd.Timestamp(item["start"])).days >= 250
        ]
        if annual:
            for item in annual:
                item = item.copy()
                item["xbrl_tag"] = tag
                yield item
            return


def parse_company_financials(
    company_facts: dict, symbol: str, cik: str, retrieved_at: datetime
) -> pd.DataFrame:
    rows: list[dict] = []
    name = company_facts.get("entityName", symbol)
    for metric, tags in METRIC_TAGS.items():
        candidates = list(_annual_facts(company_facts, tags))
        by_end: dict[str, dict] = {}
        for fact in candidates:
            end = fact["end"]
            current = by_end.get(end)
            if current is None or str(fact.get("filed", "")) > str(current.get("filed", "")):
                by_end[end] = fact
        for end, fact in by_end.items():
            accession = fact.get("accn", "")
            rows.append({
                "symbol": symbol.upper(), "cik": cik.zfill(10),
                "company_name": name, "fiscal_year": pd.Timestamp(end).year,
                "period_end": pd.Timestamp(end).date(), "metric": metric,
                "value": float(fact["val"]), "unit": "USD",
                "xbrl_tag": fact["xbrl_tag"], "form_type": fact.get("form"),
                "filed_date": pd.Timestamp(fact["filed"]).date(),
                "accession_number": accession,
                "source_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                    f"{accession.replace('-', '')}/" if accession else ""
                ),
                "source": "SEC Company Facts", "retrieved_at": retrieved_at,
            })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    pivot = frame.pivot_table(
        index=["symbol", "period_end"], columns="metric", values="value", aggfunc="first"
    )
    if {"operating_cash_flow", "capex_cash"} <= set(pivot.columns):
        fcf = (pivot["operating_cash_flow"] - pivot["capex_cash"]).dropna()
    else:
        fcf = pd.Series(dtype=float)
    derived = []
    for (sym, period_end), value in fcf.items():
        template = frame.loc[(frame["symbol"] == sym) & (frame["period_end"] == period_end)].iloc[0].to_dict()
        template.update({
            "metric": "free_cash_flow", "value": float(value),
            "xbrl_tag": "DERIVED: operating_cash_flow - capex_cash",
        })
        derived.append(template)
    if derived:
        frame = pd.concat([frame, pd.DataFrame(derived)], ignore_index=True)
    return frame.sort_values(["period_end", "metric"]).reset_index(drop=True)
