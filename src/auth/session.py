import json
import os
import threading
from pathlib import Path
from typing import Literal

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from src.auth.playwright_bootstrap import (
    browser_setup_message,
    ensure_playwright_chromium,
    is_streamlit_cloud,
    launch_chromium,
)

SELLER_CENTRAL_URL = "https://sellercentral.amazon.in"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SESSION_PATH = DATA_DIR / "sessions" / "auth_state.json"
PENDING_LOGIN_PATH = DATA_DIR / "sessions" / "login_pending_state.json"
PENDING_LOGIN_META_PATH = DATA_DIR / "sessions" / "login_pending_meta.json"

LoginPhase = Literal["complete", "otp_required"]
DEFAULT_ATSTRACK_SESSION_PATH = (
    Path(__file__).resolve().parents[3] / "atstrack" / "data" / "sessions" / "auth_state.json"
)

LOGIN_TIMEOUT_MS = 300_000
SIGNIN_STEP_TIMEOUT_MS = 60_000

BROWSER_SETUP_MESSAGE = browser_setup_message()


class BrowserNotInstalledError(RuntimeError):
    pass


class LoginError(RuntimeError):
    pass


def atstrack_session_path() -> Path:
    raw = os.environ.get("ATSTRACK_SESSION_PATH")
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_ATSTRACK_SESSION_PATH


def ensure_playwright_browser() -> None:
    try:
        ensure_playwright_chromium()
    except RuntimeError as exc:
        raise BrowserNotInstalledError(str(exc)) from exc


class SessionManager:
    _session_lock = threading.Lock()

    def __init__(self, session_path: Path | None = None) -> None:
        self.session_path = session_path or SESSION_PATH
        self.session_path.parent.mkdir(parents=True, exist_ok=True)

    def resolve_session_path(self) -> Path | None:
        if self.session_path.is_file():
            return self.session_path
        fallback = atstrack_session_path()
        if fallback.is_file():
            return fallback
        return None

    def session_source_label(self) -> str | None:
        path = self.resolve_session_path()
        if path is None:
            return None
        if path == self.session_path.resolve():
            return "local"
        return "atstrack"

    def save_storage_state(self, context: BrowserContext) -> None:
        with self._session_lock:
            context.storage_state(path=str(self.session_path))

    def has_saved_session(self) -> bool:
        return self.resolve_session_path() is not None

    def login(self) -> None:
        """Open a headed browser on your machine (ATS Track style). Local only."""
        if is_streamlit_cloud():
            raise LoginError(
                "Use the email/password sign-in form below on Streamlit Cloud."
            )
        ensure_playwright_browser()
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(SELLER_CENTRAL_URL, wait_until="domcontentloaded")
            self._wait_for_login(page)
            self.save_storage_state(context)
            browser.close()

    def has_pending_login(self) -> bool:
        return PENDING_LOGIN_PATH.is_file() and PENDING_LOGIN_META_PATH.is_file()

    def clear_pending_login(self) -> None:
        with self._session_lock:
            PENDING_LOGIN_PATH.unlink(missing_ok=True)
            PENDING_LOGIN_META_PATH.unlink(missing_ok=True)

    def login_submit_credentials(self, email: str, password: str) -> LoginPhase:
        """Step 1: email + password. Returns otp_required when Amazon prompts for OTP."""
        email = email.strip()
        if not email or not password:
            raise LoginError("Email and password are required.")

        self.clear_pending_login()
        ensure_playwright_browser()
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(SELLER_CENTRAL_URL, wait_until="domcontentloaded", timeout=SIGNIN_STEP_TIMEOUT_MS)
            page.wait_for_timeout(1500)

            if self._is_logged_in(page):
                self.save_storage_state(context)
                browser.close()
                return "complete"

            self._submit_email_and_password(page, email, password)
            self._raise_if_captcha(page)

            if self._needs_otp(page):
                self._save_pending_login(context, page.url)
                browser.close()
                return "otp_required"

            if "/ap/signin" in page.url:
                browser.close()
                raise LoginError("Sign-in failed. Check your email and password.")

            self._wait_for_login(page)
            self.save_storage_state(context)
            browser.close()
            return "complete"

    def login_submit_otp(self, otp: str) -> None:
        """Step 2: OTP after Amazon challenges following email/password."""
        otp = otp.strip()
        if not otp:
            raise LoginError("Enter the one-time password (OTP).")
        if not self.has_pending_login():
            raise LoginError("Enter your email and password first.")

        meta = json.loads(PENDING_LOGIN_META_PATH.read_text(encoding="utf-8"))
        resume_url = meta.get("url") or SELLER_CENTRAL_URL

        ensure_playwright_browser()
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=True)
            context = browser.new_context(storage_state=str(PENDING_LOGIN_PATH))
            page = context.new_page()
            page.goto(resume_url, wait_until="domcontentloaded", timeout=SIGNIN_STEP_TIMEOUT_MS)
            page.wait_for_timeout(1500)

            if not self._needs_otp(page):
                if self._is_logged_in(page):
                    self.save_storage_state(context)
                    self.clear_pending_login()
                    browser.close()
                    return
                browser.close()
                self.clear_pending_login()
                raise LoginError("OTP step expired. Enter email and password again.")

            self._submit_otp(page, otp)
            self._raise_if_captcha(page)

            if self._needs_otp(page) or "/ap/mfa" in page.url:
                browser.close()
                raise LoginError("OTP was not accepted. Try again.")

            self._wait_for_login(page)
            self.save_storage_state(context)
            self.clear_pending_login()
            browser.close()

    def _save_pending_login(self, context: BrowserContext, url: str) -> None:
        with self._session_lock:
            PENDING_LOGIN_PATH.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(PENDING_LOGIN_PATH))
            PENDING_LOGIN_META_PATH.write_text(
                json.dumps({"url": url}),
                encoding="utf-8",
            )

    def _submit_email_and_password(self, page: Page, email: str, password: str) -> None:
        email_input = page.locator("#ap_email, input[name='email']").first
        email_input.wait_for(state="visible", timeout=SIGNIN_STEP_TIMEOUT_MS)
        email_input.fill(email)
        page.locator("#continue, input#continue, button:has-text('Continue')").first.click()

        password_input = page.locator("#ap_password, input[name='password']").first
        password_input.wait_for(state="visible", timeout=SIGNIN_STEP_TIMEOUT_MS)
        password_input.fill(password)
        page.locator("#signInSubmit, input#signInSubmit, button:has-text('Sign in')").first.click()
        page.wait_for_timeout(2500)

    def _submit_otp(self, page: Page, otp: str) -> None:
        otp_input = page.locator(
            "#auth-mfa-otpcode, input[name='otpCode'], input[name='code']"
        ).first
        otp_input.wait_for(state="visible", timeout=SIGNIN_STEP_TIMEOUT_MS)
        otp_input.fill(otp)
        page.locator(
            "#auth-signin-button, input#auth-signin-button, button:has-text('Sign in')"
        ).first.click()
        page.wait_for_timeout(2500)

    def _raise_if_captcha(self, page: Page) -> None:
        if page.locator("text=/captcha|puzzle|Type the characters/i").count() > 0:
            raise LoginError(
                "Amazon showed a CAPTCHA. Sign in locally with the browser login button instead."
            )

    def _needs_otp(self, page: Page) -> bool:
        if "/ap/mfa" in page.url:
            return True
        return page.locator("#auth-mfa-otpcode, input[name='otpCode']").count() > 0

    def _wait_for_login(self, page: Page) -> None:
        page.wait_for_function(
            """() => {
                const url = window.location.href;
                const onSellerCentral = url.includes('sellercentral.amazon.in');
                const notOnSignIn = !url.includes('/ap/signin') && !url.includes('/ap/mfa');
                const hasSellerNav = document.querySelector('#sc-navbar-container, #sc-logo-top, kat-nav');
                return onSellerCentral && notOnSignIn && (hasSellerNav || url.includes('/home'));
            }""",
            timeout=LOGIN_TIMEOUT_MS,
        )

    def validate_session(self) -> bool:
        storage = self.resolve_session_path()
        if storage is None:
            return False

        try:
            ensure_playwright_browser()
            with sync_playwright() as p:
                browser = launch_chromium(p, headless=True)
                context = browser.new_context(storage_state=str(storage))
                page = context.new_page()
                page.goto(SELLER_CENTRAL_URL, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2000)
                valid = self._is_logged_in(page)
                browser.close()
                return valid
        except Exception:
            return False

    def _is_logged_in(self, page: Page) -> bool:
        url = page.url
        if "/ap/signin" in url or "/ap/mfa" in url:
            return False
        if "sellercentral.amazon.in" not in url:
            return False
        return page.locator("#sc-navbar-container, #sc-logo-top, kat-nav").count() > 0

    def new_context(self, browser: Browser) -> BrowserContext:
        storage = self.resolve_session_path()
        if storage is None:
            raise RuntimeError("No saved session. Please log in first.")
        return browser.new_context(storage_state=str(storage), accept_downloads=True)
