# kernel/lesson_engine/plan_refiner.py
"""
v2.0.0 — Lesson Engine: Plan Refiner (Phase C)

Uses GPT-5.1 to sequence and pace lesson steps without inventing content.

v2.0 Changes:
- Can add warning header if gaps remain unresolved
- Coverage summary in final plan
- Strict enforcement: cannot add resources or steps

Critical Rules:
- CANNOT add new resources or URLs
- CANNOT invent new steps
- CAN ONLY reorder, balance, format, assign day numbers
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .schemas import (
    EvidencePack,
    LessonPlan,
    LessonStep,
    GapReport,
    LessonManifest,
    validate_subdomain_coverage,
)


# =============================================================================
# PLAN REFINER
# =============================================================================

def refine_lesson_plan(
    raw_steps: List[LessonStep],
    evidence_packs: List[EvidencePack],
    quest_id: str,
    quest_title: str,
    kernel: Any,
    user_pacing: Optional[Dict] = None,
    gap_report: Optional[GapReport] = None,
    manifest: Optional[LessonManifest] = None,
) -> Generator[Dict[str, Any], None, LessonPlan]:
    """
    Phase C: Refine lesson plan - reorder, pace, format.
    
    CANNOT add resources or invent content. Only organizes existing steps.
    
    Args:
        raw_steps: Steps from Phase B
        evidence_packs: Evidence from Phase A
        quest_id: Quest identifier
        quest_title: Quest title
        kernel: NovaKernel instance
        user_pacing: Optional dict with steps_per_day
        gap_report: Optional gap report from Phase A2
        manifest: Optional manifest for coverage calculation
    
    Yields:
        Progress events
    
    Returns:
        Refined LessonPlan
    """
    yield {"type": "log", "message": f"[PlanRefiner] Refining {len(raw_steps)} steps"}
    
    if not raw_steps:
        yield {"type": "log", "message": "[PlanRefiner] No steps to refine"}
        return _create_empty_plan(quest_id, quest_title, gap_report)
    
    # Get LLM client
    llm_client = getattr(kernel, 'llm_client', None)
    
    refined_steps = raw_steps
    
    if llm_client:
        yield {"type": "log", "message": "[PlanRefiner] Using GPT-5.1 for sequencing..."}
        
        refined_steps = _refine_with_llm(raw_steps, quest_title, llm_client, user_pacing)
        
        if not refined_steps:
            yield {"type": "log", "message": "[PlanRefiner] LLM refinement failed, using original order"}
            refined_steps = raw_steps
    else:
        yield {"type": "log", "message": "[PlanRefiner] No LLM client, using programmatic refinement"}
        refined_steps = _refine_programmatic(raw_steps, user_pacing)
    
    # Calculate totals
    total_minutes = sum(s.estimated_time_minutes for s in refined_steps)
    total_hours = round(total_minutes / 60, 1)
    
    # Calculate recommended days
    steps_per_day = user_pacing.get("steps_per_day", 1) if user_pacing else 1
    recommended_days = len(refined_steps) // steps_per_day
    if len(refined_steps) % steps_per_day > 0:
        recommended_days += 1
    
    # Calculate coverage summary
    coverage_summary = ""
    if manifest:
        coverage = validate_subdomain_coverage(refined_steps, manifest)
        total = coverage["total_expected"]
        covered = coverage["total_covered"]
        
        if covered == total:
            coverage_summary = f"Coverage: {covered}/{total} subdomains covered ✓"
        else:
            missing = coverage["missing"][:3]
            coverage_summary = f"Coverage: {covered}/{total} covered ⚠️ Missing: {', '.join(missing)}"
    
    # Build final plan
    plan = LessonPlan(
        quest_id=quest_id,
        quest_title=quest_title,
        total_steps=len(refined_steps),
        total_hours=total_hours,
        steps=refined_steps,
        evidence_packs=evidence_packs,
        recommended_days=recommended_days,
        steps_per_day=steps_per_day,
        generated_at=datetime.now(timezone.utc).isoformat(),
        engine_version="2.0.0",
        gap_report=gap_report,
        coverage_summary=coverage_summary,
    )
    
    yield {"type": "log", "message": f"[PlanRefiner] Complete: {plan.total_steps} steps, {plan.total_hours}h"}
    
    if coverage_summary:
        yield {"type": "log", "message": f"[PlanRefiner] {coverage_summary}"}
    
    return plan


def _refine_with_llm(
    steps: List[LessonStep],
    quest_title: str,
    llm_client: Any,
    user_pacing: Optional[Dict] = None,
) -> List[LessonStep]:
    """Refine steps using GPT-5.1."""
    
    # Build step summary for LLM
    step_summaries = []
    for s in steps:
        step_summaries.append({
            "id": s.step_id,
            "title": s.title,
            "type": s.step_type,
            "domain": s.domain,
            "subdomain": s.subdomain,
            "subdomains_covered": s.subdomains_covered,
            "minutes": s.estimated_time_minutes,
            "actions_count": len(s.actions),
        })
    
    steps_json = json.dumps(step_summaries, indent=2)
    
    pacing_text = ""
    if user_pacing:
        pacing_text = f"\nUser prefers {user_pacing.get('steps_per_day', 1)} step(s) per day."
    
    system_prompt = """You are a curriculum sequencer. Reorder learning steps for optimal pedagogy.

STRICT RULES - YOU CANNOT BREAK THESE:
1. You CANNOT add new steps
2. You CANNOT remove steps
3. You CANNOT change step content (titles, actions, etc.)
4. You CANNOT invent new resources or URLs
5. You CAN ONLY reorder steps and assign day numbers

SEQUENCING PRINCIPLES:
- Foundational concepts before advanced topics
- INFO steps before APPLY steps
- Related subdomains should be adjacent
- BOSS steps at the end
- Balance workload across days

Output ONLY a JSON array of step IDs in the new order:
["step_1", "step_3", "step_2", "step_4", ...]

JSON array only, no explanation."""

    user_prompt = f"""Reorder these steps for "{quest_title}" for optimal learning:

{steps_json}
{pacing_text}

Return JSON array of step IDs in optimal order:"""

    try:
        result = llm_client.complete_system(
            system=system_prompt,
            user=user_prompt,
            command="lesson-plan-refine",
            think_mode=True,  # Use think mode for better reasoning
        )
        
        response_text = result.get("text", "").strip()
        
        # Parse the ordering
        new_order = _parse_order_json(response_text)
        
        if new_order and len(new_order) == len(steps):
            # Reorder steps
            step_lookup = {s.step_id: s for s in steps}
            reordered = []
            
            for i, step_id in enumerate(new_order, 1):
                if step_id in step_lookup:
                    step = step_lookup[step_id]
                    step.day_number = i
                    reordered.append(step)
            
            if len(reordered) == len(steps):
                return reordered
        
        # Fallback: return original order with day numbers
        return _assign_day_numbers(steps)
        
    except Exception as e:
        print(f"[PlanRefiner] LLM error: {e}", flush=True)
        return _assign_day_numbers(steps)


def _parse_order_json(text: str) -> List[str]:
    """Parse step order from LLM response."""
    try:
        # Strip markdown
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        
        # Find JSON array
        start = text.find("[")
        end = text.rfind("]") + 1
        
        if start == -1 or end == 0:
            return []
        
        data = json.loads(text[start:end])
        
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
        
        return []
        
    except Exception as e:
        print(f"[PlanRefiner] Parse error: {e}", flush=True)
        return []


def _refine_programmatic(
    steps: List[LessonStep],
    user_pacing: Optional[Dict] = None,
) -> List[LessonStep]:
    """Programmatic refinement - sort by domain/type and assign day numbers."""
    
    # Sort steps: INFO first, then APPLY, then RECALL, then BOSS
    type_order = {"INFO": 0, "APPLY": 1, "RECALL": 2, "BOSS": 3}
    
    # Group by domain first
    domain_groups: Dict[str, List[LessonStep]] = {}
    for step in steps:
        domain = step.domain or "General"
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(step)
    
    # Sort within each domain
    for domain in domain_groups:
        domain_groups[domain].sort(key=lambda s: type_order.get(s.step_type, 99))
    
    # Flatten back to list
    sorted_steps = []
    for domain in sorted(domain_groups.keys()):
        sorted_steps.extend(domain_groups[domain])
    
    # Assign day numbers
    return _assign_day_numbers(sorted_steps)


def _assign_day_numbers(steps: List[LessonStep]) -> List[LessonStep]:
    """
    Assign sequential day numbers to steps.
    
    This is Phase C's responsibility - Phase B outputs steps without day numbers.
    This function:
    1. Assigns step.day_number = 1, 2, 3, ...
    2. Prepends "Day X: " to each title
    """
    for i, step in enumerate(steps, 1):
        step.day_number = i
        
        # Remove any existing "Day X:" prefix and add correct one
        title = step.title
        if title.startswith("Day "):
            # Strip existing day prefix: "Day 5: Topic" -> "Topic"
            colon_idx = title.find(":")
            if colon_idx > 0:
                title = title[colon_idx + 1:].strip()
        
        # Add correct day prefix
        step.title = f"Day {i}: {title}"
    
    return steps


def _create_empty_plan(
    quest_id: str,
    quest_title: str,
    gap_report: Optional[GapReport] = None,
) -> LessonPlan:
    """Create an empty plan when no steps are available."""
    return LessonPlan(
        quest_id=quest_id,
        quest_title=quest_title,
        total_steps=0,
        total_hours=0,
        steps=[],
        evidence_packs=[],
        generated_at=datetime.now(timezone.utc).isoformat(),
        gap_report=gap_report,
        coverage_summary="No steps generated",
    )


# =============================================================================
# STORAGE
# =============================================================================

def save_final_plan(plan: LessonPlan, data_dir: Path) -> bool:
    """Save final plan to lesson_plan_final.json."""
    try:
        lessons_dir = data_dir / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = lessons_dir / "lesson_plan_final.json"
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(plan.to_dict(), f, indent=2, ensure_ascii=False)
        
        print(f"[LessonEngine] Saved final plan to {file_path}", flush=True)
        return True
        
    except Exception as e:
        print(f"[LessonEngine] Error saving final plan: {e}", flush=True)
        return False


def load_final_plan(data_dir: Path) -> Optional[LessonPlan]:
    """Load existing final plan if available."""
    try:
        file_path = data_dir / "lessons" / "lesson_plan_final.json"
        
        if not file_path.exists():
            return None
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return LessonPlan.from_dict(data)
        
    except Exception as e:
        print(f"[LessonEngine] Error loading final plan: {e}", flush=True)
        return None
