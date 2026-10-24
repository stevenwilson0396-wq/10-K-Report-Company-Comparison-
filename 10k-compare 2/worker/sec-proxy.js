/**
 * A tiny proxy that lets the comparison page read SEC EDGAR and Yahoo Finance.
 *
 * Why it exists: browsers refuse to read data.sec.gov directly because the SEC does not
 * allow cross-origin requests, and the SEC requires every request to identify who is
 * asking. This Worker makes those requests for the page, adds your contact details, and
 * returns the data with the headers browsers need. It only passes data through; the page
 * does all the calculating.
 *
 * Routes (GET only):
 *   /tickers                          every SEC-registered ticker, name and CIK
 *   /facts/<CIK>                      XBRL "company facts" for one company (CIK is digits)
 *   /submissions/<CIK>                a company's filing list (used to find its 10-K documents)
 *   /doc/<CIK>/<ACCESSION>/<FILE>     one 10-K document (an .htm file) from the SEC archive
 *   /prices/<SYMBOL>                  Yahoo Finance daily closes and splits for one ticker.
 *                                     If Yahoo refuses, Stooq closes are returned instead
 *                                     (marked "source": "stooq", with no split list).
 *
 * Settings (Cloudflare dashboard, or wrangler.toml / `wrangler secret put`):
 *   SEC_USER_AGENT  required. "Your Name you@example.com"
 *   ALLOWED_ORIGIN  optional. Your site, e.g. https://you.github.io (default: any site)
 */

const UPSTREAM = {
  tickers: () => "https://www.sec.gov/files/company_tickers.json",
  facts: (cik) => `https://data.sec.gov/api/xbrl/companyfacts/CIK${cik}.json`,
  submissions: (cik) => `https://data.sec.gov/submissions/CIK${cik}.json`,
  doc: (cik, acc, file) => `https://www.sec.gov/Archives/edgar/data/${cik}/${acc}/${file}`,
  prices: (sym) =>
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=1d&range=max&events=splits`,
};

const CACHE_SECONDS = { tickers: 86400, facts: 43200, submissions: 43200, doc: 604800, prices: 21600 };

// Stooq publishes free daily closes as CSV. It is only used when Yahoo refuses, and it does not
// list stock splits, so the page leaves market value and valuation ratios blank for those companies.
async function stooqAsYahoo(symbol) {
  const sym = symbol === "^GSPC" ? "^spx" : symbol.toLowerCase().replace(/-/g, ".") + ".us";
  const res = await fetch(`https://stooq.com/q/d/l/?s=${encodeURIComponent(sym)}&i=d`, { cf: { cacheTtl: 21600, cacheEverything: true } });
  if (!res.ok) return null;
  const lines = (await res.text()).trim().split(/\r?\n/);
  if (lines.length < 3 || !/^date,/i.test(lines[0])) return null;
  const timestamp = [], close = [];
  for (const line of lines.slice(1)) {
    const c = line.split(",");
    const t = Date.parse(c[0] + "T21:00:00Z") / 1000, v = parseFloat(c[4]);
    if (Number.isFinite(t) && Number.isFinite(v)) { timestamp.push(t); close.push(v); }
  }
  if (!timestamp.length) return null;
  return { source: "stooq", chart: { result: [{ timestamp, indicators: { quote: [{ close }] }, events: {} }] } };
}

function corsHeaders(env, request) {
  const allowed = (env.ALLOWED_ORIGIN || "*").trim();
  const origin = request.headers.get("Origin");
  const h = {
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
  if (allowed === "*") h["Access-Control-Allow-Origin"] = "*";
  else if (origin && origin === allowed) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

function fail(status, message, cors) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { "Content-Type": "application/json", ...cors },
  });
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(env, request);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (request.method !== "GET") return fail(405, "Only GET is supported.", cors);

    // When ALLOWED_ORIGIN is set, other websites get nothing (and cost you no quota).
    const allowed = (env.ALLOWED_ORIGIN || "*").trim();
    const origin = request.headers.get("Origin");
    if (allowed !== "*" && origin && origin !== allowed) return fail(403, "This proxy is not available to that site.", cors);

    const userAgent = (env.SEC_USER_AGENT || "").trim();
    if (!userAgent.includes("@"))
      return fail(500, "The proxy needs SEC_USER_AGENT set to 'Your Name you@example.com'.", cors);

    const parts = new URL(request.url).pathname.split("/").filter(Boolean).map(p => { try { return decodeURIComponent(p); } catch (e) { return p; } });
    let kind, target;
    if (parts.length === 1 && parts[0] === "tickers") {
      kind = "tickers";
      target = UPSTREAM.tickers();
    } else if (parts.length === 2 && parts[0] === "facts" && /^\d{1,10}$/.test(parts[1])) {
      kind = "facts";
      target = UPSTREAM.facts(parts[1].padStart(10, "0"));
    } else if (parts.length === 2 && parts[0] === "submissions" && /^\d{1,10}$/.test(parts[1])) {
      kind = "submissions";
      target = UPSTREAM.submissions(parts[1].padStart(10, "0"));
    } else if (parts.length === 4 && parts[0] === "doc" && /^\d{1,10}$/.test(parts[1]) && /^\d{18}$/.test(parts[2]) &&
               /^[A-Za-z0-9][A-Za-z0-9._\-]{0,99}\.htm$/i.test(parts[3])) {
      kind = "doc";
      target = UPSTREAM.doc(String(+parts[1]), parts[2], parts[3]);
    } else if (parts.length === 2 && parts[0] === "prices" && /^\^?[A-Za-z0-9.\-]{1,12}$/.test(parts[1])) {
      kind = "prices";
      target = UPSTREAM.prices(parts[1].toUpperCase().replace(/\./g, "-"));
    } else {
      return fail(404, "Unknown route. Use /tickers, /facts/<CIK>, /submissions/<CIK>, /doc/<CIK>/<ACCESSION>/<FILE> or /prices/<SYMBOL>.", cors);
    }

    const headers = { "User-Agent": kind === "prices" ? "Mozilla/5.0" : userAgent, Accept: kind === "doc" ? "text/html" : "application/json" };
    let upstream;
    try {
      upstream = await fetch(target, {
        headers,
        cf: { cacheTtl: CACHE_SECONDS[kind], cacheEverything: true },
      });
    } catch (e) {
      if (kind !== "prices") return fail(502, "Could not reach the data source.", cors);
      upstream = null;                       // Yahoo unreachable: try the backup below
    }
    if (kind === "prices" && (!upstream || !upstream.ok)) {
      try {
        const alt = await stooqAsYahoo(parts[1].toUpperCase());
        if (alt) return new Response(JSON.stringify(alt), { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": `public, max-age=${CACHE_SECONDS.prices}`, ...cors } });
      } catch (e) { /* fall through to the error below */ }
    }
    if (!upstream) return fail(502, "Could not reach the data source.", cors);
    if (upstream.status === 404) return fail(404, "No data found for that company.", cors);
    if (!upstream.ok) return fail(502, `The data source answered ${upstream.status}.`, cors);

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": kind === "doc" ? "text/html; charset=utf-8" : "application/json",
        "Cache-Control": `public, max-age=${CACHE_SECONDS[kind]}`,
        ...cors,
      },
    });
  },
};
