# Troopod Ad Personalizer – System Architecture & Workflow

## Overview
This document outlines the architecture, workflow, and technical decisions behind the Troopod Ad Personalizer system. The platform takes an Ad Creative (as context) and a target Landing Page URL, then dynamically generates a personalized iteration of the landing page. The objective is to enhance message match, maintain a high-quality user experience, and utilize strict CRO principles without breaking the original page's UI.

## System Architecture & Flow

The system acts as an autonomous pipeline connecting a frontend interface, an orchestration server (utilizing LangGraph/Python), and an LLM-powered Personalization Agent.

**1. Input Intake:**
The user provides the Ad Creative (context) and the target Landing Page URL via the frontend.

**2. Context Extraction & Analysis:**
The backend accesses the target Landing Page to formulate the necessary context for the LLM. We utilize a content-focused extraction layer (such as Jina Reader) to pull cleanly formatted textual data without overwhelming the context window with raw DOM elements.

**3. Agentic Personalization:**
The extracted context, along with the ad creative, is fed to the Personalization Agent. The agent applies CRO methodologies to map out what pieces of messaging need to change. 

**4. Surgical Enhancement (Stitching):**
The agent outputs specific mapping instructions (what to keep, what to change, and what the replacement should be). Our backend surgically applies these replacements to construct the final tailored view and sends it back to the client.

---

## Architectural Iterations & Challenges Dealt With

Building a robust personalization pipeline requires overcoming fundamental challenges associated with injecting AI-generated content into existing web architectures. We have iterated through the following approaches:

### Approach 1: Full HTML Parsing & DOM Stitching
* **Mechanism:** We scraped the full raw HTML of the landing page, parsed out the structure to identify the Hero Section, and passed that raw HTML block directly to the Personalization Agent. The agent would output an updated, personalized HTML block which we attempted to stitch back into the original DOM.
* **Problems Faced:**
  * **Broken UI & Malformed HTML:** Delegating HTML authorship to the LLM frequently resulted in missing CSS classes, dropped `data-*` attributes, and unclosed tags. The resulting DOM integration caused the layout and styling to break catastrophically.
  * **Inaccessible Content (Client-Side Rendering):** Simple HTML static scraping often encountered empty root `div`s because the majority of modern pages load their content asynchronously via JavaScript. 

### Approach 2: Content-Only Strategy via Jina Reader (Current Focus)
* **Mechanism:** To solve the structural breakage problem, we shifted to scraping strictly the textual content of the landing page utilizing Jina Reader. We feed this pure text alongside the ad creative to the Personalization Agent. The agent acts strictly as a copywriter, outputting structured mappings (`original_text_to_replace` -> `new_optimized_text`). Our backend then fetches the original HTML and executes a surgical string replacement based on these mappings.
* **Why it works better:** This guarantees that the LLM has zero impact on structural HTML elements, eliminating CSS breakage.

### Approach 3: Post-Render JavaScript Injection
* **Mechanism:** To circumvent the issues related to sites that are entirely hydrated client-side (SPAs built on React/Vue), this alternative approach involves writing a dynamically generated JavaScript snippet. Once the original page fully loads and renders in the user's browser, the injected script identifies the hero elements via DOM selectors and applies the text alterations on the fly.
* **Why it works better:** It gracefully targets the finalized state of the web application after JavaScript execution is completed.

---

## Handling Edge Cases & Reliability

Ensuring consistent, production-grade output involves rigorous guardrails around the agentic behaviors:

* **Handling Broken UI:** 
  By moving away from full HTML manipulation (Approach 1) toward pure content-replacement techniques (Approach 2 and 3), we completely isolated the layout from the LLM. The AI only modifies text nodes, ensuring that all flexbox, grid, and CSS modules continue to render flawlessly.
  
* **Mitigating Hallucinations:** 
  We ground the LLM tightly by forcing it to explicitly cite the exact text snippet from the Jina Reader extraction before it is allowed to generate a replacement. If the system cannot find the referenced string in the original HTML, the system gracefully degrades, skipping that replacement rather than injecting random text.
  
* **Managing Inconsistent Outputs:** 
  The personalizer does not output unstructured text. We enforce strict JSON schemas via Structured Outputs. The LLM must adhere to specific key-value mappings (e.g., `[{"target": "...", "replacement": "..."}]`). If the structure is invalid, the validation loop retries or falls back safely.
  
* **Handling Random Changes:** 
  The scope of the Personalization Agent is intensely restricted. Instead of giving it cart blanche over the entire document, it is targeted strictly at highly visible CRO components (H1 tags, subheadings, Call To Action buttons) within the Hero section, preventing arbitrary modifications to footers, navbars, or legal text.
