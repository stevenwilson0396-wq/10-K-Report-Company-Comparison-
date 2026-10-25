// Run:  node tests/test_metrics.js
// 1. The browser code gives the same records as the Python pipeline on synthetic bank, REIT and loss-making companies.
// 2. The bundled data files pass the sanity checks.
const fs = require("fs"), path = require("path");
const M = require("../js/sec-metrics.js"), C = require("../js/checks.js");
let failures = 0;
const fail = (m) => { failures++; console.log("FAIL", m); };
const same = (a, b) => (a === null && b === null) || a === b ||
  (typeof a === "number" && typeof b === "number" && Math.abs(a - b) <= Math.max(1e-9, Math.abs(b) * 1e-9));

for (const name of ["bank", "reit", "loss_maker"]) {
  const facts = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", name + ".json")));
  const exp = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "expected_" + name + ".json")));
  const mine = M.makeCompany({ ticker: "T", name: "T", cik: "0", facts, years: 5 });
  if (mine.kind !== exp.kind) fail(name + " kind " + mine.kind + " vs " + exp.kind);
  if (mine.years.length !== exp.years.length) fail(name + " year count");
  let cmp = 0;
  mine.years.forEach((y, i) => { for (const k of Object.keys(exp.years[i])) { cmp++; if (!same(y[k], exp.years[i][k])) fail(`${name} FY${y.fy} ${k}: js ${y[k]} py ${exp.years[i][k]}`); } });
  if (JSON.stringify(mine.quarters) !== JSON.stringify(exp.quarters)) fail(name + " quarters differ");
  console.log(`${name}: kind=${mine.kind}, ${cmp} fields compared`);
}

// expectations that matter to a reader, not just parity
const bank = M.makeCompany({ ticker: "B", name: "B", cik: "0", facts: JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "bank.json"))), years: 5 });
if (bank.kind !== "bank" || !(bank.years.at(-1).efficiency_ratio > 0)) fail("bank metrics missing");
const loss = M.makeCompany({ ticker: "L", name: "L", cik: "0", facts: JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "loss_maker.json"))), years: 5 });
const l = loss.years.at(-1);
if (l.roe !== null || l.financial_leverage !== null || l.debt_to_equity !== null) fail("negative equity should blank ROE and leverage");
if (l.net_income_growth !== null || l.cash_conversion !== null || l.payout_ratio !== null) fail("ratios on negative bases should be blank");

// unknown split history (backup price source): prices and returns stay, market value and valuation go blank
const px = { "2023-12-29": 10, "2024-12-31": 12 };
const unk = M.makeCompany({ ticker: "U", name: "U", cik: "0", facts: JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "reit.json"))), prices: px, splits: null, years: 5 });
const u = unk.years.at(-1);
if (u.price !== 12 || u.market_cap !== null || u.pe_ratio !== null || u.annual_return === null) fail("splits=null should keep price and return but blank market value: " + JSON.stringify({ p: u.price, mc: u.market_cap, r: u.annual_return }));

const dataDir = path.join(__dirname, "..", "data");
for (const f of fs.readdirSync(dataDir).filter(f => f.endsWith(".json"))) {
  const c = JSON.parse(fs.readFileSync(path.join(dataDir, f)));
  const warnings = C.checkRecords(c.years);
  console.log(`${f}: ${warnings.length} data warnings`, warnings.map(w => `FY${w.fy} ${w.message}`));
  if (warnings.length) fail(f + " has data warnings");
  if (!["operating", "bank", "reit"].includes(c.kind)) fail(f + " missing kind");
}
// the checker itself must catch obvious errors
const caught = C.checkRecords([{ fy: 2020, revenue: -1 }, { fy: 2023, revenue: 1, current_assets: 5, total_assets: 1 }]);
if (caught.length < 3) fail("checker missed planted errors: " + JSON.stringify(caught));
console.log(failures ? failures + " FAILURES" : "ALL TESTS PASSED");
process.exit(failures ? 1 : 0);
