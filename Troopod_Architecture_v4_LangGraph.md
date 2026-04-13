# AdPersonalizer — Advanced Architecture
### Troopod AI PM Assignment | Shivam Rajput
### Version 4.0 — LangGraph Stateful Agent Graph + Next.js Frontend

---

## 1. Why This Architecture Is Different

The v3 architecture was a linear pipeline:
  fetch → extract → enhance → stitch → validate

Linear pipelines have a fundamental weakness: a failure at any node poisons
every node after it, and there is no intelligent recovery — only hardcoded
fallbacks bolted on at the end.

This v4 architecture is a **stateful directed graph** built with LangGraph.
Every node reads from and writes to a shared state object. Conditional edges
route execution dynamically based on what actually happened — not what we hoped
would happen. Retry loops are first-class citizens, not afterthoughts.

Concrete problems this solves over v3:

| v3 Problem | v4 Solution |
|---|---|
| Wrong hero detected → everything downstream wrong | Confidence score on detection → route to LLM-assisted fallback if low |
| Single-shot LLM enhancement with one dumb retry | Self-correction loop: Validator node critiques output → Enhancer re-runs with critique |
| JS SPAs completely blocked | Playwright node in the graph, triggered by conditional edge on blank-page detection |
| JSON parsing from raw LLM text (fragile) | Claude structured outputs (tool_use) + Pydantic models — no string parsing |
| Agent 4 fallback was an afterthought | Stitcher failure routes back into graph to a dedicated recovery node |
| No visibility into pipeline state | LangGraph checkpointing = full state snapshot at every node, inspectable |

---

## 2. Core Concepts Used

### 2.1 LangGraph StateGraph

LangGraph models the pipeline as a directed graph where:
- **Nodes** = Python functions that take state and return partial state updates
- **Edges** = connections between nodes (static or conditional)
- **State** = a TypedDict shared across all nodes — the single source of truth
- **Conditional edges** = functions that inspect state and return the name of the
  next node to execute

```
State flows through the graph.
Nodes read state, do work, return updates.
Edges decide where to go next based on state values.
```

### 2.2 Structured Outputs (Claude Tool Use)

Instead of prompting the LLM to "return only JSON" and manually stripping markdown
fences, we define Pydantic models and use Claude's tool_use feature.

Claude is given a tool definition. To "respond", it must call that tool with
structured arguments. The arguments are guaranteed to match the schema — no
parsing, no fences, no hallucinated wrapper text.

```python
# Instead of: parse LLM's raw text → strip fences → json.loads → hope it works
# We do: LLM calls a tool → arguments are already a validated Pydantic object
```

### 2.3 LangGraph Send() for Parallelism

LangGraph's `Send()` API allows a node to dispatch multiple tasks to the same
node in parallel, with each task carrying different state. We use this to run
Ad Analyzer and LP Processor simultaneously.

### 2.4 Retry Loop with State Counter

LangGraph supports cycles in the graph (unlike a DAG). We use this for the
enhance → validate → (fail) → enhance loop. A `retry_count` field in state
terminates the loop after 2 attempts to prevent infinite cycles.

---

## 3. Shared State Schema

This is the single TypedDict that flows through every node in the graph.
Every node reads from it. Every node returns a dict updating only the fields
it owns.

```python
from typing import TypedDict, Optional, Literal
from pydantic import BaseModel

# ── Pydantic models for structured LLM outputs ──────────────────────────────

class VisualStyle(BaseModel):
    primary_color: Optional[str]
    secondary_color: Optional[str]
    mood: Optional[str]

class AdData(BaseModel):
    headline: Optional[str]
    sub_headline: Optional[str]
    offer: Optional[str]
    offer_present: bool
    cta_text: Optional[str]
    cta_urgency: Literal["low", "medium", "high"]
    tone: Literal[
        "professional", "energetic", "luxury", "playful", "urgent",
        "trustworthy", "casual", "authoritative", "empathetic", "bold"
    ]
    tone_description: Optional[str]
    target_audience: Optional[str]
    key_promise: Optional[str]
    pain_point: Optional[str]
    product_category: Optional[str]
    visual_style: Optional[VisualStyle]
    social_proof_in_ad: Optional[str]
    scarcity_signal: Optional[str]
    personalization_hooks: list[str]

class HeroDetectionResult(BaseModel):
    hero_html: str
    detection_method: str
    confidence: Literal["high", "medium", "low"]
    # high   = structural XPath (h1 + CTA found)
    # medium = semantic/attribute-based match
    # low    = positional fallback only

class EnhancedHeroResult(BaseModel):
    enhanced_html: str
    changes_made: list[str]   # human-readable list of what was changed

class ValidationResult(BaseModel):
    passed: bool
    score: int                # 0-100
    issues: list[str]         # what failed
    critique: Optional[str]   # what the enhancer should fix on retry

class ChangeRecord(BaseModel):
    element: str
    original: Optional[str]
    updated: str

# ── Main graph state ─────────────────────────────────────────────────────────

class GraphState(TypedDict):
    # ── Inputs ──────────────────────────────────────────────────
    lp_url:             str
    ad_image_base64:    Optional[str]   # set if image upload
    ad_url:             Optional[str]   # set if URL input

    # ── LP Fetch results ────────────────────────────────────────
    raw_html:           Optional[str]
    base_url:           Optional[str]
    fetch_method:       Optional[str]   # "requests" | "playwright"
    fetch_error:        Optional[str]   # set if fetch failed

    # ── Hero extraction results ─────────────────────────────────
    hero_html_chunk:           Optional[str]
    main_html_with_placeholder: Optional[str]
    hero_detection:            Optional[HeroDetectionResult]
    extraction_error:          Optional[str]

    # ── Ad analysis results ─────────────────────────────────────
    ad_data:            Optional[AdData]
    ad_analysis_error:  Optional[str]

    # ── Enhancement loop ────────────────────────────────────────
    enhanced_hero_html: Optional[str]
    enhancement_result: Optional[EnhancedHeroResult]
    validation_result:  Optional[ValidationResult]
    retry_count:        int             # starts at 0, max 2

    # ── Final output ────────────────────────────────────────────
    final_html:         Optional[str]
    change_summary:     list[ChangeRecord]
    fallback_used:      bool
    processing_steps:   list[str]      # SSE event log
    error:              Optional[str]  # terminal error message
```

---

## 4. Graph Architecture — Node Map

```
                        ┌──────────────────────────────────────┐
                        │           START                      │
                        │   (lpUrl + adCreative received)      │
                        └──────────────┬───────────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────────────┐
                        │  [fetch_lp_node]                     │
                        │  requests.get(lpUrl)                 │
                        │  → sets raw_html, base_url           │
                        │  → sets fetch_error if failed        │
                        └──────────────┬───────────────────────┘
                                       │
                        ┌──────────────▼───────────────────────┐
                        │  route_after_fetch()  [CONDITIONAL]  │
                        └──┬─────────────────┬────────────────┬┘
                           │                 │                │
                    "success"           "spa_blank"      "error"
                           │                 │                │
                           ▼                 ▼                ▼
                    [parallel          [playwright       [error_node]
                     extract]           _node]            → END
                                            │
                                     "playwright_done"
                                            │
                                     [parallel_extract]

                    ┌─────────────────────────────────────────────────┐
                    │  [parallel_extract_node]                        │
                    │  Runs simultaneously via Send():                │
                    │    ├── ad_analyzer_node   → ad_data             │
                    │    └── hero_extractor_node → hero_html_chunk    │
                    │                             main_html_with_ph.  │
                    └──────────────────┬──────────────────────────────┘
                                       │
                        ┌──────────────▼───────────────────────┐
                        │  route_after_extraction() [COND.]    │
                        └──┬──────────────────────┬────────────┘
                           │                      │
                    "confidence_high"     "confidence_low"
                    "confidence_medium"          │
                           │                     ▼
                           │         [llm_hero_fallback_node]
                           │         LLM looks at raw_html,
                           │         identifies hero section
                           │         → updates hero_html_chunk
                           │                     │
                           └──────────┬──────────┘
                                      │
                        ┌─────────────▼────────────────────────┐
                        │  [hero_enhance_node]                 │
                        │  Agent 3: ad_data + hero_html_chunk  │
                        │  → enhanced_hero_html (structured)   │
                        └─────────────┬────────────────────────┘
                                      │
                        ┌─────────────▼────────────────────────┐
                        │  [validate_node]                     │
                        │  Scores output 0-100                 │
                        │  Produces critique if failing        │
                        └─────────────┬────────────────────────┘
                                      │
                        ┌─────────────▼────────────────────────┐
                        │  route_after_validation() [COND.]   │
                        └──┬─────────────────────┬────────────┘
                           │                     │
                     "passed"              "failed + retry < 2"
                           │                     │
                           │           [hero_enhance_node]  ← LOOP BACK
                           │           (retry_count += 1,
                           │            critique injected in prompt)
                           │
                    "failed + retry >= 2"
                           │
                    [emergency_stitch_node]
                    (use best attempt so far)
                           │
                           ▼
                        ┌─────────────────────────────────────────┐
                        │  [stitch_node]                          │
                        │  Python: replace placeholder            │
                        │  → validate HTML structure              │
                        └─────────────┬───────────────────────────┘
                                      │
                        ┌─────────────▼───────────────────────────┐
                        │  route_after_stitch() [CONDITIONAL]     │
                        └──┬──────────────────────────────────────┘
                           │
                    ┌──────┴──────┐
                "html_valid"  "html_broken"
                    │              │
                    │         [llm_stitch_recovery_node]
                    │         Agent 4: LLM stitches cleanly
                    │              │
                    └──────┬───────┘
                           │
                        ┌──▼──────────────────────────────────────┐
                        │  [finalize_node]                        │
                        │  sanitize_for_iframe()                  │
                        │  generate_change_summary()              │
                        │  → final_html, change_summary           │
                        └──────────────┬──────────────────────────┘
                                       │
                                      END
```

---

## 5. Node Implementations

### 5.1 fetch_lp_node

```python
import requests
from langchain_core.runnables import RunnableConfig

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
        return {"fetch_error": "timeout", "processing_steps": ["fetch: timeout"]}
    except requests.exceptions.ConnectionError:
        return {"fetch_error": "connection", "processing_steps": ["fetch: connection error"]}

    if resp.status_code in (403, 401):
        return {"fetch_error": "blocked", "processing_steps": ["fetch: blocked (403)"]}
    if resp.status_code == 404:
        return {"fetch_error": "not_found", "processing_steps": ["fetch: 404"]}
    if resp.status_code != 200:
        return {"fetch_error": f"http_{resp.status_code}", "processing_steps": [f"fetch: HTTP {resp.status_code}"]}

    from urllib.parse import urlparse
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}/"

    return {
        "raw_html":        resp.text,
        "base_url":        base_url,
        "fetch_method":    "requests",
        "processing_steps": ["fetch: success via requests"]
    }


def route_after_fetch(state: GraphState) -> str:
    """
    Conditional edge after fetch_lp_node.
    Checks if fetch succeeded and if page has visible content.
    """
    if state.get("fetch_error"):
        # Blocked pages can still try playwright, others are terminal
        if state["fetch_error"] == "blocked":
            return "playwright"
        return "error"

    # SPA detection: if body text < 500 chars, page needs JS rendering
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
```

### 5.2 playwright_node

```python
async def playwright_node(state: GraphState) -> dict:
    """
    Headless browser fallback for JS-rendered SPAs.
    Uses Playwright to fully render the page before extracting HTML.
    Only runs when requests fetch returns blank content or is blocked.
    """
    from playwright.async_api import async_playwright
    from urllib.parse import urlparse

    url = state["lp_url"]

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                viewport={"width": 1440, "height": 900}
            )
            page = await context.new_page()

            # Navigate and wait for network idle (all resources loaded)
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Extra wait for any post-load JS animations
            await page.wait_for_timeout(2000)

            rendered_html = await page.content()
            await browser.close()

        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}/"

        # Verify we got real content this time
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
            "fetch_error":  None,       # Clear any previous fetch error
            "processing_steps": state.get("processing_steps", []) + ["playwright: rendered successfully"]
        }

    except Exception as e:
        return {
            "fetch_error": f"playwright_failed: {str(e)}",
            "processing_steps": state.get("processing_steps", []) + [f"playwright: failed — {str(e)}"]
        }
```

### 5.3 parallel_extract_node (Send() pattern)

```python
from langgraph.types import Send

def parallel_extract_node(state: GraphState) -> list[Send]:
    """
    Fan-out node: dispatches ad analysis and hero extraction simultaneously.
    LangGraph's Send() API runs both in parallel, then merges their state updates.
    """
    return [
        Send("ad_analyzer_node", state),
        Send("hero_extractor_node", state)
    ]
```

### 5.4 ad_analyzer_node (Structured Output via Tool Use)

```python
import anthropic
import base64
import json

client = anthropic.Anthropic()

# Tool definition matching AdData Pydantic schema
AD_ANALYZER_TOOL = {
    "name": "record_ad_analysis",
    "description": "Record the structured analysis of the ad creative.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline":    {"type": "string"},
            "sub_headline": {"type": ["string", "null"]},
            "offer":       {"type": ["string", "null"]},
            "offer_present": {"type": "boolean"},
            "cta_text":    {"type": ["string", "null"]},
            "cta_urgency": {"type": "string", "enum": ["low", "medium", "high"]},
            "tone": {
                "type": "string",
                "enum": ["professional", "energetic", "luxury", "playful", "urgent",
                         "trustworthy", "casual", "authoritative", "empathetic", "bold"]
            },
            "tone_description":    {"type": ["string", "null"]},
            "target_audience":     {"type": ["string", "null"]},
            "key_promise":         {"type": ["string", "null"]},
            "pain_point":          {"type": ["string", "null"]},
            "product_category":    {"type": ["string", "null"]},
            "visual_style": {
                "type": ["object", "null"],
                "properties": {
                    "primary_color":   {"type": ["string", "null"]},
                    "secondary_color": {"type": ["string", "null"]},
                    "mood":            {"type": ["string", "null"]}
                }
            },
            "social_proof_in_ad":  {"type": ["string", "null"]},
            "scarcity_signal":     {"type": ["string", "null"]},
            "personalization_hooks": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["headline", "offer_present", "cta_urgency", "tone",
                     "personalization_hooks"]
    }
}

def ad_analyzer_node(state: GraphState) -> dict:
    """
    Agent 1: Analyse ad creative → structured AdData via tool_use.
    Handles: image upload (base64), image URL, HTML ad URL.
    """
    system_prompt = """You are an expert digital advertising analyst specialising in CRO.
Analyse the provided ad creative. Call the record_ad_analysis tool with your findings.
Extract ONLY what is explicitly visible or strongly implied in the ad.
Set fields to null if not present. Never invent products, prices, or claims."""

    # Build the user message content based on input type
    content = []

    if state.get("ad_image_base64"):
        # Strip data URI prefix if present
        b64 = state["ad_image_base64"]
        if "," in b64:
            media_type, b64 = b64.split(",", 1)
            media_type = media_type.split(":")[1].split(";")[0]
        else:
            media_type = "image/jpeg"

        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64}
            },
            {"type": "text", "text": "Analyse this ad creative and call record_ad_analysis with your findings."}
        ]

    elif state.get("ad_url"):
        url = state["ad_url"]
        # Try fetching as image
        try:
            import requests as req
            resp = req.get(url, timeout=10)
            if resp.headers.get("Content-Type", "").startswith("image/"):
                b64 = base64.b64encode(resp.content).decode("utf-8")
                media_type = resp.headers["Content-Type"].split(";")[0]
                content = [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64}
                    },
                    {"type": "text", "text": "Analyse this ad creative and call record_ad_analysis."}
                ]
            else:
                # HTML ad page — use Jina Reader
                jina_resp = req.get(f"https://r.jina.ai/{url}", timeout=15)
                content = [
                    {"type": "text", "text": f"Ad page content:\n\n{jina_resp.text[:8000]}\n\nCall record_ad_analysis with your findings."}
                ]
        except Exception as e:
            return {"ad_analysis_error": f"Could not load ad URL: {str(e)}"}

    else:
        return {"ad_analysis_error": "No ad input provided."}

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            temperature=0.1,
            system=system_prompt,
            tools=[AD_ANALYZER_TOOL],
            tool_choice={"type": "tool", "name": "record_ad_analysis"},
            messages=[{"role": "user", "content": content}]
        )

        # Extract tool call arguments — guaranteed to match schema
        tool_use_block = next(b for b in response.content if b.type == "tool_use")
        ad_data = AdData(**tool_use_block.input)

        return {
            "ad_data": ad_data,
            "processing_steps": state.get("processing_steps", []) + ["ad_analyzer: complete"]
        }

    except Exception as e:
        return {
            "ad_analysis_error": f"Ad analysis failed: {str(e)}",
            "processing_steps": state.get("processing_steps", []) + [f"ad_analyzer: error — {str(e)}"]
        }
```

### 5.5 hero_extractor_node (lxml XPath with Confidence Scoring)

```python
from lxml import html as lxml_html
from lxml import etree

PLACEHOLDER = " __HERO_SECTION_PLACEHOLDER__ "

def hero_extractor_node(state: GraphState) -> dict:
    """
    Agent 2: Extract hero section from raw HTML using lxml XPath waterfall.
    Returns hero_html_chunk, main_html_with_placeholder, and confidence score.
    """
    raw_html = state.get("raw_html", "")
    base_url = state.get("base_url", "")

    try:
        tree = lxml_html.fromstring(raw_html)
    except Exception as e:
        return {"extraction_error": f"HTML parse failed: {str(e)}"}

    hero_el, method, confidence = _xpath_hero_waterfall(tree)

    if hero_el is None:
        return {
            "extraction_error": "Hero not found — all XPath levels failed",
            "hero_detection": HeroDetectionResult(
                hero_html="",
                detection_method="not_found",
                confidence="low"
            )
        }

    # Size guard — narrow if too large
    hero_el = _guard_size(hero_el)

    # Serialize hero HTML
    hero_html = lxml_html.tostring(hero_el, encoding="unicode", with_tail=False)

    # Replace hero with placeholder comment in tree
    placeholder_node = etree.Comment(PLACEHOLDER)
    parent = hero_el.getparent()
    if parent is None:
        return {"extraction_error": "Hero element has no parent."}
    parent.replace(hero_el, placeholder_node)

    # Serialize full page with placeholder
    main_html = lxml_html.tostring(
        tree,
        encoding="unicode",
        doctype="<!DOCTYPE html>",
        pretty_print=False
    )

    # Inject base href
    main_html = _inject_base_href(main_html, base_url)

    detection = HeroDetectionResult(
        hero_html=hero_html,
        detection_method=method,
        confidence=confidence
    )

    return {
        "hero_html_chunk":             hero_html,
        "main_html_with_placeholder":  main_html,
        "hero_detection":              detection,
        "processing_steps": state.get("processing_steps", []) + [
            f"hero_extractor: {method} (confidence: {confidence})"
        ]
    }


def _xpath_hero_waterfall(tree) -> tuple:
    """
    5-level XPath waterfall. Returns (element, method_string, confidence_level).
    Confidence reflects how structurally certain we are.
    """

    # LEVEL 1 — HIGHEST CONFIDENCE
    # Element containing h1 AND a CTA (button or btn-class link)
    # This is the structural definition of a hero section.
    results = tree.xpath(
        '('
        '//*[self::section or self::div or self::header or self::article]'
        '[.//h1]'
        '[.//button or .//a[contains(@class,"btn")] or '
        ' .//a[contains(@class,"cta")] or .//a[contains(@class,"button")] or '
        ' .//input[@type="submit"]]'
        ')[1]'
    )
    if results:
        return results[0], "structural: h1 + CTA element", "high"

    # LEVEL 2 — HIGH CONFIDENCE
    # Semantic <header> tag containing h1
    results = tree.xpath('(//header[.//h1])[1]')
    if results:
        return results[0], "semantic: <header> with h1", "high"

    # LEVEL 3 — MEDIUM CONFIDENCE
    # First <section> inside <main> containing h1
    results = tree.xpath('(//main//section[.//h1])[1]')
    if results:
        return results[0], "structural: first section[h1] in main", "medium"

    # LEVEL 4 — MEDIUM CONFIDENCE
    # ID or class attribute containing hero/banner/masthead keyword
    UPPER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    LOWER = 'abcdefghijklmnopqrstuvwxyz'
    keywords = ["hero", "banner", "jumbotron", "masthead", "intro"]
    xpath_conditions = " or ".join([
        f'contains(translate(@id,"{UPPER}","{LOWER}"),"{kw}") or '
        f'contains(translate(@class,"{UPPER}","{LOWER}"),"{kw}")'
        for kw in keywords
    ])
    results = tree.xpath(f'(//*[{xpath_conditions}])[1]')
    if results:
        return results[0], "attribute: id/class hero keyword match", "medium"

    # LEVEL 5 — LOW CONFIDENCE
    # First section/div containing h1 (positional only)
    results = tree.xpath('(//*[self::section or self::div][.//h1])[1]')
    if results:
        return results[0], "positional: first section/div with h1", "low"

    # LAST RESORT — h1's parent
    results = tree.xpath('//h1')
    if results:
        parent = results[0].getparent()
        if parent is not None:
            return parent, "fallback: h1 parent", "low"

    return None, "not_found", "low"


def _guard_size(hero_el) -> object:
    """Narrow hero element if serialised size exceeds 12KB."""
    html_str = lxml_html.tostring(hero_el, encoding="unicode", with_tail=False)
    if len(html_str) <= 12000:
        return hero_el
    # Find direct child that contains h1 — narrower slice
    for child in hero_el:
        child_html = lxml_html.tostring(child, encoding="unicode", with_tail=False)
        subtree = lxml_html.fromstring(child_html)
        if subtree.xpath('.//h1'):
            return child
    # Last resort: h1 grandparent
    h1_list = hero_el.xpath('.//h1')
    if h1_list:
        gp = h1_list[0].getparent()
        if gp is not None:
            return gp
    return hero_el


def _inject_base_href(html_str: str, base_url: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_str, "lxml")
    head = soup.find("head")
    if head:
        existing = head.find("base")
        if existing:
            existing["href"] = base_url
        else:
            tag = soup.new_tag("base", href=base_url)
            head.insert(0, tag)
    return str(soup)


def route_after_extraction(state: GraphState) -> str:
    """
    Conditional edge after parallel extraction completes.
    Routes to LLM hero fallback if confidence is low.
    Routes to enhance if confidence is high or medium.
    """
    if state.get("extraction_error"):
        return "llm_hero_fallback"
    if state.get("ad_analysis_error"):
        return "error"

    detection = state.get("hero_detection")
    if detection and detection.confidence == "low":
        return "llm_hero_fallback"

    return "enhance"
```

### 5.6 llm_hero_fallback_node

```python
# Tool definition for LLM hero identification
LLM_HERO_IDENTIFY_TOOL = {
    "name": "identify_hero_section",
    "description": "Identify and extract the hero section HTML from the landing page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "hero_html": {
                "type": "string",
                "description": "The complete HTML of the hero section including the outermost container tag."
            },
            "reasoning": {
                "type": "string",
                "description": "Why this element was chosen as the hero section."
            }
        },
        "required": ["hero_html", "reasoning"]
    }
}

def llm_hero_fallback_node(state: GraphState) -> dict:
    """
    When XPath detection confidence is low or failed, use LLM to identify the hero.
    Sends a truncated version of the raw HTML (first 15KB) to avoid token overflow.
    """
    raw_html = state.get("raw_html", "")
    # Send only the first 15KB — hero is always in the top portion
    html_sample = raw_html[:15000]

    system_prompt = """You are an expert HTML developer and CRO specialist.
You will receive partial HTML from a landing page.
Identify the hero section — the main above-the-fold area that contains the 
primary headline (h1), sub-headline, and call-to-action button/link.
Extract the COMPLETE outermost HTML element that wraps this section.
Call identify_hero_section with the hero HTML string."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        temperature=0.0,
        system=system_prompt,
        tools=[LLM_HERO_IDENTIFY_TOOL],
        tool_choice={"type": "tool", "name": "identify_hero_section"},
        messages=[{
            "role": "user",
            "content": f"Landing page HTML (first portion):\n\n{html_sample}\n\nIdentify and extract the hero section."
        }]
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    hero_html = tool_block.input["hero_html"]

    # Now we need to rebuild main_html_with_placeholder
    # Find this hero_html in the original raw_html and replace it with placeholder
    placeholder = f"<!--{PLACEHOLDER}-->"
    main_html = state.get("raw_html", "").replace(hero_html, placeholder, 1)

    if placeholder not in main_html:
        # String replace failed (LLM may have reformatted whitespace)
        # Fall back: use the hero_html directly, accept we'll use Agent 4 for stitching
        main_html = state.get("main_html_with_placeholder", "") or raw_html

    main_html = _inject_base_href(main_html, state.get("base_url", ""))

    return {
        "hero_html_chunk":             hero_html,
        "main_html_with_placeholder":  main_html,
        "hero_detection": HeroDetectionResult(
            hero_html=hero_html,
            detection_method="llm_fallback: LLM identified hero from raw HTML",
            confidence="medium"
        ),
        "processing_steps": state.get("processing_steps", []) + ["llm_hero_fallback: hero identified by LLM"]
    }
```

### 5.7 hero_enhance_node (Self-Correcting with Critique Injection)

```python
HERO_ENHANCE_TOOL = {
    "name": "deliver_enhanced_hero",
    "description": "Deliver the enhanced hero HTML after personalising it to match the ad.",
    "input_schema": {
        "type": "object",
        "properties": {
            "enhanced_html": {
                "type": "string",
                "description": "The complete enhanced hero HTML with all modifications applied."
            },
            "changes_made": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of changes made, e.g. ['Updated h1 to match ad headline', 'Added offer banner']"
            }
        },
        "required": ["enhanced_html", "changes_made"]
    }
}

def hero_enhance_node(state: GraphState) -> dict:
    """
    Agent 3: Personalise hero HTML to match ad creative.
    On retries, injects the validator's critique into the prompt.
    Uses tool_use to guarantee structured output.
    """
    ad_data: AdData = state["ad_data"]
    hero_html = state["hero_html_chunk"]
    retry_count = state.get("retry_count", 0)
    validation_result: Optional[ValidationResult] = state.get("validation_result")

    # Build the base prompt
    system_prompt = f"""You are an expert CRO specialist and frontend developer.

TASK: Personalise the provided hero HTML to create strong message match with the ad creative.
Message match = the user immediately sees language confirming the ad's promise when they land.

AD CREATIVE DATA:
{ad_data.model_dump_json(indent=2)}

WHAT YOU CAN CHANGE:
- Text inside h1, h2, h3 (align headline to ad's headline/promise)
- Text inside p tags in hero (align body copy to ad's messaging, 2-3 sentences max)
- Text inside button and a tags (CTA label only — never touch href, class, id, or any attribute)
- If the ad has a specific offer NOT in the hero, add ONE offer banner as FIRST child:
  <div class="ad-personalizer-banner" style="background:#EEF6FF;border:1px solid #C7E0FF;
  padding:12px 24px;text-align:center;font-weight:600;border-radius:4px;margin-bottom:16px;">
  [offer text]</div>

STRICT RULES:
1. Keep every HTML attribute (class, id, href, src, data-*, style, aria-*) exactly as-is.
2. Do NOT remove any existing elements.
3. Do NOT invent products, prices, or features not in the ad data or original hero HTML.
4. Tone must be: {ad_data.tone} — {ad_data.tone_description}
5. Call deliver_enhanced_hero with the complete modified HTML and a list of changes made."""

    # Inject critique if this is a retry
    if retry_count > 0 and validation_result and validation_result.critique:
        system_prompt += f"""

IMPORTANT — THIS IS RETRY #{retry_count}:
Your previous output failed validation. The validator's critique:
{validation_result.critique}

Fix the specific issues mentioned above. Do not repeat the same mistakes."""

    messages = [{
        "role": "user",
        "content": f"Hero HTML to personalise:\n\n{hero_html}\n\nPersonalise this and call deliver_enhanced_hero."
    }]

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        temperature=0.15,
        system=system_prompt,
        tools=[HERO_ENHANCE_TOOL],
        tool_choice={"type": "tool", "name": "deliver_enhanced_hero"},
        messages=messages
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    result = EnhancedHeroResult(**tool_block.input)

    return {
        "enhanced_hero_html":  result.enhanced_html,
        "enhancement_result":  result,
        "processing_steps": state.get("processing_steps", []) + [
            f"hero_enhancer: complete (attempt {retry_count + 1})"
        ]
    }
```

### 5.8 validate_node (Critic Agent)

```python
VALIDATE_TOOL = {
    "name": "record_validation",
    "description": "Record the validation result of the enhanced hero HTML.",
    "input_schema": {
        "type": "object",
        "properties": {
            "passed":  {"type": "boolean"},
            "score":   {"type": "integer", "minimum": 0, "maximum": 100},
            "issues":  {"type": "array", "items": {"type": "string"}},
            "critique": {
                "type": "string",
                "description": "Specific instructions for the enhancer to fix on retry. Only needed if passed=false."
            }
        },
        "required": ["passed", "score", "issues"]
    }
}

def validate_node(state: GraphState) -> dict:
    """
    Critic agent: independently evaluates the enhanced hero HTML.
    Checks: message match quality, HTML integrity, no hallucinations,
    no attribute mutations, no missing elements.
    """
    ad_data: AdData = state["ad_data"]
    original_hero = state["hero_html_chunk"]
    enhanced_hero = state["enhanced_hero_html"]

    system_prompt = """You are a strict quality assurance engineer specialising in CRO.

Evaluate the enhanced hero HTML against these criteria:
1. MESSAGE MATCH (40 pts): Does the enhanced hero clearly reflect the ad's headline, offer, and CTA?
2. HTML INTEGRITY (30 pts): Are all original tags preserved? No elements removed? All attributes unchanged?
3. GROUNDEDNESS (20 pts): Is every claim traceable to the original hero HTML or ad data?
   No invented products, prices, or features?
4. TONE MATCH (10 pts): Does the copy match the ad's tone?

Call record_validation with:
- passed: true if score >= 70, false otherwise
- score: 0-100 total
- issues: list of specific problems found
- critique: specific actionable instructions for the enhancer to fix (only if passed=false)"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        temperature=0.0,
        system=system_prompt,
        tools=[VALIDATE_TOOL],
        tool_choice={"type": "tool", "name": "record_validation"},
        messages=[{
            "role": "user",
            "content": (
                f"AD DATA:\n{ad_data.model_dump_json(indent=2)}\n\n"
                f"ORIGINAL HERO:\n{original_hero}\n\n"
                f"ENHANCED HERO:\n{enhanced_hero}\n\n"
                "Validate and call record_validation."
            )
        }]
    )

    tool_block = next(b for b in response.content if b.type == "tool_use")
    result = ValidationResult(**tool_block.input)

    return {
        "validation_result": result,
        "processing_steps": state.get("processing_steps", []) + [
            f"validator: score={result.score}, passed={result.passed}"
        ]
    }


def route_after_validation(state: GraphState) -> str:
    """
    Conditional edge: route to stitch if passed, retry if failed and under limit,
    or emergency stitch if retry limit reached.
    """
    result: ValidationResult = state["validation_result"]
    retry_count = state.get("retry_count", 0)

    if result.passed:
        return "stitch"

    if retry_count < 2:
        return "retry_enhance"   # Routes back to hero_enhance_node

    return "emergency_stitch"    # Give up retrying — use best attempt
```

### 5.9 stitch_node + finalize_node

```python
def stitch_node(state: GraphState) -> dict:
    """
    Replace placeholder with enhanced hero. Validate HTML structure.
    """
    PLACEHOLDER_STR = f"<!--{PLACEHOLDER}-->"
    main_html = state["main_html_with_placeholder"]
    enhanced = state["enhanced_hero_html"]

    if PLACEHOLDER_STR not in main_html:
        return {"error": "Placeholder not found in main HTML — cannot stitch."}

    final_html = main_html.replace(PLACEHOLDER_STR, enhanced, 1)

    # Quick structural validation
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(final_html, "lxml")
        has_html = bool(soup.find("html"))
        has_body = bool(soup.find("body"))
        placeholder_remains = "__HERO_SECTION_PLACEHOLDER__" in final_html
        html_valid = has_html and has_body and not placeholder_remains
    except Exception:
        html_valid = False

    return {
        "final_html": final_html if html_valid else None,
        "processing_steps": state.get("processing_steps", []) + [
            f"stitcher: html_valid={html_valid}"
        ]
    }


def route_after_stitch(state: GraphState) -> str:
    return "finalize" if state.get("final_html") else "llm_stitch_recovery"


def finalize_node(state: GraphState) -> dict:
    """
    Sanitise for iframe rendering. Generate change summary. Build final response.
    """
    from utils.html_validator import sanitize_for_iframe
    from utils.change_summary import generate_change_summary

    final_html = state["final_html"]
    sanitized = sanitize_for_iframe(final_html)
    changes = generate_change_summary(
        state["hero_html_chunk"],
        state["enhanced_hero_html"]
    )

    return {
        "final_html":     sanitized,
        "change_summary": changes,
        "fallback_used":  state.get("fallback_used", False),
        "processing_steps": state.get("processing_steps", []) + ["finalize: done"]
    }
```

---

## 6. Graph Assembly

```python
from langgraph.graph import StateGraph, END

def build_graph() -> StateGraph:
    graph = StateGraph(GraphState)

    # ── Add all nodes ──────────────────────────────────────────────────
    graph.add_node("fetch_lp",              fetch_lp_node)
    graph.add_node("playwright",            playwright_node)
    graph.add_node("parallel_extract",      parallel_extract_node)
    graph.add_node("ad_analyzer",           ad_analyzer_node)
    graph.add_node("hero_extractor",        hero_extractor_node)
    graph.add_node("llm_hero_fallback",     llm_hero_fallback_node)
    graph.add_node("hero_enhance",          hero_enhance_node)
    graph.add_node("validate",              validate_node)
    graph.add_node("stitch",               stitch_node)
    graph.add_node("llm_stitch_recovery",  llm_stitch_recovery_node)
    graph.add_node("finalize",             finalize_node)
    graph.add_node("error_node",           error_node)

    # ── Entry point ────────────────────────────────────────────────────
    graph.set_entry_point("fetch_lp")

    # ── Edges ──────────────────────────────────────────────────────────
    graph.add_conditional_edges("fetch_lp", route_after_fetch, {
        "success":    "parallel_extract",
        "playwright": "playwright",
        "error":      "error_node"
    })

    graph.add_edge("playwright", "parallel_extract")

    # Fan-out: parallel_extract dispatches to both sub-nodes via Send()
    graph.add_edge("parallel_extract", "ad_analyzer")
    graph.add_edge("parallel_extract", "hero_extractor")

    # Fan-in: both sub-nodes merge back into extraction routing
    graph.add_conditional_edges("hero_extractor", route_after_extraction, {
        "enhance":          "hero_enhance",
        "llm_hero_fallback": "llm_hero_fallback",
        "error":            "error_node"
    })
    graph.add_edge("ad_analyzer", "hero_extractor")  # Wait for both before routing

    graph.add_edge("llm_hero_fallback", "hero_enhance")

    graph.add_edge("hero_enhance", "validate")

    graph.add_conditional_edges("validate", route_after_validation, {
        "stitch":           "stitch",
        "retry_enhance":    "hero_enhance",     # Cycle — the retry loop
        "emergency_stitch": "stitch"
    })

    graph.add_conditional_edges("stitch", route_after_stitch, {
        "finalize":          "finalize",
        "llm_stitch_recovery": "llm_stitch_recovery"
    })
    graph.add_edge("llm_stitch_recovery", "finalize")

    graph.add_edge("finalize",  END)
    graph.add_edge("error_node", END)

    # ── Compile ────────────────────────────────────────────────────────
    return graph.compile()

app_graph = build_graph()
```

---

## 7. FastAPI Backend

```python
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import StreamingResponse
import asyncio
import json
import base64

app = FastAPI()

@app.post("/api/personalize")
async def personalize(
    lp_url:      str        = Form(...),
    ad_url:      str | None = Form(None),
    ad_image:    UploadFile | None = File(None)
):
    """
    Main endpoint. Accepts ad creative + LP URL.
    Streams SSE progress events while graph runs.
    Returns final result as last SSE event.
    """

    initial_state: GraphState = {
        "lp_url":             lp_url,
        "ad_url":             ad_url,
        "ad_image_base64":    None,
        "raw_html":           None,
        "base_url":           None,
        "fetch_method":       None,
        "fetch_error":        None,
        "hero_html_chunk":    None,
        "main_html_with_placeholder": None,
        "hero_detection":     None,
        "extraction_error":   None,
        "ad_data":            None,
        "ad_analysis_error":  None,
        "enhanced_hero_html": None,
        "enhancement_result": None,
        "validation_result":  None,
        "retry_count":        0,
        "final_html":         None,
        "change_summary":     [],
        "fallback_used":      False,
        "processing_steps":   [],
        "error":              None
    }

    if ad_image:
        contents = await ad_image.read()
        b64 = base64.b64encode(contents).decode("utf-8")
        media_type = ad_image.content_type or "image/jpeg"
        initial_state["ad_image_base64"] = f"data:{media_type};base64,{b64}"

    async def event_stream():
        # Stream SSE events as graph progresses
        async for event in app_graph.astream_events(initial_state, version="v2"):
            if event["event"] == "on_chain_end":
                node_name = event.get("name", "")
                if node_name in STREAMABLE_NODES:
                    yield f"data: {json.dumps({'step': node_name, 'done': True})}\n\n"

        # After graph completes, get final state
        final_state = await app_graph.ainvoke(initial_state)

        if final_state.get("error"):
            yield f"data: {json.dumps({'status': 'error', 'message': final_state['error']})}\n\n"
        else:
            result = {
                "status":              "success",
                "personalizedHtml":    final_state["final_html"],
                "changeSummary":       [c.model_dump() for c in final_state["change_summary"]],
                "heroDetectionMethod": final_state["hero_detection"].detection_method,
                "heroConfidence":      final_state["hero_detection"].confidence,
                "validationScore":     final_state["validation_result"].score,
                "fallbackUsed":        final_state["fallback_used"],
                "processingSteps":     final_state["processing_steps"]
            }
            yield f"data: {json.dumps(result)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

STREAMABLE_NODES = {
    "fetch_lp", "playwright", "ad_analyzer", "hero_extractor",
    "llm_hero_fallback", "hero_enhance", "validate", "stitch", "finalize"
}
```

---

## 8. Tech Stack

### Backend
```
Python 3.11+
fastapi              — API server
uvicorn              — ASGI server
langgraph            — Stateful agent graph execution
langchain-anthropic  — Claude integration for LangChain/LangGraph
anthropic            — Claude API (Vision + structured tool_use)
playwright           — Headless Chromium for JS SPA rendering
lxml                 — C-based HTML parser + XPath hero detection
beautifulsoup4       — HTML validation, change diff (lxml backend)
pydantic             — Typed state models + structured output validation
python-multipart     — File upload handling
python-dotenv        — Environment config
```

### Frontend (Next.js)
```
Next.js 14 (App Router)
TypeScript
Tailwind CSS
EventSource API      — Consume SSE stream from backend
react-dropzone       — Drag-and-drop ad image upload
```

### Infrastructure
```
Backend:   Railway (Python, supports Playwright Chromium)
Frontend:  Vercel
```

### requirements.txt
```
fastapi==0.115.0
uvicorn==0.30.6
langgraph==0.2.50
langchain-anthropic==0.3.0
anthropic==0.40.0
playwright==1.48.0
lxml==5.3.0
beautifulsoup4==4.12.3
pydantic==2.9.2
python-multipart==0.0.12
python-dotenv==1.0.1
```

---

## 9. What This Architecture Gives You Over v3

| Capability | v3 (Linear Pipeline) | v4 (LangGraph Graph) |
|---|---|---|
| JS SPA support | ❌ Manual paste only | ✅ Playwright node, auto-triggered |
| Hero detection failure recovery | ❌ Hardcoded 8-level waterfall, then give up | ✅ XPath waterfall + LLM fallback node |
| Enhancement quality assurance | ❌ One retry with no feedback | ✅ Critic agent scores 0-100, injects critique, loops up to 2x |
| Structured LLM output | ❌ Parse JSON from raw text, strip fences | ✅ Claude tool_use — Pydantic validated, guaranteed schema |
| Pipeline observability | ❌ No visibility into what happened | ✅ LangGraph state snapshot at every node, full processing_steps log |
| Parallel execution | ❌ Sequential | ✅ Send() API — ad analysis + hero extraction run simultaneously |
| Retry state memory | ❌ Retries are stateless | ✅ retry_count + validation critique persist in state across the loop |
| Stitching failure recovery | ❌ Agent 4 bolted on at end | ✅ First-class node in graph with conditional routing |

---

## 10. File Structure

```
adpersonalizer/
│
├── backend/
│   ├── main.py                      # FastAPI app + SSE endpoint
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── state.py                 # GraphState TypedDict + all Pydantic models
│   │   ├── graph_builder.py         # build_graph() — node registration + edges
│   │   └── nodes/
│   │       ├── fetch_lp.py          # fetch_lp_node + route_after_fetch
│   │       ├── playwright_node.py   # playwright_node (async)
│   │       ├── parallel_extract.py  # parallel_extract_node (Send dispatcher)
│   │       ├── ad_analyzer.py       # ad_analyzer_node + tool definition
│   │       ├── hero_extractor.py    # hero_extractor_node + XPath waterfall
│   │       ├── llm_hero_fallback.py # llm_hero_fallback_node
│   │       ├── hero_enhance.py      # hero_enhance_node + route_after_validation
│   │       ├── validate.py          # validate_node
│   │       ├── stitch.py            # stitch_node + route_after_stitch
│   │       ├── llm_stitch_recovery.py # Agent 4
│   │       ├── finalize.py          # finalize_node
│   │       └── error_node.py        # terminal error handler
│   ├── utils/
│   │   ├── html_validator.py        # sanitize_for_iframe()
│   │   └── change_summary.py        # generate_change_summary() BS4 diff
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   └── page.tsx
│   ├── components/
│   │   ├── AdInput.tsx
│   │   ├── LPInput.tsx
│   │   ├── ProcessingSteps.tsx      # SSE EventSource consumer
│   │   ├── SplitPreview.tsx
│   │   └── ChangeSummary.tsx
│   └── package.json
│
└── README.md
```

---

*Architecture Document v4.0 — Advanced LangGraph Implementation*
*Author: Shivam Rajput | Troopod AI PM Internship Assignment*
