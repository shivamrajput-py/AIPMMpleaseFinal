import os
import base64
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from graph.state import GraphState, AdData

def ad_analyzer_node(state: GraphState) -> dict:
    """
    Agent 1: Analyse ad creative → structured AdData via tool_use.
    Handles: image upload (base64), image URL, HTML ad URL.
    Uses OpenRouter via langchain ChatOpenAI with structured output.
    """
    system_prompt = """You are an expert digital advertising analyst specialising in CRO.
Analyse the provided ad creative. Call the tool to record your findings.
Extract ONLY what is explicitly visible or strongly implied in the ad.
Set fields to null if not present. Never invent products, prices, or claims."""

    content = []

    if state.get("ad_image_base64"):
        b64 = state["ad_image_base64"]
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": "Analyse this ad creative."}
        ]

    elif state.get("ad_url"):
        url = state["ad_url"]
        try:
            import requests as req
            resp = req.get(url, timeout=10)
            if resp.headers.get("Content-Type", "").startswith("image/"):
                b64 = base64.b64encode(resp.content).decode("utf-8")
                media_type = resp.headers["Content-Type"].split(";")[0]
                content = [
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
                    {"type": "text", "text": "Analyse this ad creative."}
                ]
            else:
                jina_resp = req.get(f"https://r.jina.ai/{url}", timeout=15)
                content = [{"type": "text", "text": f"Ad page content:\n\n{jina_resp.text[:8000]}\n\nAnalyse this ad."}]
        except Exception as e:
            return {"ad_analysis_error": f"Could not load ad URL: {str(e)}"}

    else:
        return {"ad_analysis_error": "No ad input provided."}

    llm = ChatOpenAI(
        model=state.get("vlm_model", "google/gemini-3.1-flash-lite-preview"),
        api_key=os.environ.get("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        temperature=0.1
    )

    try:
        structured_llm = llm.with_structured_output(AdData)
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=content)]
        ad_data = structured_llm.invoke(messages)

        return {
            "ad_data": ad_data,
            "processing_steps": state.get("processing_steps", []) + ["ad_analyzer: complete"]
        }

    except Exception as e:
        return {
            "ad_analysis_error": f"Ad analysis failed: {str(e)}",
            "processing_steps": state.get("processing_steps", []) + [f"ad_analyzer: error — {str(e)}"]
        }
