"""Drive the live UI through Playwright and capture three screenshots:

1. landing.png     — empty page, modal hidden, hint visible
2. results.png     — after typing "diabetes" and rendering 5 cards
3. modal.png       — after clicking the top card, with the detail modal open
                     including chief concern, key diagnoses, recent reports,
                     and the first linked-resource details expanded.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("/tmp/ehr-e2e")
OUT.mkdir(exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.webkit.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900},
                                  device_scale_factor=2)
        page = ctx.new_page()
        page.goto("http://127.0.0.1:8000/", wait_until="domcontentloaded")
        page.wait_for_selector("#search")
        page.screenshot(path=str(OUT / "landing.png"), full_page=False)
        print(f"saved {OUT/'landing.png'}")

        with page.expect_response(lambda r: r.url.endswith("/search"), timeout=10000):
            page.fill("#search", "diabetes")
        page.wait_for_selector("#results > li", timeout=8000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "results.png"), full_page=False)
        print(f"saved {OUT/'results.png'}")

        with page.expect_response(lambda r: "/patient/" in r.url, timeout=10000):
            page.locator("#results > li article").first.click()
        page.wait_for_selector("#modal:not([hidden])", timeout=5000)
        page.wait_for_function(
            "document.getElementById('modal-body').innerText.trim() !== 'Loading…'",
            timeout=8000,
        )
        # Expand the first linked-resource details block so the screenshot
        # shows real clinical text.
        page.locator("#modal-body details").first.locator("summary").click()
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "modal.png"), full_page=True)
        print(f"saved {OUT/'modal.png'}")

        browser.close()


if __name__ == "__main__":
    main()
