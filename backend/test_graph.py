import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env.local")

from graph.graph_builder import app_graph

async def main():
    initial_state = {
        "lp_url": "https://www.trendsta.in/",
        "ad_url": "https://example.com/ad.jpg",
        "vlm_model": "qwen/qwen-2.5-vl-72b-instruct",
        "llm_model": "qwen/qwen3-235b-a22b",
        "ad_image_base64": None,
        "ad_data": None,
        "hero_detection": None,
        "enhanced_hero_html": None,
        "validation_result": None,
        "retry_count": 0,
        "processing_steps": []
    }
    try:
        async for chunk in app_graph.astream(initial_state, stream_mode="updates"):
            for node_name, updates in chunk.items():
                print(f"[{node_name}] finished")
                if "error" in updates and updates["error"]:
                    print("Error:", updates["error"])
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
