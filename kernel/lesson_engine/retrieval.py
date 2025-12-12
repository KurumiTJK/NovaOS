# kernel/lesson_engine/retrieval.py
"""
v1.0.0 — Lesson Engine: Resource Retrieval (Phase A)

Uses Gemini 2.5 Pro with Google Search grounding to find real, verified
learning resources for each subdomain.

Purpose: Stay current and factual - DO NOT invent resources.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from .schemas import EvidenceResource, EvidencePack


# =============================================================================
# CONSTANTS
# =============================================================================

# Preferred resource providers (in order of preference)
PREFERRED_PROVIDERS = [
    # Official vendor training
    "AWS Skill Builder",
    "AWS Training",
    "Microsoft Learn",
    "Azure Learn",
    "Google Cloud Skills Boost",
    "Google Cloud Training",
    "Cisco Networking Academy",
    "Hashicorp Learn",
    
    # Vendor documentation
    "AWS Documentation",
    "Microsoft Docs",
    "Google Cloud Documentation",
    
    # Established platforms
    "Coursera",
    "edX", 
    "Pluralsight",
    "LinkedIn Learning",
    "Udemy",  # Only if clearly relevant
    
    # Technical resources
    "PortSwigger Web Security Academy",
    "OWASP",
    "TryHackMe",
    "HackTheBox",
]


# =============================================================================
# GEMINI RETRIEVAL
# =============================================================================

def retrieve_resources_for_subdomain(
    subdomain: str,
    domain: str,
    kernel: Any,
    user_constraints: Optional[Dict] = None,
) -> Generator[Dict[str, Any], None, EvidencePack]:
    """
    Phase A: Retrieve learning resources for a subdomain using Gemini with web grounding.
    
    Args:
        subdomain: The specific topic (e.g., "AWS IAM")
        domain: The parent domain (e.g., "Cloud Security")
        kernel: NovaKernel instance with Gemini access
        user_constraints: Optional dict with time_per_session, free_only, etc.
    
    Yields:
        Progress events during retrieval
    
    Returns:
        EvidencePack with verified resources
    """
    yield {"type": "log", "message": f"[Retrieval] Searching for: {subdomain}"}
    
    # Use kernel's LLM client which has Gemini configured
    llm_client = getattr(kernel, 'llm_client', None)
    if not llm_client:
        yield {"type": "log", "message": "[Retrieval] No LLM client, using fallback"}
        return _fallback_evidence_pack(subdomain, domain)
    
    # Try to use Gemini via the gemini_helper
    try:
        import google.generativeai as genai
        import os
        
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            yield {"type": "log", "message": "[Retrieval] No GEMINI_API_KEY, using fallback"}
            return _fallback_evidence_pack(subdomain, domain)
        
        genai.configure(api_key=api_key)
        has_gemini = True
    except ImportError:
        yield {"type": "log", "message": "[Retrieval] Gemini SDK not available, using fallback"}
        return _fallback_evidence_pack(subdomain, domain)
    
    # Build search prompt
    constraints_text = ""
    if user_constraints:
        if user_constraints.get("free_only"):
            constraints_text += "\n- Prefer FREE resources"
        if user_constraints.get("time_per_session"):
            constraints_text += f"\n- User has {user_constraints['time_per_session']} minutes per session"
    
    system_prompt = f"""You are a learning resource researcher. Find REAL, VERIFIED learning resources for the topic below.

CRITICAL RULES:
1. ONLY return resources that actually exist - DO NOT invent courses or URLs
2. Strongly prefer official vendor training (AWS Skill Builder, Microsoft Learn, etc.)
3. Include the ACTUAL URL from your search results
4. Estimate hours based on course descriptions you find
5. If you can't find good resources, return fewer items rather than fake ones

Topic: {subdomain}
Domain Context: {domain}
{constraints_text}

Return a JSON array of resources:
[
  {{
    "title": "Actual course/resource title",
    "provider": "Provider name",
    "type": "course|lab|guide|documentation|video|tutorial",
    "estimated_hours": 1.5,
    "difficulty": "foundational|intermediate|advanced",
    "url": "https://actual-url-from-search",
    "tags": ["relevant", "tags"],
    "description": "Brief description"
  }}
]

Return 3-6 high-quality resources. JSON array only, no markdown."""

    user_prompt = f"Find learning resources for: {subdomain}"
    
    try:
        yield {"type": "log", "message": f"[Retrieval] Calling Gemini for resources..."}
        
        # Call Gemini directly with web grounding
        model = genai.GenerativeModel(
            model_name="gemini-2.5-pro",
            system_instruction=system_prompt,
        )
        
        # Enable grounding with Google Search
        from google.generativeai.types import Tool
        google_search_tool = Tool(
            google_search={}
        )
        
        response = model.generate_content(
            user_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=2000,
            ),
            tools=[google_search_tool],
        )
        
        response_text = ""
        if hasattr(response, 'text'):
            response_text = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                for part in candidate.content.parts:
                    if hasattr(part, 'text'):
                        response_text += part.text
        
        yield {"type": "log", "message": f"[Retrieval] Got response ({len(response_text)} chars)"}
        
        # Parse JSON
        resources = _parse_resources_json(response_text)
        
        if not resources:
            yield {"type": "log", "message": f"[Retrieval] No resources parsed, using fallback"}
            return _fallback_evidence_pack(subdomain, domain)
        
        yield {"type": "log", "message": f"[Retrieval] Found {len(resources)} resources"}
        
        # Build evidence pack
        evidence_pack = EvidencePack(
            subdomain=subdomain,
            domain=domain,
            resources=resources,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        )
        
        return evidence_pack
        
    except Exception as e:
        yield {"type": "log", "message": f"[Retrieval] Error: {e}"}
        return _fallback_evidence_pack(subdomain, domain)


def retrieve_all_evidence(
    domains: List[Dict[str, Any]],
    kernel: Any,
    user_constraints: Optional[Dict] = None,
) -> Generator[Dict[str, Any], None, List[EvidencePack]]:
    """
    Retrieve evidence packs for all subdomains across all domains.
    
    Args:
        domains: List of domain dicts with name and subtopics
        kernel: NovaKernel instance
        user_constraints: Optional constraints
    
    Yields:
        Progress events
    
    Returns:
        List of EvidencePacks
    """
    all_packs = []
    
    # Count total subtopics for progress
    total_subtopics = sum(len(d.get("subtopics", [])) for d in domains)
    if total_subtopics == 0:
        # Just domains, no subtopics
        total_subtopics = len(domains)
    
    processed = 0
    
    for domain in domains:
        domain_name = domain.get("name", "Unknown")
        subtopics = domain.get("subtopics", [])
        
        if not subtopics:
            # Domain without subtopics - retrieve for domain itself
            subtopics = [domain_name]
        
        for subtopic in subtopics:
            processed += 1
            percent = int((processed / total_subtopics) * 100)
            
            yield {
                "type": "progress",
                "message": f"Retrieving: {subtopic}",
                "percent": percent,
            }
            
            # Retrieve for this subtopic
            pack = None
            for event in retrieve_resources_for_subdomain(subtopic, domain_name, kernel, user_constraints):
                if isinstance(event, EvidencePack):
                    pack = event
                else:
                    yield event
            
            if pack is None:
                # Generator returned, get the value
                pack = _fallback_evidence_pack(subtopic, domain_name)
            
            if pack:
                all_packs.append(pack)
    
    yield {"type": "log", "message": f"[Retrieval] Complete: {len(all_packs)} evidence packs"}
    
    return all_packs


# =============================================================================
# STORAGE
# =============================================================================

def save_evidence_packs(packs: List[EvidencePack], data_dir: Path) -> bool:
    """Save evidence packs to lesson_evidence.json."""
    try:
        lessons_dir = data_dir / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = lessons_dir / "lesson_evidence.json"
        
        data = {
            "version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "packs": [pack.to_dict() for pack in packs],
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"[LessonEngine] Saved {len(packs)} evidence packs to {file_path}", flush=True)
        return True
        
    except Exception as e:
        print(f"[LessonEngine] Error saving evidence: {e}", flush=True)
        return False


def load_evidence_packs(data_dir: Path) -> List[EvidencePack]:
    """Load existing evidence packs if available."""
    try:
        file_path = data_dir / "lessons" / "lesson_evidence.json"
        
        if not file_path.exists():
            return []
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        packs = [
            EvidencePack.from_dict(p)
            for p in data.get("packs", [])
        ]
        
        print(f"[LessonEngine] Loaded {len(packs)} existing evidence packs", flush=True)
        return packs
        
    except Exception as e:
        print(f"[LessonEngine] Error loading evidence: {e}", flush=True)
        return []


# =============================================================================
# HELPERS
# =============================================================================

def _parse_resources_json(text: str) -> List[EvidenceResource]:
    """Parse resources from LLM response."""
    try:
        # Strip markdown if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        
        # Find JSON array
        start = text.find("[")
        end = text.rfind("]") + 1
        
        if start == -1 or end == 0:
            return []
        
        json_text = text[start:end]
        data = json.loads(json_text)
        
        if not isinstance(data, list):
            return []
        
        resources = []
        for item in data:
            if not isinstance(item, dict):
                continue
            
            # Validate required fields
            if not item.get("title") or not item.get("url"):
                continue
            
            resource = EvidenceResource(
                title=item.get("title", ""),
                provider=item.get("provider", "Unknown"),
                type=item.get("type", "guide"),
                estimated_hours=float(item.get("estimated_hours", 1.0)),
                difficulty=item.get("difficulty", "foundational"),
                url=item.get("url", ""),
                tags=item.get("tags", []),
                description=item.get("description", ""),
                retrieved_at=datetime.now(timezone.utc).isoformat(),
            )
            resources.append(resource)
        
        return resources
        
    except json.JSONDecodeError as e:
        print(f"[Retrieval] JSON parse error: {e}", flush=True)
        return []
    except Exception as e:
        print(f"[Retrieval] Parse error: {e}", flush=True)
        return []


def _fallback_evidence_pack(subdomain: str, domain: str) -> EvidencePack:
    """Create a fallback evidence pack with generic resource guidance."""
    return EvidencePack(
        subdomain=subdomain,
        domain=domain,
        resources=[
            EvidenceResource(
                title=f"Research: {subdomain}",
                provider="Self-directed",
                type="guide",
                estimated_hours=1.5,
                difficulty="foundational",
                url="",  # Empty - user will find their own
                tags=[subdomain.lower().replace(" ", "-")],
                description=f"Research official documentation and training for {subdomain}",
                retrieved_at=datetime.now(timezone.utc).isoformat(),
            )
        ],
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
