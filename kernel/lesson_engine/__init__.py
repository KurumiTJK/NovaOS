# kernel/lesson_engine/__init__.py
"""
v3.1.0 — Lesson Engine

Retrieval-backed, step-sized lesson generation for NovaOS Quest Compose.

5-Phase Pipeline:
  Phase A1 (Retrieval): Gemini 2.5 Pro with Google Search (find URLs)
  Phase A2 (Gap Detection): Find gaps and patch with better resources
  Phase A3 (Fetch): Actually read the documents (fetch AFTER patching!)
  Phase B (Step Builder): Convert evidence to daily steps (uses real content!)
  Phase C (Plan Refiner): GPT-5.1 (reorder only, cannot add content)

IMPORTANT: Requires:
  pip install google-genai httpx beautifulsoup4
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
from .content_fetcher import (
    fetch_content_for_evidence_packs,
    get_content_for_subdomain,
    has_fetched_content,
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
    
    Args:
        domains: List of confirmed domains with subdomains
                 Format: [{"name": "Domain", "subdomains": ["sub1", "sub2"]}]
        quest_id: Quest identifier
        quest_title: Quest title
        kernel: NovaKernel instance
        user_constraints: Optional dict with time_per_session, free_only, etc.
        skip_retrieval: If True, reuse existing evidence
    
    Yields:
        Progress events
    
    Returns:
        List of step dicts in Quest Engine format
    """
    def _log(msg: str):
        print(f"[LessonEngine] {msg}", flush=True)
        return {"type": "log", "message": f"[LessonEngine] {msg}"}
    
    def _progress(msg: str, pct: int):
        return {"type": "progress", "message": msg, "percent": pct}
    
    def _steps(steps_list: List[Dict[str, Any]]):
        return {"type": "steps", "steps": steps_list}
    
    def _error(msg: str):
        print(f"[LessonEngine] ERROR: {msg}", flush=True)
        return {"type": "error", "message": msg}
    
    def _coverage(summary: str):
        return {"type": "coverage", "summary": summary}
    
    try:
        yield _log("Starting 4-phase lesson generation (v3.0)")
        yield _progress("Initializing...", 5)
        
        # Get data directory
        data_dir = Path(getattr(kernel.config, 'data_dir', 'data'))
        
        # Get LLM client from kernel
        llm_client = getattr(kernel, 'llm_client', None)
        
        # Create manifest from domains
        manifest = LessonManifest.from_domains(domains)
        save_manifest(manifest, data_dir)
        yield _log(f"Created manifest with {manifest.count_subdomains()} subdomains")
        
        evidence_packs = []
        raw_steps = []
        gap_report = None
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE A1: RETRIEVAL (Gemini with Google Search)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase A1: Resource Retrieval...", 10)
        
        if skip_retrieval:
            yield _log("Skipping retrieval, loading existing evidence...")
            evidence_packs = load_evidence_packs(data_dir)
        
        if not evidence_packs:
            yield _log("Retrieving resources with Gemini + Google Search...")
            
            # Run retrieval from manifest
            retrieval_gen = retrieve_from_manifest(manifest, kernel, user_constraints)
            
            try:
                while True:
                    event = next(retrieval_gen)
                    # Print log events for visibility
                    if event.get("type") == "log":
                        print(event.get("message", ""), flush=True)
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
        
        yield _progress("Phase A1 complete", 25)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE A2: GAP DETECTION & PATCHING (before fetching!)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase A2: Gap Detection...", 27)
        yield _log("Detecting coverage gaps and finding better resources...")
        
        gap_gen = detect_gaps_and_patch(manifest, evidence_packs, kernel)
        
        try:
            while True:
                event = next(gap_gen)
                if event.get("type") == "log":
                    print(event.get("message", ""), flush=True)
                if event.get("type") == "progress":
                    event["percent"] = 27 + int(event["percent"] * 0.13)
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
        
        yield _progress("Phase A2 complete", 40)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE A3: CONTENT FETCHING (Now fetch ALL URLs including patched ones)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase A3: Fetching Document Content...", 42)
        yield _log("Reading actual document content from URLs...")
        
        fetch_gen = fetch_content_for_evidence_packs(evidence_packs, kernel, max_per_subdomain=2)
        
        try:
            while True:
                event = next(fetch_gen)
                if event.get("type") == "log":
                    print(event.get("message", ""), flush=True)
                if event.get("type") == "progress":
                    # Scale to 42-55%
                    event["percent"] = 42 + int(event["percent"] * 0.13)
                yield event
        except StopIteration as e:
            if e.value:
                evidence_packs = e.value
        
        # Count how many have fetched content
        fetched_count = sum(1 for p in evidence_packs if has_fetched_content(p))
        yield _log(f"Fetched content for {fetched_count}/{len(evidence_packs)} subdomains")
        
        # Save updated evidence with content
        if evidence_packs:
            save_evidence_packs(evidence_packs, data_dir)
        
        yield _progress("Phase A3 complete", 55)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE B: STEP BUILDER (Uses fetched content!)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase B: Building Steps...", 57)
        yield _log("Converting evidence to daily learning steps (with real content!)...")
        
        # Run step builder
        # NOTE: build_steps_from_evidence expects (evidence_packs, quest_title, manifest, llm_client)
        step_gen = build_steps_from_evidence(evidence_packs, quest_title, manifest, llm_client)
        
        try:
            while True:
                event = next(step_gen)
                if event.get("type") == "log":
                    print(event.get("message", ""), flush=True)
                if event.get("type") == "progress":
                    event["percent"] = 57 + int(event["percent"] * 0.18)
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
            if gap_report:
                gap_report.unresolved_gaps.extend(coverage_gaps)
                save_gap_report(gap_report, data_dir)
        
        yield _progress("Phase B complete", 75)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE C: PLAN REFINEMENT (GPT-5.1)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase C: Refining Plan...", 80)
        yield _log("Refining with GPT-5.1 (sequencing, day numbers)...")
        
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
                if event.get("type") == "log":
                    print(event.get("message", ""), flush=True)
                if event.get("type") == "progress":
                    event["percent"] = 80 + int(event["percent"] * 0.15)
                yield event
        except StopIteration as e:
            final_plan = e.value
        
        if not final_plan:
            yield _log("Warning: Using raw steps without refinement")
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
        if hasattr(final_plan, 'coverage_summary') and final_plan.coverage_summary:
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
    """Non-streaming version for backwards compatibility."""
    result = []
    
    for event in generate_lesson_plan_streaming(
        domains, quest_id, quest_title, kernel, user_constraints
    ):
        if event.get("type") == "steps":
            result = event.get("steps", [])
    
    return result


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Main API
    "generate_lesson_plan",
    "generate_lesson_plan_streaming",
    # Schemas
    "LessonStep",
    "LessonPlan", 
    "EvidencePack",
    "EvidenceResource",
    "LessonManifest",
    "GapReport",
    "Gap",
]
