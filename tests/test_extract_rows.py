from pathlib import Path

from playwright.sync_api import sync_playwright

from src.scraper.fee_invoices import EXTRACT_ROWS_JS

DEBUG_HTML = (
    Path(__file__).resolve().parents[1] / "data" / "debug" / "fee_invoices_no_rows.html"
)


def test_extract_rows_from_saved_page() -> None:
    if not DEBUG_HTML.is_file():
        return

    html = DEBUG_HTML.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="domcontentloaded")
        rows = page.evaluate(EXTRACT_ROWS_JS)
        browser.close()

    assert len(rows) > 0
    assert rows[0]["invoiceNumber"] == "KA-2627-2138450"
    assert rows[0]["endDateRaw"] == "Wed Sep 30 17:30:00 UTC 2026"
