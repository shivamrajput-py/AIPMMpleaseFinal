import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env.local from the project root (one level up from backend/)
_project_root = Path(__file__).resolve().parent.parent
_env_local = _project_root / ".env.local"
_env_nextjs = _project_root / "troopod-lp-personalizer" / ".env.local"
_env_file = _project_root / ".env"

if _env_local.exists():
    load_dotenv(_env_local)
elif _env_nextjs.exists():
    load_dotenv(_env_nextjs)
elif _env_file.exists():
    load_dotenv(_env_file)

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse
import json
import base64
import traceback

from graph.graph_builder import app_graph
from graph.state import GraphState

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.get("/api/health")
async def health():
    """Quick health check endpoint."""
    has_key = bool(os.environ.get("OPENROUTER_API_KEY"))
    return {"status": "ok", "openrouter_key_set": has_key}

@app.post("/api/personalize")
async def personalize(
    lp_url:      str        = Form(...),
    ad_url:      str | None = Form(None),
    vlm_model:   str        = Form("google/gemini-3.1-flash-lite-preview"),
    llm_model:   str        = Form("google/gemini-3.1-flash-lite-preview"),
    ad_image:    UploadFile | None = File(None)
):
    """
    Main endpoint. Accepts ad creative + LP URL.
    Runs the LangGraph pipeline and returns the result as JSON.
    """
    # Verify API key is set
    if not os.environ.get("OPENROUTER_API_KEY"):
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "OPENROUTER_API_KEY is not set. Please add it to .env.local in the project root."}
        )

    initial_state: GraphState = {
        "lp_url":             lp_url,
        "ad_url":             ad_url,
        "vlm_model":          vlm_model,
        "llm_model":          llm_model,
        "ad_image_base64":    None,
        "raw_html":           None,
        "base_url":           None,
        "fetch_method":       None,
        "fetch_error":        None,
        "hero_html_chunk":    None,
        "main_html_with_placeholder": None,
        "hero_detection":     None,
        "extraction_error":   None,
        "ad_data":            None,
        "ad_analysis_error":  None,
        "enhanced_hero_html": None,
        "enhancement_result": None,
        "validation_result":  None,
        "retry_count":        0,
        "final_html":         None,
        "change_summary":     [],
        "fallback_used":      False,
        "processing_steps":   [],
        "error":              None
    }

    if ad_image:
        contents = await ad_image.read()
        b64 = base64.b64encode(contents).decode("utf-8")
        media_type = ad_image.content_type or "image/jpeg"
        initial_state["ad_image_base64"] = f"data:{media_type};base64,{b64}"

    try:
        async def event_stream():
            state = dict(initial_state)
            try:
                import asyncio
                
                # We want to yield heartbeats to prevent connection timeouts
                # during long-running nodes (like Playwright).
                async def get_stream():
                    async for chunk in app_graph.astream(initial_state, stream_mode="updates"):
                        yield chunk

                stream_iterator = get_stream()
                
                while True:
                    try:
                        # Wait for either a chunk or a heartbeat timeout
                        chunk = await asyncio.wait_for(stream_iterator.__anext__(), timeout=10.0)
                        for node_name, updates in chunk.items():
                            print(f"[DEBUG] Node finished: {node_name}")
                            state.update(updates)
                            
                            if node_name in STREAMABLE_NODES:
                                yield f"data: {json.dumps({'step': node_name, 'done': True})}\n\n"
                                
                            if "error" in updates and updates["error"]:
                                print(f"[ERROR] Node {node_name} reported error: {updates['error']}")
                                yield f"data: {json.dumps({'status': 'error', 'message': updates['error']})}\n\n"
                                return
                    except asyncio.TimeoutError:
                        # Send a keep-alive comment to the browser/proxy
                        yield ": keep-alive\n\n"
                    except StopAsyncIteration:
                        break

                # Send final success event
                result = {
                    "status":              "success",
                    "personalizedHtml":    state.get("final_html"),
                    "changeSummary":       [c.model_dump() for c in state.get("change_summary", [])] if state.get("change_summary") else [],
                    "heroDetectionMethod": state["hero_detection"].detection_method if state.get("hero_detection") else "unknown",
                    "heroConfidence":      state["hero_detection"].confidence if state.get("hero_detection") else "low",
                    "validationScore":     state["validation_result"].score if state.get("validation_result") else 0,
                    "fallbackUsed":        state.get("fallback_used", False),
                    "adData":              state.get("ad_data").model_dump() if state.get("ad_data") else None,
                    "processingSteps":     state.get("processing_steps", [])
                }
                yield f"data: {json.dumps(result)}\n\n"

            except Exception as e:
                traceback.print_exc()
                yield f"data: {json.dumps({'status': 'error', 'message': f'Pipeline error: {str(e)}'})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
        
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Pipeline initialization error: {str(e)}"}
        )

STREAMABLE_NODES = {
    "fetch_lp", "playwright", "ad_analyzer", "hero_extractor",
    "llm_hero_fallback", "hero_enhance", "validate", "stitch", "finalize"
}
