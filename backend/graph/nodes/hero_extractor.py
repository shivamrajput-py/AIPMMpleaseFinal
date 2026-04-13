from lxml import html as lxml_html
from lxml import etree
from graph.state import GraphState, HeroDetectionResult

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

    hero_el = _guard_size(hero_el)
    hero_html = lxml_html.tostring(hero_el, encoding="unicode", with_tail=False)
    
    placeholder_node = etree.Comment(PLACEHOLDER)
    parent = hero_el.getparent()
    if parent is None:
        return {"extraction_error": "Hero element has no parent."}
    parent.replace(hero_el, placeholder_node)

    main_html = lxml_html.tostring(tree, encoding="unicode", doctype="<!DOCTYPE html>", pretty_print=False)
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
    results = tree.xpath('('
        '//*[self::section or self::div or self::header or self::article]'
        '[.//h1]'
        '[.//button or .//a[contains(@class,"btn")] or '
        './/a[contains(@class,"cta")] or .//a[contains(@class,"button")] or '
        './/input[@type="submit"]]'
    ')[1]')
    if results: return results[0], "structural: h1 + CTA element", "high"

    results = tree.xpath('(//header[.//h1])[1]')
    if results: return results[0], "semantic: <header> with h1", "high"
    results = tree.xpath('(//main//section[.//h1])[1]')
    if results: return results[0], "structural: first section[h1] in main", "medium"

    UPPER, LOWER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'
    keywords = ["hero", "banner", "jumbotron", "masthead", "intro"]
    xpath_conditions = " or ".join([f'contains(translate(@id,"{UPPER}","{LOWER}"),"{kw}") or contains(translate(@class,"{UPPER}","{LOWER}"),"{kw}")' for kw in keywords])
    results = tree.xpath(f'(//*[{xpath_conditions}])[1]')
    if results: return results[0], "attribute: id/class hero keyword match", "medium"
    results = tree.xpath('(//*[self::section or self::div][.//h1])[1]')
    if results: return results[0], "positional: first section/div with h1", "low"
    results = tree.xpath('//h1')
    if results and results[0].getparent() is not None: return results[0].getparent(), "fallback: h1 parent", "low"
    return None, "not_found", "low"

def _guard_size(hero_el) -> object:
    html_str = lxml_html.tostring(hero_el, encoding="unicode", with_tail=False)
    if len(html_str) <= 12000: return hero_el
    for child in hero_el:
        child_html = lxml_html.tostring(child, encoding="unicode", with_tail=False)
        if lxml_html.fromstring(child_html).xpath('.//h1'): return child
    h1_list = hero_el.xpath('.//h1')
    if h1_list and h1_list[0].getparent() is not None: return h1_list[0].getparent()
    return hero_el

def _inject_base_href(html_str: str, base_url: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_str, "lxml")
    head = soup.find("head")
    if head:
        if head.find("base"): head.find("base")["href"] = base_url
        else: head.insert(0, soup.new_tag("base", href=base_url))
    return str(soup)

def route_after_extraction(state: GraphState) -> str:
    if state.get("extraction_error"): return "llm_hero_fallback"
    if state.get("ad_analysis_error"): return "error"
    detection = state.get("hero_detection")
    if detection and detection.confidence == "low": return "llm_hero_fallback"
    return "enhance"
