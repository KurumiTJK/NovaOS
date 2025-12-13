# kernel/lesson_engine/gap_detector.py
"""
v2.0.0 — Lesson Engine: Gap Detection & Patch Retrieval (Phase A2)

Detects missing coverage in evidence packs and attempts to fill gaps
using targeted grounded retrieval.

Gap Detection Rules:
- Zero resources for a subdomain
- No official_docs resource
- No hands_on or tutorial resource
- Resources exist but not atomizable into 60-120 min steps
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from .schemas import (
    EvidencePack,
    EvidenceResource,
    Gap,
    GapReport,
    LessonManifest,
)


# =============================================================================
# SITE FILTERS FOR OFFICIAL DOCS
# =============================================================================

OFFICIAL_DOC_SITES = {
    # Cloud providers
    "aws": "site:docs.aws.amazon.com OR site:aws.amazon.com/training",
    "azure": "site:learn.microsoft.com OR site:docs.microsoft.com",
    "gcp": "site:cloud.google.com/docs",
    
    # Container/K8s
    "docker": "site:docs.docker.com",
    "kubernetes": "site:kubernetes.io/docs",
    "helm": "site:helm.sh/docs",
    
    # CI/CD
    "github": "site:docs.github.com",
    "gitlab": "site:docs.gitlab.com",
    "jenkins": "site:www.jenkins.io/doc",
    "circleci": "site:circleci.com/docs",
    
    # Infrastructure
    "terraform": "site:developer.hashicorp.com/terraform",
    "ansible": "site:docs.ansible.com",
    
    # Security
    "owasp": "site:owasp.org",
    
    # Databases
    "postgresql": "site:postgresql.org/docs",
    "mysql": "site:dev.mysql.com/doc",
    "mongodb": "site:docs.mongodb.com",
    "redis": "site:redis.io/docs",
}


def _get_site_filter(subdomain: str) -> str:
    """Get appropriate site filter for a subdomain."""
    subdomain_lower = subdomain.lower()
    
    for keyword, site_filter in OFFICIAL_DOC_SITES.items():
        if keyword in subdomain_lower:
            return site_filter
    
    return ""


# =============================================================================
# GAP DETECTION
# =============================================================================

def detect_gaps(
    manifest: LessonManifest,
    evidence_packs: List[EvidencePack],
) -> List[Gap]:
    """
    Detect gaps in evidence coverage.
    
    A gap exists if:
    1. Zero resources for a subdomain
    2. No official_docs resource
    3. No hands_on or tutorial resource  
    4. Resources not atomizable (total time < 30 min or > 6 hours)
    
    Args:
        manifest: Expected coverage manifest
        evidence_packs: Current evidence packs
        
    Returns:
        List of detected gaps
    """
    gaps = []
    
    # Build lookup: subdomain -> evidence pack
    pack_lookup: Dict[str, EvidencePack] = {}
    for pack in evidence_packs:
        pack_lookup[pack.subdomain] = pack
    
    # Check each expected subdomain
    for entry in manifest.get_all_subdomains():
        domain = entry["domain"]
        subdomain = entry["subdomain"]
        
        pack = pack_lookup.get(subdomain)
        
        # Gap 1: No evidence pack at all
        if not pack or not pack.resources:
            gaps.append(Gap(
                domain=domain,
                subdomain=subdomain,
                reason="no_resources",
            ))
            continue
        
        # Gap 2: No official_docs
        has_official = any(
            r.resource_type in ("official_docs", "documentation")
            or "docs" in r.provider.lower()
            or "documentation" in r.type.lower()
            for r in pack.resources
        )
        if not has_official:
            gaps.append(Gap(
                domain=domain,
                subdomain=subdomain,
                reason="no_official_docs",
            ))
        
        # Gap 3: No hands_on or tutorial
        has_hands_on = any(
            r.resource_type in ("hands_on", "lab", "tutorial")
            or r.type in ("lab", "hands_on", "tutorial", "exercise")
            for r in pack.resources
        )
        if not has_hands_on:
            gaps.append(Gap(
                domain=domain,
                subdomain=subdomain,
                reason="no_hands_on",
            ))
        
        # Gap 4: Not atomizable (time issues)
        total_minutes = pack.get_total_minutes()
        if total_minutes < 30:
            gaps.append(Gap(
                domain=domain,
                subdomain=subdomain,
                reason="insufficient_content",
            ))
        elif total_minutes > 360:  # > 6 hours
            # This isn't really a gap, just means we need multiple steps
            # But flag if ALL resources are massive (> 3 hours each)
            if all(r.estimated_minutes > 180 for r in pack.resources):
                gaps.append(Gap(
                    domain=domain,
                    subdomain=subdomain,
                    reason="no_atomic_resources",
                ))
    
    return gaps


# =============================================================================
# GAP PATCHING
# =============================================================================

def patch_gap_with_retrieval(
    gap: Gap,
    kernel: Any,
) -> Generator[Dict[str, Any], None, Tuple[List[EvidenceResource], bool]]:
    """
    Attempt to patch a gap using targeted grounded retrieval.
    
    Args:
        gap: The gap to patch
        kernel: NovaKernel instance
        
    Yields:
        Progress events
        
    Returns:
        Tuple of (new_resources, resolved)
    """
    yield {"type": "log", "message": f"[GapDetector] Patching: {gap.subdomain} ({gap.reason})"}
    
    # Build targeted search query based on gap type
    site_filter = _get_site_filter(gap.subdomain)
    
    if gap.reason == "no_official_docs":
        query = f"{gap.subdomain} official documentation tutorial"
        if site_filter:
            query = f"{gap.subdomain} {site_filter}"
    elif gap.reason == "no_hands_on":
        query = f"{gap.subdomain} hands-on lab tutorial exercise"
    elif gap.reason == "no_resources":
        query = f"{gap.subdomain} learning resources course tutorial"
    elif gap.reason == "insufficient_content":
        query = f"{gap.subdomain} comprehensive guide course"
    elif gap.reason == "no_atomic_resources":
        query = f"{gap.subdomain} quick start tutorial beginner guide"
    else:
        query = f"{gap.subdomain} learning resources"
    
    # Get API key
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        yield {"type": "log", "message": "[GapDetector] No GEMINI_API_KEY, cannot patch"}
        return ([], False)
    
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        yield {"type": "log", "message": "[GapDetector] google-genai not installed"}
        return ([], False)
    
    system_prompt = f"""You are a learning resource researcher filling a gap in coverage.

GAP TYPE: {gap.reason}
SUBDOMAIN: {gap.subdomain}
DOMAIN: {gap.domain}

CRITICAL RULES:
1. Find REAL resources that actually exist
2. Include actual URLs from your search
3. For "{gap.reason}" gaps, specifically look for:
   - no_official_docs: Official vendor documentation
   - no_hands_on: Labs, tutorials, exercises, hands-on practice
   - no_resources: Any quality learning content
   - insufficient_content: More comprehensive resources
   - no_atomic_resources: Shorter, focused resources (< 2 hours)

Return JSON array of 2-4 resources:
[
  {{
    "title": "Resource title",
    "provider": "Provider name",
    "type": "documentation|lab|tutorial|video|course|guide",
    "resource_type": "official_docs|hands_on|video|tutorial|reference",
    "estimated_hours": 1.5,
    "difficulty": "foundational|intermediate|advanced",
    "url": "https://actual-url",
    "description": "Brief description"
  }}
]

JSON array only, no markdown."""

    user_prompt = f"Find resources for: {query}"
    
    try:
        yield {"type": "log", "message": f"[GapDetector] Searching: {query[:60]}..."}
        
        client = genai.Client(api_key=api_key)
        
        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[grounding_tool],
            temperature=0.3,
            max_output_tokens=1500,
        )
        
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=user_prompt,
            config=config,
        )
        
        response_text = response.text if hasattr(response, 'text') else ""
        
        # Parse resources
        resources = _parse_patch_resources(response_text, gap)
        
        if resources:
            yield {"type": "log", "message": f"[GapDetector] Found {len(resources)} patch resources"}
            
            # Check if gap is resolved
            resolved = _check_gap_resolved(gap, resources)
            return (resources, resolved)
        else:
            yield {"type": "log", "message": f"[GapDetector] No resources found for patch"}
            return ([], False)
            
    except Exception as e:
        yield {"type": "log", "message": f"[GapDetector] Patch error: {e}"}
        return ([], False)


def _parse_patch_resources(text: str, gap: Gap) -> List[EvidenceResource]:
    """Parse resources from patch retrieval response."""
    try:
        # Strip markdown
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        
        start = text.find("[")
        end = text.rfind("]") + 1
        
        if start == -1 or end == 0:
            return []
        
        data = json.loads(text[start:end])
        
        if not isinstance(data, list):
            return []
        
        resources = []
        for item in data:
            if not isinstance(item, dict):
                continue
            
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
                resource_type=item.get("resource_type", "reference"),
                source_subdomain=gap.subdomain,
            )
            resources.append(resource)
        
        return resources
        
    except Exception as e:
        print(f"[GapDetector] Parse error: {e}", flush=True)
        return []


def _check_gap_resolved(gap: Gap, new_resources: List[EvidenceResource]) -> bool:
    """Check if new resources resolve the gap."""
    if not new_resources:
        return False
    
    if gap.reason == "no_official_docs":
        return any(
            r.resource_type in ("official_docs", "documentation")
            or "docs" in r.provider.lower()
            for r in new_resources
        )
    elif gap.reason == "no_hands_on":
        return any(
            r.resource_type in ("hands_on", "lab", "tutorial")
            or r.type in ("lab", "tutorial", "exercise")
            for r in new_resources
        )
    elif gap.reason in ("no_resources", "insufficient_content"):
        return len(new_resources) >= 1
    elif gap.reason == "no_atomic_resources":
        return any(r.estimated_minutes <= 120 for r in new_resources)
    
    return len(new_resources) > 0


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

def detect_gaps_and_patch(
    manifest: LessonManifest,
    evidence_packs: List[EvidencePack],
    kernel: Any,
) -> Generator[Dict[str, Any], None, Tuple[List[EvidencePack], GapReport]]:
    """
    Phase A2: Detect gaps and attempt to patch them with retrieval.
    
    Args:
        manifest: Expected coverage manifest
        evidence_packs: Current evidence packs from Phase A1
        kernel: NovaKernel instance
        
    Yields:
        Progress events
        
    Returns:
        Tuple of (updated_evidence_packs, gap_report)
    """
    yield {"type": "log", "message": "[GapDetector] Starting gap detection..."}
    
    # Detect gaps
    gaps = detect_gaps(manifest, evidence_packs)
    
    if not gaps:
        yield {"type": "log", "message": "[GapDetector] No gaps detected ✓"}
        return (evidence_packs, GapReport())
    
    yield {"type": "log", "message": f"[GapDetector] Found {len(gaps)} gaps"}
    
    # Build pack lookup for updating
    pack_lookup: Dict[str, EvidencePack] = {p.subdomain: p for p in evidence_packs}
    
    resolved_gaps = []
    unresolved_gaps = []
    max_attempts = manifest.constraints.get("max_patch_attempts_per_subdomain", 2)
    
    # Group gaps by subdomain to avoid duplicate patches
    gaps_by_subdomain: Dict[str, List[Gap]] = {}
    for gap in gaps:
        if gap.subdomain not in gaps_by_subdomain:
            gaps_by_subdomain[gap.subdomain] = []
        gaps_by_subdomain[gap.subdomain].append(gap)
    
    total_subdomains = len(gaps_by_subdomain)
    processed = 0
    
    for subdomain, subdomain_gaps in gaps_by_subdomain.items():
        processed += 1
        percent = int((processed / total_subdomains) * 100)
        
        yield {
            "type": "progress",
            "message": f"Patching gaps: {subdomain}",
            "percent": percent,
        }
        
        # Try to patch each gap type for this subdomain
        for gap in subdomain_gaps:
            if gap.attempts >= max_attempts:
                gap.resolved = False
                unresolved_gaps.append(gap)
                continue
            
            # Attempt patch
            new_resources = []
            resolved = False
            
            for event in patch_gap_with_retrieval(gap, kernel):
                if isinstance(event, tuple):
                    new_resources, resolved = event
                else:
                    yield event
            
            gap.attempts += 1
            
            if resolved and new_resources:
                gap.resolved = True
                resolved_gaps.append(gap)
                
                # Add resources to evidence pack
                if subdomain in pack_lookup:
                    pack_lookup[subdomain].resources.extend(new_resources)
                else:
                    # Create new pack
                    new_pack = EvidencePack(
                        subdomain=subdomain,
                        domain=gap.domain,
                        resources=new_resources,
                        retrieved_at=datetime.now(timezone.utc).isoformat(),
                    )
                    pack_lookup[subdomain] = new_pack
            else:
                # Try again if under max attempts
                if gap.attempts < max_attempts:
                    yield {"type": "log", "message": f"[GapDetector] Retry {gap.attempts + 1}/{max_attempts} for {subdomain}"}
                    
                    for event in patch_gap_with_retrieval(gap, kernel):
                        if isinstance(event, tuple):
                            new_resources, resolved = event
                        else:
                            yield event
                    
                    gap.attempts += 1
                    
                    if resolved and new_resources:
                        gap.resolved = True
                        resolved_gaps.append(gap)
                        
                        if subdomain in pack_lookup:
                            pack_lookup[subdomain].resources.extend(new_resources)
                    else:
                        unresolved_gaps.append(gap)
                else:
                    unresolved_gaps.append(gap)
    
    # Build final report
    gap_report = GapReport(
        resolved_gaps=resolved_gaps,
        unresolved_gaps=unresolved_gaps,
    )
    
    # Convert pack lookup back to list
    updated_packs = list(pack_lookup.values())
    
    yield {"type": "log", "message": f"[GapDetector] Resolved: {len(resolved_gaps)}, Unresolved: {len(unresolved_gaps)}"}
    
    return (updated_packs, gap_report)


# =============================================================================
# STORAGE
# =============================================================================

def save_manifest(manifest: LessonManifest, data_dir: Path) -> bool:
    """Save manifest to lesson_manifest.json."""
    try:
        lessons_dir = data_dir / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = lessons_dir / "lesson_manifest.json"
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(manifest.to_dict(), f, indent=2, ensure_ascii=False)
        
        print(f"[LessonEngine] Saved manifest to {file_path}", flush=True)
        return True
        
    except Exception as e:
        print(f"[LessonEngine] Error saving manifest: {e}", flush=True)
        return False


def load_manifest(data_dir: Path) -> Optional[LessonManifest]:
    """Load existing manifest if available."""
    try:
        file_path = data_dir / "lessons" / "lesson_manifest.json"
        
        if not file_path.exists():
            return None
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return LessonManifest.from_dict(data)
        
    except Exception as e:
        print(f"[LessonEngine] Error loading manifest: {e}", flush=True)
        return None


def save_gap_report(report: GapReport, data_dir: Path) -> bool:
    """Save gap report to lesson_gaps.json."""
    try:
        lessons_dir = data_dir / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = lessons_dir / "lesson_gaps.json"
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        
        print(f"[LessonEngine] Saved gap report to {file_path}", flush=True)
        return True
        
    except Exception as e:
        print(f"[LessonEngine] Error saving gap report: {e}", flush=True)
        return False


def load_gap_report(data_dir: Path) -> Optional[GapReport]:
    """Load existing gap report if available."""
    try:
        file_path = data_dir / "lessons" / "lesson_gaps.json"
        
        if not file_path.exists():
            return None
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return GapReport.from_dict(data)
        
    except Exception as e:
        print(f"[LessonEngine] Error loading gap report: {e}", flush=True)
        return None
