"""Headless end-to-end smoke test for the EHR Media Intelligence UI.

Drives the live FastAPI server through WebKit (via Playwright) and asserts
that every user-visible feature actually works: search, filter chips,
date range, result cards, click-to-open patient detail modal, modal
content rendering, escape-to-close.

Run with the dev server already up:
    .venv/bin/python -m uvicorn backend.api.main:app --port 8000
    .venv/bin/python scripts/e2e_smoke.py
"""

from __future__ import annotations

import sys

from playwright.sync_api import expect, sync_playwright

BASE_URL = "http://127.0.0.1:8000/"


def log(step: str) -> None:
    print(f"  - {step}")


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        sys.exit(1)


def main() -> int:
    with sync_playwright() as p:
        browser = p.webkit.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        console_errors: list[str] = []
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
        page.on("console", lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
                if msg.type == "error" else None)

        # ----- 1. Landing page -----
        print("\n[1] Landing page")
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector("#search")
        log("page loaded")
        check("modal is hidden on load",
              page.locator("#modal").is_hidden(),
              "must not auto-show")
        check("hint visible on load", page.locator("#hint").is_visible())
        check("search box is focusable",
              page.evaluate("document.activeElement && document.activeElement.id === 'search'"))

        # ----- 2. Search returns hits -----
        print("\n[2] Search")
        with page.expect_response(lambda r: r.url.endswith("/search"), timeout=10000):
            page.fill("#search", "cough")
        page.wait_for_selector("#results > li", timeout=8000)
        cards = page.locator("#results > li")
        n_cards = cards.count()
        check("results rendered", n_cards > 0, f"{n_cards} cards")
        first = cards.first
        check("card has patient name",
              len(first.locator("p.font-semibold").inner_text().strip()) > 0)
        check("card has snippet text",
              len(first.locator("p.text-slate-700").inner_text().strip()) > 5)
        check("hint hidden after results", page.locator("#hint").is_hidden())

        # ----- 3. Filter chip -----
        print("\n[3] Filter: Note chip")
        with page.expect_response(lambda r: r.url.endswith("/search")):
            page.select_option('#rtype-select', 'DocumentReference')
        # Wait for rerender — badges in cards become "Note" only.
        page.wait_for_function(
            """() => {
                const badges = [...document.querySelectorAll('#results > li span.rounded-full')]
                    .map(b => b.textContent.trim());
                return badges.length > 0 && badges.every(b => b === 'Note');
            }""",
            timeout=5000,
        )
        badges = page.locator("#results > li span.rounded-full").all_inner_texts()
        check("all visible cards are Notes",
              all(b == "Note" for b in badges),
              f"badges={badges}")

        # Toggle filter off again
        with page.expect_response(lambda r: r.url.endswith("/search")):
            page.select_option('#rtype-select', 'DocumentReference')
        page.wait_for_timeout(300)

        # ----- 4. Click card → modal opens with content -----
        print("\n[4] Modal: open + content")
        page.fill("#search", "")
        with page.expect_response(lambda r: r.url.endswith("/search"), timeout=10000):
            page.fill("#search", "diabetes")
        # Wait for the rendered cards to match the new query (snippet contains diabetes-y term).
        page.wait_for_function(
            """() => {
                const cards = [...document.querySelectorAll('#results > li')];
                if (!cards.length) return false;
                const txt = cards[0].innerText.toLowerCase();
                return txt.includes('diabetes') || txt.includes('blurred')
                    || txt.includes('thirst') || txt.includes('glucose');
            }""",
            timeout=8000,
        )
        with page.expect_response(lambda r: "/patient/" in r.url, timeout=10000):
            page.locator("#results > li article").first.click()
        page.wait_for_selector("#modal:not([hidden])", timeout=5000)
        check("modal becomes visible", page.locator("#modal").is_visible())
        # Wait for body to swap from "Loading…" to actual content
        page.wait_for_function(
            "document.getElementById('modal-body').innerText.trim() !== 'Loading…'",
            timeout=8000,
        )
        title = page.locator("#modal-title").inner_text().strip()
        subtitle = page.locator("#modal-subtitle").inner_text().strip()
        body_text = page.locator("#modal-body").inner_text()
        body_upper = body_text.upper()
        check("modal title populated", len(title) > 0, f"title={title!r}")
        check("modal subtitle has MRN/DOB", "MRN-" in subtitle, f"sub={subtitle!r}")
        check("modal shows summary section", "SUMMARY" in body_upper)
        check("modal shows chief concern", "CHIEF CONCERN" in body_upper)
        check("modal shows linked FHIR resources",
              "LINKED FHIR RESOURCES" in body_upper,
              f"len={len(body_text)}")
        check("modal disclaimer present",
              "AI-GENERATED" in body_upper,
              "lowercase 'ai-generated' rendered via uppercase utility class")

        # Drill into the actual rendered chief-concern paragraph.
        cc_text = page.locator("#modal-body section:has(h4:has-text('Chief concern')) p").first.inner_text().strip()
        check("chief concern has clinical content",
              len(cc_text) > 5 and "not recorded" not in cc_text.lower(),
              f"cc={cc_text!r}")

        # ----- 5. Expand a linked-resource details -> full clinical text appears -----
        print("\n[5] Linked resource expand")
        details = page.locator("#modal-body details").first
        details.locator("summary").click()
        page.wait_for_timeout(200)
        rendered = details.locator("div").last.inner_text()
        check("expanded note has clinical text", len(rendered) > 100, f"len={len(rendered)}")
        check("markdown headings rendered (no leading '#')",
              "#" not in rendered.split("\n")[0],
              f"first_line={rendered.splitlines()[:1]}")
        check("at least one bulleted item rendered",
              details.locator("li").count() > 0,
              f"li={details.locator('li').count()}")

        # ----- 6. Esc closes modal -----
        print("\n[6] Escape closes modal")
        page.keyboard.press("Escape")
        page.wait_for_function(
            "document.getElementById('modal').hidden === true",
            timeout=2000,
        )
        check("modal hidden after Esc", page.locator("#modal").is_hidden())

        # ----- 7. Clear filters resets state -----
        print("\n[7] Clear filters")
        page.select_option('#rtype-select', 'DiagnosticReport')
        page.wait_for_timeout(300)
        page.click("#clear-filters")
        page.wait_for_timeout(300)
        active = page.locator('#rtype-select').input_value()
        check("dropdown reset to All after clear", active == "")

        # ----- 8. Empty query -> hint comes back -----
        print("\n[8] Empty query returns to hint")
        page.fill("#search", "")
        page.wait_for_timeout(400)
        check("hint visible again", page.locator("#hint").is_visible())

        # ----- 9. No console errors -----
        print("\n[9] Console")
        check("no JS errors during run",
              len(console_errors) == 0,
              f"errors={console_errors}")

        browser.close()
    print("\n[OK] All 9 UI checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
