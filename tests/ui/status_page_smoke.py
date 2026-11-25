from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8501"
EXPECTED_MODE = os.getenv("CLARO_UI_EXPECT_MODE", "development")
SCREENSHOT = Path(__file__).resolve().parents[2] / "data" / "claro-status.png"


def _browser_executable() -> str | None:
    configured = os.getenv("CLARO_UI_BROWSER_PATH")
    if configured:
        return configured
    candidates = (
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    )
    return next((str(path) for path in candidates if path.is_file()), None)


def main() -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=_browser_executable())
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="light")
        page.on(
            "console", lambda message: _capture_error(message.type, message.text, console_errors)
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("text=Connection successful")
        body_text = page.locator("body").inner_text()
        expected_text = (
            ("Claro", "full", "kafka", "postgresql", "redis", "healthy")
            if EXPECTED_MODE == "full"
            else (
                "Claro",
                "development",
                "in-memory-simulation",
                "sqlite",
                "healthy",
                "redis",
                "disabled",
                "kafka",
            )
        )
        for expected in expected_text:
            assert expected in body_text, f"Missing expected text: {expected}"
        assert "TypeError" not in body_text
        assert "Traceback" not in body_text
        assert page.title() == "Claro"
        background = page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--background-color').trim()"
        )
        assert background == "#FFFFFF"
        SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SCREENSHOT), full_page=True)
        page.close()

        dark_page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        dark_page.on(
            "console",
            lambda message: _capture_error(message.type, message.text, console_errors),
        )
        dark_page.on("pageerror", lambda error: page_errors.append(str(error)))
        dark_page.goto(URL, wait_until="networkidle")
        dark_page.wait_for_selector("text=Connection successful")
        dark_background = dark_page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--background-color').trim()"
        )
        assert dark_background == "#0F172A"
        dark_page.close()
        browser.close()

    if console_errors or page_errors:
        raise AssertionError(
            f"Browser errors found. console={console_errors!r}, page={page_errors!r}"
        )
    print(f"UI smoke test passed. Screenshot: {SCREENSHOT}")


def _capture_error(message_type: str, message: str, errors: list[str]) -> None:
    if message_type == "error":
        errors.append(message)


if __name__ == "__main__":
    main()
