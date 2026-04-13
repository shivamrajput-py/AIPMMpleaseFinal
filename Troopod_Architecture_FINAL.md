# AdPersonalizer — Final System Architecture
### Troopod AI PM Assignment | Shivam Rajput
### Version 3.0 — lxml XPath Hero Extraction Pipeline

---

## 1. Core Philosophy

This system does NOT rewrite landing pages. It ENHANCES them.

The ad creative defines a user's expectation before they click. The landing page
must immediately confirm that expectation in the first 20-30% of the page (the hero
section). Everything below the fold — pricing, features, FAQs, testimonials — stays
completely untouched.

Architecture principle: Extract the smallest possible chunk of HTML using structural
intelligence (not guesswork), enhance it with ad context via LLM, stitch it back
surgically, and validate before serving.

Assignment constraint respected:
"The personalized page shouldn't be a completely new page — it should be the existing
page enhanced as per CRO principles + personalized as per the ad creative."

---

## 2. High-Level Pipeline

```
[User Input]
     ├── Ad Creative (image upload OR URL)
     └── Landing Page URL
                │
                ▼
════════════════════════════════════════════════════════════
  STEP 1 — PARALLEL EXTRACTION (runs simultaneously)
════════════════════════════════════════════════════════════
     ├── [Agent 1: Ad Analyzer]    → ad_data JSON
     └── [Agent 2: LP Processor]   → hero_html_chunk
                                      main_html_with_placeholder
                │
                ▼
════════════════════════════════════════════════════════════
  STEP 2 — PERSONALIZATION
════════════════════════════════════════════════════════════
     [Agent 3: Hero Enhancer]
     INPUT:  ad_data JSON  +  hero_html_chunk
     OUTPUT: enhanced_hero_html
                │
                ▼
════════════════════════════════════════════════════════════
  STEP 3 — SURGICAL STITCHING + VALIDATION
════════════════════════════════════════════════════════════
     Python string replace: placeholder → enhanced_hero_html
     HTML validation check
     │
     ├── IF valid   → serve final_html directly
     └── IF broken  → [Agent 4: Fallback Stitcher LLM]
                                │
                                ▼
                    [Frontend: Split-view + Change Summary]
```

---

## 3. Agent 1 — Ad Analyzer

### Purpose
Convert the ad creative (image upload or URL) into a structured JSON context object
that precisely defines the ad's messaging, offer, tone, and visual identity.
This becomes the personalization blueprint for Agent 3.

### Input Handling — Conditional Branch

```
Ad Input received
      │
      ├── IF file upload (binary, .jpg/.png/.gif/.webp)
      │       └── Read bytes → base64 encode
      │               └── Send to Claude Vision as image block
      │
      ├── IF URL provided
      │       └── requests.get(url, timeout=10)
      │               └── Check response Content-Type header
      │                       ├── IF "image/*"
      │                       │       └── base64 encode response bytes
      │                       │               └── Send to Claude Vision
      │                       └── IF "text/html" (or anything else)
      │                               └── Jina Reader: GET r.jina.ai/{url}
      │                                       └── Clean markdown text
      │                                               └── Send to Claude text model
      └── IF neither resolves
              └── Return error: "Could not load ad creative. Try uploading directly."
```

### Output Schema — ad_data JSON

The LLM must return ONLY this JSON. No preamble, no markdown fences, no explanation.

```json
{
  "headline": "50% Off This Summer — Shop Now",
  "sub_headline": "Premium footwear for the season",
  "offer": "50% discount on summer collection",
  "offer_present": true,
  "cta_text": "Shop Now",
  "cta_urgency": "high",
  "tone": "energetic",
  "tone_description": "bold, punchy, excitement-driven",
  "target_audience": "young adults, fashion-conscious shoppers",
  "key_promise": "significant savings on premium seasonal products",
  "pain_point": "expensive seasonal fashion",
  "product_category": "footwear",
  "visual_style": {
    "primary_color": "#FF6B35",
    "secondary_color": "#FFFFFF",
    "mood": "bold, bright, summery"
  },
  "social_proof_in_ad": null,
  "scarcity_signal": "Limited Time",
  "personalization_hooks": [
    "summer sale",
    "50% off",
    "premium shoes"
  ]
}
```

### Agent 1 System Prompt

```
You are an expert digital advertising analyst specialising in conversion rate optimisation.

Analyse the provided ad creative and extract structured data about its messaging,
offer, tone, and intent.

STRICT RULES:
- Extract ONLY what is explicitly visible or strongly implied in the ad.
- If a field is not present or cannot be inferred, set it to null.
- Do NOT invent products, prices, discounts, or features not present in the ad.
- Return ONLY valid JSON matching the exact schema provided. No explanation. No markdown.
- For "tone": choose exactly one from:
  [professional, energetic, luxury, playful, urgent, trustworthy, casual, authoritative,
   empathetic, bold]
- For "cta_urgency": choose exactly one from: [low, medium, high]
```

### Model Config — Agent 1
```
model:       claude-sonnet-4-20250514
max_tokens:  1000
temperature: 0.1
```

---

## 4. Agent 2 — LP Processor (Hero Extractor)

### Purpose
Fetch the landing page's raw HTML, use lxml + XPath to surgically identify the
hero section, extract it as a standalone HTML string, replace it in the full page
with a named placeholder comment, and return both artifacts to Agent 3.

Why lxml + XPath instead of class-name guessing:
- XPath can express structural logic: "find the element that contains BOTH an h1
  AND a CTA button" — this is the actual definition of a hero section, not its
  class name. Class names vary wildly across site builders (Webflow, Framer,
  WordPress, custom). Structure does not.
- lxml is C-based — fast enough to parse 200KB HTML pages in milliseconds.
- lxml.html handles malformed/messy real-world HTML without crashing, unlike the
  strict XML parser.
- lxml's tree manipulation (getparent().replace()) gives us clean, correct
  serialization back to an HTML string — no risk of introducing broken tags.

### Step 1 — Fetch Raw HTML

```python
import requests

def fetch_lp_html(lp_url: str) -> tuple[str, str]:
    """
    Fetch raw HTML from landing page URL.
    Returns (raw_html, base_url) or raises LPFetchError.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        response = requests.get(lp_url, headers=headers, timeout=15)
    except requests.exceptions.Timeout:
        raise LPFetchError("timeout", "Page took too long to respond.")
    except requests.exceptions.ConnectionError:
        raise LPFetchError("connection_error", "Could not reach this URL.")

    if response.status_code == 403:
        raise LPFetchError("blocked", "This page blocks automated access.")
    if response.status_code == 404:
        raise LPFetchError("not_found", "Page not found (404).")
    if response.status_code != 200:
        raise LPFetchError("http_error", f"HTTP {response.status_code}")

    raw_html = response.text

    # SPA / JS-rendered page check
    # If body has less than 500 characters of visible text, it's likely blank
    from lxml import html as lxml_html
    temp_tree = lxml_html.fromstring(raw_html)
    body_text = " ".join(temp_tree.text_content().split())
    if len(body_text) < 500:
        raise LPFetchError(
            "spa_blank",
            "This page renders via JavaScript. Please paste the page HTML manually."
        )

    # Derive base URL for <base href> injection later
    from urllib.parse import urlparse
    parsed = urlparse(lp_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}/"

    return raw_html, base_url
```

### Step 2 — Parse with lxml.html

```python
from lxml import html as lxml_html

def parse_html(raw_html: str):
    """
    Parse raw HTML string into an lxml HtmlElement tree.
    lxml.html.fromstring() auto-wraps in <html><body> if missing,
    and handles malformed tags gracefully.
    """
    tree = lxml_html.fromstring(raw_html)
    return tree
```

### Step 3 — Hero Detection via XPath Waterfall

This is the most critical step. We use a 5-level XPath waterfall.
Each level targets a more specific structural pattern — stop at the first match.

```python
from lxml import html as lxml_html
from lxml import etree
from typing import Optional

def detect_hero_element(tree) -> tuple[Optional[object], str]:
    """
    Detect the hero section element using XPath waterfall.
    Returns (lxml_element, detection_method_description).

    Detection philosophy:
    - XPath levels 1-3: Structural (most reliable — looks for semantic meaning)
    - XPath levels 4-5: Attribute-based (naming conventions — less reliable)
    - Fallback: Pure positional heuristic
    """

    # ─────────────────────────────────────────────────────────────────
    # LEVEL 1 — STRONGEST: Element containing h1 + CTA (button or link)
    # This is the true structural definition of a hero section:
    # it has a headline AND a call-to-action.
    # We look in section, div, or header tags only (not body itself).
    # ─────────────────────────────────────────────────────────────────
    results = tree.xpath(
        '('
        '  //*[self::section or self::div or self::header or self::article]'
        '  [.//h1]'
        '  ['
        '    .//button'
        '    or .//a[contains(@class,"btn")]'
        '    or .//a[contains(@class,"cta")]'
        '    or .//a[contains(@class,"button")]'
        '    or .//a[contains(@class,"cta")]'
        '    or .//input[@type="submit"]'
        '  ]'
        ')[1]'
    )
    if results:
        return results[0], "structural: h1 + CTA container"

    # ─────────────────────────────────────────────────────────────────
    # LEVEL 2: <header> semantic tag containing h1
    # HTML5 semantic structure — if a site uses <header> correctly,
    # this is the most authoritative signal.
    # ─────────────────────────────────────────────────────────────────
    results = tree.xpath('(//header[.//h1])[1]')
    if results:
        return results[0], "semantic: <header> with h1"

    # ─────────────────────────────────────────────────────────────────
    # LEVEL 3: First <section> inside <main> that contains h1
    # Modern page structure: <main> holds content, first <section> = hero.
    # ─────────────────────────────────────────────────────────────────
    results = tree.xpath('(//main//section[.//h1])[1]')
    if results:
        return results[0], "structural: first <section[h1]> in <main>"

    # ─────────────────────────────────────────────────────────────────
    # LEVEL 4: ID or class attribute containing "hero" or "banner"
    # (case-insensitive via XPath translate())
    # This handles explicit naming conventions used by Webflow, Framer,
    # WordPress themes etc.
    # ─────────────────────────────────────────────────────────────────
    LOWERCASE = 'abcdefghijklmnopqrstuvwxyz'
    UPPERCASE = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    results = tree.xpath(
        f'(//*['
        f'  contains(translate(@id,"{UPPERCASE}","{LOWERCASE}"),"hero")'
        f'  or contains(translate(@class,"{UPPERCASE}","{LOWERCASE}"),"hero")'
        f'  or contains(translate(@id,"{UPPERCASE}","{LOWERCASE}"),"banner")'
        f'  or contains(translate(@class,"{UPPERCASE}","{LOWERCASE}"),"banner")'
        f'  or contains(translate(@id,"{UPPERCASE}","{LOWERCASE}"),"jumbotron")'
        f'  or contains(translate(@class,"{UPPERCASE}","{LOWERCASE}"),"jumbotron")'
        f'  or contains(translate(@id,"{UPPERCASE}","{LOWERCASE}"),"masthead")'
        f'  or contains(translate(@class,"{UPPERCASE}","{LOWERCASE}"),"masthead")'
        f'])[1]'
    )
    if results:
        return results[0], "attribute: id/class contains hero/banner keyword"

    # ─────────────────────────────────────────────────────────────────
    # LEVEL 5: Any first-level section or div that contains h1
    # Pure positional fallback — the first h1-containing block is
    # almost always the hero on a well-structured landing page.
    # ─────────────────────────────────────────────────────────────────
    results = tree.xpath('(//*[self::section or self::div][.//h1])[1]')
    if results:
        return results[0], "positional: first section/div containing h1"

    # ─────────────────────────────────────────────────────────────────
    # LAST RESORT: h1's parent container
    # If no section/div structure exists, grab whatever wraps the h1.
    # ─────────────────────────────────────────────────────────────────
    results = tree.xpath('//h1')
    if results:
        parent = results[0].getparent()
        if parent is not None:
            return parent, "fallback: h1 parent element"

    return None, "not_found"
```

### Step 4 — Size Guard

```python
from lxml import html as lxml_html

def guard_hero_size(hero_el, tree) -> object:
    """
    If the detected hero element is too large (>12,000 chars), it likely
    captured a nav+hero combo or a wrapper div. Narrow it down.
    Strategy: find the deepest descendant that still contains h1 + CTA.
    """
    hero_html = lxml_html.tostring(hero_el, encoding='unicode', with_tail=False)

    if len(hero_html) <= 12000:
        return hero_el  # Fine as-is

    # Try to narrow: find direct children of hero_el, pick the one with h1
    for child in hero_el:
        child_html = lxml_html.tostring(child, encoding='unicode', with_tail=False)
        child_tree = lxml_html.fromstring(child_html)
        if child_tree.xpath('.//h1'):
            return child  # Return the narrower child element

    # If narrowing failed, return the h1's grandparent as a last resort
    h1_results = hero_el.xpath('.//h1')
    if h1_results:
        grandparent = h1_results[0].getparent()
        if grandparent is not None:
            return grandparent

    return hero_el  # Return original if all narrowing failed
```

### Step 5 — Extract + Inject Placeholder

```python
from lxml import html as lxml_html
from lxml import etree

PLACEHOLDER_COMMENT = ' __HERO_SECTION_PLACEHOLDER__ '

def extract_and_placeholder(tree, hero_el) -> tuple[str, str]:
    """
    1. Serialise hero element to HTML string (hero_html_chunk).
    2. Replace hero element in the tree with a placeholder comment node.
    3. Serialise the modified full tree (main_html_with_placeholder).

    Returns (hero_html_chunk, main_html_with_placeholder).
    """
    # Capture the hero HTML string BEFORE removing it from tree
    hero_html_chunk = lxml_html.tostring(
        hero_el,
        encoding='unicode',
        with_tail=False      # Don't include trailing whitespace/text
    )

    # Create placeholder comment node
    placeholder_node = etree.Comment(PLACEHOLDER_COMMENT)

    # Replace hero in the live tree with placeholder
    # getparent() gives us the parent element so we can do the swap
    parent = hero_el.getparent()
    if parent is None:
        raise ExtractionError("Hero element has no parent — cannot replace.")
    parent.replace(hero_el, placeholder_node)

    # Serialise the full modified page
    # lxml_html.tostring on the root element gives the complete HTML
    main_html_with_placeholder = lxml_html.tostring(
        tree,
        encoding='unicode',
        doctype='<!DOCTYPE html>',
        pretty_print=False   # Don't pretty-print — preserves original whitespace
    )

    return hero_html_chunk, main_html_with_placeholder
```

### Step 6 — Inject base href

```python
from bs4 import BeautifulSoup

def inject_base_href(main_html_with_placeholder: str, base_url: str) -> str:
    """
    Adds <base href="https://original-domain.com/"> into <head>.
    This is CRITICAL — without it, all relative paths (CSS, images, fonts, JS)
    will 404 when the HTML is rendered in an iframe on our domain.

    We use BeautifulSoup with lxml backend here because it handles
    <head> injection more cleanly than lxml.html serialisation.
    """
    soup = BeautifulSoup(main_html_with_placeholder, "lxml")

    head = soup.find("head")
    if head:
        existing_base = head.find("base")
        if existing_base:
            existing_base["href"] = base_url
        else:
            new_base = soup.new_tag("base", href=base_url)
            head.insert(0, new_base)

    return str(soup)
```

### Step 7 — Full LP Processor Orchestrator

```python
def process_lp(lp_url: str) -> dict:
    """
    Full Agent 2 pipeline. Returns dict with all outputs needed by Agent 3.
    """
    # 1. Fetch
    raw_html, base_url = fetch_lp_html(lp_url)

    # 2. Parse with lxml
    tree = parse_html(raw_html)

    # 3. Detect hero via XPath waterfall
    hero_el, detection_method = detect_hero_element(tree)
    if hero_el is None:
        raise ExtractionError(f"Could not identify hero section. Method tried: {detection_method}")

    # 4. Guard size
    hero_el = guard_hero_size(hero_el, tree)

    # 5. Extract + placeholder
    hero_html_chunk, main_html_with_placeholder = extract_and_placeholder(tree, hero_el)

    # 6. Inject base href
    main_html_with_placeholder = inject_base_href(main_html_with_placeholder, base_url)

    return {
        "hero_html_chunk": hero_html_chunk,
        "main_html_with_placeholder": main_html_with_placeholder,
        "hero_detected": True,
        "hero_detection_method": detection_method,
        "hero_char_count": len(hero_html_chunk),
        "base_url": base_url
    }
```

### Agent 2 Edge Cases

| Failure | Detection Point | Response | Fallback |
|---|---|---|---|
| HTTP timeout | requests timeout >15s | "Page too slow. Try again or paste HTML." | Manual paste UI |
| HTTP 403/blocked | status_code == 403 | "Page blocks bots. Paste HTML manually." | Manual paste UI |
| HTTP 404 | status_code == 404 | "Page not found." | — |
| JS SPA (blank page) | body text < 500 chars | "Page needs JavaScript to render. Paste HTML." | Manual paste UI |
| No hero found (all 5 XPath levels fail) | hero_el is None | Take first 40% of body's child elements by count | Whole body |
| Hero too large (>12KB) | len(hero_html) > 12000 | guard_hero_size() narrows to h1-containing child | h1.getparent() |
| Hero el has no parent | getparent() returns None | ExtractionError → return error to frontend | — |

---

## 5. Agent 3 — Hero Enhancer (Core Personalisation)

### Purpose
Combine the ad_data JSON (what the user was promised) with the hero_html_chunk
(what they currently see on landing) and produce an ENHANCED version of the hero
HTML that aligns messaging with the ad's promise — without changing any structural
attributes, classes, layout, or non-text content.

### Critical Design Constraint: ENHANCE, Do Not Replace

The LLM receives only the hero chunk (~2-8KB), NOT the full page HTML.
This is intentional:
- Smaller context → fewer hallucinations
- Focused scope → LLM cannot accidentally break other sections
- Faster → lower latency, lower cost

What the LLM CAN change:
- Text content inside h1, h2, h3 (headlines)
- Text content inside p tags in the hero (body copy, max 2-3 sentences)
- Text content inside button tags and a tags (CTA label text only)
- Optionally add ONE offer banner div (only if ad has an offer not in hero)

What the LLM CANNOT change:
- Any HTML attribute: class, id, href, src, data-*, style, aria-*
- Any CSS classes or inline styles
- Image src URLs
- The HTML structure or tag hierarchy
- Any content below the hero section (it never sees it)

### Agent 3 System Prompt

```
You are an expert CRO (Conversion Rate Optimisation) specialist and frontend developer.

You will receive two inputs:
1. AD CREATIVE DATA — structured JSON describing what the user was promised in the ad:
{ad_data_json}

2. HERO HTML — the current hero section of the landing page the user arrived on:
{hero_html_chunk}

YOUR TASK:
Enhance the hero HTML so it creates strong message match with the ad creative.
Message match = the user sees language on the page that directly confirms the ad's promise.
This is the #1 CRO lever for improving landing page conversion rates.

WHAT YOU ARE ALLOWED TO MODIFY:
1. Text content inside <h1>, <h2>, <h3> tags — align headline to ad's headline/promise
2. Text content inside <p> tags within the hero — align body copy to ad's messaging
   (2-3 sentences max per paragraph, do not add new paragraphs)
3. Text content inside <button> and <a> tags — align CTA text to ad's CTA
   (change ONLY the visible text, never touch href, class, id, or any attribute)
4. If the ad has a specific offer (discount, free trial, bonus) not present in the
   hero copy, you MAY add exactly ONE offer banner using this EXACT structure:
   <div class="ad-personalizer-banner"
        style="background:#EEF6FF;border:1px solid #C7E0FF;padding:12px 24px;
               text-align:center;font-weight:600;border-radius:4px;margin-bottom:16px;">
     {offer_text_here}
   </div>
   Place it as the FIRST child element inside the outermost hero container.

STRICT RULES — THESE ARE NON-NEGOTIABLE:
1. Return ONLY the enhanced HTML. Nothing else. No explanation. No markdown. No code fences.
2. Do NOT change any HTML attribute: class, id, href, src, data-*, style, aria-* — leave ALL
   attributes exactly as they appear in the input.
3. Do NOT invent any products, prices, features, or claims not present in EITHER the ad data
   OR the original hero HTML. Your changes must be grounded in the inputs.
4. Do NOT remove any existing elements — every tag in the input must appear in the output.
5. Do NOT add new structural elements (divs, sections, containers) beyond the one offer banner.
6. Do NOT change image src URLs or any media references.
7. Tone must match the ad: {tone} — {tone_description}
8. If the hero is already well-aligned with the ad, make minimal changes or return it unchanged.
   Do not modify for the sake of modifying.
9. The output must be parseable, valid HTML — all tags opened must be closed correctly.
```

### Model Config — Agent 3
```
model:       claude-sonnet-4-20250514
max_tokens:  8000
temperature: 0.15   (low — prioritise consistency over creativity)
```

### LLM Response Cleaning

Before using the LLM's response, always strip potential markdown artifacts:

```python
import re

def clean_llm_html_response(raw_response: str) -> str:
    """
    Strip markdown code fences that the LLM might add despite instructions.
    Handles: ```html ... ```, ``` ... ```, `...`
    """
    # Remove ```html ... ``` blocks
    cleaned = re.sub(r'^```(?:html)?\s*\n?', '', raw_response.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned.strip())
    return cleaned.strip()
```

---

## 6. Step 3 — Surgical Stitching + Validation

### Primary Path — Python String Replace

```python
PLACEHOLDER_COMMENT_STRING = '<!-- __HERO_SECTION_PLACEHOLDER__ -->'

def stitch_html(main_html_with_placeholder: str, enhanced_hero_html: str) -> str:
    """
    Replace the placeholder comment with the enhanced hero HTML.
    Pure string operation — no parsing needed, no risk of re-mangling.
    """
    if PLACEHOLDER_COMMENT_STRING not in main_html_with_placeholder:
        raise StitchError("Placeholder not found in main HTML.")

    final_html = main_html_with_placeholder.replace(
        PLACEHOLDER_COMMENT_STRING,
        enhanced_hero_html,
        1   # Replace only the FIRST occurrence (safety: never replace more than one)
    )
    return final_html
```

### HTML Validation

```python
from bs4 import BeautifulSoup

def validate_html(html_string: str, enhanced_hero_html: str) -> tuple[bool, list[str]]:
    """
    Validate the stitched HTML for structural integrity.
    Returns (is_valid, list_of_issues).
    """
    issues = []

    try:
        soup = BeautifulSoup(html_string, "lxml")
    except Exception as e:
        return False, [f"Parse failed: {str(e)}"]

    # Structural checks
    if not soup.find("html"):
        issues.append("Missing <html> tag")
    if not soup.find("head"):
        issues.append("Missing <head> tag")
    if not soup.find("body"):
        issues.append("Missing <body> tag")
    if not soup.find("base"):
        issues.append("Missing <base href> tag — images/CSS may not load")

    # Placeholder was actually replaced
    if "__HERO_SECTION_PLACEHOLDER__" in html_string:
        issues.append("Placeholder was not replaced — stitching failed")

    # Enhanced content made it into the final HTML
    # Check by looking for a text fragment unique to the enhanced hero
    from bs4 import BeautifulSoup as BS
    enhanced_soup = BS(enhanced_hero_html, "lxml")
    h1_in_enhanced = enhanced_soup.find("h1")
    if h1_in_enhanced:
        enhanced_text = h1_in_enhanced.get_text(strip=True)[:30]
        if enhanced_text and enhanced_text not in html_string:
            issues.append("Enhanced hero headline not found in final output")

    return len(issues) == 0, issues
```

### Fallback Path — Agent 4 (LLM Stitcher)

Triggered when `validate_html()` returns `is_valid = False`.

```python
AGENT_4_PROMPT = """
You are an expert HTML developer performing a precise replacement task.

You will receive:
1. A complete HTML page with this exact placeholder comment inside it:
   <!-- __HERO_SECTION_PLACEHOLDER__ -->

2. An HTML snippet that must replace that placeholder.

YOUR TASK:
Return the complete, final HTML with the placeholder replaced by the provided snippet.

RULES:
- The output must be well-formed, valid HTML.
- All content outside the placeholder must be preserved exactly as given.
- The inserted snippet must appear exactly where the placeholder was.
- No content may be duplicated, removed, or modified.
- Return ONLY the final HTML. No explanation. No markdown.

MAIN HTML (with placeholder):
{main_html_with_placeholder}

SNIPPET TO INSERT (replace the placeholder with this):
{enhanced_hero_html}
"""

# Model config for Agent 4
# temperature=0.0 — this is a mechanical task, zero creativity needed
# model: claude-sonnet-4-20250514
# max_tokens: 32000 — needs enough room for full page output
```

If Agent 4 also fails validation, serve the original landing page URL in the iframe
(not our modified version) alongside the change summary of what we attempted.
Always show something — never a blank screen for the reviewer.

---

## 7. Script Sanitisation (Security)

Before rendering any HTML in a sandboxed iframe, strip executable JavaScript:

```python
from bs4 import BeautifulSoup

def sanitize_for_iframe(html_string: str) -> str:
    """
    Remove executable JavaScript for safe iframe rendering.
    Preserves: <link> stylesheets, <style> blocks, all layout.
    Removes: <script> tags, javascript: hrefs, inline event handlers.
    """
    soup = BeautifulSoup(html_string, "lxml")

    # Remove all <script> tags
    for tag in soup.find_all("script"):
        tag.decompose()

    # Remove javascript: href values
    for tag in soup.find_all(href=True):
        if tag.get("href", "").strip().lower().startswith("javascript:"):
            tag["href"] = "#"

    # Remove inline JavaScript event handler attributes
    # (onclick, onload, onmouseover, onsubmit, etc.)
    for tag in soup.find_all(True):
        attrs_to_remove = [attr for attr in tag.attrs if attr.lower().startswith("on")]
        for attr in attrs_to_remove:
            del tag.attrs[attr]

    return str(soup)
```

---

## 8. Change Summary Generation

After stitching, generate a human-readable change log.
Uses BeautifulSoup diff on hero strings — no extra LLM call needed.

```python
from bs4 import BeautifulSoup

def generate_change_summary(original_hero_html: str, enhanced_hero_html: str) -> list[dict]:
    """
    Compare original and enhanced hero HTML to produce a list of change records.
    Each record: { "element": str, "original": str|None, "updated": str }
    """
    orig = BeautifulSoup(original_hero_html, "lxml")
    enhanced = BeautifulSoup(enhanced_hero_html, "lxml")
    changes = []

    # Compare h1
    o_h1 = orig.find("h1")
    e_h1 = enhanced.find("h1")
    if o_h1 and e_h1 and o_h1.get_text(strip=True) != e_h1.get_text(strip=True):
        changes.append({
            "element": "Main Headline (H1)",
            "original": o_h1.get_text(strip=True)[:100],
            "updated":  e_h1.get_text(strip=True)[:100]
        })

    # Compare h2, h3 (sub-headlines)
    for tag_name in ["h2", "h3"]:
        o_tag = orig.find(tag_name)
        e_tag = enhanced.find(tag_name)
        if o_tag and e_tag and o_tag.get_text(strip=True) != e_tag.get_text(strip=True):
            changes.append({
                "element": f"Sub-headline ({tag_name.upper()})",
                "original": o_tag.get_text(strip=True)[:100],
                "updated":  e_tag.get_text(strip=True)[:100]
            })

    # Compare first paragraph (body copy)
    o_p = orig.find("p")
    e_p = enhanced.find("p")
    if o_p and e_p and o_p.get_text(strip=True) != e_p.get_text(strip=True):
        changes.append({
            "element": "Hero Body Copy",
            "original": o_p.get_text(strip=True)[:120],
            "updated":  e_p.get_text(strip=True)[:120]
        })

    # Compare CTA buttons and links
    o_buttons = orig.find_all(["button", "a"])
    e_buttons = enhanced.find_all(["button", "a"])
    for o_btn, e_btn in zip(o_buttons, e_buttons):
        o_text = o_btn.get_text(strip=True)
        e_text = e_btn.get_text(strip=True)
        if o_text and e_text and o_text != e_text:
            changes.append({
                "element": "CTA Button / Link",
                "original": o_text[:80],
                "updated":  e_text[:80]
            })

    # Check if offer banner was injected
    banner = enhanced.find(class_="ad-personalizer-banner")
    if banner:
        changes.append({
            "element": "Offer Banner (Added)",
            "original": None,
            "updated":  banner.get_text(strip=True)[:120]
        })

    if not changes:
        changes.append({
            "element": "No changes made",
            "original": None,
            "updated": "Hero section was already well-aligned with ad creative."
        })

    return changes
```

---

## 9. API Endpoint Specification

### POST /api/personalize

**Request (multipart/form-data or JSON):**
```json
{
    "adType":        "image",
    "adImageBase64": "data:image/jpeg;base64,...",
    "adUrl":         null,
    "lpUrl":         "https://brand.com/summer-sale"
}
```

**Success Response:**
```json
{
    "status":              "success",
    "personalizedHtml":    "<!DOCTYPE html>...",
    "originalHeroHtml":    "<section class='hero'>...</section>",
    "enhancedHeroHtml":    "<section class='hero'>...</section>",
    "adData":              { "headline": "...", "offer": "...", ... },
    "changeSummary": [
        {
            "element":  "Main Headline (H1)",
            "original": "Shop Our Collection",
            "updated":  "Get 50% Off Summer Shoes"
        },
        {
            "element":  "CTA Button / Link",
            "original": "Explore",
            "updated":  "Shop Now — Limited Time"
        },
        {
            "element":  "Offer Banner (Added)",
            "original": null,
            "updated":  "50% Off All Summer Styles — Today Only"
        }
    ],
    "heroDetectionMethod": "structural: h1 + CTA container",
    "validationPassed":    true,
    "fallbackUsed":        false,
    "processingTimeMs":    3800
}
```

**Error Response:**
```json
{
    "status":     "error",
    "errorType":  "lp_blocked",
    "message":    "This page blocks automated access. Please paste the page HTML manually.",
    "userAction": "manual_paste"
}
```

---

## 10. Frontend Specification

### Layout

```
HEADER
  AdPersonalizer | Align your landing page to every ad, instantly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INPUT PANEL
┌──────────────────────────┬─────────────────────────────────┐
│  AD CREATIVE             │  LANDING PAGE URL               │
│  ┌────────────────────┐  │  ┌───────────────────────────┐  │
│  │  Drop image here   │  │  │ https://brand.com/page    │  │
│  │  or paste URL ↓    │  │  └───────────────────────────┘  │
│  └────────────────────┘  │                                 │
│  [preview thumbnail]     │  [URL validation indicator]     │
└──────────────────────────┴─────────────────────────────────┘

            [ ✦ Personalize This Page ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROCESSING STATE (real-time steps, shown in sequence)
  ✓ Step 1/4: Analysing ad creative...
  ✓ Step 2/4: Extracting hero section from landing page...
  ⟳ Step 3/4: Personalising with ad messaging...
  ○ Step 4/4: Validating and rendering...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT STATE

CHANGE SUMMARY                                    [Collapse]
├── ✓ H1: "Shop Our Collection" → "Get 50% Off Summer Shoes"
├── ✓ CTA: "Explore" → "Shop Now — Limited Time"
└── ✓ Offer Banner Added: "50% Off All Summer Styles"

┌──────────────────────────┬─────────────────────────────────┐
│  ORIGINAL PAGE           │  PERSONALIZED PAGE              │
│  [iframe: original URL]  │  [iframe: srcdoc=finalHtml]     │
│                          │                                 │
└──────────────────────────┴─────────────────────────────────┘

[Copy HTML]  [Download .html]  [Try Different Ad]  [Reset]
```

### Processing Steps — Real-Time SSE Stream

Use Server-Sent Events to update the UI at each pipeline stage.
Do not use a generic spinner. Each step label communicates intelligence.

```
data: {"step": 1, "label": "Analysing ad creative...", "done": false}
data: {"step": 1, "label": "Ad analysed.", "done": true}
data: {"step": 2, "label": "Extracting hero section from landing page...", "done": false}
data: {"step": 2, "label": "Hero section identified.", "done": true}
data: {"step": 3, "label": "Personalising hero with ad messaging...", "done": false}
data: {"step": 3, "label": "Personalisation complete.", "done": true}
data: {"step": 4, "label": "Validating output...", "done": false}
data: {"step": 4, "label": "Ready.", "done": true}
```

### iframe Sandboxing
```html
<!-- Left: original page (by URL) -->
<iframe
    src="{lp_url}"
    style="width:100%;height:600px;border:none;"
/>

<!-- Right: personalized page (by HTML content) -->
<iframe
    srcdoc="{finalHtml}"
    sandbox="allow-same-origin allow-scripts"
    style="width:100%;height:600px;border:none;"
/>
```

---

## 11. Tech Stack

### Backend — Python FastAPI
```
fastapi              — API server
uvicorn              — ASGI runtime
requests             — HTTP client for LP fetching + ad URL resolution
lxml                 — Fast C-based HTML parser + XPath hero detection + tree manipulation
beautifulsoup4       — HTML validation, change summary diff, base href injection
                       (used with lxml as the parsing backend: BeautifulSoup(html, "lxml"))
anthropic            — Claude API client (Vision for ad images, Text for personalization)
python-multipart     — Multipart form data (image uploads)
python-dotenv        — API key management
```

### Frontend — Next.js / React
```
Next.js (App Router) — UI framework
Tailwind CSS         — Styling
react-dropzone       — Ad image drag-and-drop upload
```

### Hosting
```
Backend:   Railway or Render (free tier — Python FastAPI, auto-deploy from GitHub)
Frontend:  Vercel (free — Next.js, auto-deploy from GitHub)
```

### Environment Variables
```
ANTHROPIC_API_KEY=sk-ant-...
```

### requirements.txt
```
fastapi==0.115.0
uvicorn==0.30.6
requests==2.32.3
lxml==5.3.0
beautifulsoup4==4.12.3
anthropic==0.40.0
python-multipart==0.0.12
python-dotenv==1.0.1
```

---

## 12. File Structure

```
adpersonalizer/
│
├── backend/
│   ├── main.py                     # FastAPI app entry point
│   │                               # POST /api/personalize
│   │                               # GET  /api/health
│   │
│   ├── agents/
│   │   ├── ad_analyzer.py          # Agent 1
│   │   │                           # Input: image bytes OR url string
│   │   │                           # Output: ad_data dict (JSON)
│   │   │
│   │   ├── lp_processor.py         # Agent 2
│   │   │                           # Input: lp_url string
│   │   │                           # Output: hero_html_chunk, main_html_with_placeholder
│   │   │                           # Uses: lxml XPath waterfall + size guard
│   │   │
│   │   ├── hero_enhancer.py        # Agent 3
│   │   │                           # Input: ad_data dict + hero_html_chunk
│   │   │                           # Output: enhanced_hero_html string
│   │   │
│   │   └── fallback_stitcher.py    # Agent 4
│   │                               # Input: main_html_with_placeholder + enhanced_hero_html
│   │                               # Output: final_html string (via LLM)
│   │
│   ├── utils/
│   │   ├── html_validator.py       # validate_html() + sanitize_for_iframe()
│   │   ├── change_summary.py       # generate_change_summary() — BS4 diff
│   │   ├── stitcher.py             # stitch_html() — string replace
│   │   └── errors.py               # LPFetchError, ExtractionError, StitchError
│   │
│   ├── prompts/
│   │   ├── ad_analyzer_prompt.txt  # Agent 1 system prompt (text)
│   │   └── hero_enhancer_prompt.txt # Agent 3 system prompt (text)
│   │
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   └── page.tsx                # Main page — inputs + processing + output
│   ├── components/
│   │   ├── AdInput.tsx             # Image upload (drag-drop) + URL input + preview
│   │   ├── LPInput.tsx             # LP URL input + validation indicator
│   │   ├── ProcessingSteps.tsx     # SSE consumer — step-by-step progress UI
│   │   ├── SplitPreview.tsx        # Side-by-side iframe viewer
│   │   └── ChangeSummary.tsx       # Change log display with expand/collapse
│   └── package.json
│
└── README.md
```

---

## 13. Assumptions Made

Per the assignment instruction ("feel free to make assumptions, just mention them"):

1. Hero section = the first identifiable container holding a main headline and
   primary CTA. Typically the top 20-30% of the page. Only this is modified.
   Everything below the fold is left completely untouched.

2. Ad creative = a single image or URL per personalisation run.
   Carousels, video ads, and GIF sequences are out of scope for the MVP.

3. Image assets on the landing page are NOT replaced. Only visible text copy
   is enhanced. This prevents layout breakage from mismatched image dimensions.

4. The system performs message match personalisation only. It does not:
   - Run A/B test variant generation
   - Deploy changes to the live site
   - Track post-personalisation conversion rates (roadmap feature)

5. JavaScript-heavy SPAs that render blank on server-side fetch are handled by
   surfacing a manual HTML paste option. Headless browser (Playwright) rendering
   is a Day 2 feature — not needed for MVP validation.

6. The personalised HTML output is for demo/preview purposes.
   Direct deploy to Webflow/Framer/WordPress via API is a roadmap feature.

---

## 14. Edge Case Matrix

| Scenario | Detection Point | Primary Response | Fallback |
|---|---|---|---|
| Image upload — valid format | File extension + content-type | VLM analysis (Agent 1) | — |
| Image URL — 404 / dead | requests.get status != 200 | "Image URL broken. Upload directly." | — |
| LP URL — 403 blocked | status_code == 403 | "Page blocks bots. Paste HTML manually." | Manual paste |
| LP URL — timeout | requests timeout >15s | "Page too slow. Try again." | Manual paste |
| LP URL — JS SPA blank | Body text < 500 chars | "Needs JS rendering. Paste HTML." | Manual paste |
| No hero found (all 5 XPath levels fail) | hero_el is None | Take first 40% of body children by count | Whole `<body>` |
| Hero too large (>12KB) | len(hero_html) > 12000 | guard_hero_size() narrows element | h1.getparent() |
| LLM returns markdown fences | clean_llm_html_response() | Strip ` ```html ``` ` fences | Regex fallback |
| LLM hallucinates new products | Post-generation review prompt | Flag + regenerate with stricter prompt | Return original hero |
| Stitching produces broken HTML | validate_html() fails | Agent 4 LLM stitcher | Original LP URL |
| Agent 4 also fails | validate_html() fails again | Show original LP + attempted change log | — |
| Ad has no detectable offer | offer_present == false | Skip banner injection entirely | — |
| Non-English landing page | langdetect on body text | Personalise in detected language | English fallback |
| Hero already well-aligned | Similarity check in prompt | Minimal/no changes — show "Already aligned" | — |

---

## 15. Explanation Doc Outline (for Google Doc submission)

**Section 1 — Problem Statement**
The ad-to-landing-page disconnect. When a user clicks an ad promising X and lands on
a page talking about Y, conversion dies. Message match is the #1 CRO lever.
This tool makes it automatic.

**Section 2 — System Architecture**
Four-agent pipeline diagram. Explain each agent's role and what it consumes/produces.
Emphasise: we only modify the hero (top 20-30%) — everything else stays intact.

**Section 3 — Key Technical Decisions**
- Why lxml XPath for hero detection: structural logic ("contains h1 + CTA") is
  more reliable than class-name guessing across different site builders.
- Why BeautifulSoup with lxml backend for validation/diffing: friendlier API for
  these tasks, same speed as native lxml.
- Why ENHANCE not REPLACE: prevents hallucinations, preserves brand, maintains
  layout integrity. LLM only sees ~5KB, not 200KB.
- Why placeholder-based stitching: Python string replace is deterministic;
  LLM cannot accidentally break what it never saw.
- Why Agent 4 fallback: defense in depth — always serve something to the reviewer.
- Why temperature=0.15: consistency over creativity for a production system.

**Section 4 — Edge Case Handling**
Copy the Edge Case Matrix table above directly.

**Section 5 — What I'd Build Next (2-week roadmap)**
- A/B variant generation: 3 hero variants per ad, brand picks the winner
- Segment-level personalisation: different hero per audience segment in the ad set
- Webflow/Framer/WordPress deploy via their APIs — go from preview to live
- Conversion tracking: instrument personalised vs original page, compare CVR
- Batch mode: input 10 ads → 10 LP variants generated in parallel
- Headless browser fallback (Playwright) for JS-rendered SPAs

---

*Architecture Document v3.0 — Final*
*Author: Shivam Rajput | Troopod AI PM Internship Assignment*
