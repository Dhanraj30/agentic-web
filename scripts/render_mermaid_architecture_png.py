from pathlib import Path
import functools
import http.server
import socketserver
import threading
import time

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "docs" / "architecture-diagram-mermaid.html"
PNG_PATH = ROOT / "docs" / "architecture-diagram-mermaid.png"
ULTRA_PNG_PATH = ROOT / "docs" / "architecture-diagram-mermaid-ultra.png"
SVG_PATH = ROOT / "docs" / "architecture-diagram-mermaid.svg"


def main() -> None:
    class Handler(http.server.SimpleHTTPRequestHandler):
        extensions_map = {
            **http.server.SimpleHTTPRequestHandler.extensions_map,
            ".mjs": "text/javascript",
            ".js": "text/javascript",
        }

        def log_message(self, format: str, *args) -> None:
            return

    handler = functools.partial(Handler, directory=str(ROOT))
    server = socketserver.TCPServer(("127.0.0.1", 5179), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 4200, "height": 3200}, device_scale_factor=5)
            page.on("console", lambda msg: print(f"console[{msg.type}]: {msg.text}"))
            page.on("pageerror", lambda exc: print(f"pageerror: {exc}"))
            page.goto("http://127.0.0.1:5179/docs/architecture-diagram-mermaid.html", wait_until="networkidle")
            page.wait_for_selector(".mermaid svg", timeout=30000)
            svg = page.locator(".mermaid svg").evaluate("node => node.outerHTML")
            SVG_PATH.write_text(svg, encoding="utf-8")
            page.locator(".wrap").screenshot(path=str(PNG_PATH))
            page.locator(".wrap").screenshot(path=str(ULTRA_PNG_PATH))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(PNG_PATH)


if __name__ == "__main__":
    main()
