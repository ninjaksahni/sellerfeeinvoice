import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANAGED_BROWSERS_DIR = PROJECT_ROOT / ".playwright-browsers"

LOCAL_SETUP_MESSAGE = (
    "Playwright browser is not installed. Run this in your terminal:\n\n"
    "  source .venv/bin/activate\n"
    "  unset PLAYWRIGHT_BROWSERS_PATH\n"
    "  playwright install chromium\n\n"
    "Or run: bash scripts/setup.sh"
)

CLOUD_SETUP_MESSAGE = (
    "Playwright Chromium could not be installed on this server. "
    "Streamlit Cloud needs `packages.txt` in the repo (already included) and a cold-start "
    "browser download on first use — wait a few minutes and retry. "
    "If it still fails, run the app locally instead."
)


def is_streamlit_cloud() -> bool:
    if os.environ.get("STREAMLIT_RUNTIME_ENV") == "cloud":
        return True
    if os.environ.get("IS_STREAMLIT_CLOUD", "").lower() in ("1", "true", "yes"):
        return True
    return Path("/mount/src").is_dir()


def managed_browsers_dir() -> Path:
    MANAGED_BROWSERS_DIR.mkdir(parents=True, exist_ok=True)
    return MANAGED_BROWSERS_DIR


def _clear_sandbox_browser_path() -> None:
    current = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if "cursor-sandbox-cache" in current:
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)


def playwright_env() -> dict[str, str]:
    _clear_sandbox_browser_path()
    env = os.environ.copy()
    if not env.get("PLAYWRIGHT_BROWSERS_PATH"):
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(managed_browsers_dir())
    return env


def _try_launch() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, env=playwright_env())
        browser.close()


def _install_chromium() -> None:
    env = playwright_env()
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        env=env,
        check=True,
        timeout=600,
    )


def ensure_playwright_chromium() -> None:
    """Ensure Chromium is available (auto-install for Streamlit Cloud / fresh deploys)."""
    env = playwright_env()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = env["PLAYWRIGHT_BROWSERS_PATH"]

    try:
        _try_launch()
        return
    except PlaywrightError as exc:
        if "Executable doesn't exist" not in str(exc):
            raise

    try:
        _install_chromium()
        _try_launch()
    except (PlaywrightError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        message = CLOUD_SETUP_MESSAGE if is_streamlit_cloud() else LOCAL_SETUP_MESSAGE
        raise RuntimeError(message) from exc


def browser_setup_message() -> str:
    return CLOUD_SETUP_MESSAGE if is_streamlit_cloud() else LOCAL_SETUP_MESSAGE
