from graph.state import GraphState
from utils.html_validator import sanitize_for_iframe
from utils.change_summary import generate_change_summary

def finalize_node(state: GraphState) -> dict:
    """
    Sanitise for iframe rendering. Generate change summary. Build final response.
    """
    final_html = state["final_html"]
    sanitized = sanitize_for_iframe(final_html)
    changes = generate_change_summary(
        state.get("hero_html_chunk", ""),
        state.get("enhanced_hero_html", "")
    )

    return {
        "final_html":     sanitized,
        "change_summary": changes,
        "fallback_used":  state.get("fallback_used", False),
        "processing_steps": state.get("processing_steps", []) + ["finalize: done"]
    }
