from graph.state import GraphState

def error_node(state: GraphState) -> dict:
    """Terminal error node"""
    error_msg = state.get("fetch_error") or state.get("extraction_error") or state.get("ad_analysis_error") or state.get("error") or "Unknown error"
    return {
        "error": error_msg,
        "processing_steps": state.get("processing_steps", []) + [f"failed: {error_msg}"]
    }
