import os
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from graph.state import GraphState, HeroDetectionResult

class HeroIdentifyResponse(BaseModel):
    hero_html: str = Field(description="The complete HTML of the hero section including the outermost container tag.")
    reasoning: str = Field(description="Why this element was chosen as the hero section.")

def llm_hero_fallback_node(state: GraphState) -> dict:
    """
    When XPath detection confidence is low or failed, use LLM to identify the hero.
    """
    raw_html = state.get("raw_html", "")
    html_sample = raw_html[:15000]

    system_prompt = """You are an expert HTML developer and CRO specialist.
You will receive partial HTML from a landing page.
Identify the hero section — the main above-the-fold area that contains the 
primary headline (h1), sub-headline, and call-to-action button/link.
Extract the COMPLETE outermost HTML element that wraps this section."""

    llm = ChatOpenAI(
        model=state.get("llm_model", "google/gemini-3.1-flash-lite-preview"),
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        temperature=0.0
    )

    try:
        structured_llm = llm.with_structured_output(HeroIdentifyResponse)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Landing page HTML (first portion):\n\n{html_sample}\n\nIdentify and extract the hero section.")
        ]
        result = structured_llm.invoke(messages)
        hero_html = result.hero_html

        placeholder = "<!-- __HERO_SECTION_PLACEHOLDER__ -->"
        main_html = state.get("raw_html", "").replace(hero_html, placeholder, 1)

        if placeholder not in main_html:
            main_html = state.get("main_html_with_placeholder", "") or raw_html

        from graph.nodes.hero_extractor import _inject_base_href
        main_html = _inject_base_href(main_html, state.get("base_url", ""))

        return {
            "hero_html_chunk":             hero_html,
            "main_html_with_placeholder":  main_html,
            "hero_detection": HeroDetectionResult(
                hero_html=hero_html,
                detection_method="llm_fallback: LLM identified hero from raw HTML",
                confidence="medium"
            ),
            "processing_steps": state.get("processing_steps", []) + ["llm_hero_fallback: hero identified by LLM"]
        }
    except Exception as e:
         return {
             "extraction_error": str(e),
             "processing_steps": state.get("processing_steps", []) + [f"llm_hero_fallback error: {str(e)}"]
         }
