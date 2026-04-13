from graph.state import GraphState
from bs4 import BeautifulSoup

def stitch_node(state: GraphState) -> dict:
    """
    Replace placeholder with enhanced hero. Validate HTML structure.
    """
    PLACEHOLDER = " __HERO_SECTION_PLACEHOLDER__ "
    PLACEHOLDER_STR = f"<!--{PLACEHOLDER}-->"
    main_html = state.get("main_html_with_placeholder", "")
    enhanced = state.get("enhanced_hero_html", "")

    if PLACEHOLDER_STR not in main_html:
        # Fallback: if placeholder injection failed during extraction, apply changes directly to raw_html
        raw_html = state.get("raw_html", "")
        enhancement_result = state.get("enhancement_result")
        
        if enhancement_result and getattr(enhancement_result, "replacements", None) is not None:
            final_html = raw_html
            for r in enhancement_result.replacements:
                orig = r.original_text.strip()
                new_text = r.new_text.strip()
                if orig and orig in final_html:
                    final_html = final_html.replace(orig, new_text, 1)
                elif r.original_text in final_html:
                    final_html = final_html.replace(r.original_text, new_text, 1)
                    
            if getattr(enhancement_result, "offer_banner_text", None):
                soup = BeautifulSoup(final_html, "lxml")
                banner_html = f'<div class="ad-personalizer-banner" style="background:#111;color:#fff;border:1px solid #333;padding:12px 24px;text-align:center;font-weight:600;margin-bottom:16px;">{enhancement_result.offer_banner_text}</div>'
                banner_soup = BeautifulSoup(banner_html, "lxml").div
                if soup.body:
                    soup.body.insert(0, banner_soup)
                    final_html = str(soup)
                    
            from graph.nodes.hero_extractor import _inject_base_href
            final_html = _inject_base_href(final_html, state.get("base_url", ""))
        else:
            return {"error": "Placeholder not found in main HTML — cannot stitch."}
    else:
        final_html = main_html.replace(PLACEHOLDER_STR, enhanced, 1)

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
        "processing_steps": state.get("processing_steps", []) + [f"stitcher: html_valid={html_valid}"]
    }

def route_after_stitch(state: GraphState) -> str:
    return "finalize" if state.get("final_html") else "llm_stitch_recovery"
