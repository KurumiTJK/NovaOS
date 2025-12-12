# kernel/lesson_engine/plan_refiner.py
"""
v1.0.0 — Lesson Engine: Plan Refiner (Phase C)

Uses GPT-5.1 for sequencing, pacing, and polish.

GPT-5.1 MUST NOT:
- Invent new learning content
- Add resources not in evidence pack
- Change step scope

GPT-5.1 IS responsible for:
- Grouping steps into days/weeks
- Ensuring workload balance
- Flagging multi-step sequences
- Enforcing consistent formatting
- Making the plan feel cohesive
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .schemas import EvidencePack, LessonStep, LessonPlan, validate_lesson_plan


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
) -> Generator[Dict[str, Any], None, LessonPlan]:
    """
    Phase C: Refine raw steps into a polished lesson plan using GPT-5.1.
    
    Args:
        raw_steps: Steps from Phase B
        evidence_packs: Evidence from Phase A
        quest_id: Quest identifier
        quest_title: Quest title
        kernel: NovaKernel instance
        user_pacing: Optional pacing preferences (steps_per_day, etc.)
    
    Yields:
        Progress events
    
    Returns:
        Finalized LessonPlan
    """
    yield {"type": "log", "message": f"[PlanRefiner] Refining {len(raw_steps)} steps"}
    
    # Default pacing
    steps_per_day = 1
    if user_pacing:
        steps_per_day = user_pacing.get("steps_per_day", 1)
    
    # Get LLM client
    llm_client = getattr(kernel, 'llm_client', None)
    
    refined_steps = raw_steps
    
    if llm_client:
        yield {"type": "progress", "message": "Refining plan with GPT-5.1...", "percent": 50}
        
        # Build steps summary for GPT
        steps_summary = ""
        for step in raw_steps:
            steps_summary += f"- {step.step_id}: {step.title} ({step.step_type}, {step.estimated_time_minutes}min)\n"
            steps_summary += f"  Domain: {step.domain}, Subtopic: {step.subdomain}\n"
            steps_summary += f"  Actions: {len(step.actions)}\n"
        
        system_prompt = """You are a learning plan optimizer for NovaOS.

YOUR JOB (ONLY):
1. Ensure logical sequencing (basics before advanced)
2. Balance workload across days/weeks
3. Identify prerequisite chains
4. Ensure consistent formatting of titles and descriptions
5. Group related steps into modules/weeks

YOU MUST NOT:
- Invent new content or resources
- Change the scope of any step
- Add steps that weren't provided
- Remove any steps
- Modify action counts or time estimates

Return the SAME steps with optional refinements:
- Reordered for better learning flow
- day_number assigned for pacing
- title tweaked for consistency (keeping core content)

Output JSON array with refined steps. Keep all original fields."""

        user_prompt = f"""Refine this lesson plan for "{quest_title}".

Pacing: {steps_per_day} step(s) per day

STEPS TO REFINE (keep all, just optimize order and pacing):
{steps_summary}

Return JSON array of refined steps with same structure.
Each step must have: step_id, step_type, title, estimated_time_minutes, goal, actions, completion_check, domain, subdomain, day_number

JSON array only:"""

        try:
            result = llm_client.complete_system(
                system=system_prompt,
                user=user_prompt,
                command="lesson-plan-refine",
                think_mode=True,  # Use GPT-5.1
            )
            
            response_text = result.get("text", "").strip()
            refined_steps = _parse_refined_steps(response_text, raw_steps)
            
            yield {"type": "log", "message": f"[PlanRefiner] GPT-5.1 refinement complete"}
            
        except Exception as e:
            yield {"type": "log", "message": f"[PlanRefiner] GPT-5.1 error: {e}, using raw steps"}
    
    # Ensure all steps have day numbers
    for i, step in enumerate(refined_steps):
        if step.day_number is None:
            step.day_number = i + 1
    
    # Calculate totals
    total_hours = sum(s.estimated_time_minutes for s in refined_steps) / 60
    recommended_days = len(refined_steps) // steps_per_day
    
    # Build final plan
    plan = LessonPlan(
        quest_id=quest_id,
        quest_title=quest_title,
        total_steps=len(refined_steps),
        total_hours=round(total_hours, 1),
        steps=refined_steps,
        evidence_packs=evidence_packs,
        recommended_days=recommended_days,
        steps_per_day=steps_per_day,
        generated_at=datetime.now(timezone.utc).isoformat(),
        engine_version="1.0.0",
    )
    
    # Validate
    issues = validate_lesson_plan(plan)
    if issues:
        yield {"type": "log", "message": f"[PlanRefiner] Validation issues: {len(issues)}"}
        for issue in issues[:5]:  # Show first 5
            yield {"type": "log", "message": f"  - {issue}"}
    
    yield {"type": "progress", "message": "Plan refinement complete", "percent": 100}
    yield {"type": "log", "message": f"[PlanRefiner] Final plan: {plan.total_steps} steps, {plan.total_hours}h"}
    
    return plan


def _parse_refined_steps(text: str, original_steps: List[LessonStep]) -> List[LessonStep]:
    """Parse refined steps from GPT response, falling back to originals if needed."""
    try:
        # Strip markdown
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        
        start = text.find("[")
        end = text.rfind("]") + 1
        
        if start == -1 or end == 0:
            return original_steps
        
        data = json.loads(text[start:end])
        
        if not isinstance(data, list):
            return original_steps
        
        # Build map of original steps
        original_map = {s.step_id: s for s in original_steps}
        
        refined = []
        for item in data:
            if not isinstance(item, dict):
                continue
            
            step_id = item.get("step_id", item.get("id", ""))
            
            # Get original step as base
            if step_id in original_map:
                base = original_map[step_id]
                
                # Update only allowed fields
                refined_step = LessonStep(
                    step_id=base.step_id,
                    step_type=base.step_type,  # Don't change type
                    title=item.get("title", base.title),  # Allow title tweaks
                    estimated_time_minutes=base.estimated_time_minutes,  # Don't change time
                    goal=item.get("goal", base.goal),  # Allow minor goal tweaks
                    actions=base.actions,  # Don't change actions
                    completion_check=base.completion_check,  # Don't change
                    resource_refs=base.resource_refs,
                    domain=base.domain,
                    subdomain=base.subdomain,
                    subtopics=base.subtopics,
                    day_number=item.get("day_number", base.day_number),  # Allow reordering
                )
                refined.append(refined_step)
            else:
                # New step not in original - skip it (GPT shouldn't add)
                print(f"[PlanRefiner] Ignoring unknown step_id: {step_id}", flush=True)
        
        # If we lost too many steps, return originals
        if len(refined) < len(original_steps) * 0.8:
            print(f"[PlanRefiner] Too many steps lost, using originals", flush=True)
            return original_steps
        
        # Sort by day_number
        refined.sort(key=lambda s: s.day_number or 999)
        
        return refined
        
    except Exception as e:
        print(f"[PlanRefiner] Parse error: {e}", flush=True)
        return original_steps


# =============================================================================
# STORAGE
# =============================================================================

def save_final_plan(plan: LessonPlan, data_dir: Path) -> bool:
    """Save final lesson plan to lesson_plan_final.json."""
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
