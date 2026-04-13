import requests
from langchain_core.runnables import RunnableConfig
from graph.state import GraphState

def fetch_lp_node(state: GraphState, config: RunnableConfig) -> dict:
    """
    Fetch raw HTML from the landing page URL using requests.
    Fast path — Playwright is only triggered if this returns a blank page.
    """
    url = state["lp_url"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.Timeout:
        return {"fetch_error": "timeout", "processing_steps": state.get("processing_steps", []) + ["fetch: timeout"]}
    except requests.exceptions.ConnectionError:
        return {"fetch_error": "connection", "processing_steps": state.get("processing_steps", []) + ["fetch: connection error"]}

    if resp.status_code in (403, 401):
        return {"fetch_error": "blocked", "processing_steps": state.get("processing_steps", []) + ["fetch: blocked (403)"]}
    if resp.status_code == 404:
        return {"fetch_error": "not_found", "processing_steps": state.get("processing_steps", []) + ["fetch: 404"]}
    if resp.status_code != 200:
        return {"fetch_error": f"http_{resp.status_code}", "processing_steps": state.get("processing_steps", []) + [f"fetch: HTTP {resp.status_code}"]}

    from urllib.parse import urlparse
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}/"

    return {
        "raw_html":        resp.text,
        "base_url":        base_url,
        "fetch_method":    "requests",
        "processing_steps": state.get("processing_steps", []) + ["fetch: success via requests"]
    }

def route_after_fetch(state: GraphState) -> str:
    """
    Conditional edge after fetch_lp_node.
    Checks if fetch succeeded and if page has visible content.
    """
    if state.get("fetch_error"):
        if state["fetch_error"] == "blocked":
            return "playwright"
        return "error"

    raw = state.get("raw_html", "")
    from lxml import html as lxml_html
    try:
        tree = lxml_html.fromstring(raw)
        body_text = " ".join(tree.text_content().split())
        if len(body_text) < 500:
            return "playwright"
    except Exception:
        return "playwright"

    return "success"
