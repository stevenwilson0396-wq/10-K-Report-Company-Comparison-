# 10-K-Report-Company-Comparison-[README.md](https://github.com/user-attachments/files/33912746/README.md)
[Uploading README.md…]()
# 10-K Company Comparison

A static web page that compares two to five public companies side by side, using their SEC 10-K and 10-Q filings and stock prices. It ships with **Apple** and **Microsoft**. With a small free proxy (below) you can search **any SEC-registered company by name or ticker** and compare it live, with no files to download.

No build step and no dependencies: `index.html` plus a few script files and a data file.

## What it shows

| Tab | What is in it |
|---|---|
| Overview | Snapshot tiles and a side-by-side table. With three or more companies the table shows each company's rank. |
| Financials | Revenue, gross profit, operating income, EBITDA, net income, assets, debt, equity |
| Cash flow | Operating cash flow, capital spending, free cash flow and margin, cash conversion, buybacks, dividends, payout |
| Profitability | Margins, return on assets and equity |
| Growth | Year-over-year growth, compound growth over the chosen years, margin change, and flags (receivables or inventory growing much faster than sales, earnings not backed by cash) |
| DuPont | Return on equity split into tax burden, interest burden, operating margin, asset turnover and leverage, with a note on which factor explains the gap |
| Liquidity, Solvency, Efficiency | Current/quick/cash ratios, debt ratios and coverage, turnover and days measures |
| Stock | Year-end price, market value, annual return, and return against the S&P 500 |
| Valuation | P/E, price/sales, price/book, EV/EBITDA, earnings, free cash flow, dividend and buyback yields |
| Quarterly | The last 12 quarters of revenue and net income from 10-Q filings, growth against the same quarter last year, and last-four-quarter totals |
| Banks & REITs | Efficiency ratio, loans/deposits, net interest income, and approximate funds from operations |
| MD&A tone | Tone of Item 7 (Loughran-McDonald, VADER, uncertainty and legal wording) |
| Data table | Every number, with a link to the SEC filing each year comes from, and a CSV download |

Every chart has a **PNG** button, there is a **Copy link** button (the link reopens the same comparison, including live companies when a proxy is set), and **Print or save as PDF** prints the current tab.

## Put it on GitHub Pages

1. Create a repo and push this folder to it.
2. In the repo go to **Settings → Pages**, set the source to **Deploy from a branch**, pick `main` and `/ (root)`, and save.
3. After a minute the page is live at `https://<your-username>.github.io/<repo-name>/`.

To look at it on your own computer first, double-click `index.html`. It works from the file system.

## Search any SEC company (live)

Browsers can't read the SEC's data servers directly (the SEC blocks cross-site requests and requires every caller to identify itself). A tiny free **Cloudflare Worker** does that part for the page. It only passes data through; all the calculating happens in your browser.

1. Make a free account at cloudflare.com and install Node.js.
2. Open `worker/wrangler.toml` and set `SEC_USER_AGENT` to your name and email (the SEC requires it). Optionally set `ALLOWED_ORIGIN` to your site, e.g. `https://<your-username>.github.io`, so nobody else can use your proxy.
3. Run:
   ```bash
   cd worker
   npx wrangler deploy
   ```
   It prints an address like `https://sec-proxy.<you>.workers.dev`.
4. Put that address in `config.js` (`window.SEC_PROXY = "https://...";`) and commit it. Or, without editing anything, paste it into **Search any SEC company** at the bottom of the page and press **Save and test**. That saves it in your browser only.

Then click any company box and type a name or ticker. **The numbers update as you type**: companies already loaded switch instantly, and SEC companies load once you pause for a moment. **+ Add company** adds up to five.

Live companies:

- get financials, ratios, quarterly figures and (if a price source answers) stock charts, calculated the same way as the bundled ones;
- can have **MD&A length, uncertainty-word and legal-word shares** added with the **Score MD&A tone** button (the page downloads each 10-K and reads Item 7);
- do **not** get Loughran-McDonald polarity or VADER sentence scores. Those need dictionaries that are not bundled; add the company with `pipeline/add_company.py` to get them.

Prices come from Yahoo Finance. If Yahoo refuses (it sometimes blocks cloud servers), the proxy falls back to Stooq. Stooq does not list stock splits, so for those companies price and return still show but market value and the valuation ratios are left blank, with a message.

## Add a company permanently

```bash
pip install -r requirements.txt        # optional: only needed for the sentiment analysis
export SEC_USER_AGENT="Your Name your.email@example.com"   # the SEC requires this
python pipeline/add_company.py GOOGL
```

That writes `data/GOOGL.json` and rebuilds `data/companies.js`. Commit both and the company appears in the dropdowns. The first run also saves the S&P 500 series to `data/benchmark.json` (the Stock tab needs it).

Options:

| Flag | What it does |
|---|---|
| `--years 8` | Number of fiscal years (default 10) |
| `--no-sentiment` | Skip downloading each 10-K and scoring its MD&A. This is the slow step. |
| `--no-prices` | Skip Yahoo Finance prices |
| `--refresh-benchmark` | Download the S&P 500 series again |
| `--rebuild` | Only regenerate `data/companies.js` from the files in `data/` |

**No Python on your machine?** In your GitHub repo open **Actions → Add company → Run workflow**, enter a ticker and your name and email, and it commits the data for you.

**Just want to try a file?** Use "Search any SEC company, or add one from a file" at the bottom of the page to load a company JSON for one visit.

To remove a company, delete its file in `data/` and run `python pipeline/add_company.py --rebuild`.

## Where the numbers come from

| Data | Source | How |
|---|---|---|
| Statements, cash flow | SEC EDGAR XBRL "company facts" | Full-year figures from 10-K filings. Companies change XBRL tags over time, so each year uses the first tag in a fallback list that has a value. |
| Quarters | The same, from 10-Q filings | Q1 to Q3 are the three-month figures; Q4 is the full year minus those three. |
| Ratios | Computed here | Standard textbook definitions, formulas in `build_records()` (and its twin in `js/sec-metrics.js`) |
| Share price, returns | Yahoo Finance daily closes | Closing price on the fiscal year-end date (or the last trading day before it) |
| Market value | Price × cover-page shares | Share counts are restated for later stock splits |
| MD&A tone | The text of Item 7 in each 10-K | Loughran-McDonald polarity, VADER sentence scores, uncertainty and legal word shares |

Definitions worth knowing:

- **Fiscal year label** is the company's own (from the filing), so Apple's FY2025 ends in September 2025 and Microsoft's ends in June 2025. The page notes this when year-ends differ.
- **Total debt** = long-term debt + current portion of long-term debt + commercial paper or short-term borrowings. Lease liabilities are not included.
- **Free cash flow** = operating cash flow − capital spending (purchases of property and equipment).
- **EBITDA** = operating income + depreciation and amortization, and is blank when the company doesn't use a standard depreciation tag (Microsoft, for example).
- **Returns** are price changes only. Dividends are excluded. **Return vs S&P 500** compares price changes over each company's own fiscal year.
- **ROE, debt/equity and leverage** are blank when equity is zero or negative, because the ratios would mislead. Growth rates are blank when the earlier value is zero or negative.
- **Valuation** uses year-end market value; dividend and buyback yields divide the year's payments by that value.
- **Prices** are split-adjusted, not dividend-adjusted.

## Limits to keep in mind

- **Banks, insurers and REITs.** Banks get an efficiency ratio, loans/deposits and net interest income, and real-estate companies get approximate FFO. Which type a company is comes from a simple rule on its XBRL tags, and the bank and REIT measures were tested on invented data only, not on real bank or REIT filings. Insurers and other financial firms are not specially handled and will have blanks.
- **No sector medians.** The page compares the companies you pick. It does not compare them with an industry average, because that needs data on many companies.
- **Quarterly** shows revenue, operating income and net income only (10-Q cash flow statements are year-to-date, so they aren't split into quarters).
- Companies with several share classes (for example Alphabet) have market value computed from the summed cover-page shares at a single price, which is approximate.
- Interest expense is blank for companies that don't tag it in a standard way. Apple's FY2024 and FY2025 are an example.
- MD&A length differs a lot between companies. Tone scores from short sections rest on less text, so compare them with care.
- Very large companies have large SEC files and can take 10 to 30 seconds to load live.
- The page includes automatic **data checks** (shown under the notes) that flag impossible values or one-year jumps. They catch tagging quirks, not accounting problems.
- This is a research tool. It is not investment advice. Check numbers you rely on against the filings.

## Tests

```bash
python tests/make_fixtures.py && python tests/parity_fixtures.py   # rebuild synthetic bank/REIT/loss-maker data
python tests/test_pipeline.py          # the Python pipeline
node tests/test_metrics.js             # browser code gives the same numbers as the pipeline; bundled data passes sanity checks
node tests/test_mda.js                 # MD&A extraction
node tests/test_worker.mjs             # proxy worker (mocked network)
python tests/test_ui.py                # the page in headless Chromium (pip install playwright && playwright install chromium)
```

They run automatically on every push through `.github/workflows/tests.yml`. None of them needs network access, which also means none of them talks to the real SEC, Yahoo Finance or Cloudflare. Try those yourself after deploying.

## Layout

```
index.html                  the whole site (HTML, CSS, JS in one file)
config.js                   your proxy address (optional)
js/sec-metrics.js           in-browser version of the metric calculations
js/mda.js                   in-browser Item 7 extraction and word counts
js/checks.js                data sanity checks
worker/                     Cloudflare Worker proxy for live SEC search
data/
  companies.js              generated bundle the page loads
  benchmark.json            S&P 500 closes (made by the pipeline)
  AAPL.json, MSFT.json      one file per company
pipeline/
  add_company.py            add a company from SEC + Yahoo data
  import_sentiment.py       merge sentiment you already computed into a company file
tests/                      see above
.github/workflows/
  add-company.yml           "Add company" button for GitHub Actions
  tests.yml                 runs the tests
```
