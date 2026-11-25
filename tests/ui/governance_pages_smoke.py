"""Browser smoke test for the six Phase 04 governance pages.

Run manually with the Streamlit server on port 8501 and full mode enabled::

    python tests/ui/governance_pages_smoke.py
"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.getenv("CLARO_UI_URL", "http://localhost:8501")
SCREENSHOT = Path(__file__).resolve().parents[2] / "data" / "claro-governance-ui.png"
NAV_ITEMS = (
    "总览",
    "Policy Center",
    "Moderation Workbench",
    "Governance Decisions",
    "Enforcement Center",
    "Feedback & Audit",
)


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
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=_browser_executable()
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="light")
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("text=合成数据演示", timeout=30_000)

        last_error = {"text": ""}
        page.on(
            "console",
            lambda message: last_error.update(text=message.text)
            if message.type == "error"
            else None,
        )
        for item in NAV_ITEMS:
            page.get_by_text(item, exact=True).first.click()
            page.wait_for_timeout(2_500)
            body = page.locator("body").inner_text()
            failure_index = body.find("页面渲染失败")
            if failure_index >= 0:
                detail = body[failure_index : failure_index + 800]
                raise AssertionError(f"{item} failed to render: {detail}")
            assert "Traceback" not in body, f"{item} raised a traceback"
            assert "合成数据演示" in body
            print(f"[OK] {item}")

        page.screenshot(path=str(SCREENSHOT), full_page=True)
        browser.close()
    if errors:
        raise AssertionError("browser errors: " + "; ".join(errors))
    print(f"All {len(NAV_ITEMS)} governance pages rendered. Screenshot: {SCREENSHOT}")


if __name__ == "__main__":
    main()
