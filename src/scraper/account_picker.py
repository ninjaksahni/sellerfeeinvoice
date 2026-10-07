import os
import re

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

ACCOUNT_PICKER_TIMEOUT_MS = 30_000


def on_account_picker(page: Page) -> bool:
    if page.locator(".full-page-account-switcher").count() > 0:
        return True
    return page.locator("h1:has-text('Select an account')").count() > 0


def handle_account_picker(page: Page, on_progress=None) -> bool:
    """Confirm seller account selection if Amazon shows the global account picker."""
    if not on_account_picker(page):
        return False

    if on_progress:
        on_progress("Selecting seller account…")

    label = os.environ.get("SELLER_ACCOUNT_LABEL", "India").strip()
    if label:
        option = page.locator("button.full-page-account-switcher-account-details").filter(
            has_text=re.compile(rf"^{re.escape(label)}$", re.I)
        )
        if option.count() == 0:
            option = page.locator("button.full-page-account-switcher-account-details").filter(
                has_text=re.compile(re.escape(label), re.I)
            )
        if option.count() > 0:
            option.first.click()
            page.wait_for_timeout(800)

    confirm_selectors = [
        page.locator('kat-button[data-test="confirm-selection"]'),
        page.get_by_role("button", name=re.compile(r"select account", re.I)),
        page.locator("kat-button.full-page-account-switcher-button"),
    ]
    clicked = False
    for locator in confirm_selectors:
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=10_000)
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        raise RuntimeError(
            "Could not confirm seller account on the account picker page. "
            "Set SELLER_ACCOUNT_LABEL (e.g. India) and try again."
        )

    try:
        page.wait_for_function(
            "() => !document.querySelector('.full-page-account-switcher')",
            timeout=ACCOUNT_PICKER_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        page.wait_for_timeout(3000)

    page.wait_for_timeout(1500)
    return True
