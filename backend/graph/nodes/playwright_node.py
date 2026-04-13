from graph.state import GraphState

async def playwright_node(state: GraphState) -> dict:
    """
    Headless browser fallback for JS-rendered SPAs.
    Uses Playwright to fully render the page before extracting HTML.
    Only runs when requests fetch returns blank content or is blocked.
    """
    from playwright.async_api import async_playwright
    from urllib.parse import urlparse

    url = state["lp_url"]

    print(f"[DEBUG] Playwright starting for URL: {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                viewport={"width": 1440, "height": 900}
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            rendered_html = await page.content()
            await browser.close()
            print(f"[DEBUG] Playwright finished success: {len(rendered_html)} bytes")

        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}/"

        from lxml import html as lxml_html
        tree = lxml_html.fromstring(rendered_html)
        body_text = " ".join(tree.text_content().split())

        if len(body_text) < 200:
            return {
                "fetch_error": "spa_unrenderable",
                "processing_steps": state.get("processing_steps", []) + ["playwright: still blank after render"]
            }

        return {
            "raw_html":     rendered_html,
            "base_url":     base_url,
            "fetch_method": "playwright",
            "fetch_error":  None,
            "processing_steps": state.get("processing_steps", []) + ["playwright: rendered successfully"]
        }

    except Exception as e:
        return {
            "fetch_error": f"playwright_failed: {str(e)}",
            "processing_steps": state.get("processing_steps", []) + [f"playwright: failed — {str(e)}"]
        }
