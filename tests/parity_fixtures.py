#!/usr/bin/env python3
"""Writes Python-computed records for the synthetic fixtures to tests/fixtures/expected_<name>.json,
so tests/test_metrics.js can check the browser code gives identical results."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
import add_company as a  # noqa: E402
for name in ("bank", "reit", "loss_maker"):
    f = json.loads((HERE / "fixtures" / f"{name}.json").read_text())
    g = f["facts"]["us-gaap"]
    recs = a.build_records(f, 5, None, ())
    out = {"kind": a.classify(recs, g), "years": recs, "quarters": a.build_quarters(g)}
    (HERE / "fixtures" / f"expected_{name}.json").write_text(json.dumps(out, indent=1))
    print("wrote expected", name, out["kind"])
