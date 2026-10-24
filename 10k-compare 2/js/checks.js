/*
 * Sanity checks on a company's yearly records. They catch the kinds of mistakes that come
 * from XBRL tagging quirks (a unit change, a missing year, a wrong tag), not judgement calls.
 * Returns a list of { fy, message }. An empty list means nothing looked wrong.
 *
 * Works in a browser (window.SecChecks) and in Node (module.exports).
 */
(function (root) {
  "use strict";

  function num(x) { return typeof x === "number" && isFinite(x); }

  function checkRecords(years) {
    var out = [];
    function add(r, msg) { out.push({ fy: r.fy, message: msg }); }
    years.forEach(function (r, i) {
      if (num(r.revenue) && r.revenue < 0) add(r, "Revenue is negative.");
      if (num(r.revenue) && num(r.gross_profit) && r.revenue > 0 && r.gross_profit > r.revenue * 1.001)
        add(r, "Gross profit is larger than revenue.");
      if (num(r.current_assets) && num(r.total_assets) && r.current_assets > r.total_assets * 1.001)
        add(r, "Current assets are larger than total assets.");
      if (num(r.cash_and_st_investments) && num(r.total_assets) && r.cash_and_st_investments > r.total_assets * 1.001)
        add(r, "Cash is larger than total assets.");
      if (num(r.total_debt) && num(r.total_assets) && r.total_assets > 0 && r.total_debt > r.total_assets * 1.5)
        add(r, "Debt is more than 1.5 times total assets. Check the debt tags.");
      if (num(r.total_assets) && num(r.total_liabilities) && num(r.equity) && r.total_assets > 0) {
        var gap = Math.abs(r.total_assets - r.total_liabilities - r.equity) / r.total_assets;
        if (gap > 0.05) add(r, "Liabilities plus equity differ from total assets by " + Math.round(gap * 100) +
          "%. The company may report minority interest or redeemable equity separately.");
      }
      if (num(r.revenue_growth) && (r.revenue_growth > 300 || r.revenue_growth < -70))
        add(r, "Revenue changed by " + Math.round(r.revenue_growth) + "% in one year. Check for an acquisition, a unit change or a tagging change.");
      if (num(r.free_cash_flow) && num(r.operating_cash_flow) && r.free_cash_flow > r.operating_cash_flow + 1e-9)
        add(r, "Free cash flow is larger than operating cash flow.");
      if (num(r.current_ratio) && r.current_ratio > 100) add(r, "Current ratio is above 100. Check the liabilities tag.");
      if (i > 0 && r.fy - years[i - 1].fy > 1) add(r, "No data for FY" + (years[i - 1].fy + 1) + (r.fy - years[i - 1].fy > 2 ? " onward" : "") + ".");
    });
    return out;
  }

  var api = { checkRecords: checkRecords };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SecChecks = api;
})(typeof window !== "undefined" ? window : globalThis);
