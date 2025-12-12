# providers/gemini_client.py
"""
Nova Council — Gemini Provider

Provides Gemini API integration for:
1. gemini_quest_ideate() - Cheap quest ideation using Gemini Flash
2. gemini_live_research() - High-powered research using Gemini Pro

v1.0.0: Initial implementation
- Reads GEMINI_API_KEY from environment
- Silent fallback on failure (returns None)
- JSON-only output, no markdown, no persona
- Never stores output to long-term memory
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Gemini SDK import (optional)
try:
    import google.generativeai as genai
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False
    genai = None


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "true").lower() in ("true", "1", "yes")

# Model identifiers
GEMINI_FLASH_MODEL = "gemini-1.5-flash"
GEMINI_PRO_MODEL = "gemini-1.5-pro"

# Timeouts
GEMINI_TIMEOUT = 30  # seconds


# -----------------------------------------------------------------------------
# Prompts (Hard-coded as specified)
# -----------------------------------------------------------------------------

QUEST_IDEATE_SYSTEM_PROMPT = """You are a quest design assistant. Output VALID JSON ONLY.

Rules:
- No persona
- No markdown
- No examples in output
- One sentence per field maximum
- Maximum 5 steps
- Concise notes only, no prose

Required JSON schema:
{
  "quest_theme": "string",
  "goal": "string", 
  "difficulty": "low | medium | high",
  "estimated_duration": "string",
  "steps": [
    {"step_title": "string", "action": "string", "completion_criteria": "string"}
  ],
  "risks": ["string"],
  "notes": "string"
}

Output ONLY valid JSON. No other text."""


LIVE_RESEARCH_SYSTEM_PROMPT = """You are a research assistant. Output VALID JSON ONLY.

Rules:
- No persona
- No markdown  
- No filler text
- Concise but thorough
- If sources not available, return empty sources array

Required JSON schema:
{
  "meta": {
    "provider": "gemini",
    "model": "string",
    "mode": "live",
    "timestamp": "ISO8601"
  },
  "facts": ["string"],
  "options": [
    {
      "title": "string",
      "summary": "string",
      "tradeoffs": ["string"],
      "risks": ["string"]
    }
  ],
  "edge_cases": ["string"],
  "open_questions": ["string"],
  "sources": [
    {"title": "string", "url": "string", "note": "string"}
  ]
}

Output ONLY valid JSON. No other text."""


# -----------------------------------------------------------------------------
# Initialization
# -----------------------------------------------------------------------------

def _init_gemini() -> bool:
    """Initialize Gemini client if available and enabled."""
    if not _HAS_GEMINI:
        print("[GeminiClient] google-generativeai not installed", file=sys.stderr, flush=True)
        return False
    
    if not GEMINI_ENABLED:
        print("[GeminiClient] Gemini disabled via GEMINI_ENABLED=false", flush=True)
        return False
    
    if not GEMINI_API_KEY:
        print("[GeminiClient] GEMINI_API_KEY not set", file=sys.stderr, flush=True)
        return False
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Mask key for logging
        key_preview = f"{GEMINI_API_KEY[:8]}...{GEMINI_API_KEY[-4:]}" if len(GEMINI_API_KEY) > 12 else "***"
        print(f"[GeminiClient] Initialized with key: {key_preview}", flush=True)
        return True
    except Exception as e:
        print(f"[GeminiClient] Init failed: {e}", file=sys.stderr, flush=True)
        return False


_gemini_ready = _init_gemini() if _HAS_GEMINI else False


# -----------------------------------------------------------------------------
# JSON Extraction Helper
# -----------------------------------------------------------------------------

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON from text, handling common issues.
    Returns None if extraction fails.
    """
    if not text:
        return None
    
    # Remove markdown code fences if present
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[GeminiClient] JSON decode error: {e}", file=sys.stderr, flush=True)
        return None


# -----------------------------------------------------------------------------
# Quest Ideation (Flash - Cheap)
# -----------------------------------------------------------------------------

def gemini_quest_ideate(user_request: str) -> Optional[Dict[str, Any]]:
    """
    Generate quest ideation using Gemini Flash (cheap model).
    
    Args:
        user_request: The user's quest request/topic
        
    Returns:
        Dict with quest ideation data, or None on failure
        
    Schema:
        {
            "quest_theme": str,
            "goal": str,
            "difficulty": "low" | "medium" | "high",
            "estimated_duration": str,
            "steps": [{"step_title": str, "action": str, "completion_criteria": str}],
            "risks": [str],
            "notes": str
        }
    """
    if not _gemini_ready:
        print("[GeminiClient] gemini_quest_ideate: Not ready (disabled or no key)", flush=True)
        return None
    
    print(f"[GeminiClient] gemini_quest_ideate: model={GEMINI_FLASH_MODEL}", flush=True)
    
    try:
        model = genai.GenerativeModel(GEMINI_FLASH_MODEL)
        
        prompt = f"{QUEST_IDEATE_SYSTEM_PROMPT}\n\nUser request:\n{user_request}"
        
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=1024,
            ),
        )
        
        if not response or not response.text:
            print("[GeminiClient] gemini_quest_ideate: Empty response", file=sys.stderr, flush=True)
            return None
        
        result = _extract_json(response.text)
        
        if result:
            print(f"[GeminiClient] gemini_quest_ideate: SUCCESS", flush=True)
        else:
            print(f"[GeminiClient] gemini_quest_ideate: Invalid JSON response", file=sys.stderr, flush=True)
        
        return result
        
    except Exception as e:
        print(f"[GeminiClient] gemini_quest_ideate ERROR: {e}", file=sys.stderr, flush=True)
        return None


# -----------------------------------------------------------------------------
# Live Research (Pro - High-powered)
# -----------------------------------------------------------------------------

def gemini_live_research(user_request: str) -> Optional[Dict[str, Any]]:
    """
    Perform live research using Gemini Pro (high-powered model).
    Used for LIVE and LIVE-MAX modes.
    
    Args:
        user_request: The research query/topic
        
    Returns:
        Dict with research data, or None on failure
        
    Schema:
        {
            "meta": {"provider": "gemini", "model": str, "mode": "live", "timestamp": ISO},
            "facts": [str],
            "options": [{"title": str, "summary": str, "tradeoffs": [str], "risks": [str]}],
            "edge_cases": [str],
            "open_questions": [str],
            "sources": [{"title": str, "url": str, "note": str}]
        }
    """
    if not _gemini_ready:
        print("[GeminiClient] gemini_live_research: Not ready (disabled or no key)", flush=True)
        return None
    
    print(f"[GeminiClient] gemini_live_research: model={GEMINI_PRO_MODEL}", flush=True)
    
    try:
        model = genai.GenerativeModel(GEMINI_PRO_MODEL)
        
        prompt = f"{LIVE_RESEARCH_SYSTEM_PROMPT}\n\nResearch request:\n{user_request}"
        
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.4,
                max_output_tokens=4096,
            ),
        )
        
        if not response or not response.text:
            print("[GeminiClient] gemini_live_research: Empty response", file=sys.stderr, flush=True)
            return None
        
        result = _extract_json(response.text)
        
        if result:
            # Inject metadata if missing
            if "meta" not in result:
                result["meta"] = {}
            result["meta"]["provider"] = "gemini"
            result["meta"]["model"] = GEMINI_PRO_MODEL
            result["meta"]["mode"] = "live"
            result["meta"]["timestamp"] = datetime.now(timezone.utc).isoformat()
            
            print(f"[GeminiClient] gemini_live_research: SUCCESS", flush=True)
        else:
            print(f"[GeminiClient] gemini_live_research: Invalid JSON response", file=sys.stderr, flush=True)
        
        return result
        
    except Exception as e:
        print(f"[GeminiClient] gemini_live_research ERROR: {e}", file=sys.stderr, flush=True)
        return None


# -----------------------------------------------------------------------------
# Status Check
# -----------------------------------------------------------------------------

def is_gemini_available() -> bool:
    """Check if Gemini is available and ready."""
    return _gemini_ready


def get_gemini_status() -> Dict[str, Any]:
    """Get detailed Gemini status for debugging."""
    return {
        "available": _gemini_ready,
        "sdk_installed": _HAS_GEMINI,
        "enabled": GEMINI_ENABLED,
        "api_key_set": bool(GEMINI_API_KEY),
        "flash_model": GEMINI_FLASH_MODEL,
        "pro_model": GEMINI_PRO_MODEL,
    }


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    "gemini_quest_ideate",
    "gemini_live_research",
    "is_gemini_available",
    "get_gemini_status",
    "GEMINI_FLASH_MODEL",
    "GEMINI_PRO_MODEL",
]
