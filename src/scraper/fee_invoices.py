import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Union

from playwright.sync_api import Frame, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from src.auth.session import SessionManager, ensure_playwright_browser
from src.auth.playwright_bootstrap import launch_chromium
from src.scraper.account_picker import handle_account_picker, on_account_picker
from src.utils.dates import end_date_in_month, first_day_of_month_utc, parse_end_date_utc

FEE_INVOICES_URL = "https://sellercentral.amazon.in/tax/seller-fee-invoices"
PAGE_TIMEOUT_MS = 60_000
TABLE_WAIT_TIMEOUT_S = 120
DOWNLOAD_TIMEOUT_MS = 90_000
MAX_LOAD_MORE = 50
LOAD_MORE_ROW_WAIT_S = 12
ROW_DELAY_S = 1.0
DEBUG_DIR = Path(__file__).resolve().parents[2] / "data" / "debug"

InvoiceRoot = Union[Page, Frame]

EXTRACT_ROWS_JS = """
() => {
  const rows = [];
  for (const tr of document.querySelectorAll('table tbody tr')) {
    const btn = tr.querySelector('button[data-invoice][data-enddate]');
    if (!btn) continue;
    const infoCells = Array.from(tr.querySelectorAll('td.info')).map((td) =>
      (td.innerText || '').replace(/\\s+/g, ' ').trim()
    );
    const invoiceNumber = btn.getAttribute('data-invoice') || infoCells[2] || '';
    if (!invoiceNumber) continue;
    rows.push({
      invoiceType: infoCells[0] || '',
      fileType: infoCells[1] || btn.getAttribute('data-filetype') || 'PDF',
      invoiceNumber,
      startDateRaw: infoCells[8] || '',
      endDateRaw: btn.getAttribute('data-enddate') || infoCells[9] || '',
    });
  }
  return rows;
}
"""


class FeeInvoiceScraperError(Exception):
    pass


class SessionExpiredError(FeeInvoiceScraperError):
    pass


@dataclass
class InvoiceRow:
    invoice_type: str
    file_type: str
    invoice_number: str
    end_date_raw: str
    end_date: datetime


@dataclass
class DownloadedInvoice:
    filename: str
    data: bytes
    invoice_number: str


@dataclass
class ScrapeResult:
    files: list[DownloadedInvoice] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    matched_count: int = 0


ProgressCallback = Callable[[str], None]


class FeeInvoiceScraper:
    def __init__(self, session_manager: SessionManager | None = None) -> None:
        self.session_manager = session_manager or SessionManager()
        self._root: InvoiceRoot | None = None

    def download_month(
        self,
        year: int,
        month: int,
        on_progress: ProgressCallback | None = None,
    ) -> ScrapeResult:
        if not self.session_manager.has_saved_session():
            raise SessionExpiredError("No saved session. Please log in first.")

        ensure_playwright_browser()
        headless = os.environ.get("HEADED_DOWNLOAD", "").strip() not in ("1", "true", "yes")
        result = ScrapeResult()
        self._root = None

        def progress(msg: str) -> None:
            if on_progress:
                on_progress(msg)

        with sync_playwright() as p:
            browser = launch_chromium(p, headless=headless)
            context = self.session_manager.new_context(browser)
            page = context.new_page()

            try:
                progress("Opening Seller Fee Invoices page…")
                self._goto_fee_invoices(page, progress)
                self._root = self._wait_for_invoice_table(page, progress)
                self._ensure_logged_in(page)

                progress("Loading invoice history…")
                warning = self._load_until_month(page, year, month, on_progress)
                if warning:
                    result.warnings.append(warning)

                raw_rows = self._extract_rows()
                if not raw_rows:
                    self._dump_debug(page, "no_rows")
                    raise FeeInvoiceScraperError(
                        "Could not read invoice table. Amazon may have changed the page layout."
                    )

                matches = self._filter_rows(raw_rows, year, month)
                result.matched_count = len(matches)
                progress(f"Found {len(matches)} invoice(s) for {year}-{month:02d}")

                seen: set[str] = set()
                for index, row in enumerate(matches, start=1):
                    if row.invoice_number in seen:
                        continue
                    seen.add(row.invoice_number)
                    progress(f"Downloading {index}/{len(matches)}: {row.invoice_number}")
                    try:
                        data = self._download_pdf(page, context, row.invoice_number)
                        filename = self._pdf_filename(year, month, row.invoice_type, row.invoice_number)
                        result.files.append(
                            DownloadedInvoice(
                                filename=filename,
                                data=data,
                                invoice_number=row.invoice_number,
                            )
                        )
                    except Exception as exc:
                        result.errors.append(f"{row.invoice_number}: {exc}")
                    time.sleep(ROW_DELAY_S)
            except SessionExpiredError:
                raise
            except FeeInvoiceScraperError:
                raise
            except Exception as exc:
                self._dump_debug(page, "unexpected")
                raise FeeInvoiceScraperError(str(exc)) from exc
            finally:
                browser.close()

        return result

    def _goto_fee_invoices(self, page: Page, progress: ProgressCallback) -> None:
        page.goto(FEE_INVOICES_URL, wait_until="commit", timeout=PAGE_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(1500)

        if handle_account_picker(page, on_progress=progress):
            progress("Opening Seller Fee Invoices page…")
            page.goto(FEE_INVOICES_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            page.wait_for_timeout(2000)
            if on_account_picker(page):
                handle_account_picker(page, on_progress=progress)
                page.goto(FEE_INVOICES_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                page.wait_for_timeout(2000)

    def _find_invoice_root(self, page: Page) -> InvoiceRoot | None:
        if page.locator("button[data-invoice][data-enddate]").count() > 0:
            return page
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                if frame.locator("button[data-invoice][data-enddate]").count() > 0:
                    return frame
            except Exception:
                continue
        return None

    def _wait_for_invoice_table(self, page: Page, progress: ProgressCallback) -> InvoiceRoot:
        deadline = time.time() + TABLE_WAIT_TIMEOUT_S
        attempt = 0
        while time.time() < deadline:
            attempt += 1
            self._ensure_logged_in(page)
            if on_account_picker(page):
                handle_account_picker(page, on_progress=progress)
                page.goto(FEE_INVOICES_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                page.wait_for_timeout(2000)
            root = self._find_invoice_root(page)
            if root is not None:
                rows = root.evaluate(EXTRACT_ROWS_JS)
                if rows:
                    progress(f"Invoice table ready ({len(rows)} row(s) visible).")
                    return root
            if attempt == 1 or attempt % 4 == 0:
                progress(f"Waiting for invoice table… ({attempt})")
            page.wait_for_timeout(2000)

        self._dump_debug(page, "timeout")
        if on_account_picker(page):
            raise FeeInvoiceScraperError(
                "Stuck on Amazon's account picker. Set SELLER_ACCOUNT_LABEL=India "
                "(or your marketplace name) and retry, or pick the account in the "
                "browser with HEADED_DOWNLOAD=1."
            )
        raise FeeInvoiceScraperError(
            "Timed out waiting for the invoice table. Log in again, or set "
            "HEADED_DOWNLOAD=1 to see what the browser shows."
        )

    def _ensure_logged_in(self, page: Page) -> None:
        url = page.url
        if "/ap/signin" in url or "/ap/mfa" in url or "/ap/cvf" in url:
            raise SessionExpiredError("Session expired. Please log in again.")

    def _extract_rows(self) -> list[dict]:
        if self._root is None:
            return []
        return self._root.evaluate(EXTRACT_ROWS_JS)

    def _filter_rows(self, raw_rows: list[dict], year: int, month: int) -> list[InvoiceRow]:
        matches: list[InvoiceRow] = []
        for raw in raw_rows:
            try:
                end_date = parse_end_date_utc(raw["endDateRaw"])
            except ValueError:
                continue
            if not end_date_in_month(end_date, year, month):
                continue
            matches.append(
                InvoiceRow(
                    invoice_type=raw.get("invoiceType", "invoice"),
                    file_type=raw.get("fileType", "PDF"),
                    invoice_number=raw["invoiceNumber"],
                    end_date_raw=raw["endDateRaw"],
                    end_date=end_date,
                )
            )
        return matches

    def _oldest_end_date(self, raw_rows: list[dict]) -> datetime | None:
        oldest: datetime | None = None
        for raw in raw_rows:
            try:
                end_date = parse_end_date_utc(raw["endDateRaw"])
            except ValueError:
                continue
            if oldest is None or end_date < oldest:
                oldest = end_date
        return oldest

    def _load_until_month(
        self,
        page: Page,
        year: int,
        month: int,
        on_progress: ProgressCallback | None,
    ) -> str | None:
        target_start = first_day_of_month_utc(year, month)
        warning: str | None = None

        for attempt in range(MAX_LOAD_MORE + 1):
            raw_rows = self._extract_rows()
            oldest = self._oldest_end_date(raw_rows)
            if oldest is not None and oldest < target_start:
                break

            load_more = self._load_more_locator(page)
            if load_more is None:
                break

            if attempt == MAX_LOAD_MORE:
                warning = (
                    f"Stopped after {MAX_LOAD_MORE} Load More clicks; "
                    "older invoices may be missing."
                )
                break

            if on_progress:
                on_progress(f"Loading older invoices… ({attempt + 1})")

            previous_count = len(raw_rows)
            try:
                load_more.scroll_into_view_if_needed()
                load_more.click(timeout=10_000)
            except PlaywrightTimeoutError:
                break

            deadline = time.time() + LOAD_MORE_ROW_WAIT_S
            while time.time() < deadline:
                page.wait_for_timeout(500)
                if len(self._extract_rows()) > previous_count:
                    break

        return warning

    def _load_more_locator(self, page: Page):
        patterns = [
            page.get_by_role("button", name=re.compile(r"load\s*more", re.I)),
            page.locator("button, kat-button, a").filter(has_text=re.compile(r"load\s*more", re.I)),
        ]
        for locator in patterns:
            if locator.count() == 0:
                continue
            candidate = locator.first
            try:
                if candidate.is_visible() and candidate.is_enabled():
                    return candidate
            except Exception:
                continue
        return None

    def _row_view_button(self, invoice_number: str):
        if self._root is None:
            raise FeeInvoiceScraperError("Invoice table not loaded")
        view = self._root.locator(f'button[data-invoice="{invoice_number}"]')
        if view.count() == 0:
            row = self._root.locator("table tbody tr").filter(has_text=invoice_number).first
            view = row.get_by_role("button", name=re.compile(r"view", re.I))
        return view.first

    def _download_pdf(self, page: Page, context, invoice_number: str) -> bytes:
        view = self._row_view_button(invoice_number)
        view.scroll_into_view_if_needed()
        pages_before = len(context.pages)

        try:
            with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
                view.click()
            path = download_info.value.path()
            if path:
                return Path(path).read_bytes()
        except PlaywrightTimeoutError:
            pass

        new_page = None
        if len(context.pages) > pages_before:
            new_page = context.pages[-1]
        else:
            try:
                with context.expect_page(timeout=15_000) as page_info:
                    view.click()
                new_page = page_info.value
            except PlaywrightTimeoutError:
                raise FeeInvoiceScraperError("Could not download PDF (no download or viewer tab)")

        new_page.wait_for_load_state("domcontentloaded", timeout=PAGE_TIMEOUT_MS)

        try:
            with new_page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
                new_page.get_by_role("link", name=re.compile(r"download|pdf", re.I)).first.click(
                    timeout=5_000
                )
            path = download_info.value.path()
            if path:
                data = Path(path).read_bytes()
                new_page.close()
                return data
        except Exception:
            pass

        if new_page.url.lower().endswith(".pdf") or "pdf" in new_page.url.lower():
            response = new_page.request.get(new_page.url)
            if response.ok:
                data = response.body()
                new_page.close()
                return data

        new_page.close()
        raise FeeInvoiceScraperError("Could not download PDF (no download event or PDF URL)")

    def _pdf_filename(self, year: int, month: int, invoice_type: str, invoice_number: str) -> str:
        type_slug = re.sub(r"[^\w.-]+", "_", invoice_type.strip())[:50] or "invoice"
        number_slug = re.sub(r"[^\w.-]+", "_", invoice_number.strip())
        return f"{year:04d}-{month:02d}_{type_slug}_{number_slug}.pdf"

    def _dump_debug(self, page: Page, tag: str) -> None:
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            path = DEBUG_DIR / f"fee_invoices_{tag}.html"
            path.write_text(page.content(), encoding="utf-8")
        except Exception:
            pass
