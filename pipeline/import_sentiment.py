#!/usr/bin/env python3
"""
Merge an existing sentiment_summary.json (from the original analyze_mda_sentiment.py
scripts) into data/<TICKER>.json, so you don't have to re-score filings you already did.

    python pipeline/import_sentiment.py MSFT reports/sentiment_summary.json
    python pipeline/import_sentiment.py AAPL apple_reports/sentiment_summary.json
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from add_company import rebuild_index  # noqa: E402

FIELDS = {
    "lm_polarity": "lm_polarity",
    "vader_avg_compound": "vader",
    "pct_positive_sentences": "pos_sentences",
    "pct_negative_sentences": "neg_sentences",
    "uncertainty_pct": "uncertainty_pct",
    "litigious_pct": "litigious_pct",
    "lm_positive_count": "lm_pos_words",
    "lm_negative_count": "lm_neg_words",
    "total_words": "mda_words",
}


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    ticker, src = sys.argv[1].upper(), Path(sys.argv[2])
    target = ROOT / "data" / f"{ticker}.json"
    company = json.loads(target.read_text(encoding="utf-8"))
    rows = {int(re.search(r"\d{4}", str(r["fiscal_year"])).group()): r
            for r in json.loads(src.read_text(encoding="utf-8"))}
    merged = 0
    for rec in company["years"]:
        row = rows.get(rec["fy"])
        if row:
            for old, new in FIELDS.items():
                rec[new] = row.get(old)
            merged += 1
    target.write_text(json.dumps(company, indent=1), encoding="utf-8")
    print(f"Merged sentiment for {merged} of {len(company['years'])} years into {target.name}")
    rebuild_index()


if __name__ == "__main__":
    main()
