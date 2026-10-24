// Run:  node tests/test_mda.js
const fs = require("fs"), path = require("path"), { execFileSync } = require("child_process");
const M = require("../js/mda.js");
let failures = 0; const fail = m => { failures++; console.log("FAIL", m); };

// 1. word lists identical to the Python pipeline's
const py = JSON.parse(execFileSync("python3", ["-c",
  "import sys,json; sys.path.insert(0,'pipeline'); import add_company as a; print(json.dumps({'u':sorted(a.UNCERTAINTY_WORDS),'l':sorted(a.LITIGIOUS_WORDS)}))"],
  { cwd: path.join(__dirname, ".."), encoding: "utf8" }));
if (JSON.stringify([...M.UNCERTAINTY].sort()) !== JSON.stringify(py.u)) fail("uncertainty word list differs from add_company.py");
if (JSON.stringify([...M.LITIGIOUS].sort()) !== JSON.stringify(py.l)) fail("litigious word list differs from add_company.py");

// 2. extraction: skips the table of contents and stops before Item 7A; hidden and style content is ignored
const html = fs.readFileSync(path.join(__dirname, "fixtures", "sample_10k.htm"), "utf8");
const text = M.extractMda(html);
if (!/^Item 7\. Management’s Discussion/.test(text)) fail("did not start at the Item 7 heading: " + text.slice(0, 60));
if (/Quantitative|Item 7A/.test(text)) fail("ran past Item 7");
if (/hidden words/.test(text)) fail("hidden XBRL text leaked in");
const w = M.wordShares(text);
if (!(w.mda_words > 20 && w.uncertainty_pct > 0 && w.litigious_pct > 0)) fail("word shares look wrong " + JSON.stringify(w));
let threw = false; try { M.extractMda("<p>No such section</p>"); } catch (e) { threw = true; }
if (!threw) fail("a filing without Item 7 should throw");
console.log("mda:", JSON.stringify(w));
console.log(failures ? failures + " FAILURES" : "ALL MDA TESTS PASSED");
process.exit(failures ? 1 : 0);
