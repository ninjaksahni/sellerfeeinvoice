import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Error as PlaywrightError, Playwright, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANAGED_BROWSERS_DIR = PROJECT_ROOT / ".playwright-browsers"

SYSTEM_CHROMIUM_PATHS = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
)

CONTAINER_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
]

LOCAL_SETUP_MESSAGE = (
    "Playwright browser is not installed. Run this in your terminal:\n\n"
    "  source .venv/bin/activate\n"
    "  unset PLAYWRIGHT_BROWSERS_PATH\n"
    "  playwright install chromium\n\n"
    "Or run: bash scripts/setup.sh"
)

CLOUD_SETUP_MESSAGE = (
    "Chromium is not available on this Streamlit Cloud machine. "
    "Redeploy the app so `packages.txt` installs the system `chromium` package, "
    "then reboot the app. If it still fails, run the app locally."
)


def is_streamlit_cloud() -> bool:
    if os.environ.get("STREAMLIT_RUNTIME_ENV") == "cloud":
        return True
    if os.environ.get("IS_STREAMLIT_CLOUD", "").lower() in ("1", "true", "yes"):
        return True
    return Path("/mount/src").is_dir()


def find_system_chromium() -> Path | None:
    for path in SYSTEM_CHROMIUM_PATHS:
        candidate = Path(path)
        if candidate.is_file():
            return candidate
    return None


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
    if is_streamlit_cloud():
        env.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    elif not env.get("PLAYWRIGHT_BROWSERS_PATH"):
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(managed_browsers_dir())
    return env


def _launch_kwargs(headless: bool) -> dict[str, Any]:
    env = playwright_env()
    kwargs: dict[str, Any] = {"headless": headless, "env": env}
    if is_streamlit_cloud():
        system_chromium = find_system_chromium()
        if system_chromium is None:
            raise RuntimeError(CLOUD_SETUP_MESSAGE)
        kwargs["executable_path"] = str(system_chromium)
        kwargs["args"] = CONTAINER_CHROMIUM_ARGS
    return kwargs


def launch_chromium(playwright: Playwright, headless: bool = True) -> Browser:
    return playwright.chromium.launch(**_launch_kwargs(headless))


def _try_launch_bundled() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, env=playwright_env())
        browser.close()


def _install_bundled_chromium() -> None:
    env = playwright_env()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = env["PLAYWRIGHT_BROWSERS_PATH"]
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        env=env,
        check=True,
        timeout=600,
    )


def ensure_playwright_chromium() -> None:
    """Verify Chromium is usable (system binary on Cloud, bundled install locally)."""
    if is_streamlit_cloud():
        if find_system_chromium() is None:
            raise RuntimeError(CLOUD_SETUP_MESSAGE)
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=True)
            browser.close()
        return

    env = playwright_env()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = env.get("PLAYWRIGHT_BROWSERS_PATH", "")

    try:
        _try_launch_bundled()
        return
    except PlaywrightError as exc:
        if "Executable doesn't exist" not in str(exc):
            raise

    try:
        _install_bundled_chromium()
        _try_launch_bundled()
    except (PlaywrightError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(LOCAL_SETUP_MESSAGE) from exc


def browser_setup_message() -> str:
    return CLOUD_SETUP_MESSAGE if is_streamlit_cloud() else LOCAL_SETUP_MESSAGE
