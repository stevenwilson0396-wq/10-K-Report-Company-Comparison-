#!/usr/bin/env python3
"""Run:  python tests/test_pipeline.py   (no network)"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
import add_company as a  # noqa: E402


def fixture(name):
    return json.loads((HERE / "fixtures" / f"{name}.json").read_text())


class Pipeline(unittest.TestCase):
    def test_bank_is_classified_and_has_bank_metrics(self):
        f = fixture("bank")
        recs = a.build_records(f, 5)
        self.assertEqual(a.classify(recs, f["facts"]["us-gaap"]), "bank")
        r = recs[-1]
        self.assertEqual(r["revenue"], 14.8)                  # net interest income + noninterest income
        self.assertAlmostEqual(r["efficiency_ratio"], 55.41, 2)
        self.assertAlmostEqual(r["loan_to_deposit"], 69.47, 2)

    def test_reit_is_classified_and_ffo(self):
        f = fixture("reit")
        recs = a.build_records(f, 5)
        self.assertEqual(a.classify(recs, f["facts"]["us-gaap"]), "reit")
        self.assertAlmostEqual(recs[-1]["ffo"], 0.57, 2)      # 0.28 net income + 0.34 D&A - 0.05 gain

    def test_negative_bases_give_blanks(self):
        r = a.build_records(fixture("loss_maker"), 5)[-1]
        for k in ("roe", "financial_leverage", "debt_to_equity", "net_income_growth", "cash_conversion", "payout_ratio", "tax_burden"):
            self.assertIsNone(r[k], k)
        self.assertEqual(r["free_cash_flow"], -0.3)

    def test_growth_needs_a_positive_base(self):
        self.assertIsNone(a.growth(5, -1))
        self.assertIsNone(a.growth(5, 0))
        self.assertEqual(a.growth(110, 100), 10.0)

    def test_fourth_quarter_is_the_year_minus_three_quarters(self):
        g = fixture("bank")["facts"]["us-gaap"]
        q = {(r["fy"], r["q"]): r for r in a.build_quarters(g)}
        self.assertAlmostEqual(q[(2024, 4)]["net_income"], 3.2 - (0.6 + 0.7 + 0.65), 3)

    def test_unknown_splits_blank_market_value(self):
        f = fixture("reit")
        recs = a.build_records(f, 5, {"2024-12-31": 12.0, "2023-12-29": 10.0}, None)
        self.assertEqual(recs[-1]["price"], 12.0)
        self.assertIsNone(recs[-1]["market_cap"])

    def test_yahoo_payload(self):
        payload = {"chart": {"result": [{"timestamp": [1704205800, 1704292200], "indicators": {"quote": [{"close": [10.123456, None]}]},
                                         "events": {"splits": {"1": {"date": 1704205800, "numerator": 4, "denominator": 1}}}}]}}
        prices, splits = a.parse_yahoo_chart(payload)
        self.assertEqual(prices, {"2024-01-02": 10.1235})
        self.assertEqual(splits, [("2024-01-02", 4.0)])

    def test_benchmark_is_bundled_but_not_listed_as_a_company(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = a.DATA
            a.DATA = Path(tmp)
            try:
                (a.DATA / "XYZ.json").write_text(json.dumps({"ticker": "XYZ", "name": "X", "years": []}))
                (a.DATA / "benchmark.json").write_text(json.dumps({"symbol": "^GSPC", "prices": {"2024-01-02": 4742.83}}))
                a.rebuild_index()
                js = (a.DATA / "companies.js").read_text()
            finally:
                a.DATA = old
        self.assertIn("window.COMPANIES = [", js)
        self.assertEqual(js.count('"ticker"'), 1)
        self.assertIn("window.BENCHMARK = ", js)
        self.assertIn("4742.83", js)


if __name__ == "__main__":
    unittest.main(verbosity=1)
