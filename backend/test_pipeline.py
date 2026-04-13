import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from graph.graph_builder import app_graph
from graph.state import AdData, ChangeRecord

async def main():
    dummy_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    
    initial_state = {
        "lp_url":             "https://troopod.io/",
        "ad_url":             None,
        "ad_image_base64":    f"data:image/png;base64,{dummy_b64}",
        "vlm_model":          "google/gemini-3.1-flash-lite-preview",
        "llm_model":          "google/gemini-3.1-flash-lite-preview",
        "processing_steps":   []
    }
    
    state = dict(initial_state)
    print("Starting astream...")
    try:
        async for chunk in app_graph.astream(initial_state, stream_mode="updates"):
            for node, updates in chunk.items():
                print(f"--- Node: {node} ---")
                state.update(updates)
                
                if "error" in updates and updates["error"]:
                    print("Hit error update:", updates["error"])
                    return

        print("Finished astream.")
        # Try constructing final dict
        result = {
            "status":              "success",
            "personalizedHtml":    state.get("final_html"),
            "changeSummary":       [c.model_dump() for c in state.get("change_summary", [])] if state.get("change_summary") else [],
            "heroDetectionMethod": state["hero_detection"].detection_method if state.get("hero_detection") else "unknown",
            "heroConfidence":      state["hero_detection"].confidence if state.get("hero_detection") else "low",
            "validationScore":     state["validation_result"].score if state.get("validation_result") else 0,
            "fallbackUsed":        state.get("fallback_used", False),
            "adData":              state.get("ad_data").model_dump() if state.get("ad_data", None) else None,
            "processingSteps":     state.get("processing_steps", [])
        }
        print("Success dict built successfully!")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
