# AdPersonalizer — Revised System Architecture
### Troopod AI PM Assignment | Shivam Rajput
### Version 2.0 — Surgical Hero Extraction Pipeline

---

## 1. Core Philosophy

This system does NOT rewrite landing pages. It ENHANCES them.

The ad creative defines a user's expectation before they click. The landing page must
immediately confirm that expectation in the first 20-30% of the page (the hero section).
Everything below the fold — pricing, features, FAQs, testimonials — stays untouched.

Architecture principle: Extract the smallest possible chunk of HTML, enhance it with
ad context using an LLM, stitch it back surgically, and validate before serving.

Assignment constraint respected: "The personalized page shouldn't be a completely new page,
it should be existing page enhanced as per CRO principles + personalized as per the ad creative."

---

## 2. High-Level Pipeline

```
[User Input]
     ├── Ad Creative (image upload OR URL)
     └── Landing Page URL
                │
                ▼
════════════════════════════════════════════════════
  STEP 1 — PARALLEL EXTRACTION
════════════════════════════════════════════════════
     ├── [Agent 1: Ad Analyzer]      → ad_data JSON
     └── [Agent 2: LP Processor]     → hero_html_chunk
                                        main_html_with_placeholder
                │
                ▼
════════════════════════════════════════════════════
  STEP 2 — PERSONALIZATION
════════════════════════════════════════════════════
     [Agent 3: Hero Enhancer]
     INPUT:  ad_data JSON + hero_html_chunk
     OUTPUT: enhanced_hero_html
                │
                ▼
════════════════════════════════════════════════════
  STEP 3 — SURGICAL STITCHING
════════════════════════════════════════════════════
     Python: replace placeholder → validate HTML
     IF valid → serve final HTML
     IF broken → [Agent 4: Fallback Stitcher LLM]
                │
                ▼
     [Frontend: Split-view preview + Change Summary]
```

---

## 3. Agent 1 — Ad Analyzer

### Purpose
Convert the ad creative (image or URL) into a structured JSON context object
that defines the ad's messaging, offer, tone, and visual identity.

### Input Handling (Conditional Branch)

```
Ad Input
   │
   ├── IF image upload (.jpg/.png/.gif/.webp)
   │      └── encode to base64 → send to Claude Vision (claude-sonnet-4-20250514)
   │
   ├── IF URL ends in image extension (.jpg/.png/.gif/.webp)
   │      └── requests.get(url) → check Content-Type: image/*
   │              ├── YES → encode to base64 → Claude Vision
   │              └── NO  → treat as HTML page → Jina Reader scrape → Claude text
   │
   └── IF URL is a webpage (HTML ad / ad landing page)
          └── Jina Reader (r.jina.ai/{url}) → clean text → Claude text
```

### Output Schema (ad_data JSON)

The LLM must return ONLY this JSON. No extra text. No markdown fences.

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
You are an expert digital advertising analyst specializing in conversion rate optimization.

Analyze the provided ad creative and extract structured data about its messaging, 
offer, tone, and intent.

STRICT RULES:
- Extract ONLY what is explicitly visible or strongly implied in the ad.
- If a field is not present or cannot be inferred, set it to null.
- Do NOT invent products, prices, discounts, or features not present in the ad.
- Return ONLY valid JSON matching the schema. No explanation. No markdown.
- For tone: choose from [professional, energetic, luxury, playful, urgent, trustworthy, 
  casual, authoritative, empathetic, bold]
- For cta_urgency: choose from [low, medium, high]
```

---

## 4. Agent 2 — LP Processor (Hero Extractor)

### Purpose
Fetch the landing page's full raw HTML, use BeautifulSoup to surgically identify
and extract the hero section (top 20-30% of the page), replace it with a named
placeholder, and output two artifacts:
1. `main_html_with_placeholder` — the full page HTML with hero section removed
2. `hero_html_chunk` — the extracted hero section HTML only

### Step-by-Step Logic

#### 4a. Fetch Raw HTML
```python
import requests
from bs4 import BeautifulSoup

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
response = requests.get(lp_url, headers=headers, timeout=15)
raw_html = response.text
```

#### 4b. Parse with BeautifulSoup
```python
soup = BeautifulSoup(raw_html, "html.parser")
```

#### 4c. Hero Section Identification Strategy

Use a priority waterfall — stop at the first match:

```python
def find_hero_section(soup):
    """
    Priority waterfall to identify the hero section.
    Returns the BeautifulSoup Tag object if found, else None.
    """

    # Priority 1: Explicit semantic tag
    hero = soup.find("header")
    if hero and len(hero.get_text(strip=True)) > 50:
        return hero

    # Priority 2: ID-based selectors (most specific)
    id_candidates = ["hero", "banner", "jumbotron", "main-hero", 
                     "hero-section", "top-section", "intro", "above-fold"]
    for id_val in id_candidates:
        hero = soup.find(id=id_val)
        if hero:
            return hero

    # Priority 3: Class-based selectors (common frameworks)
    class_candidates = [
        "hero", "hero-section", "hero-banner", "hero-area", "hero-content",
        "banner", "jumbotron", "landing-hero", "page-hero", "site-hero",
        "masthead", "intro-section", "top-section", "above-fold",
        "header-section", "main-banner", "full-screen", "full-width-hero"
    ]
    for class_name in class_candidates:
        hero = soup.find(class_=lambda c: c and class_name in c.lower().split())
        if hero:
            return hero

    # Priority 4: Data attributes (common in modern CMSes)
    hero = soup.find(attrs={"data-section": lambda v: v and "hero" in v.lower()})
    if hero:
        return hero

    # Priority 5: First <section> tag inside <main> (structural heuristic)
    main_tag = soup.find("main")
    if main_tag:
        first_section = main_tag.find("section")
        if first_section:
            return first_section

    # Priority 6: First <section> in body
    first_section = soup.find("section")
    if first_section:
        return first_section

    # Priority 7: First <div> with substantial text that contains an <h1>
    for div in soup.find_all("div", recursive=True):
        if div.find("h1") and len(div.get_text(strip=True)) > 100:
            return div

    # Priority 8: Fallback — just grab the <h1> and its parent container
    h1 = soup.find("h1")
    if h1:
        return h1.parent

    return None
```

#### 4d. Extract and Replace with Placeholder

```python
PLACEHOLDER_TOKEN = "<!-- __HERO_SECTION_PLACEHOLDER__ -->"

def extract_hero(soup, hero_tag):
    """
    Extracts hero HTML and replaces it with a placeholder in the soup.
    Returns (hero_html_string, modified_soup)
    """
    hero_html = str(hero_tag)  # Save the hero HTML string

    # Replace the hero tag in the soup with our placeholder comment
    from bs4 import Comment
    placeholder = Comment("__HERO_SECTION_PLACEHOLDER__")
    hero_tag.replace_with(placeholder)

    return hero_html, soup
```

#### 4e. Inject Base HREF (Critical for Styles/Images to Load)

```python
def inject_base_href(soup, lp_url):
    """
    Adds <base href> so all relative URLs (CSS, images, fonts) resolve correctly
    when HTML is rendered in an iframe on our domain.
    """
    from urllib.parse import urlparse
    parsed = urlparse(lp_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}/"

    # Insert or update <base> tag in <head>
    head = soup.find("head")
    if head:
        existing_base = head.find("base")
        if existing_base:
            existing_base["href"] = base_url
        else:
            base_tag = soup.new_tag("base", href=base_url)
            head.insert(0, base_tag)
    return soup
```

#### 4f. Size Safety Check

```python
# If hero_html_chunk exceeds 15,000 characters, it's likely a nav+hero combo.
# In this case, try to narrow to just the element containing <h1>.
if len(hero_html) > 15000:
    h1 = BeautifulSoup(hero_html, "html.parser").find("h1")
    if h1:
        # Re-run extraction targeting the h1's grandparent
        hero_tag = h1.parent.parent
        hero_html = str(hero_tag)
```

### Outputs from Agent 2

```python
{
    "hero_html_chunk": "<section class='hero'>...</section>",   # ~2-8KB
    "main_html_with_placeholder": "<!DOCTYPE html>...",         # full page, placeholder inside
    "hero_identified": true,
    "hero_detection_method": "class-based: hero-section",
    "hero_char_count": 3420,
    "base_href_injected": "https://brand.com/"
}
```

### Agent 2 Edge Cases

| Problem | Detection | Solution |
|---|---|---|
| Fetch timeout | requests timeout > 15s | Return error to user: "Page took too long. Try again or paste HTML manually." |
| HTTP 403/blocked | Status code != 200 | Return error: "This page blocks automated access. Paste the page source manually." |
| Blank page (JS SPA) | response.text contains less than 500 chars of visible text | Fallback: show error + manual paste option (no Playwright in MVP) |
| No hero found | all 8 priority checks fail | Fallback: extract `<body>` first 40% of child elements by count |
| Hero too large (>15KB) | char count check | Narrow to h1.parent.parent as described above |
| No `<head>` tag | missing head | Create one and inject base href |

---

## 5. Agent 3 — Hero Enhancer (Core Personalization)

### Purpose
Take the ad_data JSON (what the user was promised) and the hero_html_chunk (what
they currently see on landing) and produce an ENHANCED version of the hero HTML
that aligns messaging with the ad — without breaking the HTML structure.

### Critical Design Decision: ENHANCE, Don't Replace

The LLM must:
- KEEP: All existing HTML tags, CSS classes, IDs, attributes, image src URLs,
  data attributes, aria labels, structural layout
- MODIFY: Visible text content in headlines, sub-headlines, CTA button text,
  body copy paragraphs
- ADD: An offer/personalization banner if ad has a specific offer that isn't
  already reflected in the hero
- NEVER: Remove elements, change class names, invent new sections,
  add inline styles, change button href values, alter form elements

### Agent 3 System Prompt

```
You are an expert CRO (Conversion Rate Optimization) specialist and frontend developer.

CONTEXT:
You have two inputs:
1. AD CREATIVE DATA — what the user was promised in the ad they clicked:
{ad_data_json}

2. HERO HTML — the current hero section of the landing page they arrived on:
{hero_html_chunk}

YOUR TASK:
Enhance the hero HTML so it better aligns with the ad creative's messaging,
following CRO best practices. This creates message match between ad and landing page.

WHAT YOU CAN CHANGE:
- Text content inside <h1>, <h2>, <h3> tags (headline and subheadlines)
- Text content inside <p> tags within the hero (body copy, max 2-3 sentences)
- Text content inside <a> and <button> tags (CTA text only — NOT href/type/class)
- If the ad has a specific offer (discount, free trial, bonus) not present in the
  hero, you MAY add ONE offer banner element using this exact structure:
  <div class="ad-personalizer-banner" style="background:#f0f7ff;border:1px solid #cce0ff;
  padding:12px 24px;text-align:center;font-weight:600;border-radius:4px;
  margin-bottom:16px;">{offer_text}</div>
  Insert this as the FIRST child element inside the hero container.

STRICT RULES — READ CAREFULLY:
1. Return ONLY the enhanced HTML. No explanation. No markdown. No code fences.
2. Keep every HTML tag, attribute, class, id, src, href, data-* exactly as-is.
3. Do NOT invent products, prices, or features not in EITHER the ad data OR the 
   original hero HTML. Only use what is grounded in the inputs.
4. Do NOT remove any existing elements.
5. Do NOT add new sections, divs, or containers beyond the one offer banner above.
6. Do NOT change any CSS class names or inline styles.
7. Do NOT change href values on links or action values on forms.
8. Match the tone of the ad: {tone} / {tone_description}
9. The enhanced hero must feel like a natural evolution of the original — same brand
   voice, same layout, just copy that's aligned to the ad's promise.
10. If the hero is already well-aligned with the ad, make minimal changes or return
    it unchanged. Do not change for the sake of changing.
```

### Temperature and Model Config
```python
{
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 8000,
    "temperature": 0.15,  # Low — deterministic, consistent outputs
}
```

---

## 6. Step 3 — Surgical Stitching + Validation

### Primary Path: Python String Replace

```python
def stitch_html(main_html_with_placeholder, enhanced_hero_html):
    """
    Replace the placeholder comment with enhanced hero HTML.
    """
    return main_html_with_placeholder.replace(
        "<!-- __HERO_SECTION_PLACEHOLDER__ -->",
        enhanced_hero_html
    )
```

### HTML Validation

```python
from bs4 import BeautifulSoup

def validate_html(html_string):
    """
    Attempt to parse the final HTML. Check for critical structural elements.
    Returns (is_valid: bool, issues: list)
    """
    issues = []
    try:
        soup = BeautifulSoup(html_string, "html.parser")
        
        if not soup.find("html"):
            issues.append("Missing <html> tag")
        if not soup.find("head"):
            issues.append("Missing <head> tag")
        if not soup.find("body"):
            issues.append("Missing <body> tag")
        if not soup.find("base"):
            issues.append("Missing <base href> tag")
        
        # Check placeholder was actually replaced
        if "__HERO_SECTION_PLACEHOLDER__" in html_string:
            issues.append("Placeholder was not replaced")
        
        # Check enhanced hero made it in
        if "ad-personalizer-banner" in enhanced_hero_html:
            if "ad-personalizer-banner" not in html_string:
                issues.append("Enhanced hero content missing from final output")
        
        return len(issues) == 0, issues
    except Exception as e:
        return False, [str(e)]
```

### Fallback Path: Agent 4 — LLM Stitcher

If `validate_html()` returns `is_valid = False`, run Agent 4.

```
Agent 4 Input:
  1. main_html_with_placeholder (full page HTML with comment placeholder)
  2. enhanced_hero_html (the enhanced section to insert)

Agent 4 System Prompt:
"You are an expert HTML developer. You will receive two inputs:
1. A complete HTML page with a placeholder comment: <!-- __HERO_SECTION_PLACEHOLDER__ -->
2. An HTML snippet that should replace that placeholder.

Your task: Return the complete, valid final HTML with the placeholder replaced by the 
provided snippet. Ensure:
- The final HTML is well-formed and valid
- All original content outside the placeholder is preserved exactly
- The inserted snippet is placed exactly where the placeholder was
- No content is duplicated, removed, or modified
- Return ONLY the final HTML. No explanation."

Agent 4 Temperature: 0.0 (fully deterministic — this is a mechanical task)
Agent 4 Max Tokens: 32000 (needs to handle full page)
```

If Agent 4 also fails validation, serve the `main_html_with_placeholder` with
the hero chunk directly appended at top of `<body>` as a hard fallback.
Always serve something — never show an error page to the end reviewer.

---

## 7. Script Sanitization (Security)

Before rendering any HTML in an iframe, strip executable scripts:

```python
def sanitize_for_iframe(html_string):
    """
    Remove <script> tags and javascript: hrefs for safe iframe rendering.
    Preserves <link> stylesheets, <style> tags, and all layout.
    """
    soup = BeautifulSoup(html_string, "html.parser")
    
    # Remove all <script> tags
    for script in soup.find_all("script"):
        script.decompose()
    
    # Remove javascript: href attributes
    for tag in soup.find_all(href=True):
        if tag["href"].strip().lower().startswith("javascript:"):
            tag["href"] = "#"
    
    # Remove onclick and other inline JS handlers
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.startswith("on"):  # onclick, onload, onmouseover etc
                del tag.attrs[attr]
    
    return str(soup)
```

---

## 8. Change Summary Generation

After stitching, generate a human-readable change log to show in the UI.
This uses a simple diff — no extra LLM call needed.

```python
def generate_change_summary(original_hero_html, enhanced_hero_html):
    """
    Compares original and enhanced hero to produce bullet point summary.
    Uses BeautifulSoup text extraction — no LLM needed.
    """
    orig_soup = BeautifulSoup(original_hero_html, "html.parser")
    enhanced_soup = BeautifulSoup(enhanced_hero_html, "html.parser")
    changes = []
    
    # Compare h1
    orig_h1 = orig_soup.find("h1")
    new_h1 = enhanced_soup.find("h1")
    if orig_h1 and new_h1 and orig_h1.get_text() != new_h1.get_text():
        changes.append({
            "element": "Main Headline",
            "original": orig_h1.get_text(strip=True)[:80],
            "updated": new_h1.get_text(strip=True)[:80]
        })
    
    # Compare h2/h3
    for tag in ["h2", "h3"]:
        orig_tag = orig_soup.find(tag)
        new_tag = enhanced_soup.find(tag)
        if orig_tag and new_tag and orig_tag.get_text() != new_tag.get_text():
            changes.append({
                "element": "Sub-headline",
                "original": orig_tag.get_text(strip=True)[:80],
                "updated": new_tag.get_text(strip=True)[:80]
            })
    
    # Check for added banner
    if enhanced_soup.find(class_="ad-personalizer-banner"):
        banner_text = enhanced_soup.find(class_="ad-personalizer-banner").get_text(strip=True)
        changes.append({
            "element": "Offer Banner Added",
            "original": None,
            "updated": banner_text[:100]
        })
    
    # Compare CTA buttons
    orig_ctас = orig_soup.find_all(["button", "a"])
    new_ctas = enhanced_soup.find_all(["button", "a"])
    for orig_cta, new_cta in zip(orig_ctас, new_ctas):
        if orig_cta.get_text() != new_cta.get_text():
            changes.append({
                "element": "CTA Button",
                "original": orig_cta.get_text(strip=True)[:50],
                "updated": new_cta.get_text(strip=True)[:50]
            })
    
    return changes
```

---

## 9. API Endpoint Specification

### POST /api/personalize

**Request:**
```json
{
    "adType": "image",
    "adImageBase64": "data:image/jpeg;base64,...",
    "adUrl": null,
    "lpUrl": "https://brand.com/summer-sale"
}
```

**Response:**
```json
{
    "status": "success",
    "personalizedHtml": "<!DOCTYPE html>...",
    "originalHeroHtml": "<section class='hero'>...</section>",
    "enhancedHeroHtml": "<section class='hero'>...</section>",
    "adData": { ... },
    "changeSummary": [
        {
            "element": "Main Headline",
            "original": "Shop Our Collection",
            "updated": "Get 50% Off Summer Shoes"
        },
        {
            "element": "Offer Banner Added",
            "original": null,
            "updated": "Limited Time: 50% Off All Summer Styles"
        }
    ],
    "heroDetectionMethod": "class-based: hero-section",
    "validationPassed": true,
    "fallbackUsed": false,
    "processingTimeMs": 4200
}
```

**Error Response:**
```json
{
    "status": "error",
    "errorType": "lp_blocked",
    "message": "This page blocks automated access. Please paste the page HTML manually.",
    "userAction": "manual_paste"
}
```

---

## 10. Frontend Specification

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  AdPersonalizer                                             │
│  Align your landing page to every ad, instantly.           │
├──────────────────────────┬──────────────────────────────────┤
│   AD CREATIVE            │   LANDING PAGE                   │
│                          │                                  │
│  ┌────────────────────┐  │  ┌──────────────────────────┐   │
│  │  Drop image here   │  │  │  https://brand.com/...   │   │
│  │  or paste URL      │  │  │                          │   │
│  └────────────────────┘  │  └──────────────────────────┘   │
│                          │                                  │
│  [Preview of ad image]   │                                  │
└──────────────────────────┴──────────────────────────────────┘

              [  Personalize This Page  →  ]

════════════════ PROCESSING STATE ════════════════
  ● Analyzing ad creative...          (Agent 1 running)
  ● Extracting hero section...        (Agent 2 running)
  ⟳ Personalizing with ad context...  (Agent 3 running)
  ⟳ Validating output...              (Stitch + validate)

════════════════ OUTPUT STATE ════════════════

  CHANGE SUMMARY                          [Collapse ▲]
  ├── ✓ Headline: "Shop All" → "Get 50% Off Summer Shoes"
  ├── ✓ Sub-headline updated to match seasonal offer
  ├── ✓ CTA: "Explore" → "Shop Now — Limited Time"
  └── ✓ Offer banner added: "50% Off All Summer Styles"

  ┌─────────────────────────┬──────────────────────────────┐
  │   ORIGINAL PAGE         │   PERSONALIZED PAGE          │
  │   [iframe: lp_url]      │   [iframe: personalizedHtml] │
  │                         │                              │
  └─────────────────────────┴──────────────────────────────┘

  [Copy HTML]  [Download .html]  [Try Different Ad]
```

### Processing State — Show Each Step in Real-Time

Use Server-Sent Events (SSE) or WebSocket to stream progress:
```
Step 1/4: Reading ad creative...
Step 2/4: Extracting hero section from landing page...
Step 3/4: Enhancing with ad messaging (CRO principles)...
Step 4/4: Validating and rendering...
```
This communicates intelligence — not just a spinner.

### iFrame Sandboxing
```html
<iframe
    srcdoc="{personalizedHtml}"
    sandbox="allow-same-origin allow-scripts"
    style="width:100%;height:600px;border:none;"
/>
```

---

## 11. Tech Stack

### Backend (Python FastAPI)
```
fastapi              — API server
uvicorn              — ASGI runtime
requests             — LP HTML fetching
beautifulsoup4       — HTML parsing and hero extraction
anthropic            — Claude API (Vision + Text)
python-multipart     — Image upload handling
python-dotenv        — API key management
```

### Frontend
```
Next.js / React      — UI framework
Tailwind CSS         — Styling
react-dropzone       — Ad image drag-and-drop
```

### Hosting
```
Backend:   Railway or Render (free tier, Python FastAPI)
Frontend:  Vercel (free, Next.js)
```

### Environment Variables
```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 12. File Structure

```
adpersonalizer/
├── backend/
│   ├── main.py                    # FastAPI app + /api/personalize endpoint
│   ├── agents/
│   │   ├── ad_analyzer.py         # Agent 1: VLM ad analysis → ad_data JSON
│   │   ├── lp_processor.py        # Agent 2: HTML fetch + BeautifulSoup hero extraction
│   │   ├── hero_enhancer.py       # Agent 3: LLM hero personalization
│   │   └── fallback_stitcher.py   # Agent 4: LLM fallback for broken stitching
│   ├── utils/
│   │   ├── html_validator.py      # validate_html() + sanitize_for_iframe()
│   │   ├── change_summary.py      # generate_change_summary() diff logic
│   │   └── base_href.py           # inject_base_href() utility
│   ├── prompts/
│   │   ├── ad_analyzer_prompt.txt
│   │   └── hero_enhancer_prompt.txt
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   └── page.tsx               # Main UI: inputs + split preview
│   ├── components/
│   │   ├── AdInput.tsx            # Image upload + URL input with preview
│   │   ├── LPInput.tsx            # LP URL input with validation
│   │   ├── ProcessingSteps.tsx    # Real-time step indicator
│   │   ├── SplitPreview.tsx       # Side-by-side iframe comparison
│   │   └── ChangeSummary.tsx      # Bullet list of what changed
│   └── package.json
│
└── README.md
```

---

## 13. Assumptions Made (for Explanation Doc)

Per assignment instructions ("feel free to make assumptions, just mention them"):

1. Hero section = top 20-30% of the page = the first identifiable container
   holding the main headline, subheadline, and primary CTA. This is the only
   section changed. Everything below (pricing, features, FAQs) is untouched.

2. Ad creative is a single image or single URL per run (not a carousel or video).

3. Image assets on the landing page are NOT replaced — only text copy is enhanced.

4. The system personalizes message match and offer visibility only. It does not
   run A/B test variant generation or deploy changes directly to the live site.

5. For JavaScript-heavy SPAs that render blank via server-side fetch: the MVP
   surfaces an error and asks the user to paste HTML manually. Playwright/headless
   rendering is a Day 2 feature.

6. The output HTML is for demo/preview purposes. Production deployment to live
   Webflow/Framer/WordPress sites is a roadmap feature.

---

## 14. Edge Case Matrix (Complete)

| Scenario | Detection | Primary Response | Fallback |
|---|---|---|---|
| Image upload — valid | Content-Type check | VLM analysis | — |
| Image URL — dead link | requests.get 404 | "Image URL broken. Upload directly." | — |
| LP URL — 403/blocked | Status != 200 | Manual paste prompt | — |
| LP URL — timeout | >15s | Retry once, then manual paste | — |
| LP URL — JS SPA (blank) | <500 chars body text | Manual paste prompt | — |
| No hero found (all 8 fail) | hero_tag = None | First 40% of body children | Full body |
| Hero too large (>15KB) | char count | Narrow to h1.parent.parent | h1 element only |
| LLM returns markdown fences | response parsing | Strip ```html``` fences | Regex clean |
| LLM hallucinates new products | Post-check vs ad_data | Regenerate with stricter prompt | Return original |
| Stitching breaks HTML | validate_html() | Agent 4 LLM stitcher | Append to body top |
| Agent 4 also fails | validate_html() again | Original LP + change summary of what was attempted | — |
| Ad has no clear offer | offer_present: false | Skip banner injection | — |
| Non-English LP | langdetect library | Personalize in detected language | English fallback |
| Hero already well-aligned | Similarity score check | Minimal/no changes. Show: "Good alignment already." | — |

---

## 15. Explanation Doc Outline (Google Doc)

**Section 1: Problem**
The ad-to-page disconnect. Why message match matters for conversion. What this tool solves.

**Section 2: Architecture**
The 4-agent pipeline with diagram. Emphasize the surgical extraction approach and why it's better than full-page rewriting.

**Section 3: Key Technical Decisions**
- Why BeautifulSoup extraction over sending full HTML to LLM
- Why ENHANCE not REPLACE (CRO principles + hallucination prevention)
- Why the placeholder-based stitching approach preserves UI integrity
- Why Agent 4 fallback exists (defense in depth)
- Why temperature=0.15 (consistency over creativity)

**Section 4: Edge Case Handling**
Use the Edge Case Matrix table above — directly copy it in.

**Section 5: What I'd Build Next**
- Segment-level personalization (different heroes per ad audience segment)
- Auto A/B variant generation (3 variants per ad, let brand pick)
- Webflow/Framer/WordPress direct deploy via API
- Conversion tracking: personalized vs original page performance
- Multi-ad support: sync 10 ads → 10 landing page variants in batch

---

*Architecture Document v2.0*
*Author: Shivam Rajput | Troopod AI PM Internship Assignment*
