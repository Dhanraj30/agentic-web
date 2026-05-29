"""
Browser Tool — AgenticWeb
Playwright-based browser automation for the MCP tool layer.
"""
from __future__ import annotations
import logging
import os

logger = logging.getLogger(__name__)

_pw = None
_browser = None
_page = None


async def _get_page():
    global _pw, _browser, _page
    if _page is None or _page.is_closed():
        from playwright.async_api import async_playwright
        headless = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
        slow_mo = int(os.getenv("BROWSER_SLOW_MO_MS", "0"))
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(headless=headless, slow_mo=slow_mo)
        ctx = await _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
        )
        ctx.set_default_timeout(8000)
        _page = await ctx.new_page()
    return _page


async def page_state() -> str:
    page = await _get_page()
    title = await page.title()
    url = page.url
    text = await _visible_text(page, limit=2500)
    return f"[{title}]\nURL: {url}\n\n{text}"


async def navigate(url: str) -> str:
    page = await _get_page()
    try:
        if url and not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    try:
        title = await page.title()
        content = await _visible_text(page)
        return f"[{title}]\nURL: {page.url}\n\n{content}"
    except Exception as e:
        return f"Error navigating to {url}: {e}"


async def click(target: str) -> str:
    page = await _get_page()
    candidates = [
        lambda: page.get_by_role("button", name=target, exact=False).first.click(),
        lambda: page.get_by_role("link", name=target, exact=False).first.click(),
        lambda: page.get_by_label(target, exact=False).first.click(),
        lambda: page.get_by_text(target, exact=False).first.click(),
        lambda: page.click(target),
    ]
    try:
        for attempt in candidates:
            try:
                await attempt()
                await page.wait_for_timeout(800)
                return f"Clicked: {target}"
            except Exception:
                continue
        return f"Could not click '{target}': no matching visible element"
    except Exception as e:
        return f"Could not click '{target}': {e}"


async def type_text(selector: str, text: str) -> str:
    page = await _get_page()
    candidates = [
        lambda: page.fill(selector, text),
        lambda: page.get_by_placeholder(selector, exact=False).fill(text),
        lambda: page.get_by_label(selector, exact=False).fill(text),
        lambda: page.get_by_role("textbox", name=selector, exact=False).fill(text),
    ]
    for attempt in candidates:
        try:
            await attempt()
            return f"Typed into {selector}"
        except Exception:
            continue
    editor_result = await _type_into_code_editor(page, text)
    if editor_result:
        return editor_result
    return f"Could not type into '{selector}'"


async def press_key(key: str) -> str:
    page = await _get_page()
    try:
        await page.keyboard.press(key)
        await page.wait_for_timeout(800)
        return f"Pressed key: {key}"
    except Exception as e:
        return f"Could not press key '{key}': {e}"


async def wait(seconds: float = 2.0) -> str:
    page = await _get_page()
    ms = max(0, min(float(seconds), 30.0)) * 1000
    await page.wait_for_timeout(ms)
    return await page_state()


async def extract(instruction: str, llm_router=None) -> dict:
    page = await _get_page()
    content = await page.evaluate("() => document.body?.innerText || ''")
    content = " ".join(content.split())[:4000]
    if not llm_router:
        return {"raw": content[:500]}
    try:
        from .llm_router import LLMRouter
        router = llm_router if llm_router else LLMRouter()
        result = router.complete(
            [{"role": "user", "content": f"Extract from page:\n{instruction}\n\nContent:\n{content}"}],
            system="Extract structured data. Return JSON only.",
        )
        import json, re
        m = re.search(r'\{.*\}', result, re.DOTALL)
        return json.loads(m.group()) if m else {"raw": result}
    except Exception as e:
        return {"raw": content[:500], "error": str(e)}


async def take_screenshot() -> str:
    page = await _get_page()
    try:
        b64 = await page.screenshot(type="jpeg", quality=40, full_page=False)
        import base64
        return base64.b64encode(b64).decode()
    except Exception as e:
        logger.warning("Screenshot failed: %s", e)
        return ""


async def close_browser():
    global _pw, _browser, _page
    if _browser:
        await _browser.close()
    if _pw:
        await _pw.stop()
    _pw = _browser = _page = None


async def _visible_text(page, limit: int = 3500) -> str:
    content = await page.evaluate("""
        () => {
            ['script','style','noscript','iframe'].forEach(
                t => document.querySelectorAll(t).forEach(e => e.remove())
            );
            return document.body?.innerText || '';
        }
    """)
    return " ".join(content.split())[:limit]


async def _type_into_code_editor(page, text: str) -> str:
    try:
        editor_api = await page.evaluate(
            """value => {
                const monacoModels = window.monaco?.editor?.getModels?.();
                if (monacoModels && monacoModels.length) {
                    monacoModels[0].setValue(value);
                    return 'monaco';
                }
                const codeMirrorHost = document.querySelector('.CodeMirror');
                if (codeMirrorHost?.CodeMirror) {
                    codeMirrorHost.CodeMirror.setValue(value);
                    return 'codemirror5';
                }
                const cmContent = document.querySelector('.cm-content[contenteditable="true"]');
                if (cmContent) {
                    cmContent.textContent = value;
                    cmContent.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                    return 'codemirror6';
                }
                if (window.ace) {
                    const aceEditor = window.ace.edit(document.querySelector('.ace_editor'));
                    if (aceEditor) {
                        aceEditor.setValue(value, -1);
                        return 'ace';
                    }
                }
                return '';
            }""",
            text,
        )
        if editor_api:
            return f"Typed into code editor via {editor_api}"
    except Exception:
        pass

    editor_selectors = [
        ".monaco-editor textarea",
        ".monaco-editor",
        ".cm-content",
        ".CodeMirror textarea",
        ".ace_text-input",
        "[contenteditable='true']",
        "textarea",
    ]
    for selector in editor_selectors:
        try:
            locator = page.locator(selector).first
            if not await locator.count():
                continue
            await locator.click(force=True)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.insert_text(text)
            await page.wait_for_timeout(300)
            return f"Typed into code editor via {selector}"
        except Exception:
            continue
    return ""
