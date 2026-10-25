#!/usr/bin/env python3
"""Builds small synthetic SEC 'company facts' files (a bank, a REIT and a loss-making company).

They are invented numbers in the same shape as the SEC's data, used to check that the Python
pipeline and the in-browser code agree and that bank and REIT metrics are picked up.
Run:  python tests/make_fixtures.py
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "fixtures"
B = 1_000_000_000


def flow(entries, concept, by_year, unit="USD"):
    for fy, val in by_year.items():
        entries.setdefault(concept, {"units": {}})["units"].setdefault(unit, []).append(
            {"start": f"{fy}-01-01", "end": f"{fy}-12-31", "val": val, "fy": fy, "fp": "FY", "form": "10-K",
             "filed": f"{fy + 1}-02-20", "accn": f"0001234567-{fy % 100 + 1:02d}-000001"})


def instant(entries, concept, by_year, unit="USD"):
    for fy, val in by_year.items():
        entries.setdefault(concept, {"units": {}})["units"].setdefault(unit, []).append(
            {"end": f"{fy}-12-31", "val": val, "fy": fy, "fp": "FY", "form": "10-K",
             "filed": f"{fy + 1}-02-20", "accn": f"0001234567-{fy % 100 + 1:02d}-000001"})


def quarters(entries, concept, by_year_q):
    """by_year_q: {fy: [q1, q2, q3]} three-month figures from 10-Q filings."""
    ends = ["03-31", "06-30", "09-30"]
    starts = ["01-01", "04-01", "07-01"]
    for fy, vals in by_year_q.items():
        for i, v in enumerate(vals):
            entries.setdefault(concept, {"units": {}})["units"].setdefault("USD", []).append(
                {"start": f"{fy}-{starts[i]}", "end": f"{fy}-{ends[i]}", "val": v, "fy": fy, "fp": f"Q{i + 1}",
                 "form": "10-Q", "filed": f"{fy}-{ends[i][:2]}-28", "accn": "0001234567-00-000002"})


YEARS = [2020, 2021, 2022, 2023, 2024]


def bank():
    g = {}
    flow(g, "NetIncomeLoss", {y: (2 + i * 0.3) * B for i, y in enumerate(YEARS)})
    flow(g, "InterestIncomeExpenseNet", {y: (8 + i * 0.5) * B for i, y in enumerate(YEARS)})
    flow(g, "NoninterestIncome", {y: (4 + i * 0.2) * B for i, y in enumerate(YEARS)})
    flow(g, "NoninterestExpense", {y: (7 + i * 0.3) * B for i, y in enumerate(YEARS)})
    instant(g, "Deposits", {y: (150 + i * 10) * B for i, y in enumerate(YEARS)})
    instant(g, "LoansAndLeasesReceivableNetReportedAmount", {y: (100 + i * 8) * B for i, y in enumerate(YEARS)})
    instant(g, "Assets", {y: (200 + i * 12) * B for i, y in enumerate(YEARS)})
    instant(g, "StockholdersEquity", {y: (20 + i) * B for i, y in enumerate(YEARS)})
    flow(g, "NetCashProvidedByUsedInOperatingActivities", {y: (3 + i * 0.1) * B for i, y in enumerate(YEARS)})
    quarters(g, "NetIncomeLoss", {2024: [0.6 * B, 0.7 * B, 0.65 * B]})
    return {"facts": {"us-gaap": g, "dei": {}}}


def reit():
    g = {}
    flow(g, "Revenues", {y: (1 + i * 0.1) * B for i, y in enumerate(YEARS)})
    flow(g, "NetIncomeLoss", {y: (0.2 + i * 0.02) * B for i, y in enumerate(YEARS)})
    flow(g, "DepreciationAndAmortization", {y: (0.3 + i * 0.01) * B for i, y in enumerate(YEARS)})
    flow(g, "GainLossOnSaleOfPropertiesNetOfApplicableIncomeTaxes", {y: 0.05 * B for y in YEARS})
    instant(g, "RealEstateInvestmentPropertyNet", {y: (8 + i) * B for i, y in enumerate(YEARS)})
    instant(g, "Assets", {y: (9 + i) * B for i, y in enumerate(YEARS)})
    instant(g, "StockholdersEquity", {y: (4 + i * 0.2) * B for i, y in enumerate(YEARS)})
    flow(g, "NetCashProvidedByUsedInOperatingActivities", {y: (0.5 + i * 0.02) * B for i, y in enumerate(YEARS)})
    flow(g, "PaymentsOfDividends", {y: 0.25 * B for y in YEARS})
    return {"facts": {"us-gaap": g, "dei": {}}}


def loss_maker():
    """Negative earnings and negative equity: ratios that need a positive base must come back blank."""
    g = {}
    flow(g, "Revenues", {y: (1 + i * 0.5) * B for i, y in enumerate(YEARS)})
    flow(g, "CostOfRevenue", {y: (0.8 + i * 0.4) * B for i, y in enumerate(YEARS)})
    flow(g, "OperatingIncomeLoss", {y: -0.3 * B for y in YEARS})
    flow(g, "NetIncomeLoss", {y: -0.4 * B for y in YEARS})
    flow(g, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", {y: -0.4 * B for y in YEARS})
    instant(g, "Assets", {y: 2 * B for y in YEARS})
    instant(g, "StockholdersEquity", {y: -0.5 * B for y in YEARS})
    flow(g, "NetCashProvidedByUsedInOperatingActivities", {y: -0.2 * B for y in YEARS})
    flow(g, "PaymentsToAcquirePropertyPlantAndEquipment", {y: 0.1 * B for y in YEARS})
    return {"facts": {"us-gaap": g, "dei": {}}}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in (("bank", bank), ("reit", reit), ("loss_maker", loss_maker)):
        (OUT / f"{name}.json").write_text(json.dumps(fn(), indent=1), encoding="utf-8")
        print("wrote", name)
