from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "docs" / "architecture-diagram.html"
PNG_PATH = ROOT / "docs" / "architecture-diagram.png"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1800, "height": 2200}, device_scale_factor=1)
        page.goto(HTML_PATH.as_uri(), wait_until="networkidle")
        page.locator(".page").screenshot(path=str(PNG_PATH))
        browser.close()
    print(PNG_PATH)


if __name__ == "__main__":
    main()
