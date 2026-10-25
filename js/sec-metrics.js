/*
 * Turns SEC "company facts" (XBRL) and Yahoo Finance prices into the same per-year
 * records that pipeline/add_company.py writes to data/<TICKER>.json.
 *
 * This is a line-for-line port of build_records() in add_company.py, so a company loaded
 * live in the browser matches one added with the script. MD&A sentiment is not
 * computed here (it needs the filings' full text), so those fields stay null.
 *
 * Works in a browser (window.SecMetrics) and in Node (module.exports) for testing.
 */
(function (root) {
  "use strict";

  var MONTHS = ["January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"];

  // ---- dates as whole days since 1970 (UTC), so differences are exact -------------
  function day(s) {
    var p = s.split("-");
    return Date.UTC(+p[0], +p[1] - 1, +p[2]) / 86400000;
  }
  function iso(n) { return new Date(n * 86400000).toISOString().slice(0, 10); }

  function rnd(x, d) { return Number(x.toFixed(d)); }  // Python round() equivalent except on exact ties

  function entries(facts, concept, unit) {
    var c = facts[concept];
    var u = c && c.units && c.units[unit || "USD"];
    return u || [];
  }

  // {period_end: value} for full-year figures from 10-K filings. `concepts` is a fallback
  // list: for each period the first concept that has a value wins.
  function annualFlow(facts, concepts, unit) {
    var out = new Map();
    concepts.forEach(function (concept) {
      var best = new Map();
      entries(facts, concept, unit).forEach(function (e) {
        if (e.form !== "10-K" || !e.start || !e.end) return;
        var days = day(e.end) - day(e.start);
        if (days < 350 || days > 380) return;
        var filed = e.filed || "";
        var cur = best.get(e.end);
        if (!cur || filed > cur[1]) best.set(e.end, [e.val, filed]);
      });
      best.forEach(function (v, end) { if (!out.has(end)) out.set(end, v[0]); });
    });
    return out;
  }

  // {period_end: value} for balance-sheet (point in time) figures.
  function annualInstant(facts, concepts, unit) {
    var out = new Map();
    concepts.forEach(function (concept) {
      var best = new Map();
      entries(facts, concept, unit).forEach(function (e) {
        if (e.form !== "10-K" || e.start || !e.end) return;
        var filed = e.filed || "";
        var cur = best.get(e.end);
        if (!cur || filed > cur[1]) best.set(e.end, [e.val, filed]);
      });
      best.forEach(function (v, end) { if (!out.has(end)) out.set(end, v[0]); });
    });
    return out;
  }

  // Value at `end`, or at the closest reported date within a week (52/53-week years).
  function near(series, end) {
    if (series.has(end)) return series.get(end);
    var target = day(end), bestKey = null, bestDiff = Infinity;
    series.forEach(function (_, k) {
      var diff = Math.abs(day(k) - target);
      if (diff < bestDiff) { bestDiff = diff; bestKey = k; }
    });
    return bestKey !== null && bestDiff <= 7 ? series.get(bestKey) : null;
  }

  // {period_end: [first_filed, fy, accn]} for every full fiscal year seen in a 10-K.
  function annualEnds(facts) {
    var ends = new Map();
    ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
      "NetIncomeLoss", "OperatingIncomeLoss", "ProfitLoss"].forEach(function (concept) {
      entries(facts, concept).forEach(function (e) {
        if (e.form !== "10-K" || !e.start || !e.end) return;
        var days = day(e.end) - day(e.start);
        if (days < 350 || days > 380) return;
        var filed = e.filed || "9999", cur = ends.get(e.end);
        if (!cur || filed < cur[0]) ends.set(e.end, [filed, e.fy, e.accn]);
      });
    });
    return ends;
  }

  function fiscalPeriods(facts, nYears, ends) {
    ends = ends || annualEnds(facts);
    var byLabel = new Map();
    ends.forEach(function (v, end) {
      var year = +end.slice(0, 4), fy = v[1];
      var label = Number.isInteger(fy) && Math.abs(fy - year) <= 1 ? fy : year;
      if (!byLabel.has(label) || end > byLabel.get(label)) byLabel.set(label, end);
    });
    var periods = Array.from(byLabel.entries()).sort(function (a, b) { return a[0] - b[0]; });
    return periods.slice(-nYears);
  }

  var REVENUE = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"];
  var COGS = ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"];
  var INTEREST = ["InterestExpense", "InterestExpenseNonoperating", "InterestAndDebtExpense", "InterestExpenseDebt"];
  var EQUITY = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"];
  var SHORT_TERM_INVEST = ["MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"];
  var SHORT_TERM_DEBT = ["CommercialPaper", "ShortTermBorrowings"];
  var OCF = ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"];
  var CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "PaymentsForCapitalImprovements"];
  var BUYBACKS = ["PaymentsForRepurchaseOfCommonStock"];
  var DIVIDENDS = ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"];
  var DEPRECIATION = ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndOther"];
  var PRETAX = ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"];
  var NII = ["InterestIncomeExpenseNet"];
  var NONINT_INCOME = ["NoninterestIncome"];
  var NONINT_EXPENSE = ["NoninterestExpense"];
  var DEPOSITS = ["Deposits"];
  var LOANS = ["LoansAndLeasesReceivableNetReportedAmount", "LoansAndLeasesReceivableNetOfDeferredIncome"];
  var PROPERTY = ["RealEstateInvestmentPropertyNet", "RealEstateInvestmentPropertyAtCost"];
  var GAIN_ON_SALE = ["GainLossOnSaleOfPropertiesNetOfApplicableIncomeTaxes",
    "GainLossOnSaleOfRealEstateInvestmentPropertyNetOfTax", "GainLossOnSaleOfPropertyPlantEquipment"];

  function ratio(a, b, d) {
    if (a == null || b == null || b === 0) return null;
    return rnd(a / b, d === undefined ? 2 : d);
  }
  function pct(a, b) {
    var r = ratio(a, b, 6);
    return r === null ? null : rnd(r * 100, 2);
  }
  function bn(x) { return x == null ? null : rnd(x / 1e9, 2); }
  function or0(x) { return x == null ? 0 : x; }
  function positive(x) { return x != null && x > 0; }
  // Percent change, only when the earlier value is positive.
  function growth(cur, prev) {
    if (cur == null || prev == null || prev <= 0) return null;
    return rnd((cur / prev - 1) * 100, 2);
  }

  // Shares from the 10-K cover page, summed across share classes: [shares, date] or [null, null].
  function coverShares(dei, periodEnd) {
    var pe = day(periodEnd);
    var cover = entries(dei, "EntityCommonStockSharesOutstanding", "shares").filter(function (e) {
      if (e.form !== "10-K" || !e.end) return false;
      var d = day(e.end) - pe;
      return d >= 0 && d <= 120;
    });
    if (!cover.length) return [null, null];
    var first = cover.reduce(function (m, e) { return e.end < m ? e.end : m; }, cover[0].end);
    var byFiling = new Map();
    cover.forEach(function (e) {
      if (e.end !== first) return;
      if (!byFiling.has(e.accn)) byFiling.set(e.accn, []);
      byFiling.get(e.accn).push(e.val);
    });
    var vals = null;
    byFiling.forEach(function (v) { if (vals === null || v.length > vals.length) vals = v; });
    return [vals.reduce(function (a, b) { return a + b; }, 0), first];
  }

  function sharesAt(dei, periodEnd, fyShares) {
    var r = coverShares(dei, periodEnd);
    if (r[0]) return r;
    var s = near(fyShares, periodEnd);
    return s ? [s, periodEnd] : [null, null];
  }

  // Product of split ratios after `after`, to restate share counts that pre-date a split.
  function splitFactor(splits, after) {
    var f = 1;
    (splits || []).forEach(function (s) { if (s[0] > after) f *= s[1]; });
    return f;
  }

  function closestPrice(prices, dateStr) {
    if (!prices) return null;
    var t = day(dateStr);
    for (var back = 0; back <= 10; back++) {
      var d = iso(t - back);
      if (prices[d] !== undefined) return prices[d];
    }
    return null;
  }

  // Yahoo "chart" JSON -> { prices: {date: close}, splits: [[date, ratio], ...] }
  function parseYahoo(json) {
    var result = json && json.chart && json.chart.result && json.chart.result[0];
    if (!result) throw new Error("Yahoo Finance returned no price data");
    var ts = result.timestamp || [], closes = (result.indicators.quote[0] || {}).close || [];
    var prices = {};
    for (var i = 0; i < ts.length; i++) {
      if (closes[i] != null) prices[iso(Math.floor(ts[i] / 86400))] = rnd(closes[i], 4);
    }
    var splits = [];
    var ev = (result.events && result.events.splits) || {};
    Object.keys(ev).forEach(function (k) {
      splits.push([iso(Math.floor(ev[k].date / 86400)), ev[k].numerator / ev[k].denominator]);
    });
    splits.sort(function (a, b) { return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0; });
    return { prices: prices, splits: splits };
  }

  function buildRecords(factsAll, nYears, prices, splits) {
    var gaap = factsAll.facts && factsAll.facts["us-gaap"];
    if (!gaap) throw new Error("No US GAAP data. This company may not file 10-Ks with XBRL (foreign filers use 20-F or 40-F).");
    var dei = factsAll.facts.dei || {};
    var endsInfo = annualEnds(gaap);
    var periods = fiscalPeriods(gaap, nYears + 1, endsInfo);

    var rev = annualFlow(gaap, REVENUE), cogs = annualFlow(gaap, COGS), gp = annualFlow(gaap, ["GrossProfit"]);
    var op = annualFlow(gaap, ["OperatingIncomeLoss"]), ni = annualFlow(gaap, ["NetIncomeLoss", "ProfitLoss"]);
    var intexp = annualFlow(gaap, INTEREST);
    var cashSti = annualInstant(gaap, ["CashCashEquivalentsAndShortTermInvestments"]);
    var cash = annualInstant(gaap, ["CashAndCashEquivalentsAtCarryingValue"]);
    var sti = annualInstant(gaap, SHORT_TERM_INVEST);
    var ar = annualInstant(gaap, ["AccountsReceivableNetCurrent"]), inv = annualInstant(gaap, ["InventoryNet"]);
    var ca = annualInstant(gaap, ["AssetsCurrent"]), ta = annualInstant(gaap, ["Assets"]);
    var cl = annualInstant(gaap, ["LiabilitiesCurrent"]), tl = annualInstant(gaap, ["Liabilities"]);
    var eq = annualInstant(gaap, EQUITY);
    var ltdNc = annualInstant(gaap, ["LongTermDebtNoncurrent"]), ltdAll = annualInstant(gaap, ["LongTermDebt"]);
    var ltdCur = annualInstant(gaap, ["LongTermDebtCurrent"]), stDebt = annualInstant(gaap, SHORT_TERM_DEBT);
    var sharesFyEnd = annualInstant(gaap, ["CommonStockSharesOutstanding"], "shares");
    var ocfS = annualFlow(gaap, OCF), capexS = annualFlow(gaap, CAPEX);
    var buybS = annualFlow(gaap, BUYBACKS), divS = annualFlow(gaap, DIVIDENDS);
    var daS = annualFlow(gaap, DEPRECIATION), pretaxS = annualFlow(gaap, PRETAX);
    var niiS = annualFlow(gaap, NII), nonintIncS = annualFlow(gaap, NONINT_INCOME);
    var nonintExpS = annualFlow(gaap, NONINT_EXPENSE);
    var depositsS = annualInstant(gaap, DEPOSITS), loansS = annualInstant(gaap, LOANS);
    var gainS = annualFlow(gaap, GAIN_ON_SALE);

    var records = [];
    periods.forEach(function (p) {
      var fy = p[0], end = p[1];
      var r = near(rev, end), c = near(cogs, end), g = near(gp, end);
      var o = near(op, end), n = near(ni, end), ie = near(intexp, end);
      var nii = near(niiS, end), nonintInc = near(nonintIncS, end), nonintExp = near(nonintExpS, end);
      if (r === null && nii !== null && nonintInc !== null) r = nii + nonintInc;
      if (g === null && r !== null && c !== null) g = r - c;
      if (c === null && r !== null && g !== null) c = r - g;

      var cs = near(cashSti, end);
      if (cs === null) {
        var a = near(cash, end), b = near(sti, end);
        cs = a === null && b === null ? null : or0(a) + or0(b);
      }
      var aR = near(ar, end), iV = near(inv, end);
      var curA = near(ca, end), totA = near(ta, end), curL = near(cl, end);
      var totL = near(tl, end), eQ = near(eq, end);
      if (totL === null && totA !== null && eQ !== null) totL = totA - eQ;

      var debt, nc = near(ltdNc, end), all = near(ltdAll, end);
      if (nc !== null) debt = nc + or0(near(ltdCur, end)) + or0(near(stDebt, end));
      else if (all !== null) debt = all + or0(near(stDebt, end));
      else debt = (or0(near(ltdCur, end)) + or0(near(stDebt, end))) || null;

      var ocf = near(ocfS, end), capex = near(capexS, end);
      capex = capex === null ? null : Math.abs(capex);
      var fcf = ocf === null || capex === null ? null : ocf - capex;
      var buyb = near(buybS, end), div = near(divS, end);
      buyb = buyb === null ? null : Math.abs(buyb);
      div = div === null ? null : Math.abs(div);
      var returned = buyb === null && div === null ? null : or0(buyb) + or0(div);
      var da = near(daS, end), pretax = near(pretaxS, end);
      var ebitda = o === null || da === null ? null : o + da;
      var deposits = near(depositsS, end), loans = near(loansS, end);
      var gain = near(gainS, end);
      var ffo = n === null || da === null ? null : n + da - or0(gain);
      var info = near(endsInfo, end) || [null, null, null];

      var rec = {
        fy: fy, period_end: end,
        filing_accn: info[2] == null ? null : info[2],
        filed: info[0] == null || info[0] === "9999" ? null : info[0],
        revenue: bn(r), cogs: bn(c), gross_profit: bn(g), operating_income: bn(o), net_income: bn(n),
        interest_expense: ie == null ? null : rnd(ie / 1e9, 3),
        cash_and_st_investments: bn(cs), receivables: bn(aR), inventories: bn(iV),
        current_assets: bn(curA), total_assets: bn(totA), current_liabilities: bn(curL),
        total_liabilities: bn(totL), total_debt: bn(debt), equity: bn(eQ),
        pretax_income: bn(pretax), operating_cash_flow: bn(ocf), capex: bn(capex), free_cash_flow: bn(fcf),
        buybacks: bn(buyb), dividends_paid: bn(div), depreciation_amortization: bn(da), ebitda: bn(ebitda),
        net_interest_income: bn(nii), noninterest_income: bn(nonintInc), noninterest_expense: bn(nonintExp),
        deposits: bn(deposits), loans: bn(loans), ffo: bn(ffo),
        current_ratio: ratio(curA, curL),
        quick_ratio: ratio(cs === null && aR === null ? null : or0(cs) + or0(aR), curL),
        cash_ratio: ratio(cs, curL),
        debt_to_equity: positive(eQ) ? ratio(debt, eQ) : null, debt_to_assets: ratio(debt, totA),
        financial_leverage: positive(eQ) ? ratio(totA, eQ) : null,
        interest_coverage: ie && ie > 0 ? ratio(o, ie, 1) : null,
        asset_turnover: ratio(r, totA),
        inventory_turnover: ratio(c, iV, 1),
        dsi: c && iV ? rnd(iV / c * 365, 1) : null,
        receivables_turnover: ratio(r, aR),
        dso: r && aR ? rnd(aR / r * 365, 1) : null,
        gross_margin: pct(g, r), operating_margin: pct(o, r), net_margin: pct(n, r),
        roa: pct(n, totA), roe: positive(eQ) ? pct(n, eQ) : null,
        equity_to_assets: pct(eQ, totA),
        tax_burden: positive(pretax) ? ratio(n, pretax, 3) : null,
        interest_burden: positive(o) ? ratio(pretax, o, 3) : null,
        fcf_margin: pct(fcf, r), capex_pct_revenue: pct(capex, r),
        cash_conversion: positive(n) ? ratio(ocf, n) : null,
        payout_ratio: positive(n) ? pct(div, n) : null,
        shareholder_return_pct_fcf: positive(fcf) ? pct(returned, fcf) : null,
        accruals_ratio: pct(n === null || ocf === null ? null : n - ocf, totA),
        revenue_growth: null, operating_income_growth: null, net_income_growth: null, fcf_growth: null,
        receivables_growth_gap: null, inventory_growth_gap: null,
        efficiency_ratio: nii !== null && nonintInc !== null ? pct(nonintExp, nii + nonintInc) : null,
        loan_to_deposit: pct(loans, deposits), nii_to_assets: pct(nii, totA),
        price: null, market_cap: null, annual_return: null,
        pe_ratio: null, price_to_sales: null, price_to_book: null, ev_to_ebitda: null,
        earnings_yield: null, dividend_yield: null, buyback_yield: null, fcf_yield: null,
        lm_polarity: null, vader: null, pos_sentences: null, neg_sentences: null,
        uncertainty_pct: null, litigious_pct: null, lm_pos_words: null, lm_neg_words: null, mda_words: null
      };

      if (prices) {
        var px = closestPrice(prices, end);
        rec.price = px === null ? null : rnd(px, 2);
        var sh = sharesAt(dei, end, sharesFyEnd);
        if (px && sh[0] && splits !== null) {   // splits === null: split history unknown, so market value would be wrong
          var mc = px * sh[0] * splitFactor(splits, sh[1]);
          rec.market_cap = rnd(mc / 1e9, 1);
          rec.pe_ratio = positive(n) ? ratio(mc, n, 1) : null;
          rec.price_to_sales = positive(r) ? ratio(mc, r) : null;
          rec.price_to_book = positive(eQ) ? ratio(mc, eQ) : null;
          var ev = mc + or0(debt) - or0(cs);
          rec.ev_to_ebitda = positive(ebitda) ? ratio(ev, ebitda, 1) : null;
          rec.earnings_yield = pct(n, mc);
          rec.dividend_yield = pct(div, mc);
          rec.buyback_yield = pct(buyb, mc);
          rec.fcf_yield = pct(fcf, mc);
        }
        var prev = records.length ? records[records.length - 1] : null;
        if (prev && prev.price && px) rec.annual_return = rnd((px / prev.price - 1) * 100, 2);
      }
      if (records.length) {
        var pv = records[records.length - 1];
        rec.revenue_growth = growth(rec.revenue, pv.revenue);
        rec.operating_income_growth = growth(rec.operating_income, pv.operating_income);
        rec.net_income_growth = growth(rec.net_income, pv.net_income);
        rec.fcf_growth = growth(rec.free_cash_flow, pv.free_cash_flow);
        var arG = growth(rec.receivables, pv.receivables), invG = growth(rec.inventories, pv.inventories);
        if (arG !== null && rec.revenue_growth !== null) rec.receivables_growth_gap = rnd(arG - rec.revenue_growth, 2);
        if (invG !== null && rec.revenue_growth !== null) rec.inventory_growth_gap = rnd(invG - rec.revenue_growth, 2);
      }
      records.push(rec);
    });
    return records.slice(-nYears);
  }

  // 'bank', 'reit' or 'operating': a rough guide to which metrics make sense.
  function classify(records, gaap) {
    var n = Math.max(1, records.length);
    var banks = records.filter(function (r) {
      return r.net_interest_income !== null && (r.deposits !== null || r.noninterest_expense !== null);
    }).length;
    if (banks * 2 >= n) return "bank";
    var prop = annualInstant(gaap, PROPERTY);
    var reits = records.filter(function (r) { return near(prop, r.period_end) !== null; }).length;
    var recentGp = records.slice(-2).some(function (r) { return r.gross_profit; });
    if (reits * 2 >= n && !recentGp) return "reit";
    return "operating";
  }

  // Quarterly revenue, operating income and net income (newest nQuarters). Q1-Q3 come from
  // 10-Q filings; Q4 is the full year minus those three.
  function buildQuarters(gaap, nQuarters) {
    nQuarters = nQuarters || 12;
    var endsInfo = annualEnds(gaap);
    var byEnd = new Map();
    fiscalPeriods(gaap, 99, endsInfo).forEach(function (p) { byEnd.set(p[1], p[0]); });
    var yearEnds = Array.from(byEnd.keys()).sort();
    var series = {
      revenue: REVENUE, operating_income: ["OperatingIncomeLoss"], net_income: ["NetIncomeLoss", "ProfitLoss"]
    };
    var keys = Object.keys(series), quarter = {}, annual = {}, qEnds = new Set();
    keys.forEach(function (key) {
      quarter[key] = new Map();
      series[key].forEach(function (concept) {
        var best = new Map();
        entries(gaap, concept).forEach(function (e) {
          if (e.form !== "10-Q" || !e.start || !e.end) return;
          var d = day(e.end) - day(e.start);
          if (d < 80 || d > 100) return;
          var filed = e.filed || "", cur = best.get(e.end);
          if (!cur || filed > cur[1]) best.set(e.end, [e.val, filed]);
        });
        best.forEach(function (v, end) { if (!quarter[key].has(end)) quarter[key].set(end, v[0]); });
      });
      annual[key] = annualFlow(gaap, series[key]);
      quarter[key].forEach(function (_, end) { qEnds.add(end); });
    });
    yearEnds.forEach(function (ye) {
      var mids = Array.from(qEnds).filter(function (e) { var d = day(ye) - day(e); return d > 30 && d < 300; }).sort().slice(-3);
      if (mids.length === 3 && day(ye) - day(mids[2]) < 130) {
        keys.forEach(function (key) {
          if (annual[key].has(ye) && mids.every(function (m) { return quarter[key].has(m); })) {
            quarter[key].set(ye, annual[key].get(ye) - mids.reduce(function (a, m) { return a + quarter[key].get(m); }, 0));
          }
        });
        qEnds.add(ye);
      }
    });
    var rows = [];
    Array.from(qEnds).sort().forEach(function (end) {
      var fy, later = yearEnds.filter(function (ye) { return ye >= end && day(ye) - day(end) < 372; });
      if (later.length) fy = byEnd.get(later[0]);
      else if (yearEnds.length && end > yearEnds[yearEnds.length - 1]) fy = byEnd.get(yearEnds[yearEnds.length - 1]) + 1;
      else return;
      var row = { fy: fy, period_end: end };
      keys.forEach(function (k) { row[k] = quarter[k].has(end) ? rnd(quarter[k].get(end) / 1e9, 3) : null; });
      rows.push(row);
    });
    rows = rows.filter(function (r) { return r.revenue !== null || r.net_income !== null; });
    var counts = {};
    rows.forEach(function (r) { counts[r.fy] = (counts[r.fy] || 0) + 1; r.q = counts[r.fy]; });
    return rows.slice(-nQuarters);
  }

  // Full company object in the same shape as data/<TICKER>.json.
  function makeCompany(opts) {
    var years = buildRecords(opts.facts, opts.years || 10, opts.prices || null, opts.splits === null ? null : (opts.splits || []));
    if (!years.length) throw new Error("No annual 10-K data found for this company.");
    return {
      ticker: opts.ticker, name: opts.name, cik: opts.cik,
      fiscal_year_end: MONTHS[+years[years.length - 1].period_end.slice(5, 7) - 1],
      generated: new Date().toISOString().slice(0, 10),
      sources: "SEC EDGAR XBRL company facts; Yahoo Finance daily closes",
      live: true,
      kind: classify(years, opts.facts.facts["us-gaap"]),
      years: years,
      quarters: buildQuarters(opts.facts.facts["us-gaap"])
    };
  }

  var api = { buildRecords: buildRecords, buildQuarters: buildQuarters, classify: classify, makeCompany: makeCompany, parseYahoo: parseYahoo, MONTHS: MONTHS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SecMetrics = api;
})(typeof window !== "undefined" ? window : globalThis);
