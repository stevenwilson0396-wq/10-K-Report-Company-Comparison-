#!/usr/bin/env python3
"""
Add a company to the 10-K comparison site.

    python pipeline/add_company.py GOOGL
    python pipeline/add_company.py NVDA --years 8
    python pipeline/add_company.py --rebuild          # only regenerate data/companies.js

What it does for the ticker you give it
  1. SEC EDGAR XBRL "company facts"  -> income statement + balance sheet items
  2. Computes liquidity / solvency / efficiency / profitability ratios
  3. Yahoo Finance daily closes      -> fiscal-year-end price, market cap, annual return
  4. (optional) downloads each 10-K, extracts Item 7 (MD&A) and scores its tone
     with Loughran-McDonald and VADER
  5. Writes data/<TICKER>.json and rebuilds data/companies.js, which index.html loads.

SEC requires every request to identify you. Set an environment variable first:

    export SEC_USER_AGENT="Your Name your.email@example.com"

Works best for ordinary (non-bank) companies that file 10-Ks. Banks, insurers and
other companies without a classified balance sheet will have blank liquidity and
margin fields.
"""
import argparse
import datetime as dt
import gzip
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------


def sec_user_agent():
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        sys.exit(
            "SEC requires a contact in the User-Agent.\n"
            'Run:  export SEC_USER_AGENT="Your Name your.email@example.com"'
        )
    return ua


def http_get(url, headers, retries=3, pause=0.2):
    req = urllib.request.Request(url, headers={**headers, "Accept-Encoding": "gzip"})
    for attempt in range(1, retries + 1):
        try:
            time.sleep(pause)  # SEC allows 10 requests/second
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            if attempt == retries or e.code in (400, 401, 403, 404):
                raise
        except urllib.error.URLError:
            if attempt == retries:
                raise
            time.sleep(2)
    raise RuntimeError(f"Could not fetch {url}")


def sec_json(url):
    return json.loads(http_get(url, {"User-Agent": sec_user_agent()}).decode("utf-8"))


def lookup_company(ticker):
    """Ticker -> (zero-padded CIK, company name) using SEC's ticker file."""
    data = sec_json("https://www.sec.gov/files/company_tickers.json")
    want = ticker.upper().replace("-", ".")
    for row in data.values():
        if row["ticker"].upper().replace("-", ".") == want:
            return str(row["cik_str"]).zfill(10), row["title"]
    sys.exit(f"Ticker {ticker!r} not found in SEC's company list.")


def fetch_prices(ticker):
    """Daily closes (split-adjusted) and stock splits from Yahoo Finance.

    Returns ({YYYY-MM-DD: close}, [(YYYY-MM-DD, split_ratio)]). A 4-for-1 split has ratio 4.
    """
    symbol = urllib.parse.quote(ticker.upper().replace(".", "-"))   # "^GSPC" becomes "%5EGSPC"
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           "?interval=1d&range=max&events=div%2Csplits")
    raw = http_get(url, {"User-Agent": "Mozilla/5.0"}, pause=0.5)
    return parse_yahoo_chart(json.loads(raw.decode("utf-8")))


def parse_yahoo_chart(payload):
    """Yahoo 'chart' JSON -> ({date: close}, [(date, split_ratio)])."""
    result = payload["chart"]["result"][0]
    out = {}
    for ts, close in zip(result["timestamp"], result["indicators"]["quote"][0]["close"]):
        if close is not None:
            day = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%d")
            out[day] = round(close, 4)
    splits = []
    for ev in result.get("events", {}).get("splits", {}).values():
        day = dt.datetime.fromtimestamp(ev["date"], tz=dt.timezone.utc).strftime("%Y-%m-%d")
        splits.append((day, ev["numerator"] / ev["denominator"]))
    return out, sorted(splits)


def benchmark_path():
    return DATA / "benchmark.json"


def fetch_benchmark(years=14):
    """S&P 500 closes, saved to data/benchmark.json so the page can show returns against the market."""
    prices, _ = fetch_prices("^GSPC")
    cutoff = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    prices = {d: round(v, 2) for d, v in prices.items() if d >= cutoff}
    DATA.mkdir(exist_ok=True)
    benchmark_path().write_text(json.dumps({
        "symbol": "^GSPC", "name": "S&P 500 (price index)", "generated": dt.date.today().isoformat(), "prices": prices,
    }, separators=(",", ":")), encoding="utf-8")
    print(f"  Benchmark: S&P 500, {len(prices):,} days saved to data/benchmark.json")


def load_prices_file(path):
    """Accepts {date: close} or {"prices": {...}, "splits": [["2020-08-31", 4]]}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if "prices" in raw:
        return raw["prices"], [(d, float(r)) for d, r in raw.get("splits", [])]
    return raw, []


# ----------------------------------------------------------------------------
# XBRL helpers
# ----------------------------------------------------------------------------


def _d(s):
    return dt.date.fromisoformat(s)


def _entries(facts, concept, unit="USD"):
    return facts.get(concept, {}).get("units", {}).get(unit, [])


def annual_flow(facts, concepts, unit="USD"):
    """{period_end: value} for full-year 10-K figures.

    `concepts` is a fallback list: for each period the FIRST concept that has a value
    wins. (Companies switch XBRL tags over the years, so this is checked per period.)
    If the latest 10-K restated a number, the restated value is used.
    """
    out = {}
    for concept in concepts:
        best = {}
        for e in _entries(facts, concept, unit):
            if e.get("form") != "10-K" or not e.get("start") or not e.get("end"):
                continue
            days = (_d(e["end"]) - _d(e["start"])).days
            if not 350 <= days <= 380:
                continue
            filed = e.get("filed", "")
            if e["end"] not in best or filed > best[e["end"]][1]:
                best[e["end"]] = (e["val"], filed)
        for end, (val, _) in best.items():
            out.setdefault(end, val)
    return out


def annual_instant(facts, concepts, unit="USD"):
    """{period_end: value} for balance-sheet (point in time) 10-K figures."""
    out = {}
    for concept in concepts:
        best = {}
        for e in _entries(facts, concept, unit):
            if e.get("form") != "10-K" or e.get("start") or not e.get("end"):
                continue
            filed = e.get("filed", "")
            if e["end"] not in best or filed > best[e["end"]][1]:
                best[e["end"]] = (e["val"], filed)
        for end, (val, _) in best.items():
            out.setdefault(end, val)
    return out


def near(series, end, tol_days=7):
    """Value at `end`, or at the closest reported date within a week (52/53-week years)."""
    if end in series:
        return series[end]
    target = _d(end)
    hits = sorted(series, key=lambda k: abs((_d(k) - target).days))
    if hits and abs((_d(hits[0]) - target).days) <= tol_days:
        return series[hits[0]]
    return None


def annual_ends(facts):
    """{period_end: (first_filed, fy, accn)} for every full fiscal year seen in a 10-K."""
    ends = {}
    for concept in (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "NetIncomeLoss",
        "OperatingIncomeLoss",
        "ProfitLoss",
    ):
        for e in _entries(facts, concept):
            if e.get("form") != "10-K" or not e.get("start") or not e.get("end"):
                continue
            days = (_d(e["end"]) - _d(e["start"])).days
            if not 350 <= days <= 380:
                continue
            cur = ends.get(e["end"])
            if cur is None or e.get("filed", "9999") < cur[0]:
                ends[e["end"]] = (e.get("filed", "9999"), e.get("fy"), e.get("accn"))
    return ends


def fiscal_periods(facts, n_years, ends=None):
    """[(fiscal_year_label, period_end)] oldest -> newest.

    The label is the company's own fiscal-year label (DocumentFiscalYearFocus, taken
    from the first 10-K that reported the period). If that looks wrong it falls back
    to the calendar year of the period end.
    """
    ends = ends or annual_ends(facts)
    by_label = {}
    for end, (_, fy, _) in ends.items():
        year = int(end[:4])
        label = fy if isinstance(fy, int) and abs(fy - year) <= 1 else year
        if label not in by_label or end > by_label[label]:
            by_label[label] = end
    periods = sorted(by_label.items())
    return periods[-n_years:]


# ----------------------------------------------------------------------------
# Financial metrics
# ----------------------------------------------------------------------------

REVENUE = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueGoodsNet",
]
COGS = ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"]
INTEREST = [
    "InterestExpense",
    "InterestExpenseNonoperating",
    "InterestAndDebtExpense",
    "InterestExpenseDebt",
]
EQUITY = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
SHORT_TERM_INVEST = ["MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]
SHORT_TERM_DEBT = ["CommercialPaper", "ShortTermBorrowings"]  # often the same item tagged twice: take one
OCF = ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "PaymentsForCapitalImprovements"]
BUYBACKS = ["PaymentsForRepurchaseOfCommonStock"]
DIVIDENDS = ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"]
DEPRECIATION = ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndOther"]
PRETAX = [
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
]
# banks
NII = ["InterestIncomeExpenseNet"]
NONINT_INCOME = ["NoninterestIncome"]
NONINT_EXPENSE = ["NoninterestExpense"]
DEPOSITS = ["Deposits"]
LOANS = ["LoansAndLeasesReceivableNetReportedAmount", "LoansAndLeasesReceivableNetOfDeferredIncome"]
# real-estate companies
PROPERTY = ["RealEstateInvestmentPropertyNet", "RealEstateInvestmentPropertyAtCost"]
GAIN_ON_SALE = ["GainLossOnSaleOfPropertiesNetOfApplicableIncomeTaxes", "GainLossOnSaleOfRealEstateInvestmentPropertyNetOfTax",
                "GainLossOnSaleOfPropertyPlantEquipment"]


def ratio(a, b, digits=2):
    if a is None or b in (None, 0):
        return None
    return round(a / b, digits)


def pct(a, b):
    r = ratio(a, b, 6)
    return None if r is None else round(r * 100, 2)


def bn(x):
    return None if x is None else round(x / 1e9, 2)


def growth(cur, prev):
    """Percent change, only when the earlier value is positive (otherwise it means nothing)."""
    if cur is None or prev is None or prev <= 0:
        return None
    return round((cur / prev - 1) * 100, 2)


def positive(x):
    return x is not None and x > 0


def cover_shares(dei, period_end):
    """(shares, date) from the 10-K cover page, summed across share classes."""
    cover = [
        e for e in _entries(dei, "EntityCommonStockSharesOutstanding", "shares")
        if e.get("form") == "10-K" and e.get("end")
        and 0 <= (_d(e["end"]) - _d(period_end)).days <= 120
    ]
    if not cover:
        return None, None
    first = min(e["end"] for e in cover)
    by_filing = {}
    for e in cover:
        if e["end"] == first:
            by_filing.setdefault(e.get("accn"), []).append(e["val"])
    vals = max(by_filing.values(), key=len)
    return sum(vals), first


def shares_at(dei, period_end, fy_shares_series):
    """(shares, as_of_date): cover page if available, else the balance-sheet count."""
    s, when = cover_shares(dei, period_end)
    if s:
        return s, when
    s = near(fy_shares_series, period_end)
    return (s, period_end) if s else (None, None)


def split_factor(splits, after_date):
    """Product of split ratios that happened after `after_date` (to restate old share counts)."""
    f = 1.0
    for day, ratio in splits:
        if day > after_date:
            f *= ratio
    return f


def closest_price(prices, date_str):
    """Closing price on or just before `date_str` (within 10 days)."""
    if not prices:
        return None, None
    target = _d(date_str)
    for back in range(0, 11):
        d = (target - dt.timedelta(days=back)).isoformat()
        if d in prices:
            return d, prices[d]
    return None, None


def build_records(facts_all, n_years, prices=None, splits=()):
    gaap = facts_all["facts"]["us-gaap"]
    dei = facts_all["facts"].get("dei", {})
    ends_info = annual_ends(gaap)
    periods = fiscal_periods(gaap, n_years + 1, ends_info)  # +1 so the oldest year gets a return

    rev = annual_flow(gaap, REVENUE)
    cogs = annual_flow(gaap, COGS)
    gp = annual_flow(gaap, ["GrossProfit"])
    op = annual_flow(gaap, ["OperatingIncomeLoss"])
    ni = annual_flow(gaap, ["NetIncomeLoss", "ProfitLoss"])
    intexp = annual_flow(gaap, INTEREST)

    cash_sti = annual_instant(gaap, ["CashCashEquivalentsAndShortTermInvestments"])
    cash = annual_instant(gaap, ["CashAndCashEquivalentsAtCarryingValue"])
    sti = annual_instant(gaap, SHORT_TERM_INVEST)
    ar = annual_instant(gaap, ["AccountsReceivableNetCurrent"])
    inv = annual_instant(gaap, ["InventoryNet"])
    ca = annual_instant(gaap, ["AssetsCurrent"])
    ta = annual_instant(gaap, ["Assets"])
    cl = annual_instant(gaap, ["LiabilitiesCurrent"])
    tl = annual_instant(gaap, ["Liabilities"])
    eq = annual_instant(gaap, EQUITY)
    ltd_nc = annual_instant(gaap, ["LongTermDebtNoncurrent"])
    ltd_all = annual_instant(gaap, ["LongTermDebt"])
    ltd_cur = annual_instant(gaap, ["LongTermDebtCurrent"])
    st_debt = annual_instant(gaap, SHORT_TERM_DEBT)
    shares_fy_end = annual_instant(gaap, ["CommonStockSharesOutstanding"], "shares")
    ocf_s, capex_s = annual_flow(gaap, OCF), annual_flow(gaap, CAPEX)
    buyb_s, div_s = annual_flow(gaap, BUYBACKS), annual_flow(gaap, DIVIDENDS)
    da_s, pretax_s = annual_flow(gaap, DEPRECIATION), annual_flow(gaap, PRETAX)
    nii_s, nonint_inc_s = annual_flow(gaap, NII), annual_flow(gaap, NONINT_INCOME)
    nonint_exp_s = annual_flow(gaap, NONINT_EXPENSE)
    deposits_s, loans_s = annual_instant(gaap, DEPOSITS), annual_instant(gaap, LOANS)
    gain_s = annual_flow(gaap, GAIN_ON_SALE)

    records = []
    for fy, end in periods:
        r, c, g = near(rev, end), near(cogs, end), near(gp, end)
        o, n, ie = near(op, end), near(ni, end), near(intexp, end)
        nii, nonint_inc, nonint_exp = near(nii_s, end), near(nonint_inc_s, end), near(nonint_exp_s, end)
        if r is None and nii is not None and nonint_inc is not None:
            r = nii + nonint_inc  # banks: net revenue = net interest income + noninterest income
        if g is None and r is not None and c is not None:
            g = r - c
        if c is None and r is not None and g is not None:
            c = r - g

        cs = near(cash_sti, end)
        if cs is None:
            a, b = near(cash, end), near(sti, end)
            cs = None if a is None and b is None else (a or 0) + (b or 0)
        a_r, i_v = near(ar, end), near(inv, end)
        cur_a, tot_a, cur_l = near(ca, end), near(ta, end), near(cl, end)
        tot_l, e_q = near(tl, end), near(eq, end)
        if tot_l is None and tot_a is not None and e_q is not None:
            tot_l = tot_a - e_q

        nc = near(ltd_nc, end)
        if nc is not None:
            debt = nc + (near(ltd_cur, end) or 0) + (near(st_debt, end) or 0)
        elif near(ltd_all, end) is not None:
            debt = near(ltd_all, end) + (near(st_debt, end) or 0)  # total already includes current part
        else:
            debt = (near(ltd_cur, end) or 0) + (near(st_debt, end) or 0) or None

        ocf, capex = near(ocf_s, end), near(capex_s, end)
        capex = None if capex is None else abs(capex)
        fcf = None if ocf is None or capex is None else ocf - capex
        buyb, div = near(buyb_s, end), near(div_s, end)
        buyb = None if buyb is None else abs(buyb)
        div = None if div is None else abs(div)
        returned = None if buyb is None and div is None else (buyb or 0) + (div or 0)
        da, pretax = near(da_s, end), near(pretax_s, end)
        ebitda = None if o is None or da is None else o + da
        deposits, loans = near(deposits_s, end), near(loans_s, end)
        gain = near(gain_s, end)
        ffo = None if n is None or da is None else n + da - (gain or 0)
        info = near(ends_info, end) or (None, None, None)

        rec = {
            "fy": fy,
            "period_end": end,
            "filing_accn": info[2],
            "filed": None if info[0] in (None, "9999") else info[0],
            "revenue": bn(r),
            "cogs": bn(c),
            "gross_profit": bn(g),
            "operating_income": bn(o),
            "net_income": bn(n),
            "interest_expense": None if ie is None else round(ie / 1e9, 3),
            "cash_and_st_investments": bn(cs),
            "receivables": bn(a_r),
            "inventories": bn(i_v),
            "current_assets": bn(cur_a),
            "total_assets": bn(tot_a),
            "current_liabilities": bn(cur_l),
            "total_liabilities": bn(tot_l),
            "total_debt": bn(debt),
            "equity": bn(e_q),
            "pretax_income": bn(pretax),
            "operating_cash_flow": bn(ocf),
            "capex": bn(capex),
            "free_cash_flow": bn(fcf),
            "buybacks": bn(buyb),
            "dividends_paid": bn(div),
            "depreciation_amortization": bn(da),
            "ebitda": bn(ebitda),
            "net_interest_income": bn(nii),
            "noninterest_income": bn(nonint_inc),
            "noninterest_expense": bn(nonint_exp),
            "deposits": bn(deposits),
            "loans": bn(loans),
            "ffo": bn(ffo),
            # liquidity
            "current_ratio": ratio(cur_a, cur_l),
            "quick_ratio": ratio(None if cs is None and a_r is None else (cs or 0) + (a_r or 0), cur_l),
            "cash_ratio": ratio(cs, cur_l),
            # solvency
            "debt_to_equity": ratio(debt, e_q) if positive(e_q) else None,  # blank when equity is negative: the ratio would mislead
            "debt_to_assets": ratio(debt, tot_a),
            "financial_leverage": ratio(tot_a, e_q) if positive(e_q) else None,
            "interest_coverage": ratio(o, ie, 1) if ie and ie > 0 else None,
            # efficiency
            "asset_turnover": ratio(r, tot_a),
            "inventory_turnover": ratio(c, i_v, 1),
            "dsi": None if not (c and i_v) else round(i_v / c * 365, 1),
            "receivables_turnover": ratio(r, a_r),
            "dso": None if not (r and a_r) else round(a_r / r * 365, 1),
            # profitability
            "gross_margin": pct(g, r),
            "operating_margin": pct(o, r),
            "net_margin": pct(n, r),
            "roa": pct(n, tot_a),
            "roe": pct(n, e_q) if positive(e_q) else None,
            "equity_to_assets": pct(e_q, tot_a),
            # DuPont extras: ROE = tax burden x interest burden x operating margin x asset turnover x leverage
            "tax_burden": ratio(n, pretax, 3) if positive(pretax) else None,
            "interest_burden": ratio(pretax, o, 3) if positive(o) else None,
            # cash flow and capital allocation
            "fcf_margin": pct(fcf, r),
            "capex_pct_revenue": pct(capex, r),
            "cash_conversion": ratio(ocf, n) if positive(n) else None,
            "payout_ratio": pct(div, n) if positive(n) else None,
            "shareholder_return_pct_fcf": pct(returned, fcf) if positive(fcf) else None,
            "accruals_ratio": pct(None if n is None or ocf is None else n - ocf, tot_a),
            # growth (filled below from the previous year)
            "revenue_growth": None,
            "operating_income_growth": None,
            "net_income_growth": None,
            "fcf_growth": None,
            "receivables_growth_gap": None,
            "inventory_growth_gap": None,
            # banks
            "efficiency_ratio": pct(nonint_exp, nii + nonint_inc) if nii is not None and nonint_inc is not None else None,
            "loan_to_deposit": pct(loans, deposits),
            "nii_to_assets": pct(nii, tot_a),
            # stock (filled below)
            "price": None,
            "market_cap": None,
            "annual_return": None,
            # valuation (filled below)
            "pe_ratio": None,
            "price_to_sales": None,
            "price_to_book": None,
            "ev_to_ebitda": None,
            "earnings_yield": None,
            "dividend_yield": None,
            "buyback_yield": None,
            "fcf_yield": None,
            # sentiment (filled by add_sentiment)
            "lm_polarity": None,
            "vader": None,
            "pos_sentences": None,
            "neg_sentences": None,
            "uncertainty_pct": None,
            "litigious_pct": None,
            "lm_pos_words": None,
            "lm_neg_words": None,
            "mda_words": None,
        }

        if prices:
            _, px = closest_price(prices, end)
            rec["price"] = None if px is None else round(px, 2)
            sh, when = shares_at(dei, end, shares_fy_end)
            if px and sh and splits is not None:
                # prices are split-adjusted, so restate older (pre-split) share counts too
                mc = px * sh * split_factor(splits, when)
                rec["market_cap"] = round(mc / 1e9, 1)
                rec["pe_ratio"] = ratio(mc, n, 1) if positive(n) else None
                rec["price_to_sales"] = ratio(mc, r) if positive(r) else None
                rec["price_to_book"] = ratio(mc, e_q) if positive(e_q) else None
                ev = mc + (debt or 0) - (cs or 0)
                rec["ev_to_ebitda"] = ratio(ev, ebitda, 1) if positive(ebitda) else None
                rec["earnings_yield"] = pct(n, mc)
                rec["dividend_yield"] = pct(div, mc)
                rec["buyback_yield"] = pct(buyb, mc)
                rec["fcf_yield"] = pct(fcf, mc)
            if records and records[-1]["price"] and px:
                rec["annual_return"] = round((px / records[-1]["price"] - 1) * 100, 2)
        if records:
            prev = records[-1]
            rec["revenue_growth"] = growth(rec["revenue"], prev["revenue"])
            rec["operating_income_growth"] = growth(rec["operating_income"], prev["operating_income"])
            rec["net_income_growth"] = growth(rec["net_income"], prev["net_income"])
            rec["fcf_growth"] = growth(rec["free_cash_flow"], prev["free_cash_flow"])
            ar_g, inv_g = growth(rec["receivables"], prev["receivables"]), growth(rec["inventories"], prev["inventories"])
            if ar_g is not None and rec["revenue_growth"] is not None:
                rec["receivables_growth_gap"] = round(ar_g - rec["revenue_growth"], 2)
            if inv_g is not None and rec["revenue_growth"] is not None:
                rec["inventory_growth_gap"] = round(inv_g - rec["revenue_growth"], 2)
        records.append(rec)

    # the extra leading year only exists to give the oldest shown year a return
    return records[-n_years:]


def classify(records, gaap):
    """'bank', 'reit' or 'operating'. A rough guide used to choose which metrics make sense."""
    n = max(1, len(records))
    if sum(1 for r in records if r["net_interest_income"] is not None and (r["deposits"] is not None or r["noninterest_expense"] is not None)) * 2 >= n:
        return "bank"
    prop = annual_instant(gaap, PROPERTY)
    if sum(1 for r in records if near(prop, r["period_end"]) is not None) * 2 >= n and not any(r["gross_profit"] for r in records[-2:]):
        return "reit"
    return "operating"


def build_quarters(gaap, n_quarters=12):
    """Quarterly revenue, operating income and net income (newest `n_quarters`).

    Q1 to Q3 come from 10-Q filings (three-month figures). Q4 is the full year minus those
    three, because companies do not file a 10-Q for the fourth quarter.
    """
    ends_info = annual_ends(gaap)
    labels = dict(fiscal_periods(gaap, 99, ends_info))
    by_end = {e: l for l, e in labels.items()}
    year_ends = sorted(by_end)
    series = {"revenue": REVENUE, "operating_income": ["OperatingIncomeLoss"], "net_income": ["NetIncomeLoss", "ProfitLoss"]}
    quarter = {k: {} for k in series}  # key -> {end: (value, start)}
    for key, concepts in series.items():
        for concept in concepts:
            best = {}
            for e in _entries(gaap, concept):
                if e.get("form") != "10-Q" or not e.get("start") or not e.get("end"):
                    continue
                if not 80 <= (_d(e["end"]) - _d(e["start"])).days <= 100:
                    continue
                filed = e.get("filed", "")
                if e["end"] not in best or filed > best[e["end"]][2]:
                    best[e["end"]] = (e["val"], e["start"], filed)
            for end, (val, start, _) in best.items():
                quarter[key].setdefault(end, (val, start))
    annual = {
        "revenue": annual_flow(gaap, REVENUE),
        "operating_income": annual_flow(gaap, ["OperatingIncomeLoss"]),
        "net_income": annual_flow(gaap, ["NetIncomeLoss", "ProfitLoss"]),
    }
    q_ends = set()
    for key in series:
        q_ends |= set(quarter[key])
    for ye in year_ends:  # derived fourth quarters
        mids = sorted(e for e in q_ends if 30 < (_d(ye) - _d(e)).days < 300)
        mids = [e for e in mids if (_d(ye) - _d(e)).days < 300][-3:]
        if len(mids) == 3 and (_d(ye) - _d(mids[-1])).days < 130:
            for key in series:
                if ye in annual[key] and all(m in quarter[key] for m in mids):
                    quarter[key][ye] = (annual[key][ye] - sum(quarter[key][m][0] for m in mids), None)
            q_ends.add(ye)
    rows = []
    for end in sorted(q_ends):
        later = [ye for ye in year_ends if ye >= end and (_d(ye) - _d(end)).days < 372]
        if later:
            fy = by_end[later[0]]
        elif year_ends and end > year_ends[-1]:
            fy = by_end[year_ends[-1]] + 1  # the year in progress
        else:
            continue
        rows.append({"fy": fy, "period_end": end,
                     **{k: (None if end not in quarter[k] else round(quarter[k][end][0] / 1e9, 3)) for k in series}})
    rows = [r for r in rows if r["revenue"] is not None or r["net_income"] is not None]
    counts = {}
    for row in rows:  # quarter number within its fiscal year, in date order
        counts[row["fy"]] = counts.get(row["fy"], 0) + 1
        row["q"] = counts[row["fy"]]
    return rows[-n_quarters:]


# ----------------------------------------------------------------------------
# MD&A sentiment (optional: needs pysentiment2 + vaderSentiment)
# ----------------------------------------------------------------------------

UNCERTAINTY_WORDS = {
    'anticipate', 'anticipates', 'anticipated', 'anticipating', 'anticipation',
    'approximate', 'approximately', 'approximation', 'arbitrary',
    'assume', 'assumed', 'assumes', 'assuming', 'assumption', 'assumptions',
    'believe', 'believes', 'believed', 'believing',
    'contingent', 'contingency', 'contingencies',
    'depend', 'depends', 'depended', 'depending', 'dependence', 'dependent',
    'fluctuate', 'fluctuates', 'fluctuated', 'fluctuating', 'fluctuation', 'fluctuations',
    'indefinite', 'indefinitely',
    'pending', 'preliminary', 'predict', 'predicts', 'predicted', 'predicting', 'prediction',
    'probable', 'probably', 'probability',
    'risk', 'risks', 'risky',
    'uncertain', 'uncertainty', 'uncertainties',
    'unclear', 'unpredictable', 'unforeseen',
    'variable', 'variables', 'variability', 'volatility', 'volatile',
}
LITIGIOUS_WORDS = {
    'allegation', 'allegations', 'allege', 'alleged', 'alleges', 'alleging',
    'arbitration', 'arbitrator', 'claim', 'claims', 'claimant', 'claimants',
    'counterclaim', 'counterclaims', 'court', 'defendant', 'defendants',
    'dispute', 'disputes', 'disputed', 'infringe', 'infringes', 'infringed', 'infringing', 'infringement',
    'investigation', 'investigations', 'judgment', 'judgments', 'jurisdiction',
    'lawsuit', 'lawsuits', 'legal', 'legislation', 'litigate', 'litigated', 'litigating', 'litigation',
    'litigious', 'plaintiff', 'plaintiffs', 'pleading', 'pleadings', 'proceeding', 'proceedings',
    'prosecute', 'prosecuted', 'prosecution', 'regulatory', 'settle', 'settled', 'settlement', 'subpoena', 'tribunal',
}


def clean_html_to_text(content):
    text = re.sub(r"(?is)<ix:hidden.*?</ix:hidden>", "", content)
    text = re.sub(r"(?is)<style.*?</style>", "", text)
    text = re.sub(r"(?is)<script.*?</script>", "", text)
    text = re.sub(r"(?is)<xml.*?</xml>", "", text)
    text = re.sub(r"(?i)<(p|div|tr|br|h[1-6]|li)\b[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = htmllib.unescape(text).replace("\xa0", " ").replace("​", " ")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


ITEM7_START = re.compile(r"(?im)^\s*item\s*7\s*[.:\-–—]?\s*management")
ITEM7_END = re.compile(r"(?im)^\s*item\s*(7a|8)\s*[.:\-–—]?\s*(quantitative|financial|consolidated)")


def extract_mda(html_content):
    """Return the text of Item 7 (MD&A), choosing the longest candidate span so that
    table-of-contents entries (which are one line long) are ignored."""
    text = clean_html_to_text(html_content)
    best = ""
    for m in ITEM7_START.finditer(text):
        end = ITEM7_END.search(text, m.end())
        if end and end.start() - m.start() > len(best):
            best = text[m.start():end.start()]
    if not best:
        raise ValueError("could not locate Item 7 (MD&A)")
    return best


def score_text(text, lm, vader):
    words = [w.lower() for w in re.findall(r"\b[a-zA-Z]{2,}\b", text)]
    total = len(words)
    toks = lm.tokenize(text)
    s = lm.get_score(toks)
    unc = sum(1 for w in words if w in UNCERTAINTY_WORDS)
    lit = sum(1 for w in words if w in LITIGIOUS_WORDS)
    scores = []
    for sent in (x.strip() for x in re.split(r"(?<=[.!?])\s+", text)):
        if len(sent) <= 25 or sum(ch.isdigit() for ch in sent) / len(sent) > 0.4:
            continue
        scores.append(vader.polarity_scores(sent)["compound"])
    n = len(scores)
    return {
        "mda_words": total,
        "lm_polarity": round(float(s["Polarity"]), 4),
        "lm_pos_words": int(s["Positive"]),
        "lm_neg_words": int(s["Negative"]),
        "vader": round(sum(scores) / n, 4) if n else None,
        "pos_sentences": round(sum(1 for c in scores if c >= 0.05) / n * 100, 2) if n else None,
        "neg_sentences": round(sum(1 for c in scores if c <= -0.05) / n * 100, 2) if n else None,
        "uncertainty_pct": round(unc / total * 100, 3) if total else None,
        "litigious_pct": round(lit / total * 100, 3) if total else None,
    }


def list_10k_filings(cik):
    """[(report_date, accession, primary_document)] from SEC submissions (all history)."""
    sub = sec_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    blocks = [sub["filings"]["recent"]]
    for f in sub["filings"].get("files", []):
        blocks.append(sec_json(f"https://data.sec.gov/submissions/{f['name']}"))
    out = []
    for b in blocks:
        for form, rd, acc, doc in zip(b["form"], b["reportDate"], b["accessionNumber"], b["primaryDocument"]):
            if form == "10-K" and rd:
                out.append((rd, acc, doc))
    return out


def add_sentiment(records, cik):
    try:
        import pysentiment2 as ps
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    except ImportError:
        print("  Skipping sentiment: run  pip install -r requirements.txt  to enable it.")
        return
    lm, vader = ps.LM(), SentimentIntensityAnalyzer()
    filings = list_10k_filings(cik)
    cik_int = str(int(cik))
    for rec in records:
        match = [f for f in filings if abs((_d(f[0]) - _d(rec["period_end"])).days) <= 7]
        if not match:
            print(f"  FY{rec['fy']}: no 10-K filing found, skipping sentiment")
            continue
        rd, acc, doc = match[0]
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc.replace('-', '')}/{doc}"
        try:
            page = http_get(url, {"User-Agent": sec_user_agent()}).decode("utf-8", errors="ignore")
            rec.update(score_text(extract_mda(page), lm, vader))
            print(f"  FY{rec['fy']}: MD&A {rec['mda_words']:,} words, LM polarity {rec['lm_polarity']:+.4f}")
        except Exception as e:  # keep going: one bad filing shouldn't lose the rest
            print(f"  FY{rec['fy']}: sentiment failed ({e})")


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def rebuild_index():
    """Bundle data/*.json into data/companies.js (a script tag works from file:// too)."""
    DATA.mkdir(exist_ok=True)
    companies = []
    for p in sorted(DATA.glob("*.json")):
        if p.name == "benchmark.json":
            continue
        try:
            companies.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            print(f"Skipping unreadable {p.name}")
    companies.sort(key=lambda c: c["ticker"])
    body = json.dumps(companies, separators=(",", ":"))
    bench = ""
    if benchmark_path().exists():
        bench = "window.BENCHMARK = " + json.dumps(json.loads(benchmark_path().read_text(encoding="utf-8")), separators=(",", ":")) + ";\n"
    (DATA / "companies.js").write_text(f"window.COMPANIES = {body};\n{bench}", encoding="utf-8")
    print(f"data/companies.js now holds {len(companies)} companies: {', '.join(c['ticker'] for c in companies)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ticker", nargs="?", help="stock ticker, e.g. GOOGL")
    ap.add_argument("--years", type=int, default=10, help="fiscal years to include (default 10)")
    ap.add_argument("--no-sentiment", action="store_true", help="skip the slow 10-K download + MD&A scoring")
    ap.add_argument("--no-prices", action="store_true", help="skip Yahoo Finance prices")
    ap.add_argument("--rebuild", action="store_true", help="only regenerate data/companies.js")
    ap.add_argument("--facts-file", help="use a saved SEC company-facts JSON instead of downloading")
    ap.add_argument("--prices-file", help='saved prices: {date: close} or {"prices": {...}, "splits": [["2020-08-31", 4]]}')
    ap.add_argument("--refresh-benchmark", action="store_true", help="download the S&P 500 series again (it is fetched once if missing)")
    ap.add_argument("--name", help="company name (needed with --facts-file)")
    ap.add_argument("--cik", help="CIK (needed with --facts-file)")
    args = ap.parse_args()

    if args.rebuild:
        return rebuild_index()
    if not args.ticker:
        ap.error("give a ticker, or use --rebuild")
    ticker = args.ticker.upper()

    if args.facts_file:
        facts = json.loads(Path(args.facts_file).read_text(encoding="utf-8"))
        cik = (args.cik or str(facts.get("cik", ""))).zfill(10)
        name = args.name or facts.get("entityName", ticker)
    else:
        cik, name = lookup_company(ticker)
        print(f"{ticker}: {name} (CIK {cik})")
        facts = sec_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")

    prices, splits = None, []
    if args.prices_file:
        prices, splits = load_prices_file(args.prices_file)
    elif not args.no_prices:
        try:
            prices, splits = fetch_prices(ticker)
            print(f"  Prices: {len(prices):,} days ({min(prices)} to {max(prices)})")
        except Exception as e:
            print(f"  Warning: could not fetch prices ({e}). Market cap and returns will be blank.")

    if not args.no_prices and not args.prices_file and (args.refresh_benchmark or not benchmark_path().exists()):
        try:
            fetch_benchmark()
        except Exception as e:
            print(f"  Warning: could not fetch the S&P 500 series ({e}). The page will skip return-vs-market.")

    records = build_records(facts, args.years, prices, splits)
    if not records:
        sys.exit("No annual 10-K data found for this company.")
    print(f"  Financials: FY{records[0]['fy']} to FY{records[-1]['fy']}")

    if not args.no_sentiment and not args.facts_file:
        add_sentiment(records, cik)

    out = {
        "ticker": ticker,
        "name": name,
        "cik": cik,
        "fiscal_year_end": MONTHS[int(records[-1]["period_end"][5:7]) - 1],
        "generated": dt.date.today().isoformat(),
        "sources": "SEC EDGAR XBRL company facts; Yahoo Finance daily closes; 10-K Item 7 text",
        "kind": classify(records, facts["facts"]["us-gaap"]),
        "years": records,
        "quarters": build_quarters(facts["facts"]["us-gaap"]),
    }
    DATA.mkdir(exist_ok=True)
    (DATA / f"{ticker}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"  Wrote data/{ticker}.json")
    rebuild_index()


if __name__ == "__main__":
    main()
