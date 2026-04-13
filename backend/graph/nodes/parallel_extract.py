from langgraph.types import Send
from graph.state import GraphState

def parallel_extract_node(state: GraphState) -> list[Send]:
    """
    Fan-out node: dispatches ad analysis and hero extraction simultaneously.
    LangGraph's Send() API runs both in parallel, then merges their state updates.
    """
    return [
        Send("ad_analyzer", state),
        Send("hero_extractor", state)
    ]
