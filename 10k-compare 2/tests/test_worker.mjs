// Run:  node tests/test_worker.mjs   (no network: fetch is replaced with a mock)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(here, "..", "worker", "sec-proxy.js"), "utf8");
const worker = (await import("data:text/javascript;base64," + Buffer.from(src).toString("base64"))).default;

let failures = 0;
const check = (name, ok, extra = "") => { if (!ok) { failures++; console.log("FAIL", name, extra); } else console.log("ok  ", name); };

const calls = [];
let yahooDown = false;
globalThis.fetch = async (url, opts = {}) => {
  calls.push({ url, ua: (opts.headers || {})["User-Agent"] });
  if (url.includes("CIK0000000404")) return new Response("nope", { status: 404 });
  if (url.includes("finance.yahoo.com") && (yahooDown || url.includes("BAD"))) return new Response("x", { status: 429 });
  if (url.includes("stooq.com")) {
    if (url.includes("zzz")) return new Response("No data", { status: 200 });
    return new Response("Date,Open,High,Low,Close,Volume\n2024-01-02,10,11,9,10.5,1000\n2024-01-03,10,11,9,10.75,1000\n", { status: 200 });
  }
  if (url.includes("/Archives/edgar/")) return new Response("<html>10-K</html>", { status: 200, headers: { "content-type": "text/html" } });
  return new Response(JSON.stringify({ ok: true, url }), { status: 200, headers: { "content-type": "application/json" } });
};
const env = { SEC_USER_AGENT: "Jane Doe jane@example.com", ALLOWED_ORIGIN: "*" };
const get = (p, e = env, init = {}) => worker.fetch(new Request("https://proxy.example" + p, init), e);
const last = () => calls[calls.length - 1];

let r = await get("/facts/789019");
check("facts pads the CIK", r.status === 200 && last().url.endsWith("CIK0000789019.json") && last().ua.includes("@"));
r = await get("/submissions/320193");
check("submissions route", r.status === 200 && last().url === "https://data.sec.gov/submissions/CIK0000320193.json");
r = await get("/doc/320193/000032019325000079/aapl-20250927.htm");
check("doc route", r.status === 200 && last().url === "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm" && /text\/html/.test(r.headers.get("content-type")));
for (const bad of ["/doc/320193/0000320193250000/x.htm", "/doc/320193/000032019325000079/../../etc.htm", "/doc/320193/000032019325000079/x.exe", "/doc/320193/000032019325000079/a%2Fb.htm", "/doc/abc/000032019325000079/x.htm"])
  check("doc rejects " + bad, (await get(bad)).status === 404);
r = await get("/prices/brk.b");
check("prices maps BRK.B to BRK-B", last().url.includes("/BRK-B?"));
r = await get("/prices/%5EGSPC");
check("index symbol allowed", r.status === 200 && last().url.includes("%5EGSPC"));
r = await get("/prices/BAD");
const j = await r.json();
check("Yahoo refusal falls back to Stooq", r.status === 200 && j.source === "stooq" && j.chart.result[0].timestamp.length === 2 && j.chart.result[0].indicators.quote[0].close[1] === 10.75, JSON.stringify(j).slice(0, 120));
check("Stooq result carries no split list", Object.keys(j.chart.result[0].events).length === 0);
r = await get("/prices/ZZZ"); yahooDown = true; r = await get("/prices/ZZZ");
check("both sources failing is a clean 502", r.status === 502); yahooDown = false;
check("unknown route 404", (await get("/foo")).status === 404);
check("traversal in cik refused", (await get("/facts/12..34")).status === 404);
check("POST refused", (await get("/tickers", env, { method: "POST" })).status === 405);
check("missing user agent is a 500", (await get("/tickers", { ALLOWED_ORIGIN: "*" })).status === 500);
const locked = { ...env, ALLOWED_ORIGIN: "https://me.github.io" };
check("allowed origin gets CORS", (await get("/tickers", locked, { headers: { Origin: "https://me.github.io" } })).headers.get("access-control-allow-origin") === "https://me.github.io");
check("other origin blocked", (await get("/tickers", locked, { headers: { Origin: "https://evil.example" } })).status === 403);
console.log(failures ? failures + " FAILURES" : "ALL WORKER TESTS PASSED");
process.exit(failures ? 1 : 0);
