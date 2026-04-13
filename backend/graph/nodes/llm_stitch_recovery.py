import os
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from graph.state import GraphState

class StitchRecoveryResponse(BaseModel):
    final_html: str = Field(description="The complete, repaired HTML of the page.")

def llm_stitch_recovery_node(state: GraphState) -> dict:
    """
    Agent 4: Stitch failsafe. Uses LLM to cleanly place the hero HTML inside the raw page.
    """
    raw_html = state.get("raw_html", "")
    enhanced_hero = state.get("enhanced_hero_html", "")

    system_prompt = """You are an expert HTML developer.
    Your task is to cleanly replace the old hero section in the provided HTML 
    with the NEW ENHANCED HERO HTML.
    Return ONLY the perfectly stitched, valid HTML document."""

    llm = ChatOpenAI(
        model=state.get("llm_model", "google/gemini-3.1-flash-lite-preview"),
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        temperature=0.0
    )

    try:
        structured_llm = llm.with_structured_output(StitchRecoveryResponse)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"NEW ENHANCED HERO HTML:\n{enhanced_hero}\n\nORIGINAL PAGE HTML (please update the hero):\n{raw_html}")
        ]
        result = structured_llm.invoke(messages)

        return {
            "final_html": result.final_html,
            "fallback_used": True,
            "processing_steps": state.get("processing_steps", []) + ["llm_stitch_recovery: forced clean stitch via Agent 4"]
        }
    except Exception as e:
         return {
             "error": f"Stitch recovery failed: {str(e)}"
         }
