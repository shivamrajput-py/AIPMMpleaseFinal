# AdPersonalizer — Product Architecture Document
### Troopod AI PM Assignment | Built by Shivam Rajput

---

## 1. Product Summary

**What it does:**
AdPersonalizer takes an ad creative (image upload or URL) + a landing page URL, and generates a fully personalized landing page where the copy, tone, CTA, and messaging are aligned with the ad — eliminating the ad-to-page disconnect that kills conversions.

**Core Value Prop:**
When a user clicks an ad promising "50% off summer shoes", they should land on a page that says exactly that — not a generic homepage. This tool makes that personalization instant and automatic.

---

## 2. User Flow (End-to-End)

```
[User] 
  → Inputs: Ad Creative (image upload OR ad URL) + Landing Page URL
  → Clicks: "Personalize"
  → Sees: Split view — Original LP (left) | Personalized LP (right)
  → Can: Copy HTML | Download | See change summary
```

---

## 3. System Architecture

### 3.1 Three-Agent Pipeline

```
INPUT
  ├── Ad Creative (Image/URL)  →  [Agent 1: Ad Analyzer]
  └── Landing Page URL         →  [Agent 2: LP Extractor]
                                         ↓
                               [Agent 3: Personalizer]
                                         ↓
                               OUTPUT: Personalized HTML Page
```

---

### 3.2 Agent 1 — Ad Analyzer

**Purpose:** Extract structured signal from the ad creative.

**Input Handling (Conditional Branch):**

| Input Type | Method |
|---|---|
| Image upload (JPG/PNG/GIF) | Send directly to Claude Vision (claude-sonnet-4-20250514) as base64 |
| Ad URL (image link) | Fetch image → base64 → Claude Vision |
| HTML ad URL (banner page) | Jina Reader scrape → text → Claude text model |
| Assumption fallback | If image fails to load, treat as HTML page and scrape |

**Output Schema (Structured JSON):**
```json
{
  "headline": "50% Off This Summer — Shop Now",
  "sub_headline": "Premium footwear for the season",
  "offer": "50% discount",
  "cta_text": "Shop Now",
  "cta_urgency": "high",
  "tone": "energetic",
  "target_audience": "young adults, fashion-conscious",
  "key_promise": "savings on premium shoes",
  "visual_theme": {
    "primary_color": "#FF6B35",
    "secondary_color": "#FFFFFF",
    "style": "bold, bright, summery"
  },
  "product_focus": "footwear",
  "pain_point_addressed": "expensive seasonal fashion"
}
```

**Prompt Instructions for Agent 1:**
```
You are an expert ad analyst. Analyze this ad creative and extract ONLY what is 
explicitly visible or strongly implied. Do NOT invent products, prices, or claims 
not present in the ad. Return ONLY valid JSON matching the schema above. 
If a field is unclear, set it to null. Never hallucinate.
```

---

### 3.3 Agent 2 — LP Extractor

**Purpose:** Extract structured content from the existing landing page.

**Method:**
```
URL → Jina Reader (r.jina.ai/{URL}) → Clean Markdown Text
```

Why Jina Reader: handles JS-rendered pages, removes nav/footer noise, handles paywalls gracefully, returns clean markdown — uses far fewer tokens than raw HTML.

**What to Extract (Structured):**
```json
{
  "page_title": "...",
  "hero_headline": "...",
  "hero_subheadline": "...",
  "primary_cta": "...",
  "secondary_cta": "...",
  "sections": [
    { "type": "hero", "content": "..." },
    { "type": "features", "content": "..." },
    { "type": "social_proof", "content": "..." },
    { "type": "pricing", "content": "..." },
    { "type": "faq", "content": "..." }
  ],
  "brand_name": "...",
  "brand_voice": "professional | casual | playful | luxury",
  "color_palette": "...",
  "existing_offers": "...",
  "trust_signals": ["reviews", "logos", "guarantees"]
}
```

**Edge Case Handling:**

| Problem | Solution |
|---|---|
| Page is very long (100KB+) | Extract only: title, hero section, first CTA, key feature bullets. Cap at 8,000 tokens. |
| JS-heavy SPA (blank on scrape) | Fallback: Playwright headless browser screenshot → VLM to read structure |
| Scrape returns 403/blocked | Show user error: "This page blocks automated access. Please paste the page text manually." |
| Non-English page | Detect language, personalize in same language |
| Page has no clear sections | LLM to identify sections from raw markdown using structural heuristics |

---

### 3.4 Agent 3 — Personalizer (Core Intelligence)

**Purpose:** Combine ad signals + LP content → generate personalized LP HTML.

**Input to this agent:**
1. Ad Analyzer JSON output
2. LP Extractor JSON output  
3. Original LP HTML (preserved for structure/styles)
4. Output schema definition

**Strategy:**
Do NOT rewrite the entire LP from scratch. Instead:
- Keep: brand identity, visual structure, color palette, trust signals, pricing
- Change: headline, sub-headline, hero CTA text, hero body copy, offer callout
- Add: ad-message banner or hero badge if relevant offer exists
- Preserve: all original CSS classes, layout, images

**Prompt Template:**
```
You are an expert conversion copywriter and web developer.

CONTEXT:
- Ad Creative Data: {ad_json}
- Landing Page Data: {lp_json}
- Original LP HTML: {original_html}

TASK:
Rewrite ONLY the following elements of the landing page HTML to align with the ad:
1. The main <h1> headline in the hero section
2. The hero sub-headline or description paragraph
3. The primary CTA button text
4. Any promotional banner or offer badge (add one if the ad has an offer)
5. The hero section body copy (2-3 sentences max)

STRICT RULES:
- Do NOT change any CSS, colors, fonts, or layout
- Do NOT invent products, prices, or features not present in either the ad or the LP
- Do NOT remove trust signals, reviews, or pricing sections
- Keep the brand name exactly as-is
- Match the tone of the ad: {tone}
- The output must be complete, valid HTML
- Return ONLY the modified HTML — no explanation, no markdown fences
```

**Temperature:** 0.2 (low — for consistency)

---

## 4. Output Rendering

**What user sees:**

```
┌─────────────────────────────────────────────────┐
│  ORIGINAL LANDING PAGE        PERSONALIZED PAGE  │
│  [iframe: original URL]       [iframe: new HTML]  │
│                                                   │
│  Change Summary:                                  │
│  ✓ Headline updated to match ad offer             │
│  ✓ CTA updated: "Shop Now" → "Get 50% Off"       │
│  ✓ Hero copy aligned to summer footwear           │
│                                                   │
│  [Copy HTML]  [Download .html]  [Regenerate]     │
└─────────────────────────────────────────────────┘
```

**HTML Rendering Method:**
- Inject generated HTML into a sandboxed `<iframe srcdoc="...">` 
- Sanitize script tags before rendering (security)
- Show raw HTML in a collapsible code block below

---

## 5. Edge Case Handling (Complete)

### 5.1 Hallucination Prevention
- System prompt explicitly forbids inventing any claims
- All content changes must be traceable to either ad_json or lp_json
- Post-generation validation: LLM re-reads its own output and flags any content not sourced from inputs
- If validation fails → regenerate once → if still fails → return original LP with just headline changed

### 5.2 Broken UI / Invalid HTML Output
- Run generated HTML through an HTML parser (DOMParser in browser / BeautifulSoup in Python)
- Check: Does it have `<html>`, `<head>`, `<body>` tags? Are all tags closed? 
- If invalid: Extract just the changed text elements as JSON → inject into original HTML template using string replacement (surgical fallback)
- Always have a "Minimal Mode" fallback: just change headline + CTA text, guaranteed to work

### 5.3 Inconsistent Outputs (Same input → different output)
- `temperature=0.2` on Personalizer agent
- Cache the Ad Analyzer output per ad image hash (don't re-analyze same ad)
- Deterministic prompt (no "be creative" instructions)
- Lock output schema — Personalizer must return structured JSON first, then render to HTML

### 5.4 Random/Unpredictable Changes
- The Personalizer receives a whitelist of exactly which HTML elements it can modify (by CSS selector or section label)
- Anything outside that whitelist → untouched
- Change diff shown to user so they can see exactly what was modified

### 5.5 LP Scraping Failures
| Failure Type | Handling |
|---|---|
| Timeout (>10s) | Show error + allow manual HTML paste |
| Blocked (403/CAPTCHA) | Prompt user to paste HTML manually |
| Empty content | Ask user to confirm if URL is publicly accessible |
| Very long page | Intelligent truncation to hero + first 3 sections |

### 5.6 Ad Input Failures
| Failure Type | Handling |
|---|---|
| Image too small (<100px) | Warn: "Low quality ad, results may vary" |
| Non-ad image detected | Warn: "This doesn't look like an ad creative" |
| Image URL 404 | Ask user to upload image directly |
| No clear offer in ad | Proceed with tone/messaging match only |

---

## 6. Tech Stack

### Frontend
- **Framework:** Next.js (React) or plain HTML/CSS/JS
- **Styling:** Tailwind CSS
- **Ad upload:** React Dropzone (drag & drop)
- **LP preview:** Sandboxed iframe with `srcdoc`
- **Hosting:** Vercel (free, instant deploy)

### Backend / AI Pipeline
- **API Runtime:** Python FastAPI OR Next.js API routes
- **LP Scraping:** Jina Reader API (`r.jina.ai/{url}`) — free, no setup
- **Ad Analysis:** Anthropic Claude claude-sonnet-4-20250514 with vision
- **LP Personalization:** Anthropic Claude claude-sonnet-4-20250514 text
- **HTML Validation:** BeautifulSoup (Python) or DOMParser (JS)
- **Hosting:** Railway / Render (free tier for FastAPI backend)

### No-Code / Low-Code Alternative Stack
If building with a no-code tool (Cursor / Lovable / Bolt):
- Use Lovable for full-stack app generation
- Use Make.com (Integromat) or n8n for the AI pipeline orchestration
- Jina Reader as HTTP GET node
- Anthropic API as HTTP POST node
- Store outputs in Supabase or Airtable

---

## 7. File & Component Structure

```
adpersonalizer/
├── app/
│   ├── page.tsx                  # Main UI: inputs + output
│   ├── api/
│   │   ├── analyze-ad/route.ts   # Agent 1: Ad Analyzer
│   │   ├── extract-lp/route.ts   # Agent 2: LP Extractor  
│   │   └── personalize/route.ts  # Agent 3: Personalizer
├── components/
│   ├── AdInput.tsx               # Upload or URL input
│   ├── LPInput.tsx               # LP URL input
│   ├── SplitPreview.tsx          # Side-by-side iframe comparison
│   ├── ChangeSummary.tsx         # Bullet list of what changed
│   └── LoadingState.tsx          # Step-by-step progress indicator
├── lib/
│   ├── jinaReader.ts             # LP scraping utility
│   ├── claudeVision.ts           # Ad image analysis
│   ├── htmlValidator.ts          # Output validation
│   └── prompts.ts                # All system prompts
└── types/
    ├── AdSchema.ts               # Ad analyzer output type
    └── LPSchema.ts               # LP extractor output type
```

---

## 8. UI Specification

### Main Page Layout
```
HEADER: "AdPersonalizer by Troopod" | Minimal nav

STEP 1 — INPUT (Card)
  ┌──────────────────┬──────────────────┐
  │   Ad Creative    │  Landing Page    │
  │  [Drop image]    │  [Enter URL]     │
  │  [or paste URL]  │                  │
  └──────────────────┴──────────────────┘
  [Personalize →] button (disabled until both filled)

STEP 2 — PROCESSING (Animated steps)
  ✓ Analyzing ad creative...
  ✓ Extracting landing page content...
  ⟳ Generating personalized page...

STEP 3 — OUTPUT (Split View)
  Original | Personalized
  [iframe] | [iframe]
  
  Change Summary panel (collapsible):
  • Headline: "Shop All Products" → "Get 50% Off Summer Shoes"
  • CTA: "Explore" → "Shop Now — Limited Time"
  • Hero copy: Updated to match ad offer and tone
  
  [Copy HTML] [Download] [Try Again]
```

### Loading State Details
Show each pipeline step in real-time:
- "Reading your ad..." (Agent 1 running)
- "Understanding your landing page..." (Agent 2 running)  
- "Personalizing the page..." (Agent 3 running)
- "Validating output..." (Validation running)

This shows the system is intelligent, not just a spinner.

---

## 9. Assumptions Made

Per the assignment instruction ("feel free to make assumptions"):

1. **Input scope:** Ad creative can be an image (JPG/PNG/GIF/WEBP) OR a URL pointing to an image or ad page. HTML banner ads are treated as URLs to scrape.

2. **Output scope:** The personalized page is a modified version of the original LP — not a brand new page built from scratch. Brand identity, design system, and structure are preserved.

3. **Personalization depth:** Only hero section elements are modified (headline, sub-headline, CTA, body copy). Deeper sections (pricing, features, FAQs) are not touched to avoid hallucination risk.

4. **Image assets:** We do not replace images on the LP. Only text/copy is personalized.

5. **Multi-language:** System detects LP language and personalizes in the same language.

6. **Ad creative = single creative unit:** One ad image per personalization run (not a carousel).

---

## 10. Evaluation / Success Metrics

(Include this in your explanation doc to show PM thinking)

| Metric | How to Measure |
|---|---|
| Message Match Score | LLM judge: Does output LP headline align with ad headline? (1-5 score) |
| Brand Preservation | Check: brand name, colors, structure unchanged |
| HTML Validity | Parse success rate |
| Personalization Accuracy | Human review: % of outputs that correctly reflect the ad |
| Consistency | Same input → same output across 5 runs |

---

## 11. Build Order (3-Day Plan)

### Day 1 — Core Pipeline (Python script, no UI)
- [ ] Jina Reader integration — scrape any LP URL → clean text
- [ ] Claude Vision — analyze ad image → structured JSON
- [ ] Claude text — personalize LP copy → modified HTML
- [ ] Test end-to-end with 3 real examples (different brands, different ad types)
- [ ] Identify failure cases, fix prompts

### Day 2 — UI + Hosting
- [ ] Build Streamlit or Next.js frontend (use Lovable/Bolt to generate base)
- [ ] Wire up API endpoints
- [ ] Add split-view iframe preview
- [ ] Add change summary component
- [ ] Add loading states
- [ ] Deploy on Vercel + Railway/Render

### Day 3 — Polish + Explanation Doc
- [ ] Test 5+ real ad + LP combos
- [ ] Fix edge cases found in testing
- [ ] Write Google Doc explanation (system flow, agent design, edge case handling)
- [ ] Record a 90-second Loom demo (optional but strong signal)
- [ ] Send to nj@troopod.io

---

## 12. Explanation Doc Outline (Google Doc)

**Section 1: Problem Statement**
The ad-to-landing-page disconnect. Why it matters for brands. What this tool solves.

**Section 2: System Architecture**
The three-agent pipeline with a diagram. Input → Agent 1 → Agent 2 → Agent 3 → Output.

**Section 3: Key Design Decisions**
- Why Jina Reader over raw scraping
- Why surgical edits over full page rewrite
- Why structured JSON intermediate step reduces hallucinations
- Why temperature=0.2

**Section 4: Edge Case Handling**
Table format: Problem | Detection | Solution | Fallback

**Section 5: What I'd Build Next (if given 2 more weeks)**
- A/B testing: generate 3 variants, let brands pick
- Multivariate personalization by ad segment
- Auto-deploy to Webflow/Framer via API
- Feedback loop: track conversion rate of personalized vs original

---
*Document prepared for Troopod AI PM Internship Assignment*
*Author: Shivam Rajput*
