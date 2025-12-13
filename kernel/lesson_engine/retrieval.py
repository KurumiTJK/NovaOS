# kernel/lesson_engine/retrieval.py
"""
v2.0.0 — Lesson Engine: Resource Retrieval (Phase A1)

Uses Gemini 2.5 Pro with Google Search grounding to find real, verified
learning resources for each subdomain.

v2.0 Changes:
- Retrieval is now per-subdomain (not per-domain)
- Populates resource_type for gap detection
- Populates source_subdomain for traceability
- Improved resource type classification

Purpose: Stay current and factual - DO NOT invent resources.

Requires: pip install google-genai
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .schemas import EvidenceResource, EvidencePack, LessonManifest


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
    "Udemy",
    
    # Technical resources
    "PortSwigger Web Security Academy",
    "OWASP",
    "TryHackMe",
    "HackTheBox",
]


# Resource type classification keywords
RESOURCE_TYPE_KEYWORDS = {
    "official_docs": ["documentation", "docs", "reference", "manual", "api reference"],
    "hands_on": ["lab", "hands-on", "exercise", "workshop", "practical", "sandbox"],
    "video": ["video", "youtube", "course video", "lecture"],
    "tutorial": ["tutorial", "guide", "how-to", "walkthrough", "getting started"],
    "course": ["course", "learning path", "certification", "training"],
    "lab": ["lab", "hands-on lab", "playground", "sandbox environment"],
}


def _classify_resource_type(title: str, type_str: str, provider: str, description: str) -> str:
    """Classify resource into a resource_type based on content."""
    combined = f"{title} {type_str} {provider} {description}".lower()
    
    # Check for official docs first (highest priority)
    if any(kw in combined for kw in RESOURCE_TYPE_KEYWORDS["official_docs"]):
        if "docs." in combined or "documentation" in combined:
            return "official_docs"
    
    # Check for hands-on/lab
    if any(kw in combined for kw in RESOURCE_TYPE_KEYWORDS["hands_on"]):
        return "hands_on"
    
    if any(kw in combined for kw in RESOURCE_TYPE_KEYWORDS["lab"]):
        return "lab"
    
    # Check for video
    if any(kw in combined for kw in RESOURCE_TYPE_KEYWORDS["video"]):
        return "video"
    
    # Check for tutorial
    if any(kw in combined for kw in RESOURCE_TYPE_KEYWORDS["tutorial"]):
        return "tutorial"
    
    # Check for course
    if any(kw in combined for kw in RESOURCE_TYPE_KEYWORDS["course"]):
        return "course"
    
    # Default based on type field
    type_lower = type_str.lower()
    if type_lower in ("documentation", "docs"):
        return "official_docs"
    elif type_lower in ("lab", "hands_on", "exercise"):
        return "hands_on"
    elif type_lower == "video":
        return "video"
    elif type_lower in ("tutorial", "guide"):
        return "tutorial"
    elif type_lower == "course":
        return "course"
    
    return "reference"


# =============================================================================
# GEMINI RETRIEVAL WITH WEB GROUNDING
# =============================================================================

def retrieve_resources_for_subdomain(
    subdomain: str,
    domain: str,
    kernel: Any,
    user_constraints: Optional[Dict] = None,
) -> Generator[Dict[str, Any], None, EvidencePack]:
    """
    Phase A1: Retrieve learning resources for a subdomain using Gemini with web grounding.
    
    Args:
        subdomain: The specific topic (e.g., "Docker Image Layers")
        domain: The parent domain (e.g., "Docker Fundamentals")
        kernel: NovaKernel instance with Gemini access
        user_constraints: Optional dict with time_per_session, free_only, etc.
    
    Yields:
        Progress events during retrieval
    
    Returns:
        EvidencePack with verified resources
    """
    yield {"type": "log", "message": f"[Retrieval] Searching for: {subdomain}"}
    
    # Get API key
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        yield {"type": "log", "message": "[Retrieval] No GEMINI_API_KEY, using fallback"}
        return _fallback_evidence_pack(subdomain, domain)
    
    # Try to use the new google-genai SDK
    try:
        from google import genai
        from google.genai import types
        
        yield {"type": "log", "message": "[Retrieval] Using google-genai SDK with web grounding"}
        
    except ImportError:
        yield {"type": "log", "message": "[Retrieval] google-genai not installed, using fallback"}
        yield {"type": "log", "message": "[Retrieval] Install with: pip install google-genai"}
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
6. IMPORTANT: Classify each resource's resource_type accurately:
   - official_docs: Official vendor documentation
   - hands_on: Labs, exercises, interactive tutorials
   - video: Video courses or tutorials
   - tutorial: Written step-by-step guides
   - course: Full courses or learning paths
   - reference: Reference materials, cheat sheets

Topic: {subdomain}
Domain Context: {domain}
{constraints_text}

Return a JSON array of resources:
[
  {{
    "title": "Actual course/resource title",
    "provider": "Provider name",
    "type": "course|lab|guide|documentation|video|tutorial",
    "resource_type": "official_docs|hands_on|video|tutorial|course|reference",
    "estimated_hours": 1.5,
    "difficulty": "foundational|intermediate|advanced",
    "url": "https://actual-url-from-search",
    "tags": ["relevant", "tags"],
    "description": "Brief description"
  }}
]

Return 3-5 high-quality resources. Include at least:
- 1 official documentation resource
- 1 hands-on or tutorial resource

JSON array only, no markdown."""

    user_prompt = f"Find learning resources for: {subdomain}"
    
    try:
        yield {"type": "log", "message": f"[Retrieval] Calling Gemini with Google Search grounding..."}
        
        # Initialize client with API key
        client = genai.Client(api_key=api_key)
        
        # Create Google Search grounding tool
        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        
        # Configure the request
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[grounding_tool],
            temperature=0.3,
            max_output_tokens=2000,
        )
        
        # Make the grounded request
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=user_prompt,
            config=config,
        )
        
        response_text = response.text if hasattr(response, 'text') else ""
        
        yield {"type": "log", "message": f"[Retrieval] Got response ({len(response_text)} chars)"}
        
        # Check for grounding metadata
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                grounding = candidate.grounding_metadata
                if hasattr(grounding, 'web_search_queries'):
                    yield {"type": "log", "message": f"[Retrieval] Search queries: {grounding.web_search_queries}"}
        
        # Parse JSON
        resources = _parse_resources_json(response_text, subdomain)
        
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
    
    v2.0: Now retrieves per-subdomain, not per-domain.
    
    Args:
        domains: List of domain dicts with name and subdomains
        kernel: NovaKernel instance
        user_constraints: Optional constraints
    
    Yields:
        Progress events
    
    Returns:
        List of EvidencePacks
    """
    all_packs = []
    
    # Flatten to list of (domain, subdomain) pairs
    subdomain_list = []
    for domain in domains:
        domain_name = domain.get("name", "Unknown")
        subdomains = domain.get("subdomains", domain.get("subtopics", []))
        
        if not subdomains:
            # Domain without subdomains - retrieve for domain itself
            subdomain_list.append((domain_name, domain_name))
        else:
            for subdomain in subdomains:
                subdomain_list.append((domain_name, subdomain))
    
    total = len(subdomain_list)
    if total == 0:
        yield {"type": "log", "message": "[Retrieval] No subdomains to retrieve"}
        return all_packs
    
    for i, (domain_name, subdomain) in enumerate(subdomain_list):
        percent = int(((i + 1) / total) * 100)
        
        yield {
            "type": "progress",
            "message": f"Retrieving: {subdomain}",
            "percent": percent,
        }
        
        # Retrieve for this subdomain
        pack = None
        retrieval_gen = retrieve_resources_for_subdomain(subdomain, domain_name, kernel, user_constraints)
        
        try:
            while True:
                event = next(retrieval_gen)
                yield event
        except StopIteration as e:
            pack = e.value if e.value else _fallback_evidence_pack(subdomain, domain_name)
        
        if pack:
            all_packs.append(pack)
    
    yield {"type": "log", "message": f"[Retrieval] Complete: {len(all_packs)} evidence packs"}
    
    return all_packs


def retrieve_from_manifest(
    manifest: LessonManifest,
    kernel: Any,
    user_constraints: Optional[Dict] = None,
) -> Generator[Dict[str, Any], None, List[EvidencePack]]:
    """
    Retrieve evidence packs from a manifest.
    
    This is the preferred entry point for v2.0 - uses the manifest's
    subdomain structure directly.
    
    Args:
        manifest: LessonManifest with domains and subdomains
        kernel: NovaKernel instance
        user_constraints: Optional constraints
    
    Yields:
        Progress events
    
    Returns:
        List of EvidencePacks
    """
    # Convert manifest to domains format
    domains = []
    for d in manifest.domains:
        domains.append({
            "name": d.get("name", ""),
            "subdomains": d.get("subdomains", []),
        })
    
    # Delegate to retrieve_all_evidence
    result = []
    gen = retrieve_all_evidence(domains, kernel, user_constraints)
    
    try:
        while True:
            event = next(gen)
            yield event
    except StopIteration as e:
        result = e.value if e.value else []
    
    return result


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
            "version": "2.0.0",
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

def _parse_resources_json(text: str, subdomain: str) -> List[EvidenceResource]:
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
            
            # Get base fields
            title = item.get("title", "")
            provider = item.get("provider", "Unknown")
            type_str = item.get("type", "guide")
            description = item.get("description", "")
            
            # Classify resource type
            resource_type = item.get("resource_type", "")
            if not resource_type or resource_type == "reference":
                resource_type = _classify_resource_type(title, type_str, provider, description)
            
            # Calculate estimated minutes
            estimated_hours = float(item.get("estimated_hours", 1.0))
            estimated_minutes = int(estimated_hours * 60)
            
            resource = EvidenceResource(
                title=title,
                provider=provider,
                type=type_str,
                estimated_hours=estimated_hours,
                difficulty=item.get("difficulty", "foundational"),
                url=item.get("url", ""),
                tags=item.get("tags", []),
                description=description,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                resource_type=resource_type,
                estimated_minutes=estimated_minutes,
                source_subdomain=subdomain,
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
                resource_type="reference",
                estimated_minutes=90,
                source_subdomain=subdomain,
            )
        ],
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )
