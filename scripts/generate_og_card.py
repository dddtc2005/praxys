"""Render Praxys OG cards to PNG via headless Chromium.

Sources:
  - web/public/og-card.html          -> web/public/og-card.png          (1200x630, 2x)
  - web/public/og-card-wechat.html   -> web/public/og-card-wechat.png   (1080x864, 2x)

The 1200x630 card is the canonical OpenGraph / Twitter card. The 1080x864
(5:4) card is used as a WeChat chat-bubble-optimized image and is also
bundled into the WeChat Mini Program for onShareAppMessage.

Run: python scripts/generate_og_card.py

Requires: playwright (see requirements.txt) + `playwright install chromium`.
Idempotent - re-running produces the same PNGs for the same HTML.
"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_PUBLIC = REPO_ROOT / "web" / "public"

CARDS = [
    # (source_html, output_png, width, height)
    ("og-card.html",        "og-card.png",        1200, 630),
    ("og-card-wechat.html", "og-card-wechat.png", 1080, 864),
]


def render_card(page, source_html: Path, output_png: Path, width: int, height: int) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(source_html.as_uri())
    # Wait for web fonts to actually be ready - without this the screenshot
    # occasionally catches a fallback system font mid-swap.
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(200)  # small settle for gradient paint
    page.screenshot(path=str(output_png), omit_background=False, full_page=False)
    print(f"  {output_png.relative_to(REPO_ROOT)}  ({width}x{height})")


def main() -> None:
    print("Rendering OG cards...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # device_scale_factor=2 -> crisp on retina/2x displays.
        context = browser.new_context(device_scale_factor=2)
        page = context.new_page()
        for source, output, w, h in CARDS:
            render_card(page, WEB_PUBLIC / source, WEB_PUBLIC / output, w, h)
        browser.close()
    print("Done.")


if __name__ == "__main__":
    main()
