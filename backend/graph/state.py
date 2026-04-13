from typing import TypedDict, Optional, Literal, List
from pydantic import BaseModel

# ── Pydantic models for structured LLM outputs ──────────────────────────────

class VisualStyle(BaseModel):
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    mood: Optional[str] = None

class AdData(BaseModel):
    headline: Optional[str] = None
    sub_headline: Optional[str] = None
    offer: Optional[str] = None
    offer_present: bool = False
    cta_text: Optional[str] = None
    cta_urgency: Literal["low", "medium", "high"] = "low"
    tone: Literal[
        "professional", "energetic", "luxury", "playful", "urgent",
        "trustworthy", "casual", "authoritative", "empathetic", "bold"
    ] = "professional"
    tone_description: Optional[str] = None
    target_audience: Optional[str] = None
    key_promise: Optional[str] = None
    pain_point: Optional[str] = None
    product_category: Optional[str] = None
    visual_style: Optional[VisualStyle] = None
    social_proof_in_ad: Optional[str] = None
    scarcity_signal: Optional[str] = None
    personalization_hooks: List[str] = []

class HeroDetectionResult(BaseModel):
    hero_html: str
    detection_method: str
    confidence: Literal["high", "medium", "low"]

class TextReplacement(BaseModel):
    original_text: str
    new_text: str

class EnhancedHeroResult(BaseModel):
    replacements: List[TextReplacement]
    offer_banner_text: Optional[str] = None
    changes_made: List[str]   # human-readable list of what was changed

class ValidationResult(BaseModel):
    passed: bool
    score: int                # 0-100
    issues: List[str]         # what failed
    critique: Optional[str] = None  # what the enhancer should fix on retry

class ChangeRecord(BaseModel):
    element: str
    original: Optional[str]
    updated: str

# ── Main graph state ─────────────────────────────────────────────────────────

class GraphState(TypedDict):
    # ── Inputs ──────────────────────────────────────────────────
    lp_url:             str
    ad_image_base64:    Optional[str]   # set if image upload
    ad_url:             Optional[str]   # set if URL input
    vlm_model:          str
    llm_model:          str

    # ── LP Fetch results ────────────────────────────────────────
    raw_html:           Optional[str]
    base_url:           Optional[str]
    fetch_method:       Optional[str]   # "requests" | "playwright"
    fetch_error:        Optional[str]   # set if fetch failed

    # ── Hero extraction results ─────────────────────────────────
    hero_html_chunk:           Optional[str]
    main_html_with_placeholder: Optional[str]
    hero_detection:            Optional[HeroDetectionResult]
    extraction_error:          Optional[str]

    # ── Ad analysis results ─────────────────────────────────────
    ad_data:            Optional[AdData]
    ad_analysis_error:  Optional[str]

    # ── Enhancement loop ────────────────────────────────────────
    enhanced_hero_html: Optional[str]
    enhancement_result: Optional[EnhancedHeroResult]
    validation_result:  Optional[ValidationResult]
    retry_count:        int             # starts at 0, max 2

    # ── Final output ────────────────────────────────────────────
    final_html:         Optional[str]
    change_summary:     List[ChangeRecord]
    fallback_used:      bool
    processing_steps:   List[str]      # SSE event log
    error:              Optional[str]  # terminal error message
