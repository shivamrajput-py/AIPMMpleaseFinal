from langgraph.graph import StateGraph, END
from graph.state import GraphState

from graph.nodes.fetch_lp import fetch_lp_node, route_after_fetch
from graph.nodes.playwright_node import playwright_node
from graph.nodes.ad_analyzer import ad_analyzer_node
from graph.nodes.hero_extractor import hero_extractor_node, route_after_extraction
from graph.nodes.llm_hero_fallback import llm_hero_fallback_node
from graph.nodes.hero_enhance import hero_enhance_node
from graph.nodes.validate import validate_node, route_after_validation
from graph.nodes.stitch import stitch_node, route_after_stitch
from graph.nodes.llm_stitch_recovery import llm_stitch_recovery_node
from graph.nodes.finalize import finalize_node
from graph.nodes.error_node import error_node

def build_graph() -> StateGraph:
    graph = StateGraph(GraphState)

    # ── Add all nodes ──────────────────────────────────────────────────
    graph.add_node("fetch_lp",              fetch_lp_node)
    graph.add_node("playwright",            playwright_node)
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

    # Step 1: Fetch LP HTML (requests first, Playwright fallback)
    graph.add_conditional_edges("fetch_lp", route_after_fetch, {
        "success":    "ad_analyzer",
        "playwright": "playwright",
        "error":      "error_node"
    })
    graph.add_edge("playwright", "ad_analyzer")

    # Step 2: Analyse ad creative → then extract hero
    graph.add_edge("ad_analyzer", "hero_extractor")

    # Step 3: Route based on hero extraction confidence
    graph.add_conditional_edges("hero_extractor", route_after_extraction, {
        "enhance":           "hero_enhance",
        "llm_hero_fallback": "llm_hero_fallback",
        "error":             "error_node"
    })

    # Step 3b: LLM fallback → then enhance
    graph.add_edge("llm_hero_fallback", "hero_enhance")

    # Step 4: Enhance → Validate → (retry loop or stitch)
    graph.add_edge("hero_enhance", "validate")

    graph.add_conditional_edges("validate", route_after_validation, {
        "stitch":           "stitch",
        "retry_enhance":    "hero_enhance",     # Self-correcting retry loop
        "emergency_stitch": "stitch"
    })

    # Step 5: Stitch → (finalize or LLM recovery)
    graph.add_conditional_edges("stitch", route_after_stitch, {
        "finalize":            "finalize",
        "llm_stitch_recovery": "llm_stitch_recovery"
    })
    graph.add_edge("llm_stitch_recovery", "finalize")

    # Terminal edges
    graph.add_edge("finalize",  END)
    graph.add_edge("error_node", END)

    # ── Compile ────────────────────────────────────────────────────────
    return graph.compile()

app_graph = build_graph()
