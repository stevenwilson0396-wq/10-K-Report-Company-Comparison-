#!/usr/bin/env python3
"""Run:  python tests/test_ui.py     (needs: pip install playwright && playwright install chromium)

Opens index.html in a headless browser with a mock proxy standing in for the SEC, and checks the
search, auto-update, multi-company and error paths. No network access is used.
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
URL = (ROOT / "index.html").as_uri()
bank, reit = (FIX / "bank.json").read_bytes(), (FIX / "reit.json").read_bytes()
CORS = {"access-control-allow-origin": "*"}
TICKERS = {str(i): {"cik_str": c, "ticker": t, "title": n} for i, (c, t, n) in enumerate([
    (111, "BANKCO", "Test Bank Corp"), (222, "REITCO", "Test Realty Trust"), (404, "NOFACTS", "Nodata Holdings Inc"),
    (333, "NOPX", "Pxless Inc"), (444, "ALPHA", "Alpha Industries"), (555, "ALPHB", "Alpha B Industries")])}
failures = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name, extra if not cond else "")
    if not cond:
        failures.append(name)


def wire(pg):
    pg.route("**/config.js", lambda r: r.fulfill(status=200, content_type="application/javascript", body="window.SEC_PROXY='https://sec-proxy.test';"))
    pg.route("https://sec-proxy.test/tickers", lambda r: r.fulfill(status=200, headers=CORS, content_type="application/json", body=json.dumps(TICKERS)))

    def facts(r):
        u = r.request.url
        if u.endswith("0000000404"):
            r.fulfill(status=404, headers=CORS, content_type="application/json", body='{"error":"No data found for that company."}')
        else:
            r.fulfill(status=200, headers=CORS, content_type="application/json", body=bank if u.endswith("0000000111") else reit)
    pg.route("https://sec-proxy.test/facts/*", facts)
    pg.route("https://sec-proxy.test/prices/*", lambda r: r.fulfill(status=502, headers=CORS, content_type="application/json", body='{"error":"no prices"}'))


def page(b, **kw):
    pg = b.new_context(**kw).new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    return pg


def ready(pg, suffix=""):
    pg.goto(URL + suffix)
    pg.wait_for_selector(".tile")


def loaded(pg):
    pg.wait_for_function("document.getElementById('liveMsg').textContent.startsWith('Loaded')", timeout=30000)


with sync_playwright() as p:
    b = p.chromium.launch()

    # --- every tab renders, with the bundled companies and no proxy
    pg = page(b, viewport={"width": 1280, "height": 900}); ready(pg)
    tabs = pg.eval_on_selector_all("#tabs button", "els => els.map(e => e.dataset.tab)")
    check("15 tabs", len(tabs) == 15, str(tabs))
    for t in tabs:
        pg.click(f'#tabs button[data-tab="{t}"]')
        check(f"tab {t} renders", pg.locator("#panel h2").count() > 0)
    pg.click('#tabs button[data-tab="data"]')
    check("filing links in the data table", pg.locator('a[href*="sec.gov/Archives"]').count() >= 10)
    pg.focus("#in1"); pg.fill("#in1", "zzz")
    check("hint without a proxy", "Live search is off" in pg.inner_text("#list1"))
    pg.keyboard.press("Escape")
    check("no add button when every loaded company is already chosen", pg.is_hidden("#addCo"))
    check("no page errors", not pg.errors, str(pg.errors))
    pg.context.close()

    # --- live search with the mock proxy
    pg = page(b, viewport={"width": 1280, "height": 900}); wire(pg); ready(pg)
    pg.focus("#in1"); pg.keyboard.type("alph"); pg.wait_for_timeout(200)
    txt = pg.inner_text("#list1")
    check("search finds both Alpha companies", "ALPHA" in txt and "ALPHB" in txt, txt)
    pg.fill("#in1", "bankco")
    check("numbers do not change until the pause is over", "BANKCO" not in pg.inner_text(".tile"))
    loaded(pg)
    check("auto-loaded without pressing Enter", "BANKCO" in pg.inner_text(".tile") and pg.is_visible("#list1"))
    pg.keyboard.press("Escape")
    check("Escape puts the previous company back", "BANKCO" not in pg.inner_text(".tile"))
    pg.focus("#in1"); pg.fill("#in1", "bankco"); pg.wait_for_timeout(200); pg.keyboard.press("Enter"); pg.wait_for_timeout(200)   # already loaded, so instant
    check("bank classified from live data", pg.evaluate("companies.find(c => c.ticker === 'BANKCO').kind") == "bank")
    pg.click('#tabs button[data-tab="liquidity"]')
    check("bank note on liquidity", "looks like a bank" in pg.inner_text("#panel"))
    pg.click('#tabs button[data-tab="quarterly"]')
    check("quarterly charts for live company", pg.locator(".card svg.chart path.ln, .card svg.chart path.bar").count() > 0)
    check("tone button offered for live company", pg.locator('button:has-text("Score MD&A tone")').count() == 1)
    pg.mouse.click(5, 5); pg.click("#addCo"); pg.wait_for_selector("#in2")
    check("third picker added", pg.locator(".company-fields input").count() == 3 and pg.locator("button.x").count() == 3)
    pg.keyboard.press("Escape"); pg.mouse.click(5, 5)
    pg.click('button[aria-label="Remove company C"]')
    check("remove works", pg.locator(".company-fields input").count() == 2)
    pg.focus("#in0"); pg.fill("#in0", "nofacts"); pg.keyboard.press("Enter"); pg.wait_for_timeout(700)
    check("company with no SEC data says so", "no financial data" in pg.inner_text("#liveMsg"))
    pg.focus("#in0"); pg.fill("#in0", "nopx"); loaded(pg)
    check("missing prices warn but load", "Share prices were not available" in pg.inner_text("#liveMsg"))
    for _ in range(3):
        if pg.is_visible("#addCo"):
            pg.keyboard.press("Escape"); pg.mouse.click(5, 5)   # close the new box's list first
            pg.click("#addCo")
    check("add button hides at five", pg.locator(".company-fields input").count() == 5 and pg.is_hidden("#addCo"))
    link = pg.evaluate("location.hash")
    check("link lists the chosen companies and skips the empty box", link.count("%2C") == 3 and "NOPX" in link, link)
    check("no page errors (live)", not pg.errors, str(pg.errors))
    pg.context.close()

    # --- a shared link restores a live company
    pg = page(b, viewport={"width": 1280, "height": 900}); wire(pg)
    pg.goto(URL + "#cos=AAPL,REITCO&tab=sector")
    pg.wait_for_function("document.querySelectorAll('.company-fields input')[1] && document.querySelectorAll('.company-fields input')[1].value.includes('REITCO:')", timeout=30000)
    pg.wait_for_selector(".card")
    check("link restores REITCO", pg.evaluate("companies.some(c => c.ticker === 'REITCO' && c.kind === 'reit')"))
    check("FFO chart has data", pg.locator(".no-data").count() < 10)
    pg.context.close()
    # same link, no proxy: falls back to bundled companies
    pg = page(b, viewport={"width": 1280, "height": 900}); ready(pg, "#cos=AAPL,REITCO,MSFT")
    check("unknown company without proxy is dropped", pg.eval_on_selector_all(".company-fields input", "e => e.map(x => x.value.split(':')[0])") == ["AAPL", "MSFT"])
    pg.context.close()

    # --- phone, dark: no sideways scroll with five companies
    pg = page(b, viewport={"width": 390, "height": 844}, color_scheme="dark"); wire(pg); ready(pg, "#cos=AAPL,MSFT")
    for _ in range(3):
        pg.keyboard.press("Escape"); pg.mouse.click(5, 5)
        pg.click("#addCo")
    check("phone: no horizontal scroll", not pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"))
    pg.click('#tabs button[data-tab="profitability"]')
    check("phone: charts fit", not pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"))
    pg.context.close()
    b.close()

print("\n" + (f"{len(failures)} FAILURES: {failures}" if failures else "ALL UI TESTS PASSED"))
sys.exit(1 if failures else 0)
