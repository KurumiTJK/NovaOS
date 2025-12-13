# kernel/lesson_engine/__init__.py
"""
v2.0.0 — Lesson Engine

Retrieval-backed, step-sized lesson generation for NovaOS Quest Compose.

4-Phase Pipeline:
  Phase A1 (Retrieval): Gemini 2.5 Pro with web grounding (per subdomain)
  Phase A2 (Gap Fill): Detect gaps and patch with targeted retrieval
  Phase B (Step Builder): Gemini 2.5 Pro with action type validation
  Phase C (Plan Refiner): GPT-5.1 (reorder only, cannot add content)

v2.0 Changes:
- Per-subdomain retrieval
- Gap detection and patching (Phase A2)
- Manifest-based coverage tracking
- Action type validation (read/do/verify)
- Coverage summary in output

This module provides:
  - generate_lesson_plan(): Main entry point for Quest Compose
  - generate_lesson_plan_streaming(): Streaming version with progress events
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .schemas import (
    EvidencePack,
    EvidenceResource,
    LessonPlan,
    LessonStep,
    LessonManifest,
    GapReport,
    Gap,
    validate_lesson_plan,
    validate_subdomain_coverage,
)
from .retrieval import (
    retrieve_all_evidence,
    retrieve_from_manifest,
    save_evidence_packs,
    load_evidence_packs,
)
from .step_builder import (
    build_steps_from_evidence,
    save_raw_steps,
    load_raw_steps,
    validate_steps_coverage,
)
from .plan_refiner import (
    refine_lesson_plan,
    save_final_plan,
    load_final_plan,
)
from .gap_detector import (
    detect_gaps,
    detect_gaps_and_patch,
    save_manifest,
    load_manifest,
    save_gap_report,
    load_gap_report,
)


# =============================================================================
# PUBLIC API
# =============================================================================

def generate_lesson_plan_streaming(
    domains: List[Dict[str, Any]],
    quest_id: str,
    quest_title: str,
    kernel: Any,
    user_constraints: Optional[Dict] = None,
    skip_retrieval: bool = False,
) -> Generator[Dict[str, Any], None, List[Dict[str, Any]]]:
    """
    Generate a lesson plan using the 4-phase engine.
    Streaming version that yields progress events.
    
    This is the main integration point for Quest Compose.
    
    Args:
        domains: List of confirmed domains with subdomains
                 Format: [{"name": "Domain", "subdomains": ["sub1", "sub2"]}]
        quest_id: Quest identifier
        quest_title: Quest title
        kernel: NovaKernel instance
        user_constraints: Optional dict with time_per_session, free_only, etc.
        skip_retrieval: If True, reuse existing evidence (idempotent refinement)
    
    Yields:
        Progress events:
        - {"type": "log", "message": "..."}
        - {"type": "progress", "message": "...", "percent": N}
        - {"type": "steps", "steps": [...]}  # Final steps
        - {"type": "error", "message": "..."}
        - {"type": "coverage", "summary": "..."}  # Coverage summary
    
    Returns:
        List of step dicts in Quest Engine format
    """
    def _log(msg: str):
        return {"type": "log", "message": f"[LessonEngine] {msg}"}
    
    def _progress(msg: str, pct: int):
        return {"type": "progress", "message": msg, "percent": pct}
    
    def _steps(steps_list: List[Dict[str, Any]]):
        return {"type": "steps", "steps": steps_list}
    
    def _error(msg: str):
        return {"type": "error", "message": msg}
    
    def _coverage(summary: str):
        return {"type": "coverage", "summary": summary}
    
    try:
        yield _log("Starting 4-phase lesson generation (v2.0)")
        yield _progress("Initializing Lesson Engine...", 5)
        
        # Get data directory
        data_dir = Path(getattr(kernel.config, 'data_dir', 'data'))
        
        # Create manifest from domains
        manifest = LessonManifest.from_domains(domains)
        save_manifest(manifest, data_dir)
        yield _log(f"Created manifest with {manifest.count_subdomains()} subdomains")
        
        evidence_packs = []
        raw_steps = []
        gap_report = None
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE A1: RETRIEVAL (Gemini with web grounding, per subdomain)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase A1: Resource Retrieval...", 10)
        
        if skip_retrieval:
            yield _log("Skipping retrieval, loading existing evidence...")
            evidence_packs = load_evidence_packs(data_dir)
        
        if not evidence_packs:
            yield _log("Retrieving resources with Gemini web grounding...")
            
            # Run retrieval from manifest
            retrieval_gen = retrieve_from_manifest(manifest, kernel, user_constraints)
            
            try:
                while True:
                    event = next(retrieval_gen)
                    # Adjust progress for Phase A1 (10-30%)
                    if event.get("type") == "progress":
                        event["percent"] = 10 + int(event["percent"] * 0.20)
                    yield event
            except StopIteration as e:
                evidence_packs = e.value if e.value else []
            
            # Save evidence
            if evidence_packs:
                save_evidence_packs(evidence_packs, data_dir)
                yield _log(f"Saved {len(evidence_packs)} evidence packs")
        
        if not evidence_packs:
            yield _error("No evidence packs generated - cannot proceed")
            return []
        
        yield _progress("Phase A1 complete", 30)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE A2: GAP DETECTION & PATCHING
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase A2: Gap Detection...", 32)
        yield _log("Detecting coverage gaps...")
        
        gap_gen = detect_gaps_and_patch(manifest, evidence_packs, kernel)
        
        try:
            while True:
                event = next(gap_gen)
                # Adjust progress for Phase A2 (32-45%)
                if event.get("type") == "progress":
                    event["percent"] = 32 + int(event["percent"] * 0.13)
                yield event
        except StopIteration as e:
            if e.value:
                evidence_packs, gap_report = e.value
            else:
                gap_report = GapReport()
        
        # Save updated evidence and gap report
        if evidence_packs:
            save_evidence_packs(evidence_packs, data_dir)
        if gap_report:
            save_gap_report(gap_report, data_dir)
            if gap_report.has_unresolved():
                yield _log(f"⚠️ {len(gap_report.unresolved_gaps)} unresolved gaps remain")
        
        yield _progress("Phase A2 complete", 45)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE B: STEP BUILDER (Gemini with validation)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase B: Building Steps...", 50)
        yield _log("Converting evidence to atomic learning steps...")
        
        # Run step builder
        step_gen = build_steps_from_evidence(evidence_packs, quest_title, kernel, manifest)
        
        try:
            while True:
                event = next(step_gen)
                # Adjust progress for Phase B (50-75%)
                if event.get("type") == "progress":
                    event["percent"] = 50 + int(event["percent"] * 0.25)
                yield event
        except StopIteration as e:
            raw_steps = e.value if e.value else []
        
        if not raw_steps:
            yield _error("No steps generated from evidence")
            return []
        
        # Save raw steps
        save_raw_steps(raw_steps, data_dir)
        yield _log(f"Built {len(raw_steps)} raw steps")
        
        # Validate coverage
        all_covered, coverage_gaps = validate_steps_coverage(raw_steps, manifest)
        if not all_covered:
            yield _log(f"⚠️ {len(coverage_gaps)} subdomains not covered by steps")
            # Add to gap report
            if gap_report:
                gap_report.unresolved_gaps.extend(coverage_gaps)
                save_gap_report(gap_report, data_dir)
        
        yield _progress("Phase B complete", 75)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE C: PLAN REFINEMENT (GPT-5.1)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase C: Refining Plan...", 80)
        yield _log("Refining with GPT-5.1 (sequencing, pacing)...")
        
        # Get user pacing from constraints
        user_pacing = None
        if user_constraints:
            user_pacing = {"steps_per_day": user_constraints.get("steps_per_day", 1)}
        
        # Run plan refiner
        final_plan = None
        refine_gen = refine_lesson_plan(
            raw_steps, evidence_packs, quest_id, quest_title,
            kernel, user_pacing, gap_report, manifest
        )
        
        try:
            while True:
                event = next(refine_gen)
                # Adjust progress for Phase C (80-95%)
                if event.get("type") == "progress":
                    event["percent"] = 80 + int(event["percent"] * 0.15)
                yield event
        except StopIteration as e:
            final_plan = e.value
        
        if not final_plan:
            yield _log("Warning: Using raw steps without refinement")
            # Create plan from raw steps
            total_hours = sum(s.estimated_time_minutes for s in raw_steps) / 60
            final_plan = LessonPlan(
                quest_id=quest_id,
                quest_title=quest_title,
                total_steps=len(raw_steps),
                total_hours=round(total_hours, 1),
                steps=raw_steps,
                evidence_packs=evidence_packs,
                gap_report=gap_report,
            )
        
        # Save final plan
        save_final_plan(final_plan, data_dir)
        
        # ═══════════════════════════════════════════════════════════════════════
        # FINALIZE
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Complete!", 100)
        yield _log(f"Generated {final_plan.total_steps} steps ({final_plan.total_hours}h total)")
        
        # Emit coverage summary
        if final_plan.coverage_summary:
            yield _coverage(final_plan.coverage_summary)
        
        # Convert to Quest Engine format
        quest_steps = final_plan.to_quest_steps()
        yield _steps(quest_steps)
        
        return quest_steps
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield _error(f"Lesson generation failed: {str(e)}")
        return []


def generate_lesson_plan(
    domains: List[Dict[str, Any]],
    quest_id: str,
    quest_title: str,
    kernel: Any,
    user_constraints: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    """
    Non-streaming version of lesson plan generation.
    
    Args:
        domains: List of confirmed domains with subdomains
        quest_id: Quest identifier
        quest_title: Quest title
        kernel: NovaKernel instance
        user_constraints: Optional constraints
    
    Returns:
        List of step dicts in Quest Engine format
    """
    result = []
    
    for event in generate_lesson_plan_streaming(domains, quest_id, quest_title, kernel, user_constraints):
        if event.get("type") == "steps":
            result = event.get("steps", [])
        elif event.get("type") == "log":
            print(event.get("message", ""), flush=True)
        elif event.get("type") == "coverage":
            print(event.get("summary", ""), flush=True)
    
    return result


# =============================================================================
# MANIFEST HELPER
# =============================================================================

def create_manifest_from_domains(domains: List[Dict[str, Any]], data_dir: Path) -> LessonManifest:
    """
    Create and save a manifest from confirmed domains.
    
    Call this when domains+subdomains are confirmed in quest-compose.
    
    Args:
        domains: List of domain dicts with subdomains
        data_dir: Data directory for saving
    
    Returns:
        Created manifest
    """
    manifest = LessonManifest.from_domains(domains)
    save_manifest(manifest, data_dir)
    return manifest


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Main API
    "generate_lesson_plan",
    "generate_lesson_plan_streaming",
    "create_manifest_from_domains",
    
    # Schemas
    "EvidencePack",
    "EvidenceResource",
    "LessonPlan",
    "LessonStep",
    "LessonManifest",
    "GapReport",
    "Gap",
    "validate_lesson_plan",
    "validate_subdomain_coverage",
    
    # Individual phases (for testing/debugging)
    "retrieve_all_evidence",
    "retrieve_from_manifest",
    "detect_gaps",
    "detect_gaps_and_patch",
    "build_steps_from_evidence",
    "refine_lesson_plan",
    
    # Storage
    "save_evidence_packs",
    "load_evidence_packs",
    "save_raw_steps",
    "load_raw_steps",
    "save_final_plan",
    "load_final_plan",
    "save_manifest",
    "load_manifest",
    "save_gap_report",
    "load_gap_report",
]
