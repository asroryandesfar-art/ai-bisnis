"""
Capture 3 screenshots (Landing Page, Executive Center, Investor Demo) for the
BotNesia Company Profile PDF (Investor-Readiness Assets follow-up). Requires
the app server running locally on 127.0.0.1:8000 (./start_all.sh status) and
Playwright + Chromium installed (pip install --user --break-system-packages
playwright && python3 -m playwright install chromium).

Executive Center is captured by injecting a JWT directly into localStorage
(via main.create_token(), the same helper already used for live smoke tests
throughout this project) rather than automating the login form -- avoids
needing/typing a real password, and the JWT never touches disk.

Run: python3 scripts/capture_marketing_screenshots.py
Output: docs/marketing/screenshots/{landing-page,executive-center,investor-demo}.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

import main  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"
OUT_DIR = Path(__file__).parent.parent / "docs" / "marketing" / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}

# Same demo org/user ID already used for every live smoke test in this
# project this session (real seeded data, not fabricated for this script).
DEMO_USER_ID = "94d11961-9a88-4d45-a040-4995fe064c18"
DEMO_ORG_ID = "d04b5662-4118-4030-839c-013d8f0f4a5a"


def capture_landing(browser) -> None:
    page = browser.new_page(viewport=VIEWPORT)
    page.goto(f"{BASE_URL}/", wait_until="networkidle")
    page.wait_for_timeout(600)  # let scroll-reveal animations settle
    page.screenshot(path=str(OUT_DIR / "landing-page.png"))
    page.close()


def capture_investor_demo(browser) -> None:
    page = browser.new_page(viewport=VIEWPORT)
    page.goto(f"{BASE_URL}/demo", wait_until="networkidle")
    page.click("#run-demo-btn")
    page.wait_for_selector(".demo-banner", timeout=30_000)
    page.wait_for_timeout(400)
    # Anchor the viewport on the result banner + KPI scoreboard (the most
    # compelling "wow" view) rather than wherever the auto-scroll during the
    # stepper animation happened to leave the page.
    page.eval_on_selector(".demo-banner", "el => el.scrollIntoView({block: 'start'})")
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT_DIR / "investor-demo.png"))
    page.close()


def capture_executive_center(browser) -> None:
    token = main.create_token(DEMO_USER_ID, DEMO_ORG_ID)
    context = browser.new_context(viewport=VIEWPORT)
    context.add_init_script(f"window.localStorage.setItem('bn_token', '{token}');")
    page = context.new_page()
    page.goto(f"{BASE_URL}/dashboard#executive", wait_until="networkidle")
    page.wait_for_selector(".business-panel, .grid-4", timeout=20_000)
    page.wait_for_timeout(800)
    page.screenshot(path=str(OUT_DIR / "executive-center.png"))
    page.close()
    context.close()


def main_() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        capture_landing(browser)
        print(f"Wrote {OUT_DIR / 'landing-page.png'}")
        capture_investor_demo(browser)
        print(f"Wrote {OUT_DIR / 'investor-demo.png'}")
        capture_executive_center(browser)
        print(f"Wrote {OUT_DIR / 'executive-center.png'}")
        browser.close()


if __name__ == "__main__":
    main_()
