"""Verify the AI-summary button surfaces backend errors in-modal.

Without ANTHROPIC_API_KEY the POST /patient/{id}/summarize endpoint must
return a 400 with an instructive detail; the modal should render that
text in the red banner rather than crashing or silently doing nothing.
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright


def main() -> int:
    with sync_playwright() as p:
        browser = p.webkit.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900},
                                  device_scale_factor=2)
        page = ctx.new_page()
        page.goto("http://127.0.0.1:8000/", wait_until="domcontentloaded")
        page.wait_for_selector("#search")

        with page.expect_response(lambda r: r.url.endswith("/search"), timeout=10000):
            page.fill("#search", "diabetes")
        page.wait_for_selector("#results > li", timeout=8000)

        with page.expect_response(lambda r: "/patient/" in r.url and r.request.method == "GET",
                                  timeout=10000):
            page.locator("#results > li article").first.click()
        page.wait_for_selector("#modal:not([hidden])", timeout=5000)
        page.wait_for_function(
            "document.getElementById('gen-ai-btn') !== null",
            timeout=5000,
        )

        btn = page.locator("#gen-ai-btn")
        assert btn.is_visible(), "AI button not visible"
        print(f"[PASS] AI button present  ({btn.inner_text().strip()!r})")

        with page.expect_response(lambda r: "/summarize" in r.url, timeout=10000):
            btn.click()

        page.wait_for_function(
            "!document.getElementById('ai-banner').hidden",
            timeout=5000,
        )
        banner = page.locator("#ai-banner").inner_text().strip()
        print(f"[PASS] error banner shown  ({banner!r})")
        assert "ANTHROPIC_API_KEY" in banner, f"banner missing key reference: {banner}"
        print(f"[PASS] banner references ANTHROPIC_API_KEY")

        page.screenshot(path="/tmp/ehr-e2e/ai-no-key.png", full_page=False)
        print("saved /tmp/ehr-e2e/ai-no-key.png")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
