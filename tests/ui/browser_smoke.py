"""Real-browser smoke test for every Claro screen (manual, not pytest).

``tests/ui/test_screens_smoke.py`` renders the screens through Streamlit's
``AppTest`` harness, which catches Python-level failures but not browser-side
ones (broken HTML strings, unreadable dark-mode text, a chart that draws an
empty box). This script drives the real Chrome binary against a running server
and checks both colour schemes.

Pages are reached through their ``st.navigation`` URL path, which is the same
route a bookmarked link uses; the sidebar is checked separately to prove the
menu lists every page.

Run it with the app already started::

    scripts\\start_app.ps1
    .venv\\Scripts\\python.exe tests\\ui\\browser_smoke.py
    .venv\\Scripts\\python.exe tests\\ui\\browser_smoke.py --screenshots

Exit code is 1 if any page reports a render error, a traceback, a missing menu
entry, or a browser console error.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHOT_DIR = PROJECT_ROOT / "docs" / "screenshots"

# (label, url_path) mirroring ``claro.ui.app.NAVIGATION``.
PAGES: tuple[tuple[str, str], ...] = (
    ("治理总览", ""),
    ("消息探查", "messages"),
    ("审核工作台", "moderation"),
    ("治理决策", "decisions"),
    ("处置中心", "enforcement"),
    ("策略中心", "policy"),
    ("风险情报", "risk-intelligence"),
    ("分析总览", "analytics"),
    ("风险分析", "analytics-risk"),
    ("社区分析", "analytics-community"),
    ("治理分析", "analytics-governance"),
    ("模型分析", "analytics-model"),
    ("策略评估", "analytics-strategy"),
    ("反馈与审计", "audit"),
    ("系统设置", "settings"),
)

# Streamlit serves the default page when a URL does not match a registered
# route, so a missing route must be treated as a failure instead of a pass.
FAILURE_MARKERS = (
    "页面渲染失败",
    "Traceback",
    "KeyError",
    "AttributeError",
    "does not seem to exist",
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


def _slug(label: str) -> str:
    return {
        "治理总览": "overview",
        "消息探查": "message-explorer",
        "审核工作台": "moderation-workbench",
        "治理决策": "governance-decisions",
        "处置中心": "enforcement-center",
        "策略中心": "policy-center",
        "风险情报": "risk-intelligence",
        "分析总览": "analytics-overview",
        "风险分析": "analytics-risk",
        "社区分析": "analytics-community",
        "治理分析": "analytics-governance",
        "模型分析": "analytics-model",
        "策略评估": "analytics-strategy",
        "反馈与审计": "feedback-audit",
        "系统设置": "settings",
    }[label]


# Streamlit's frontend asks for its health endpoint relative to the current URL,
# so a deep link such as /analytics also requests /analytics/_stcore/health and
# gets a 404. The page itself is unaffected (verified by the body checks), so
# only that specific asset noise is filtered; every other console error fails.
BENIGN_ASSET_PATHS = ("_stcore/health", "_stcore/host-config")


def _record_console(message, sink: list[str]) -> None:
    if message.type != "error":
        return
    url = (message.location or {}).get("url", "")
    if any(fragment in url for fragment in BENIGN_ASSET_PATHS):
        return
    sink.append(f"{message.text} ({url})" if url else message.text)


def _check_body(page, label: str) -> None:
    body = page.locator("body").inner_text()
    for marker in FAILURE_MARKERS:
        if marker in body:
            index = body.find(marker)
            raise AssertionError(f"{label}: found {marker!r}: {body[index : index + 400]}")
    if "合成数据演示" not in body:
        raise AssertionError(f"{label}: sidebar identity missing, page did not finish loading")


def _check_menu(page) -> None:
    """Every page must be reachable from the sidebar.

    Streamlit collapses the tail of a nav menu behind "View N more", so the menu
    is checked once as-is and once after expanding, instead of assuming that all
    fifteen labels are painted at once.
    """
    body = page.locator("body").inner_text()
    missing = [label for label, _ in PAGES if label not in body]
    if missing:
        more = page.get_by_text(re.compile(r"View \d+ more"))
        if more.count():
            more.first.click()
            page.wait_for_timeout(1000)
            body = page.locator("body").inner_text()
            missing = [label for label, _ in PAGES if label not in body]
    if missing:
        raise AssertionError(f"sidebar menu is missing: {missing}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8501")
    parser.add_argument("--screenshots", action="store_true", help="also write docs/screenshots")
    parser.add_argument("--wait", type=int, default=3000, help="ms to wait after each page load")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    errors: list[str] = []
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=_browser_executable())
        if args.screenshots:
            SHOT_DIR.mkdir(parents=True, exist_ok=True)

        for scheme in ("light", "dark"):
            page = browser.new_page(viewport={"width": 1560, "height": 1100}, color_scheme=scheme)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: _record_console(message, console_errors))
            page.goto(base, wait_until="networkidle")
            page.wait_for_selector("text=合成数据演示", timeout=60_000)
            page.wait_for_timeout(args.wait)
            _check_menu(page)
            print(f"[OK] {scheme:5s} sidebar menu lists all {len(PAGES)} pages", flush=True)

            for label, path in PAGES:
                page.goto(f"{base}/{path}" if path else base, wait_until="networkidle")
                page.wait_for_timeout(args.wait)
                _check_body(page, f"{label} [{scheme}]")
                print(f"[OK] {scheme:5s} {label}", flush=True)
                if args.screenshots:
                    target = SHOT_DIR / f"{_slug(label)}-{scheme}.png"
                    page.screenshot(path=str(target), full_page=True)
            page.close()
        browser.close()

    if errors:
        raise AssertionError("browser page errors: " + "; ".join(errors[:5]))
    if console_errors:
        raise AssertionError("browser console errors: " + "; ".join(console_errors[:5]))
    print(f"All {len(PAGES)} screens rendered in both colour schemes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
