import re
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

SIGNIN_STEP_TIMEOUT_MS = 90_000
DEBUG_DIR = Path(__file__).resolve().parents[2] / "data" / "debug"

CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

AMAZON_IN_SIGNIN_URL = (
    "https://www.amazon.in/ap/signin"
    "?openid.pape.max_auth_age=0"
    "&openid.return_to=https%3A%2F%2Fsellercentral.amazon.in%2Fhome"
    "&openid.identity=http://specs.openid.net/auth/2.0/identifier_select"
    "&openid.assoc_handle=sc_in_amazon_v2"
    "&openid.mode=form"
    "&openid.claimed_id=http://specs.openid.net/auth/2.0/identifier_select"
    "&openid.ns=http://specs.openid.net/auth/2.0"
)

SIGN_IN_READY_SELECTOR = (
    "#ap_email, input[name='email'], input[type='email'], "
    "#ap_password, input[name='password'], "
    "#auth-mfa-otpcode, #cvf_input_code, input[name='otpCode']"
)

EMAIL_SELECTOR = (
    "#ap_email, input[name='email'], input[type='email'], "
    "input[autocomplete='username'], #ap_email_login"
)


def auth_context_options() -> dict:
    return {
        "user_agent": CHROME_USER_AGENT,
        "viewport": {"width": 1365, "height": 900},
        "locale": "en-IN",
        "timezone_id": "Asia/Kolkata",
        "extra_http_headers": {"Accept-Language": "en-IN,en;q=0.9"},
    }


def dump_login_debug(page: Page, tag: str) -> None:
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / f"login_{tag}.html").write_text(page.content(), encoding="utf-8")
        (DEBUG_DIR / f"login_{tag}.url.txt").write_text(page.url, encoding="utf-8")
    except Exception:
        pass


def read_auth_error(page: Page) -> str | None:
    selectors = (
        "#auth-error-message-box",
        "#auth-email-invalid-claim-alert",
        "#auth-password-missing-alert",
        ".a-alert-content",
        "#ap_error_page_message",
    )
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            text = locator.first.inner_text().strip()
        except Exception:
            continue
        if text and len(text) < 500:
            return " ".join(text.split())
    return None


def on_sign_in_flow(page: Page) -> bool:
    url = page.url.lower()
    if "/ap/signin" in url or "/ap/mfa" in url or "/ap/cvf" in url:
        return True
    if page.locator(SIGN_IN_READY_SELECTOR).count() > 0:
        return True
    return False


def needs_otp(page: Page) -> bool:
    url = page.url.lower()
    if "/ap/mfa" in url or "/ap/cvf" in url:
        return True
    otp_selectors = (
        "#auth-mfa-otpcode",
        "input[name='otpCode']",
        "input[name='code']",
        "#cvf_input_code",
        "input[autocomplete='one-time-code']",
    )
    for selector in otp_selectors:
        if page.locator(selector).count() > 0:
            return True
    if page.locator("text=/one.time password|two.step verification|enter otp/i").count() > 0:
        return True
    return False


def has_captcha(page: Page) -> bool:
    return page.locator("text=/captcha|puzzle|type the characters you see/i").count() > 0


def try_send_otp(page: Page) -> None:
    patterns = [
        page.get_by_role("button", name=re.compile(r"send\s*otp|send\s*code|text\s*me", re.I)),
        page.locator("input[type='submit']").filter(
            has_text=re.compile(r"send|text|otp|code", re.I)
        ),
        page.locator("a, button, span").filter(has_text=re.compile(r"send\s*otp", re.I)),
    ]
    for locator in patterns:
        if locator.count() == 0:
            continue
        try:
            candidate = locator.first
            if candidate.is_visible():
                candidate.click(timeout=5000)
                page.wait_for_timeout(2000)
                return
        except Exception:
            continue


def wait_after_password_submit(page: Page) -> None:
    try:
        page.wait_for_function(
            """() => {
                const url = location.href.toLowerCase();
                if (url.includes('/ap/mfa') || url.includes('/ap/cvf')) return true;
                if (document.querySelector('#auth-mfa-otpcode, #cvf_input_code, input[name="otpCode"]')) {
                    return true;
                }
                if (document.querySelector('#auth-error-message-box, .a-alert-content')) return true;
                if (url.includes('sellercentral.amazon.in')
                    && !url.includes('/ap/signin')
                    && !url.includes('/ap/mfa')) return true;
                return false;
            }""",
            timeout=25_000,
        )
    except PlaywrightTimeoutError:
        page.wait_for_timeout(3000)


def wait_for_sign_in_ready(page: Page) -> None:
    try:
        page.wait_for_selector(
            SIGN_IN_READY_SELECTOR,
            state="visible",
            timeout=SIGNIN_STEP_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        dump_login_debug(page, "signin_form_timeout")
        msg = read_auth_error(page)
        hint = (
            f"Amazon sign-in form did not appear (page: {page.url}). "
            "Streamlit Cloud IPs are often blocked — log in on your Mac with "
            "`bash scripts/launch.sh` and **Login to Seller Central** instead."
        )
        if msg:
            hint = f"{hint} Amazon said: {msg}"
        raise ValueError(hint)


def prepare_sign_in_page(page: Page, handle_account_picker) -> None:
    """Navigate to a page where email/password or OTP can be entered."""
    urls = [
        AMAZON_IN_SIGNIN_URL,
        "https://sellercentral.amazon.in/ap/signin",
        "https://sellercentral.amazon.in/home",
    ]
    for url in urls:
        page.goto(url, wait_until="domcontentloaded", timeout=SIGNIN_STEP_TIMEOUT_MS)
        page.wait_for_timeout(2500)
        try:
            handle_account_picker(page)
        except Exception:
            pass
        page.wait_for_timeout(1000)
        if on_sign_in_flow(page):
            wait_for_sign_in_ready(page)
            return
        sign_in_link = page.get_by_role("link", name=re.compile(r"log\s*in|sign\s*in", re.I))
        if sign_in_link.count() > 0:
            try:
                sign_in_link.first.click(timeout=5000)
                page.wait_for_load_state("domcontentloaded", timeout=SIGNIN_STEP_TIMEOUT_MS)
                page.wait_for_timeout(2000)
            except Exception:
                pass
        if on_sign_in_flow(page):
            wait_for_sign_in_ready(page)
            return

    wait_for_sign_in_ready(page)


def _click_continue(page: Page) -> None:
    for locator in (
        page.locator("#continue"),
        page.locator("input#continue"),
        page.get_by_role("button", name=re.compile(r"continue", re.I)),
    ):
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=5000)
            return
        except Exception:
            continue


def _fill_email_if_needed(page: Page, email: str) -> None:
    email_input = page.locator(EMAIL_SELECTOR).first
    try:
        email_input.wait_for(state="visible", timeout=8000)
    except PlaywrightTimeoutError:
        return

    try:
        current = email_input.input_value()
        if current.strip():
            return
    except Exception:
        pass

    email_input.fill(email)
    _click_continue(page)
    page.wait_for_timeout(2000)


def submit_email_and_password(page: Page, email: str, password: str) -> None:
    wait_for_sign_in_ready(page)

    if needs_otp(page):
        return

    _fill_email_if_needed(page, email)

    password_input = page.locator("#ap_password, input[name='password']").first
    password_input.wait_for(state="visible", timeout=SIGNIN_STEP_TIMEOUT_MS)
    password_input.fill(password)

    for locator in (
        page.locator("#signInSubmit"),
        page.locator("input#signInSubmit"),
        page.get_by_role("button", name=re.compile(r"sign\s*in", re.I)),
        page.locator("input[type='submit']"),
    ):
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=5000)
            break
        except Exception:
            continue

    wait_after_password_submit(page)


def submit_otp(page: Page, otp: str) -> None:
    otp_selectors = (
        "#auth-mfa-otpcode",
        "input[name='otpCode']",
        "input[name='code']",
        "#cvf_input_code",
        "input[autocomplete='one-time-code']",
    )
    otp_input = None
    for selector in otp_selectors:
        locator = page.locator(selector)
        if locator.count() > 0:
            otp_input = locator.first
            break
    if otp_input is None:
        raise ValueError("OTP field not found on page.")

    otp_input.wait_for(state="visible", timeout=SIGNIN_STEP_TIMEOUT_MS)
    otp_input.fill(otp)
    page.locator(
        "#auth-signin-button, input#auth-signin-button, #cvf-submit-otp-button, "
        "button:has-text('Sign in'), input[type='submit']"
    ).first.click()
    wait_after_password_submit(page)
