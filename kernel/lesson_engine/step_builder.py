# kernel/lesson_engine/step_builder.py
"""
v1.0.0 — Lesson Engine: Step Builder (Phase B)

Converts evidence packs into atomic learning steps.
Uses Gemini 2.5 Pro to create properly-sized steps.

Critical Rules:
- Each step MUST be 60-120 minutes
- Each step MUST have concrete actions
- Each step MUST have a completion check
- Large topics MUST be split into multiple steps
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .schemas import EvidencePack, EvidenceResource, LessonStep


# =============================================================================
# STEP BUILDER
# =============================================================================

def build_steps_from_evidence(
    evidence_packs: List[EvidencePack],
    quest_title: str,
    kernel: Any,
) -> Generator[Dict[str, Any], None, List[LessonStep]]:
    """
    Phase B: Convert evidence packs into atomic learning steps using Gemini 2.5 Pro.
    
    Args:
        evidence_packs: List of evidence packs from Phase A
        quest_title: Title of the quest for context
        kernel: NovaKernel instance
    
    Yields:
        Progress events
    
    Returns:
        List of LessonStep objects
    """
    yield {"type": "log", "message": f"[StepBuilder] Building steps from {len(evidence_packs)} evidence packs"}
    
    all_steps = []
    step_counter = 1
    
    total_packs = len(evidence_packs)
    
    for i, pack in enumerate(evidence_packs):
        percent = int(((i + 1) / total_packs) * 100)
        yield {
            "type": "progress",
            "message": f"Building steps: {pack.subdomain}",
            "percent": percent,
        }
        
        # Build steps for this evidence pack
        steps = _build_steps_for_pack(pack, quest_title, step_counter, kernel)
        
        for step in steps:
            yield {"type": "log", "message": f"[StepBuilder]   Step {step.step_id}: {step.title} ({step.estimated_time_minutes} min)"}
        
        all_steps.extend(steps)
        step_counter += len(steps)
    
    yield {"type": "log", "message": f"[StepBuilder] Complete: {len(all_steps)} steps built"}
    
    return all_steps


def _build_steps_for_pack(
    pack: EvidencePack,
    quest_title: str,
    start_step_num: int,
    kernel: Any,
) -> List[LessonStep]:
    """Build steps for a single evidence pack using Gemini 2.5 Pro."""
    
    # Calculate total resource time
    total_hours = sum(r.estimated_hours for r in pack.resources)
    
    # Determine how many steps we need (each step 60-120 min = 1-2 hours)
    target_minutes_per_step = 90  # Sweet spot
    total_minutes = total_hours * 60
    num_steps = max(1, int(total_minutes / target_minutes_per_step + 0.5))
    
    # Cap steps per pack to avoid explosion
    num_steps = min(num_steps, 5)
    
    # Try to use Gemini 2.5 Pro
    try:
        import google.generativeai as genai
        
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            print(f"[StepBuilder] No GEMINI_API_KEY, using programmatic fallback", flush=True)
            return _build_steps_programmatic(pack, start_step_num, num_steps)
        
        genai.configure(api_key=api_key)
        
    except ImportError:
        print(f"[StepBuilder] Gemini SDK not available, using programmatic fallback", flush=True)
        return _build_steps_programmatic(pack, start_step_num, num_steps)
    
    # Build resource summary for Gemini
    resource_summary = ""
    for r in pack.resources:
        resource_summary += f"- {r.title} ({r.provider}, {r.estimated_hours}h, {r.difficulty})\n"
        resource_summary += f"  URL: {r.url}\n"
        if r.description:
            resource_summary += f"  Description: {r.description[:100]}\n"
    
    system_prompt = f"""You are a micro-learning step designer. Convert resources into atomic learning steps.

HARD CONSTRAINTS (MUST FOLLOW):
1. Each step = 60-120 minutes (NO EXCEPTIONS)
2. Each step has 3-5 CONCRETE actions (not vague like "learn about X")
3. Each action = 15-25 minutes, SPECIFIC and COMPLETABLE
4. Each step has a completion check: "You're done when..."
5. If a resource is > 2 hours, SPLIT it into multiple steps

STEP TYPES:
- INFO: Reading, watching, studying concepts
- APPLY: Hands-on labs, building, configuring, testing
- RECALL: Flashcards, quizzes, summarizing from memory
- BOSS: Capstone challenge combining multiple subtopics

ACTIONS MUST BE SPECIFIC STRINGS, like:
✓ "Watch the IAM Policies video (20 min) on AWS Skill Builder"
✓ "Create a custom IAM policy that allows S3 read-only access"
✓ "Write a 1-paragraph summary of policy evaluation logic"

NOT VAGUE like:
✗ "Learn about IAM policies"
✗ "Understand how policies work"
✗ "Study the documentation"

IMPORTANT: Actions must be plain strings, NOT objects/dicts.

Output ONLY JSON array. No markdown."""

    user_prompt = f"""Create {num_steps} learning step(s) for "{pack.subdomain}" (part of {quest_title}).

RESOURCES TO USE:
{resource_summary}

Generate a JSON array with plain string actions:
[
  {{
    "step_type": "INFO",
    "title": "Day X: Specific Topic Focus",
    "estimated_time_minutes": 90,
    "goal": "What you will understand/accomplish",
    "actions": [
      "Specific 15-25 min task with resource reference (20 min)",
      "Another specific task (25 min)",
      "Practice or apply task (25 min)"
    ],
    "completion_check": "You're done when you can explain/do X",
    "resource_refs": ["url1", "url2"]
  }}
]

JSON array only:"""

    try:
        print(f"[StepBuilder] Calling Gemini 2.5 Pro for {pack.subdomain}...", flush=True)
        
        # Call Gemini 2.5 Pro
        model = genai.GenerativeModel(
            model_name="gemini-2.5-pro",
            system_instruction=system_prompt,
        )
        
        response = model.generate_content(
            user_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=2000,
            ),
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
        
        print(f"[StepBuilder] Gemini response: {len(response_text)} chars", flush=True)
        
        steps = _parse_steps_json(response_text, pack, start_step_num)
        
        if steps:
            return steps
        
        print(f"[StepBuilder] Failed to parse Gemini response, using fallback", flush=True)
        
    except Exception as e:
        print(f"[StepBuilder] Gemini error for {pack.subdomain}: {e}", flush=True)
    
    # Fallback to programmatic
    return _build_steps_programmatic(pack, start_step_num, num_steps)


def _parse_steps_json(text: str, pack: EvidencePack, start_num: int) -> List[LessonStep]:
    """Parse steps from LLM response."""
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
        
        steps = []
        step_num = start_num
        
        for item in data:
            if not isinstance(item, dict):
                continue
            
            # Validate and fix time
            time_mins = int(item.get("estimated_time_minutes", 90))
            if time_mins < 60:
                time_mins = 60
            if time_mins > 120:
                time_mins = 120
            
            # Get actions - handle both string and dict formats from Gemini
            raw_actions = item.get("actions", [])
            if not isinstance(raw_actions, list):
                raw_actions = []
            
            actions = []
            for a in raw_actions:
                if not a:
                    continue
                if isinstance(a, dict):
                    # Gemini sometimes returns {"description": "...", "estimated_time_minutes": N}
                    desc = a.get("description", a.get("action", ""))
                    time_mins_action = a.get("estimated_time_minutes", a.get("time"))
                    if desc:
                        if time_mins_action:
                            actions.append(f"{desc} ({time_mins_action} min)")
                        else:
                            actions.append(desc)
                else:
                    actions.append(str(a))
            
            # Ensure minimum actions
            if len(actions) < 2:
                actions.append("Review and take notes on key concepts")
                actions.append("Test your understanding with a quick self-quiz")
            
            step = LessonStep(
                step_id=f"step_{step_num}",
                step_type=item.get("step_type", "INFO").upper(),
                title=item.get("title", f"Step {step_num}: {pack.subdomain}"),
                estimated_time_minutes=time_mins,
                goal=item.get("goal", ""),
                actions=actions[:5],  # Max 5 actions
                completion_check=item.get("completion_check", "You can explain the key concepts"),
                resource_refs=item.get("resource_refs", []),
                domain=pack.domain,
                subdomain=pack.subdomain,
                subtopics=[pack.subdomain],
                day_number=step_num,
            )
            
            steps.append(step)
            step_num += 1
        
        return steps
        
    except json.JSONDecodeError as e:
        print(f"[StepBuilder] JSON parse error: {e}", flush=True)
        return []
    except Exception as e:
        print(f"[StepBuilder] Parse error: {e}", flush=True)
        return []


def _build_steps_programmatic(
    pack: EvidencePack,
    start_num: int,
    num_steps: int,
) -> List[LessonStep]:
    """Programmatic fallback for step building."""
    steps = []
    
    # Distribute resources across steps
    resources_per_step = max(1, len(pack.resources) // num_steps)
    
    for i in range(num_steps):
        step_num = start_num + i
        
        # Determine step type
        if i == num_steps - 1 and num_steps > 2:
            step_type = "BOSS"
        elif i % 3 == 1:
            step_type = "APPLY"
        elif i % 3 == 2:
            step_type = "RECALL"
        else:
            step_type = "INFO"
        
        # Get resources for this step
        start_idx = i * resources_per_step
        end_idx = min(start_idx + resources_per_step, len(pack.resources))
        step_resources = pack.resources[start_idx:end_idx] if pack.resources else []
        
        # Build actions from resources
        actions = []
        for r in step_resources:
            if r.type == "video":
                actions.append(f"Watch: {r.title} ({r.provider})")
            elif r.type == "lab":
                actions.append(f"Complete lab: {r.title}")
            elif r.type == "course":
                actions.append(f"Work through: {r.title} ({r.estimated_hours}h)")
            else:
                actions.append(f"Study: {r.title} ({r.provider})")
        
        # Add generic actions if needed
        if len(actions) < 3:
            actions.append(f"Take notes on key concepts from {pack.subdomain}")
            actions.append("Create a summary of what you learned")
        
        step = LessonStep(
            step_id=f"step_{step_num}",
            step_type=step_type,
            title=f"Day {step_num}: {pack.subdomain}" + (" (Boss)" if step_type == "BOSS" else ""),
            estimated_time_minutes=90,
            goal=f"Understand and practice {pack.subdomain} concepts",
            actions=actions[:5],
            completion_check=f"You can explain the key concepts of {pack.subdomain}",
            resource_refs=[r.url for r in step_resources if r.url],
            domain=pack.domain,
            subdomain=pack.subdomain,
            subtopics=[pack.subdomain],
            day_number=step_num,
        )
        
        steps.append(step)
    
    return steps


# =============================================================================
# STORAGE
# =============================================================================

def save_raw_steps(steps: List[LessonStep], data_dir: Path) -> bool:
    """Save raw steps to lesson_steps_raw.json."""
    try:
        lessons_dir = data_dir / "lessons"
        lessons_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = lessons_dir / "lesson_steps_raw.json"
        
        data = {
            "version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "steps": [step.to_dict() for step in steps],
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"[LessonEngine] Saved {len(steps)} raw steps to {file_path}", flush=True)
        return True
        
    except Exception as e:
        print(f"[LessonEngine] Error saving raw steps: {e}", flush=True)
        return False


def load_raw_steps(data_dir: Path) -> List[LessonStep]:
    """Load existing raw steps if available."""
    try:
        file_path = data_dir / "lessons" / "lesson_steps_raw.json"
        
        if not file_path.exists():
            return []
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        steps = [
            LessonStep.from_dict(s)
            for s in data.get("steps", [])
        ]
        
        return steps
        
    except Exception as e:
        print(f"[LessonEngine] Error loading raw steps: {e}", flush=True)
        return []
