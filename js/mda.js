/*
 * Finds Item 7 (Management's Discussion and Analysis) in a 10-K's HTML and counts its words.
 * This is a port of extract_mda() and the word-list part of score_text() in pipeline/add_company.py,
 * so a company scored in the browser gets the same MD&A length, uncertainty share and litigious
 * share as one added with the script. The Loughran-McDonald polarity and VADER scores need
 * dictionaries that are not bundled here, so those are only available from the script.
 *
 * Works in a browser (window.SecMda) and in Node (module.exports).
 */
(function (root) {
  "use strict";

  // Same lists as UNCERTAINTY_WORDS and LITIGIOUS_WORDS in add_company.py (tests/test_mda.js checks they match).
  var UNCERTAINTY = new Set(["anticipate", "anticipated", "anticipates", "anticipating", "anticipation", "approximate", "approximately", "approximation", "arbitrary", "assume", "assumed", "assumes", "assuming", "assumption", "assumptions", "believe", "believed", "believes", "believing", "contingencies", "contingency", "contingent", "depend", "depended", "dependence", "dependent", "depending", "depends", "fluctuate", "fluctuated", "fluctuates", "fluctuating", "fluctuation", "fluctuations", "indefinite", "indefinitely", "pending", "predict", "predicted", "predicting", "prediction", "predicts", "preliminary", "probability", "probable", "probably", "risk", "risks", "risky", "uncertain", "uncertainties", "uncertainty", "unclear", "unforeseen", "unpredictable", "variability", "variable", "variables", "volatile", "volatility"]);
  var LITIGIOUS = new Set(["allegation", "allegations", "allege", "alleged", "alleges", "alleging", "arbitration", "arbitrator", "claim", "claimant", "claimants", "claims", "counterclaim", "counterclaims", "court", "defendant", "defendants", "dispute", "disputed", "disputes", "infringe", "infringed", "infringement", "infringes", "infringing", "investigation", "investigations", "judgment", "judgments", "jurisdiction", "lawsuit", "lawsuits", "legal", "legislation", "litigate", "litigated", "litigating", "litigation", "litigious", "plaintiff", "plaintiffs", "pleading", "pleadings", "proceeding", "proceedings", "prosecute", "prosecuted", "prosecution", "regulatory", "settle", "settled", "settlement", "subpoena", "tribunal"]);

  var NAMED = { nbsp: "\u00a0", amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", ndash: "\u2013", mdash: "\u2014",
    lsquo: "\u2018", rsquo: "\u2019", ldquo: "\u201c", rdquo: "\u201d", hellip: "\u2026", bull: "\u2022", middot: "\u00b7",
    trade: "\u2122", reg: "\u00ae", copy: "\u00a9", deg: "\u00b0", times: "\u00d7", sect: "\u00a7", para: "\u00b6",
    eacute: "\u00e9", egrave: "\u00e8", aacute: "\u00e1", oacute: "\u00f3", uacute: "\u00fa", iacute: "\u00ed",
    ntilde: "\u00f1", ccedil: "\u00e7", uuml: "\u00fc", ouml: "\u00f6", auml: "\u00e4", euro: "\u20ac", pound: "\u00a3",
    yen: "\u00a5", cent: "\u00a2", frac12: "\u00bd", frac14: "\u00bc", frac34: "\u00be", larr: "\u2190", rarr: "\u2192",
    thinsp: "\u2009", ensp: "\u2002", emsp: "\u2003", zwnj: "\u200c", zwj: "\u200d", shy: "\u00ad", laquo: "\u00ab", raquo: "\u00bb" };

  function unescapeHtml(text) {
    return text.replace(/&(?:#(\d+)|#[xX]([0-9a-fA-F]+)|([A-Za-z][A-Za-z0-9]*));?/g, function (m, dec, hex, name) {
      try {
        if (dec) return String.fromCodePoint(+dec);
        if (hex) return String.fromCodePoint(parseInt(hex, 16));
      } catch (e) { return m; }
      return Object.prototype.hasOwnProperty.call(NAMED, name) ? NAMED[name] : m;
    });
  }

  function cleanHtmlToText(content) {
    var text = content
      .replace(/<ix:hidden[\s\S]*?<\/ix:hidden>/gi, "")
      .replace(/<style[\s\S]*?<\/style>/gi, "")
      .replace(/<script[\s\S]*?<\/script>/gi, "")
      .replace(/<xml[\s\S]*?<\/xml>/gi, "")
      .replace(/<(p|div|tr|br|h[1-6]|li)\b[^>]*>/gi, "\n")
      .replace(/<[^>]+>/g, " ");
    text = unescapeHtml(text).replace(/\u00a0/g, " ").replace(/\u200b/g, " ");
    return text.split("\n").map(function (ln) { return ln.replace(/\s+/g, " ").trim(); })
      .filter(function (ln) { return ln; }).join("\n");
  }

  var ITEM7_START = /^\s*item\s*7\s*[.:\-\u2013\u2014]?\s*management/gim;
  var ITEM7_END = /^\s*item\s*(7a|8)\s*[.:\-\u2013\u2014]?\s*(quantitative|financial|consolidated)/gim;

  // The text of Item 7. The longest candidate wins, so one-line table-of-contents entries are ignored.
  function extractMda(html) {
    var text = cleanHtmlToText(html), best = "", m;
    ITEM7_START.lastIndex = 0;
    while ((m = ITEM7_START.exec(text)) !== null) {
      ITEM7_END.lastIndex = ITEM7_START.lastIndex;
      var end = ITEM7_END.exec(text);
      if (end && end.index - m.index > best.length) best = text.slice(m.index, end.index);
      if (m.index === ITEM7_START.lastIndex) ITEM7_START.lastIndex++;
    }
    if (!best) throw new Error("could not locate Item 7 (MD&A)");
    return best;
  }

  function wordShares(text) {
    var words = (text.match(/\b[a-zA-Z]{2,}\b/g) || []).map(function (w) { return w.toLowerCase(); });
    var total = words.length, unc = 0, lit = 0;
    words.forEach(function (w) { if (UNCERTAINTY.has(w)) unc++; if (LITIGIOUS.has(w)) lit++; });
    return {
      mda_words: total,
      uncertainty_pct: total ? Number((unc / total * 100).toFixed(3)) : null,
      litigious_pct: total ? Number((lit / total * 100).toFixed(3)) : null
    };
  }

  var api = { cleanHtmlToText: cleanHtmlToText, extractMda: extractMda, wordShares: wordShares, UNCERTAINTY: UNCERTAINTY, LITIGIOUS: LITIGIOUS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SecMda = api;
})(typeof window !== "undefined" ? window : globalThis);
