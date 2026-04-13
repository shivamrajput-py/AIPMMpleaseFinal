import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from graph.state import GraphState, ValidationResult

def validate_node(state: GraphState) -> dict:
    """
    Critic agent: independently evaluates the enhanced hero HTML.
    Checks: message match quality, HTML integrity, no hallucinations,
    no attribute mutations, no missing elements.
    """
    ad_data = state["ad_data"]
    original_hero = state["hero_html_chunk"]
    enhanced_hero = state["enhanced_hero_html"]

    system_prompt = """You are a strict quality assurance engineer specialising in CRO.

Evaluate the enhanced hero HTML against these criteria:
1. MESSAGE MATCH (40 pts): Does the enhanced hero clearly reflect the ad's headline, offer, and CTA?
2. HTML INTEGRITY (30 pts): Are all original tags preserved? No elements removed? All attributes unchanged?
3. GROUNDEDNESS (20 pts): Is every claim traceable to the original hero HTML or ad data? No invented products, prices, or features?
4. TONE MATCH (10 pts): Does the copy match the ad's tone?"""

    llm = ChatOpenAI(
        model=state.get("llm_model", "google/gemini-3.1-flash-lite-preview"),
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        temperature=0.0
    )

    try:
        structured_llm = llm.with_structured_output(ValidationResult)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"AD DATA:\nHeadline: {ad_data.headline}\nOffer: {ad_data.offer}\n\nORIGINAL HERO:\n{original_hero}\n\nENHANCED HERO:\n{enhanced_hero}\n\nValidate and evaluate.")
        ]
        
        result = structured_llm.invoke(messages)

        return {
            "validation_result": result,
            "processing_steps": state.get("processing_steps", []) + [f"validator: score={result.score}, passed={result.passed}"]
        }
    except Exception as e:
         return {
             "error": f"Validation failed: {str(e)}"
         }

def route_after_validation(state: GraphState) -> str:
    result = state.get("validation_result")
    retry_count = state.get("retry_count", 0)

    if result and result.passed:
        return "stitch"

    if retry_count < 2:
        return "retry_enhance"
    return "emergency_stitch"
