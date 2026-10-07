from datetime import date

import streamlit as st

from src.auth.playwright_bootstrap import ensure_playwright_chromium, is_streamlit_cloud
from src.auth.session import (
    BROWSER_SETUP_MESSAGE,
    BrowserNotInstalledError,
    LoginError,
    SessionManager,
)
from src.scraper.fee_invoices import FeeInvoiceScraper, SessionExpiredError
from src.services.zip_bundle import ZipEntry, build_zip_bytes

st.set_page_config(page_title="Seller Fee Invoices", page_icon="📄", layout="centered")

MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

session_manager = SessionManager()
scraper = FeeInvoiceScraper(session_manager)


def init_session_state() -> None:
    if "session_valid" not in st.session_state:
        st.session_state.session_valid = None
    if "last_zip" not in st.session_state:
        st.session_state.last_zip = None
    if "last_zip_name" not in st.session_state:
        st.session_state.last_zip_name = None
    if "last_errors" not in st.session_state:
        st.session_state.last_errors = []
    if "last_warnings" not in st.session_state:
        st.session_state.last_warnings = []
    if "cloud_login_phase" not in st.session_state:
        st.session_state.cloud_login_phase = "credentials"


def check_session() -> bool:
    if not session_manager.has_saved_session():
        st.session_state.session_valid = False
        return False
    if st.session_state.session_valid is None:
        st.session_state.session_valid = session_manager.validate_session()
    return bool(st.session_state.session_valid)


def has_session_file() -> bool:
    return session_manager.has_saved_session()


def session_status_text() -> str:
    try:
        if not has_session_file():
            return "No saved session"
        source = session_manager.session_source_label()
        if check_session():
            return f"Logged in ({source} session)"
        if source == "atstrack":
            return "ATS Track session on disk (re-validate or log in here to refresh)"
        return f"Session may be expired ({source} file present)"
    except Exception as exc:
        return f"Session status unavailable ({exc})"


def render_sidebar() -> None:
    st.sidebar.header("Seller Central")
    st.sidebar.caption(session_status_text())

    if not is_streamlit_cloud():
        try:
            ensure_playwright_chromium()
        except RuntimeError as exc:
            st.sidebar.warning(str(exc))

    if is_streamlit_cloud():
        pending_otp = session_manager.has_pending_login()
        if pending_otp:
            st.session_state.cloud_login_phase = "otp"

        if st.session_state.cloud_login_phase == "otp":
            st.sidebar.info("Amazon sent an OTP. Enter it below.")
            with st.sidebar.form("cloud_login_otp"):
                otp = st.text_input("One-time password (OTP)", type="password")
                otp_submitted = st.form_submit_button("Verify OTP", use_container_width=True)
            if st.sidebar.button("Start over", use_container_width=True):
                session_manager.clear_pending_login()
                st.session_state.cloud_login_phase = "credentials"
                st.rerun()
            if otp_submitted:
                with st.spinner("Verifying OTP…"):
                    try:
                        session_manager.login_submit_otp(otp)
                        st.session_state.session_valid = True
                        st.session_state.cloud_login_phase = "credentials"
                        st.sidebar.success("Login successful!")
                        st.rerun()
                    except BrowserNotInstalledError:
                        st.sidebar.error("Playwright browser not installed.")
                        st.sidebar.code(BROWSER_SETUP_MESSAGE, language="bash")
                    except LoginError as exc:
                        st.sidebar.error(str(exc))
                    except Exception as exc:
                        st.sidebar.error(f"Login failed: {exc}")
        else:
            st.sidebar.warning(
            "Amazon often blocks sign-in from Streamlit Cloud (no OTP). "
            "Reliable option: run locally with `bash scripts/launch.sh` → Login to Seller Central."
        )
        st.sidebar.caption("Step 1: email and password")
            with st.sidebar.form("cloud_login_credentials"):
                email = st.text_input("Email", autocomplete="username")
                password = st.text_input("Password", type="password", autocomplete="current-password")
                cred_submitted = st.form_submit_button("Continue", use_container_width=True)
            if cred_submitted:
                with st.spinner("Signing in…"):
                    try:
                        phase = session_manager.login_submit_credentials(email, password)
                        if phase == "otp_required":
                            st.session_state.cloud_login_phase = "otp"
                            st.sidebar.success(
                                "Password accepted. Amazon should send an OTP — enter it in step 2."
                            )
                            st.rerun()
                        st.session_state.session_valid = True
                        st.session_state.cloud_login_phase = "credentials"
                        st.sidebar.success("Login successful!")
                        st.rerun()
                    except BrowserNotInstalledError:
                        st.sidebar.error("Playwright browser not installed.")
                        st.sidebar.code(BROWSER_SETUP_MESSAGE, language="bash")
                    except LoginError as exc:
                        st.sidebar.error(str(exc))
                    except Exception as exc:
                        st.sidebar.error(f"Login failed: {exc}")
    elif st.sidebar.button("Login to Seller Central", use_container_width=True):
        with st.spinner("Opening browser for login…"):
            try:
                session_manager.login()
                st.session_state.session_valid = True
                st.sidebar.success("Login successful!")
                st.rerun()
            except BrowserNotInstalledError:
                st.sidebar.error("Playwright browser not installed.")
                st.sidebar.code(BROWSER_SETUP_MESSAGE, language="bash")
            except LoginError as exc:
                st.sidebar.error(str(exc))
            except Exception as exc:
                st.sidebar.error(f"Login failed: {exc}")

    if has_session_file() and st.sidebar.button("Re-validate session", use_container_width=True):
        st.session_state.session_valid = session_manager.validate_session()
        st.rerun()


def main() -> None:
    init_session_state()
    if is_streamlit_cloud():
        try:
            ensure_playwright_chromium()
        except RuntimeError as exc:
            st.error(str(exc))

    render_sidebar()

    st.title("Seller Fee Invoice Downloader")
    st.markdown(
        "Download PDF seller fee invoices from "
        "[Seller Central](https://sellercentral.amazon.in/tax/seller-fee-invoices) "
        "for a calendar month (matched on invoice **End Date**, UTC)."
    )

    today = date.today()
    col_month, col_year = st.columns(2)
    with col_month:
        month_label = st.selectbox("Month", MONTH_NAMES, index=today.month - 1)
        month = MONTH_NAMES.index(month_label) + 1
    with col_year:
        year = st.number_input(
            "Year",
            min_value=2015,
            max_value=today.year,
            value=today.year,
            step=1,
        )

    session_ok = has_session_file()
    if not session_ok:
        st.info("Log in via the sidebar (same flow as ATS Track).")
    elif not check_session():
        st.warning("Session may be stale. Try **Re-validate session** or log in again.")

    if st.button("Download invoices", type="primary", disabled=not session_ok):
        st.session_state.last_zip = None
        st.session_state.last_zip_name = None
        st.session_state.last_errors = []
        st.session_state.last_warnings = []

        status = st.status("Starting download…", expanded=True)
        progress_slot = st.empty()

        def on_progress(message: str) -> None:
            status.write(message)
            progress_slot.caption(message)

        try:
            result = scraper.download_month(int(year), month, on_progress=on_progress)
            st.session_state.last_errors = result.errors
            st.session_state.last_warnings = result.warnings

            if result.warnings:
                for warning in result.warnings:
                    status.write(f"⚠️ {warning}")

            if not result.files:
                status.update(label="No invoices found", state="error")
                if result.errors:
                    for err in result.errors:
                        st.error(err)
                else:
                    st.warning(f"No invoices with End Date in {year}-{month:02d}.")
            else:
                entries = [ZipEntry(f.filename, f.data) for f in result.files]
                zip_name = f"seller-fee-invoices_{year:04d}-{month:02d}.zip"
                st.session_state.last_zip = build_zip_bytes(entries)
                st.session_state.last_zip_name = zip_name
                status.update(
                    label=f"Downloaded {len(result.files)} PDF(s)",
                    state="complete",
                )
        except SessionExpiredError as exc:
            st.session_state.session_valid = False
            status.update(label="Session expired", state="error")
            st.error(str(exc))
        except BrowserNotInstalledError:
            status.update(label="Browser not installed", state="error")
            st.error(BROWSER_SETUP_MESSAGE)
        except Exception as exc:
            status.update(label="Download failed", state="error")
            st.error(str(exc))

    if st.session_state.last_errors:
        with st.expander("Download errors", expanded=True):
            for err in st.session_state.last_errors:
                st.write(err)

    if st.session_state.last_warnings:
        with st.expander("Warnings"):
            for warning in st.session_state.last_warnings:
                st.write(warning)

    if st.session_state.last_zip and st.session_state.last_zip_name:
        st.download_button(
            label="Save ZIP file",
            data=st.session_state.last_zip,
            file_name=st.session_state.last_zip_name,
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
