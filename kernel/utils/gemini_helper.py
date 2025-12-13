# kernel/gemini_helper.py
"""
Two-Pass Quest Generation Pipeline

v4.0.0: Gemini Draft → GPT Polish/Verify

Flow:
1. Gemini generates draft (fast, cheap, may be imperfect)
2. GPT polishes/verifies into production-grade output
3. User ONLY sees final GPT result

If Gemini draft is unusable, GPT regenerates from scratch.
User never sees "fallback" or "polish" - just clean results.

SCOPED TO #quest-compose ONLY - does not affect other commands.
"""

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Gemini SDK import
try:
    import google.generativeai as genai
    _HAS_GEMINI_SDK = True
except ImportError:
    _HAS_GEMINI_SDK = False
    genai = None


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class TwoPassConfig:
    """Configuration for two-pass quest generation."""
    # Routing mode
    routing_mode: str = "gemini_then_gpt"  # or "gpt_only"
    
    # Gemini settings
    gemini_enabled: bool = True
    gemini_model: str = "gemini-2.5-pro"
    gemini_temperature: float = 0.4
    gemini_max_tokens_domains: int = 1200   # Increased from 700
    gemini_max_tokens_steps: int = 4000     # Increased from 2200
    
    # GPT Polish settings
    gpt_model_polish: str = "gpt-5.1"
    gpt_temperature_polish: float = 0.2
    gpt_max_tokens_domains: int = 700
    gpt_max_tokens_steps: int = 2200
    
    # Constraints
    min_domains: int = 3
    max_domains: int = 8
    min_steps: int = 8
    max_steps: int = 14
    
    # Content limits
    lesson_max_chars: int = 360
    practice_max_chars: int = 360
    deliverable_max_chars: int = 140


def load_config() -> TwoPassConfig:
    """Load config from environment."""
    return TwoPassConfig(
        routing_mode=os.getenv("QUEST_COMPOSE_ROUTING_MODE", "gemini_then_gpt"),
        gemini_enabled=os.getenv("GEMINI_ENABLED", "true").lower() in ("true", "1", "yes"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
        gemini_temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.4")),
        gemini_max_tokens_domains=int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS_DOMAINS", "1200")),
        gemini_max_tokens_steps=int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS_STEPS", "4000")),
        gpt_model_polish=os.getenv("OPENAI_MODEL_POLISH", "gpt-5.1"),
        gpt_temperature_polish=float(os.getenv("OPENAI_TEMPERATURE_POLISH", "0.2")),
        gpt_max_tokens_domains=int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS_DOMAINS", "700")),
        gpt_max_tokens_steps=int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS_STEPS", "2200")),
    )


CONFIG = load_config()

# Gemini state
_gemini_initialized = False


# =============================================================================
# GEMINI CLIENT
# =============================================================================

def _init_gemini() -> bool:
    """Initialize Gemini client."""
    global _gemini_initialized
    
    if _gemini_initialized:
        return True
    
    if not _HAS_GEMINI_SDK:
        print("[TwoPass] Gemini SDK not installed", flush=True)
        return False
    
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("[TwoPass] GEMINI_API_KEY not set", flush=True)
        return False
    
    try:
        genai.configure(api_key=api_key)
        _gemini_initialized = True
        print(f"[TwoPass] Gemini initialized (model={CONFIG.gemini_model})", flush=True)
        return True
    except Exception as e:
        print(f"[TwoPass] Gemini init failed: {e}", flush=True)
        return False


def _call_gemini(prompt: str, system: str, max_tokens: int) -> Optional[str]:
    """Call Gemini API for draft generation."""
    if not CONFIG.gemini_enabled:
        print("[TwoPass] Gemini disabled", flush=True)
        return None
    
    if not _init_gemini():
        return None
    
    # Use actual model name - NEVER use 'auto' as model name
    model_name = CONFIG.gemini_model
    if not model_name or model_name == "auto":
        model_name = "gemini-2.5-pro"
    
    print(f"[TwoPass] Using Gemini model: {model_name}, max_tokens={max_tokens}", flush=True)
    
    try:
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system,
        )
        
        # Add permissive safety settings for educational content
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_ONLY_HIGH"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
        ]
        
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=CONFIG.gemini_temperature,
                max_output_tokens=max_tokens,
            ),
            safety_settings=safety_settings,
        )
        
        # Check for blocked response
        if not response:
            print("[TwoPass] Gemini returned None", flush=True)
            return None
        
        # Log prompt feedback if blocked
        if hasattr(response, 'prompt_feedback'):
            feedback = response.prompt_feedback
            if hasattr(feedback, 'block_reason') and feedback.block_reason:
                print(f"[TwoPass] Gemini prompt blocked: {feedback.block_reason}", flush=True)
                return None
        
        # Try to get text from candidates
        text = None
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, 'finish_reason', None)
            print(f"[TwoPass] Gemini finish_reason={finish_reason}", flush=True)
            
            # Try to extract text from parts even on MAX_TOKENS
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                parts = candidate.content.parts
                if parts:
                    text_parts = []
                    for part in parts:
                        if hasattr(part, 'text') and part.text:
                            text_parts.append(part.text)
                    if text_parts:
                        text = "".join(text_parts)
                        print(f"[TwoPass] Extracted {len(text)} chars from parts", flush=True)
            
            # Log safety ratings if concerning
            if hasattr(candidate, 'safety_ratings'):
                for rating in candidate.safety_ratings:
                    prob = getattr(rating, 'probability', None)
                    if prob and prob not in ('NEGLIGIBLE', 'LOW', 0, 1):
                        cat = getattr(rating, 'category', 'unknown')
                        print(f"[TwoPass] Gemini safety flag: {cat}={prob}", flush=True)
            
            # 1=STOP (ok), 2=MAX_TOKENS (partial ok), 3=SAFETY, 4=RECITATION, 5=OTHER
            if finish_reason and finish_reason not in (1, 2):
                print(f"[TwoPass] Gemini blocked: finish_reason={finish_reason}", flush=True)
                return None
        else:
            print("[TwoPass] Gemini no candidates", flush=True)
        
        # If we got text from parts, use it
        if text:
            print(f"[TwoPass] Gemini draft ({model_name}): {len(text)} chars", flush=True)
            return text.strip()
        
        # Fallback to response.text
        try:
            text = response.text
            if text:
                print(f"[TwoPass] Gemini draft ({model_name}): {len(text)} chars", flush=True)
                return text.strip()
            else:
                print("[TwoPass] Gemini empty text", flush=True)
        except ValueError as e:
            print(f"[TwoPass] Gemini no valid parts: {e}", flush=True)
            return None
        
        return None
        
    except Exception as e:
        print(f"[TwoPass] Gemini error: {e}", flush=True)
        return None


# =============================================================================
# GPT CLIENT (via llm_client)
# =============================================================================

def _call_gpt(prompt: str, system: str, max_tokens: int, llm_client: Any) -> Optional[str]:
    """Call GPT-5.1 for polish/verify pass."""
    if not llm_client:
        print("[TwoPass] No llm_client for GPT", flush=True)
        return None
    
    try:
        # Don't pass max_tokens - let llm_client handle it
        # gpt-5.1 requires max_completion_tokens, not max_tokens
        result = llm_client.complete_system(
            system=system,
            user=prompt,
            command="quest-compose-steps",  # Routes to gpt-5.1
            think_mode=True,
        )
        
        text = result.get("text", "").strip() if result else ""
        if text:
            print(f"[TwoPass] GPT polish: {len(text)} chars", flush=True)
        return text if text else None
        
    except Exception as e:
        print(f"[TwoPass] GPT error: {e}", flush=True)
        return None


# =============================================================================
# DRAFT QUALITY INSPECTION
# =============================================================================

# Hard-fail patterns - draft is unusable
UNUSABLE_PATTERNS = [
    (r"\btask\s*[1-9]\b", "placeholder 'task N'"),
    (r"\bminute\s+task\b", "placeholder 'minute task'"),
    (r"\bplaceholder\b", "contains 'placeholder'"),
    (r"\bTBD\b", "contains 'TBD'"),
    (r"\bActions:\b", "contains 'Actions:'"),
    (r"\[INFO\]", "contains [INFO] tag"),
    (r"\[RECALL\]", "contains [RECALL] tag"),
    (r"\[APPLY\]", "contains [APPLY] tag"),
    (r"\[BOSS\]", "contains [BOSS] tag"),
    (r"Generated\s+\d+\s+steps", "contains 'Generated X steps'"),
]


def inspect_gemini_draft(raw_text: Optional[str]) -> Dict[str, Any]:
    """
    Inspect Gemini draft for usability.
    
    Returns:
        {
            "usable": bool,
            "reasons": [...],  # Why unusable
            "parsed": dict or None,  # Parsed JSON if valid
        }
    """
    result = {"usable": False, "reasons": [], "parsed": None}
    
    if not raw_text:
        result["reasons"].append("empty response")
        return result
    
    # Check for hard-fail patterns
    for pattern, reason in UNUSABLE_PATTERNS:
        if re.search(pattern, raw_text, re.IGNORECASE):
            result["reasons"].append(reason)
    
    # Try to parse JSON
    parsed = _parse_json(raw_text)
    if parsed is None:
        result["reasons"].append("JSON parse failed")
    else:
        result["parsed"] = parsed
    
    # If no reasons, it's usable
    result["usable"] = len(result["reasons"]) == 0
    
    if not result["usable"]:
        print(f"[TwoPass] Draft unusable: {result['reasons']}", flush=True)
    
    return result


def _parse_json(text: str) -> Optional[Any]:
    """Parse JSON from response text."""
    if not text:
        return None
    
    text = text.strip()
    
    # Strip markdown
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()
    
    # Find JSON
    start_obj = text.find("{")
    start_arr = text.find("[")
    
    if start_obj == -1 and start_arr == -1:
        return None
    
    if start_arr == -1 or (start_obj != -1 and start_obj < start_arr):
        start = start_obj
        end = text.rfind("}") + 1
    else:
        start = start_arr
        end = text.rfind("]") + 1
    
    if start == -1 or end <= start:
        return None
    
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        # Try repair
        repaired = _repair_json(text[start:end])
        if repaired:
            try:
                return json.loads(repaired)
            except:
                pass
        return None


def _repair_json(text: str) -> Optional[str]:
    """Try to repair truncated JSON."""
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    
    if open_braces == 0 and open_brackets == 0:
        return None
    
    repaired = text.rstrip().rstrip(",")
    
    for _ in range(open_brackets):
        repaired += "]"
    for _ in range(open_braces):
        repaired += "}"
    
    return repaired


# =============================================================================
# PROMPTS
# =============================================================================

# --- GEMINI DRAFT PROMPTS ---

GEMINI_DOMAIN_SYSTEM = """You are a curriculum architect.

Extract learning domains from the user's objectives.

OUTPUT FORMAT - Return ONLY valid JSON:
{
  "domains": [
    {"name": "Domain Name", "confidence": 0.85, "rationale": "Why relevant"}
  ]
}

RULES:
- 3-8 domains
- name: 2-40 chars
- confidence: 0.0-1.0
- rationale: max 160 chars
- No duplicates

Return ONLY valid JSON. No markdown. No headings. No preamble.
Never use placeholders like 'domain 1' or 'TBD'."""


GEMINI_STEPS_SYSTEM = """You are a curriculum designer creating day-by-day learning steps.

Each step is ONE DAY (30-90 minutes) for someone with a full-time job.

OUTPUT FORMAT - Return ONLY valid JSON:
{
  "steps": [
    {
      "day": 1,
      "title": "Specific title",
      "domain": "Must match confirmed domain",
      "est_minutes": 60,
      "difficulty": 2,
      "lesson": "1-3 sentences explaining what/why (max 360 chars)",
      "practice": "Concrete action with command/file/tool (max 360 chars)",
      "deliverable": "Verifiable output proving completion (max 140 chars)"
    }
  ]
}

RULES:
- 8-14 steps total
- day: sequential 1, 2, 3...
- est_minutes: 30-90
- difficulty: 1-5 (trend upward)
- Include lesson + practice + deliverable fields exactly

Return ONLY valid JSON. No markdown. No headings. No preamble.
Never use placeholders like 'task 1', 'TBD', or '[INFO]' tags."""


# --- GPT POLISH PROMPTS ---

GPT_DOMAIN_POLISH_SYSTEM = """You are polishing/verifying a learning domain list into production-grade quality.

You will receive:
1. Original objectives
2. A Gemini draft (may be usable or unusable)
3. Inspection notes

YOUR JOB:
- If Gemini draft is usable: polish it, fix any issues, ensure quality
- If Gemini draft is unusable: regenerate fresh from objectives

OUTPUT FORMAT - Return ONLY valid JSON:
{
  "domains": [
    {"name": "Domain Name", "confidence": 0.85, "rationale": "Why relevant"}
  ]
}

CONSTRAINTS:
- 3-8 domains
- name: 2-40 chars, no emojis
- confidence: 0.0-1.0
- rationale: max 160 chars
- No duplicates (case-insensitive)
- Must be relevant to objectives

Output ONLY valid JSON. No markdown. No explanation."""


GPT_STEPS_POLISH_SYSTEM = """You are polishing/verifying learning steps into production-grade quality.

You will receive:
1. Original objectives
2. Confirmed domains
3. A Gemini draft (may be usable or unusable)
4. Inspection notes

YOUR JOB:
- If Gemini draft is usable: polish it, ensure quality, fix any issues
- If Gemini draft is unusable: regenerate fresh from objectives + domains

OUTPUT FORMAT - Return ONLY valid JSON:
{
  "steps": [
    {
      "day": 1,
      "title": "Specific title for this day",
      "domain": "Must match a confirmed domain exactly",
      "est_minutes": 60,
      "difficulty": 2,
      "lesson": "1-3 sentences explaining what/why. Plain English. Max 360 chars.",
      "practice": "Concrete action with specific command/file/tool. Max 360 chars.",
      "deliverable": "Verifiable output proving completion. Max 140 chars."
    }
  ]
}

CONSTRAINTS:
- 8-14 steps total
- day: sequential starting at 1
- est_minutes: 30-90
- difficulty: 1-5 with upward trend (last 3 avg > first 3 avg)
- domain: MUST match one of the confirmed domains exactly
- lesson: teaches what/why (max 360 chars)
- practice: concrete action with tools/commands (max 360 chars)
- deliverable: verifiable artifact (max 140 chars)

Every step should feel like: "I learned something real, did something real, and can prove it."

Output ONLY valid JSON. No markdown. No explanation."""


# =============================================================================
# TWO-PASS GENERATORS
# =============================================================================

def generate_domains_two_pass(
    objectives_text: str,
    llm_client: Any,
) -> Optional[List[Dict[str, Any]]]:
    """
    Two-pass domain generation:
    1. Gemini draft
    2. GPT polish/verify → FINAL
    
    Returns list of domain dicts or None.
    """
    print("[TwoPass] === DOMAINS START ===", flush=True)
    
    # --- PASS 1: Gemini Draft ---
    gemini_draft = None
    inspection = {"usable": False, "reasons": ["skipped"], "parsed": None}
    
    if CONFIG.gemini_enabled and _HAS_GEMINI_SDK:
        print("[TwoPass] Pass 1: Gemini draft...", flush=True)
        
        prompt = f"""Extract learning domains from these objectives:

{objectives_text}

Return ONLY valid JSON."""
        
        raw = _call_gemini(prompt, GEMINI_DOMAIN_SYSTEM, CONFIG.gemini_max_tokens_domains)
        inspection = inspect_gemini_draft(raw)
        gemini_draft = raw
    else:
        print("[TwoPass] Gemini disabled, GPT-only mode", flush=True)
    
    # --- PASS 2: GPT Polish/Verify ---
    print("[TwoPass] Pass 2: GPT polish...", flush=True)
    
    # Build polish prompt
    draft_section = ""
    if gemini_draft:
        draft_section = f"""
GEMINI DRAFT:
{gemini_draft}

INSPECTION:
- Usable: {inspection['usable']}
- Issues: {inspection['reasons'] if inspection['reasons'] else 'none'}
"""
    else:
        draft_section = """
GEMINI DRAFT: (none - generate fresh)
"""
    
    polish_prompt = f"""OBJECTIVES:
{objectives_text}
{draft_section}
Output ONLY valid JSON matching the schema."""
    
    gpt_raw = _call_gpt(polish_prompt, GPT_DOMAIN_POLISH_SYSTEM, CONFIG.gpt_max_tokens_domains, llm_client)
    
    if not gpt_raw:
        print("[TwoPass] GPT polish failed", flush=True)
        print("[TwoPass] === DOMAINS END (FAILED) ===", flush=True)
        return None
    
    # Parse final result
    parsed = _parse_json(gpt_raw)
    if not parsed:
        print("[TwoPass] GPT output not valid JSON", flush=True)
        print("[TwoPass] === DOMAINS END (FAILED) ===", flush=True)
        return None
    
    # Extract domains
    domains = parsed.get("domains", []) if isinstance(parsed, dict) else parsed
    if not isinstance(domains, list):
        domains = []
    
    # Validate
    valid_domains = _validate_domains(domains)
    
    if valid_domains:
        print(f"[TwoPass] FINAL: {len(valid_domains)} domains", flush=True)
        print("[TwoPass] === DOMAINS END ===", flush=True)
        return valid_domains
    
    print("[TwoPass] === DOMAINS END (FAILED) ===", flush=True)
    return None


def generate_steps_two_pass(
    objectives_text: str,
    confirmed_domains: List[str],
    llm_client: Any,
) -> Optional[List[Dict[str, Any]]]:
    """
    Two-pass step generation:
    1. Gemini draft
    2. GPT polish/verify → FINAL
    
    Returns list of step dicts or None.
    """
    print("[TwoPass] === STEPS START ===", flush=True)
    
    domains_str = ", ".join(confirmed_domains)
    
    # --- PASS 1: Gemini Draft ---
    gemini_draft = None
    inspection = {"usable": False, "reasons": ["skipped"], "parsed": None}
    
    if CONFIG.gemini_enabled and _HAS_GEMINI_SDK:
        print("[TwoPass] Pass 1: Gemini draft...", flush=True)
        
        prompt = f"""Generate day-by-day learning steps for:

OBJECTIVES:
{objectives_text}

CONFIRMED DOMAINS (use these exactly):
{domains_str}

Each step = ONE DAY (30-90 min). Include lesson, practice, deliverable.

Return ONLY valid JSON."""
        
        raw = _call_gemini(prompt, GEMINI_STEPS_SYSTEM, CONFIG.gemini_max_tokens_steps)
        inspection = inspect_gemini_draft(raw)
        gemini_draft = raw
    else:
        print("[TwoPass] Gemini disabled, GPT-only mode", flush=True)
    
    # --- PASS 2: GPT Polish/Verify ---
    print("[TwoPass] Pass 2: GPT polish...", flush=True)
    
    # Build polish prompt
    draft_section = ""
    if gemini_draft:
        draft_section = f"""
GEMINI DRAFT:
{gemini_draft}

INSPECTION:
- Usable: {inspection['usable']}
- Issues: {inspection['reasons'] if inspection['reasons'] else 'none'}
"""
    else:
        draft_section = """
GEMINI DRAFT: (none - generate fresh)
"""
    
    polish_prompt = f"""OBJECTIVES:
{objectives_text}

CONFIRMED DOMAINS:
{domains_str}
{draft_section}
Output ONLY valid JSON matching the schema."""
    
    gpt_raw = _call_gpt(polish_prompt, GPT_STEPS_POLISH_SYSTEM, CONFIG.gpt_max_tokens_steps, llm_client)
    
    if not gpt_raw:
        print("[TwoPass] GPT polish failed", flush=True)
        print("[TwoPass] === STEPS END (FAILED) ===", flush=True)
        return None
    
    # Parse final result
    parsed = _parse_json(gpt_raw)
    if not parsed:
        print("[TwoPass] GPT output not valid JSON", flush=True)
        print("[TwoPass] === STEPS END (FAILED) ===", flush=True)
        return None
    
    # Extract steps
    steps = parsed.get("steps", []) if isinstance(parsed, dict) else parsed
    if not isinstance(steps, list):
        steps = []
    
    # Validate and convert
    valid_steps = _validate_steps(steps, confirmed_domains)
    
    if valid_steps:
        print(f"[TwoPass] FINAL: {len(valid_steps)} steps", flush=True)
        print("[TwoPass] === STEPS END ===", flush=True)
        return _convert_to_wizard_format(valid_steps)
    
    print("[TwoPass] === STEPS END (FAILED) ===", flush=True)
    return None


# =============================================================================
# VALIDATORS
# =============================================================================

def _validate_domains(domains: List[Dict]) -> List[Dict[str, Any]]:
    """Validate and clean domain list."""
    if not domains:
        return []
    
    seen = set()
    valid = []
    
    for d in domains:
        if not isinstance(d, dict):
            continue
        
        name = d.get("name", "").strip()
        if not name or len(name) < 2 or len(name) > 40:
            continue
        
        name_lower = name.lower()
        if name_lower in seen:
            continue
        seen.add(name_lower)
        
        confidence = d.get("confidence", 0.8)
        if not isinstance(confidence, (int, float)):
            confidence = 0.8
        confidence = max(0.0, min(1.0, float(confidence)))
        
        rationale = d.get("rationale", "")[:160]
        
        valid.append({
            "name": name,
            "confidence": confidence,
            "rationale": rationale,
        })
    
    if len(valid) < CONFIG.min_domains or len(valid) > CONFIG.max_domains:
        print(f"[TwoPass] Domain count out of range: {len(valid)}", flush=True)
    
    return valid


def _validate_steps(steps: List[Dict], confirmed_domains: List[str]) -> List[Dict[str, Any]]:
    """Validate and clean step list."""
    if not steps:
        return []
    
    domain_lookup = {d.lower(): d for d in confirmed_domains}
    valid = []
    
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            continue
        
        day = s.get("day", i + 1)
        if not isinstance(day, int):
            day = i + 1
        
        title = s.get("title", "").strip()
        if not title:
            continue
        
        # Map domain
        domain_raw = s.get("domain", "").strip().lower()
        domain = domain_lookup.get(domain_raw, "")
        if not domain:
            for d_lower, d_orig in domain_lookup.items():
                if domain_raw in d_lower or d_lower in domain_raw:
                    domain = d_orig
                    break
        if not domain and confirmed_domains:
            domain = confirmed_domains[0]
        
        est_minutes = s.get("est_minutes", 60)
        if not isinstance(est_minutes, int):
            try:
                est_minutes = int(est_minutes)
            except:
                est_minutes = 60
        est_minutes = max(30, min(90, est_minutes))
        
        difficulty = s.get("difficulty", 2)
        if not isinstance(difficulty, int):
            try:
                difficulty = int(difficulty)
            except:
                difficulty = 2
        difficulty = max(1, min(5, difficulty))
        
        lesson = s.get("lesson", "").strip()[:CONFIG.lesson_max_chars]
        practice = s.get("practice", "").strip()[:CONFIG.practice_max_chars]
        deliverable = s.get("deliverable", "").strip()[:CONFIG.deliverable_max_chars]
        
        valid.append({
            "day": len(valid) + 1,
            "title": title,
            "domain": domain,
            "est_minutes": est_minutes,
            "difficulty": difficulty,
            "lesson": lesson,
            "practice": practice,
            "deliverable": deliverable,
        })
    
    return valid


def _convert_to_wizard_format(steps: List[Dict]) -> List[Dict[str, Any]]:
    """Convert to quest_compose_wizard expected format."""
    wizard_steps = []
    
    for step in steps:
        day = step.get("day", len(wizard_steps) + 1)
        title = step.get("title", f"Day {day}")
        domain = step.get("domain", "")
        est_minutes = step.get("est_minutes", 60)
        difficulty = step.get("difficulty", 2)
        lesson = step.get("lesson", "")
        practice = step.get("practice", "")
        deliverable = step.get("deliverable", "")
        
        # Map difficulty to type
        if difficulty >= 4:
            step_type = "apply"
        elif difficulty >= 3:
            step_type = "recall"
        else:
            step_type = "info"
        
        # Build actions
        actions = []
        if practice:
            actions.append(practice)
        if deliverable:
            actions.append(f"Deliverable: {deliverable}")
        if not actions:
            actions = ["Complete the day's learning"]
        
        wizard_steps.append({
            "id": f"step_{day}",
            "type": step_type,
            "title": f"Day {day}: {title}",
            "prompt": lesson,
            "actions": actions,
            "domain": domain,
            "est_minutes": est_minutes,
            "difficulty": difficulty,
            "lesson": lesson,
            "practice": practice,
            "deliverable": deliverable,
            "_source": "two_pass",
        })
    
    return wizard_steps


# =============================================================================
# PUBLIC API (called from quest_compose_wizard.py)
# =============================================================================

def is_gemini_available() -> bool:
    """Check if Gemini is available."""
    if not CONFIG.gemini_enabled:
        return False
    if not _HAS_GEMINI_SDK:
        return False
    return _init_gemini()


def gemini_extract_domains(
    raw_text: str,
    llm_client: Any = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Extract domains using two-pass pipeline.
    
    Gemini draft → GPT polish → FINAL
    """
    if not raw_text or len(raw_text.strip()) < 10:
        return None
    
    return generate_domains_two_pass(raw_text, llm_client)


def gemini_generate_quest_steps(
    draft: Dict[str, Any],
    llm_client: Any = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Generate steps using two-pass pipeline.
    
    Gemini draft → GPT polish → FINAL
    """
    objectives = draft.get("objectives", [])
    if not objectives:
        return None
    
    if isinstance(objectives, list):
        objectives_text = "\n".join(f"- {obj}" for obj in objectives)
    else:
        objectives_text = str(objectives)
    
    domains = draft.get("domains", [])
    confirmed_domains = [
        d.get("name", "") for d in domains if d.get("name")
    ] if domains else []
    
    if not confirmed_domains:
        confirmed_domains = ["General"]
    
    return generate_steps_two_pass(objectives_text, confirmed_domains, llm_client)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "is_gemini_available",
    "gemini_extract_domains",
    "gemini_generate_quest_steps",
    "generate_domains_two_pass",
    "generate_steps_two_pass",
    "CONFIG",
]
