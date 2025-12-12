# kernel/quest_compose_wizard.py
"""
v0.8.3 — Interactive Quest Composer Wizard

A multi-step interactive wizard for creating new quests.
Guides the user through:
1. Quest metadata (title, category, difficulty, skill_tree_path)
2. Learning objectives
3. Step definitions (info, recall, apply, reflect, boss)
4. Validation/completion criteria
5. Tags
6. Preview and confirmation

The wizard maintains session state and can be pre-filled with arguments.

Usage:
    #quest-compose                           → Start interactive wizard
    #quest-compose title="My Quest"          → Pre-fill title, ask for rest
    #quest-compose mode=noninteractive ...   → Create immediately if all fields present
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

from .command_types import CommandResponse

# Gemini helper for quest generation (try Gemini first, fall back to GPT)
try:
    from .gemini_helper import (
        gemini_generate_quest_steps,
        gemini_extract_domains,
        is_gemini_available,
    )
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False
    def gemini_generate_quest_steps(*args, **kwargs): return None
    def gemini_extract_domains(*args, **kwargs): return None
    def is_gemini_available(): return False


# v1.0.0: Lesson Engine for retrieval-backed step generation
_HAS_LESSON_ENGINE = False
try:
    from kernel.lesson_engine import generate_lesson_plan_streaming
    _HAS_LESSON_ENGINE = True
    print("[QuestCompose] Lesson Engine loaded successfully", flush=True)
except ImportError as e:
    print(f"[QuestCompose] Lesson Engine not available: {e}", flush=True)


# =============================================================================
# WIZARD SESSION STATE
# =============================================================================

@dataclass
class QuestComposeSession:
    """
    State for an active quest-compose wizard session.
    
    Stages:
    - metadata: Collecting title, category, difficulty, skill_tree_path
    - objectives: Collecting learning objectives
    - domain_review: Reviewing extracted domains (NEW - human-in-the-loop)
    - steps: Collecting step definitions
    - validation: Collecting completion criteria
    - tags: Collecting tags
    - confirm: Showing preview, waiting for confirmation
    - edit: User chose to edit a field
    """
    stage: str = "metadata"
    substage: str = "title"  # For multi-part stages like metadata
    
    # Draft quest data
    draft: Dict[str, Any] = field(default_factory=lambda: {
        "id": None,
        "title": None,
        "category": None,
        "difficulty": None,
        "skill_tree_path": None,
        "objectives": [],
        "steps": [],
        "validation": [],
        "tags": [],
        "estimated_minutes": 15,
        "description": None,
        "subtitle": None,
        # NEW: Domain-related fields
        "domains": [],  # Confirmed domains for generation
        "raw_text": None,  # Original pasted text
    })
    
    # For edit mode
    edit_field: Optional[str] = None
    
    # NEW: Domain review state
    candidate_domains: List[Dict[str, Any]] = field(default_factory=list)
    domains_confirmed: bool = False
    awaiting_manual_domains: bool = False  # True when user typed "manual"
    
    def is_metadata_complete(self) -> bool:
        """Check if all required metadata is collected."""
        d = self.draft
        return all([
            d.get("title"),
            d.get("category"),
            # difficulty is now auto-calculated, not required
        ])


# Global session storage (per session_id)
_compose_sessions: Dict[str, QuestComposeSession] = {}


def get_compose_session(session_id: str) -> Optional[QuestComposeSession]:
    """Get active compose session for a user session."""
    return _compose_sessions.get(session_id)


def set_compose_session(session_id: str, session: QuestComposeSession) -> None:
    """Set compose session for a user session."""
    _compose_sessions[session_id] = session


def clear_compose_session(session_id: str) -> None:
    """Clear compose session for a user session."""
    _compose_sessions.pop(session_id, None)


def has_active_compose_session(session_id: str) -> bool:
    """Check if a compose wizard is active for this session."""
    return session_id in _compose_sessions


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _base_response(
    cmd_name: str,
    summary: str,
    extra: Dict[str, Any] | None = None,
) -> CommandResponse:
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=extra or {},
        type=cmd_name,
    )


def _error_response(
    cmd_name: str,
    message: str,
    error_code: str = "ERROR",
) -> CommandResponse:
    return CommandResponse(
        ok=False,
        command=cmd_name,
        summary=message,
        error_code=error_code,
        error_message=message,
        type=cmd_name,
    )


def _generate_quest_id(title: str, existing_ids: List[str]) -> str:
    """
    Generate a unique quest ID from the title.
    
    Converts "JWT Basics – Intro Quest" to "jwt_basics_intro_quest"
    and ensures uniqueness.
    """
    # Normalize title to snake_case
    # Remove special characters, convert to lowercase
    normalized = re.sub(r'[^\w\s]', '', title.lower())
    # Replace spaces with underscores
    normalized = re.sub(r'\s+', '_', normalized.strip())
    # Truncate if too long
    if len(normalized) > 40:
        normalized = normalized[:40].rstrip('_')
    
    # Ensure uniqueness
    base_id = normalized
    counter = 1
    while normalized in existing_ids:
        normalized = f"{base_id}_{counter}"
        counter += 1
    
    return normalized or f"quest_{uuid.uuid4().hex[:8]}"


def _parse_steps_input(text: str) -> List[Dict[str, Any]]:
    """
    Parse step definitions from user input.
    
    Supports formats like:
    - "info: Read the JWT intro notes"
    - "recall: Explain what a JWT is"
    - "apply: Decode a sample JWT"
    
    Returns list of step dicts with type, title/prompt.
    """
    steps = []
    lines = text.strip().split('\n')
    
    valid_types = {"info", "recall", "apply", "reflect", "boss", "action", "transfer", "mini_boss"}
    step_counter = 1
    
    for line in lines:
        line = line.strip()
        if not line or line.lower() == "done":
            continue
        
        # Try to parse "type: description" format
        match = re.match(r'^(\w+)\s*[:–-]\s*(.+)$', line, re.IGNORECASE)
        if match:
            step_type = match.group(1).lower()
            description = match.group(2).strip()
            
            # Validate step type
            if step_type not in valid_types:
                step_type = "info"  # Default to info for unrecognized types
            
            steps.append({
                "id": f"step_{step_counter}",
                "type": step_type,
                "prompt": description,
                "title": description[:50] + "..." if len(description) > 50 else description,
            })
            step_counter += 1
        else:
            # No type prefix - default to info
            steps.append({
                "id": f"step_{step_counter}",
                "type": "info",
                "prompt": line,
                "title": line[:50] + "..." if len(line) > 50 else line,
            })
            step_counter += 1
    
    return steps


def _parse_list_input(text: str) -> List[str]:
    """
    Parse a list from user input.
    
    Supports:
    - Numbered list: "1. First\n2. Second"
    - Bullet list: "- First\n- Second"
    - Comma separated: "first, second, third"
    - Newline separated: "first\nsecond"
    """
    items = []
    text = text.strip()
    
    # Check for numbered or bullet lists
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Remove list prefixes
        line = re.sub(r'^[\d]+[.)]\s*', '', line)  # "1. " or "1) "
        line = re.sub(r'^[-•*]\s*', '', line)      # "- " or "• " or "* "
        
        if line:
            items.append(line)
    
    # If no newlines found, try comma separation
    if len(items) <= 1 and ',' in text:
        items = [item.strip() for item in text.split(',') if item.strip()]
    
    return items


def _calculate_difficulty(steps: List[Dict[str, Any]], objectives: List[str]) -> int:
    """
    Auto-calculate quest difficulty based on steps and objectives.
    
    Factors:
    - Number of steps (more steps = harder)
    - Step types (boss/apply = harder, info = easier)
    - Prompt complexity (longer prompts = harder)
    - Number of objectives
    
    Returns difficulty 1-5.
    """
    if not steps:
        return 1
    
    score = 0.0
    
    # Factor 1: Number of steps (0-2 points)
    num_steps = len(steps)
    if num_steps <= 3:
        score += 0.5
    elif num_steps <= 5:
        score += 1.0
    elif num_steps <= 7:
        score += 1.5
    else:
        score += 2.0
    
    # Factor 2: Step type complexity (0-2 points)
    type_weights = {
        "info": 0.1,
        "recall": 0.3,
        "reflect": 0.4,
        "apply": 0.6,
        "action": 0.6,
        "transfer": 0.7,
        "mini_boss": 0.8,
        "boss": 1.0,
    }
    type_score = sum(type_weights.get(s.get("type", "info"), 0.3) for s in steps)
    avg_type_score = type_score / len(steps) if steps else 0
    score += avg_type_score * 2  # Scale to 0-2
    
    # Factor 3: Prompt complexity (0-1 point)
    avg_prompt_len = sum(len(s.get("prompt", "")) for s in steps) / len(steps) if steps else 0
    if avg_prompt_len > 300:
        score += 1.0
    elif avg_prompt_len > 150:
        score += 0.6
    elif avg_prompt_len > 75:
        score += 0.3
    
    # Factor 4: Number of objectives (0-0.5 points)
    num_objectives = len(objectives) if objectives else 0
    score += min(num_objectives * 0.15, 0.5)
    
    # Convert score to 1-5 difficulty
    # Score range is roughly 0.5 to 5.5
    difficulty = max(1, min(5, round(score)))
    
    return difficulty


def _get_difficulty_label(difficulty: int) -> str:
    """Get a human-readable label for difficulty level."""
    labels = {
        1: "Beginner",
        2: "Easy", 
        3: "Intermediate",
        4: "Advanced",
        5: "Expert",
    }
    return labels.get(difficulty, "Unknown")


def _get_default_validation(steps: List[Dict[str, Any]]) -> List[str]:
    """Generate default validation criteria based on quest steps."""
    criteria = ["Complete all steps"]
    
    # Check if there's a boss step
    has_boss = any(step.get('type') == 'boss' for step in steps)
    if has_boss:
        criteria.append("Pass boss challenge")
    
    return criteria


def _format_steps_with_actions(steps: List[Dict[str, Any]], verbose: bool = True) -> str:
    """
    Format steps for display, optionally showing actions.
    
    Args:
        steps: List of step dicts with type, title, prompt, actions
        verbose: If True, show full prompt and actions under each step
    
    Returns:
        Formatted string for display (no markdown)
    """
    lines = []
    for i, step in enumerate(steps, 1):
        step_type = step.get('type', 'info')
        title = step.get('title', step.get('prompt', '')[:50])
        
        # Step header with separator
        lines.append("────────────────────────────────────────")
        lines.append(f"{i}. [{step_type.upper()}] {title}")
        lines.append("")
        
        if verbose:
            # Show full prompt
            prompt = step.get('prompt', '')
            if prompt:
                lines.append(prompt)
                lines.append("")
            
            # Show actions
            actions = step.get('actions', [])
            if actions:
                lines.append("Actions:")
                for j, action in enumerate(actions, 1):
                    # Handle both string and dict formats
                    if isinstance(action, dict):
                        desc = action.get('description', action.get('action', str(action)))
                        time_mins = action.get('estimated_time_minutes', action.get('time'))
                        if time_mins:
                            lines.append(f"   {j}. {desc} ({time_mins} min)")
                        else:
                            lines.append(f"   {j}. {desc}")
                    else:
                        lines.append(f"   {j}. {action}")
                lines.append("")
        
        lines.append("")  # Extra blank line between steps
    
    lines.append("────────────────────────────────────────")
    return "\n".join(lines)


def _format_preview(draft: Dict[str, Any]) -> str:
    """Format the draft quest as a preview for the user (no markdown)."""
    # Calculate difficulty if not set
    difficulty = draft.get('difficulty')
    if difficulty is None:
        difficulty = _calculate_difficulty(
            draft.get('steps', []),
            draft.get('objectives', [])
        )
        draft['difficulty'] = difficulty  # Store it
    
    difficulty_label = _get_difficulty_label(difficulty)
    
    lines = [
        "═══ New Quest Draft ═══",
        "",
        f"ID: {draft.get('id') or '(auto-generated)'}",
        f"Title: {draft.get('title')}",
        f"Category: {draft.get('category')}",
        f"Module: {draft.get('module_id') or '(standalone)'}",
        f"Difficulty: {'⭐' * difficulty}{'☆' * (5 - difficulty)} ({difficulty_label})",
    ]
    
    if draft.get('skill_tree_path'):
        lines.append(f"Skill Path: {draft['skill_tree_path']}")
    
    if draft.get('tags'):
        lines.append(f"Tags: [{', '.join(draft['tags'])}]")
    
    lines.append("")
    
    # Note: Objectives hidden from preview but kept in internal data
    
    # Steps (simple list without actions)
    steps = draft.get('steps', [])
    if steps:
        lines.append(f"Steps: ({len(steps)} total)")
        for i, step in enumerate(steps, 1):
            step_type = step.get('type', 'info')
            title = step.get('title') or step.get('prompt', '')[:50]
            lines.append(f"  {i}. [{step_type}] {title}")
        lines.append("")
    
    # Validation (hidden - use defaults)
    
    # XP Rewards
    xp = len(steps) * 5 if steps else 0
    lines.append("Rewards:")
    lines.append(f"  {xp} XP")
    lines.append("")
    
    return "\n".join(lines)


def _build_quest_dict(draft: Dict[str, Any], existing_ids: List[str]) -> Dict[str, Any]:
    """
    Build a complete quest dictionary from the draft.
    
    This conforms to the Quest.from_dict() expected structure.
    """
    # Generate ID if not provided
    quest_id = draft.get('id') or _generate_quest_id(draft['title'], existing_ids)
    
    # Build steps with proper structure
    steps = []
    for i, step_data in enumerate(draft.get('steps', []), 1):
        step = {
            "id": step_data.get('id') or f"step_{i}",
            "type": step_data.get('type', 'info'),
            "prompt": step_data.get('prompt', ''),
            "title": step_data.get('title'),
            "help_text": step_data.get('help_text'),
            "actions": step_data.get('actions', []),  # Include actionable sub-steps
            "difficulty": step_data.get('difficulty', 1),
            "validation": step_data.get('validation'),
            "passing_threshold": 0.7,
        }
        steps.append(step)
    
    # Calculate difficulty if not set
    difficulty = draft.get('difficulty')
    if difficulty is None:
        difficulty = _calculate_difficulty(
            draft.get('steps', []),
            draft.get('objectives', [])
        )
    
    # Build the quest structure
    quest_dict = {
        "id": quest_id,
        "title": draft['title'],
        "subtitle": draft.get('subtitle'),
        "description": draft.get('description') or ". ".join(draft.get('objectives', [])),
        "category": draft.get('category', 'general'),
        "module_id": draft.get('module_id') or draft.get('category', 'general'),
        "skill_tree_path": draft.get('skill_tree_path') or f"{draft.get('category', 'general')}.{quest_id}",
        "difficulty": difficulty,
        "estimated_minutes": draft.get('estimated_minutes', 15),
        "tags": draft.get('tags', []),
        "steps": steps,
        "rewards": {
            "xp": len(steps) * 5,  # 5 XP per step base
            "shortcuts": [],
            "visual_unlock": None,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    return quest_dict


# =============================================================================
# WIZARD PROMPTS BY STAGE
# =============================================================================

STAGE_PROMPTS = {
    "metadata_title": (
        "╔══ Quest Composer ══╗\n"
        "\n"
        "Let's create a new quest!\n"
        "\n"
        "—— Step 1/4: Quest Metadata ——\n"
        "\n"
        "What's the quest title?\n"
        "\n"
        "Type cancel at any time to exit."
    ),
    "metadata_category": (
        "—— Step 1/4: Quest Metadata ——\n"
        "\n"
        "Category?\n"
        "\n"
        "This groups your quest with similar content for filtering and organization.\n"
        "\n"
        "Common categories: cyber, finance, meta, learning, personal"
    ),
    "metadata_module": (
        "—— Step 1/4: Quest Metadata ——\n"
        "\n"
        "Module (required)\n"
        "\n"
        "Which module should this quest belong to?\n"
        "\n"
        "{module_list}\n"
        "\n"
        "Type a module name:"
    ),
    "objectives": (
        "—— Step 2/4: Learning Objectives ——\n"
        "\n"
        "What should the learner accomplish?\n"
        "\n"
        "List 1-3 objectives that define success for this quest.\n"
        "\n"
        "These will be used to generate the quest steps and domains."
    ),
    "steps": (
        "—— Step 3/4: Quest Steps ——\n"
        "\n"
        "How would you like to define the steps?\n"
        "\n"
        "generate — Auto-generate steps based on your objectives (recommended)\n"
        "manual — Define steps yourself"
    ),
    "steps_manual": (
        "—— Step 3/4: Quest Steps ——\n"
        "\n"
        "Define steps manually.\n"
        "\n"
        "For each step, specify: type: description\n"
        "\n"
        "Step types:\n"
        "  info – Information/reading\n"
        "  recall – Knowledge check\n"
        "  apply – Hands-on practice\n"
        "  reflect – Reflection prompt\n"
        "  boss – Final challenge\n"
        "\n"
        "Type your steps (one per line), then type done."
    ),
    "steps_generating": (
        "—— Step 3/4: Quest Steps ——\n"
        "\n"
        "Generating quest steps...\n"
        "\n"
        "Creating steps based on your objectives. One moment..."
    ),
    "validation": (
        "—— Step 4/4: Final Details ——\n"
        "\n"
        "Completion criteria?\n"
        "\n"
        "How do we know the quest is complete? List 1-3 criteria.\n"
        "\n"
        "Type skip for default criteria."
    ),
    "tags": (
        "—— Step 4/4: Final Details ——\n"
        "\n"
        "Tags? (optional)\n"
        "\n"
        "Add tags for organization (comma-separated).\n"
        "\n"
        "Type skip to use default tags."
    ),
    # Domain Review prompts
    "domain_review": (
        "—— Step 2/4: Domain Review ——\n"
        "\n"
        "I parsed the following domains from your content:\n"
        "\n"
        "{domain_list}\n"
        "\n"
        "accept — Use these domains and generate quest steps\n"
        "regen — Re-extract domains from the same text\n"
        "manual — Type your own domain list"
    ),
    "domain_manual_input": (
        "—— Step 2/4: Domain Review ——\n"
        "\n"
        "Type your domains, one per line.\n"
        "\n"
        "For subtopics, use parentheses: Topic (sub1, sub2, sub3)\n"
        "\n"
        "Type your domains, then type done."
    ),
    "confirm": (
        "{preview}\n"
        "\n"
        "═══════════════════════\n"
        "\n"
        "Does this look good?\n"
        "\n"
        "confirm — Save this quest\n"
        "edit — Modify a field\n"
        "cancel — Discard"
    ),
    "edit_select": (
        "—— Edit Quest ——\n"
        "\n"
        "Which field would you like to edit?\n"
        "\n"
        "title, category, difficulty, skill_path, objectives, steps, validation, tags\n"
        "\n"
        "Type the field name."
    ),
}


# =============================================================================
# MAIN WIZARD HANDLER
# =============================================================================

def handle_quest_compose_wizard(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: Any,
    meta: Dict[str, Any],
) -> CommandResponse:
    """
    Main handler for #quest-compose with interactive wizard support.
    
    Modes:
    1. Interactive wizard (default): Guide user through all fields
    2. Pre-filled: Accept args to skip some wizard steps
    3. Non-interactive: Create immediately if all required fields present
    
    Usage:
        #quest-compose                                    → Start wizard
        #quest-compose title="My Quest" category=cyber    → Pre-fill some fields
        #quest-compose mode=noninteractive title="..." ...→ Direct creation
    """
    engine = kernel.quest_engine
    
    # Parse arguments
    if not isinstance(args, dict):
        args = {}
    
    # Get raw user input for wizard continuation
    user_input = args.get("full_input", "") or args.get("raw_text", "") or ""
    if context:
        user_input = user_input or context.get("raw_text", "") or ""
    user_input = user_input.strip()
    
    # Check for cancel
    if user_input.lower() == "cancel":
        clear_compose_session(session_id)
        return _base_response(
            cmd_name,
            "Quest composition cancelled.",
            {"wizard_active": False}
        )
    
    # Check for non-interactive mode
    mode = args.get("mode", "interactive")
    if mode == "noninteractive":
        return _handle_noninteractive(cmd_name, args, engine)
    
    # Check for existing wizard session
    session = get_compose_session(session_id)
    
    if session:
        # Continue existing wizard
        return _process_wizard_input(cmd_name, session, user_input, session_id, engine)
    
    # ═══════════════════════════════════════════════════════════════════════
    # NEW WIZARD - Check for modules first (REQUIRED)
    # ═══════════════════════════════════════════════════════════════════════
    available_modules = _get_available_modules(kernel)
    if not available_modules:
        return _base_response(
            cmd_name,
            "⚠️ No modules found.\n\n"
            "Quests must belong to a module. Please create a module first:\n\n"
            "  #modules-add\n\n"
            "Then run #quest-compose again.",
            {"wizard_active": False}
        )
    
    # Start new wizard session
    session = QuestComposeSession()
    
    # Pre-fill from arguments
    _prefill_from_args(session, args)
    
    # Determine starting point based on what's already filled
    _advance_to_next_missing(session)
    
    # Save session
    set_compose_session(session_id, session)
    
    # Return first prompt
    return _get_current_prompt(cmd_name, session)


def _prefill_from_args(session: QuestComposeSession, args: Dict[str, Any]) -> None:
    """Pre-fill session draft from provided arguments."""
    draft = session.draft
    
    # Direct mappings
    if args.get("id"):
        draft["id"] = args["id"]
    if args.get("title"):
        draft["title"] = args["title"]
    if args.get("category"):
        draft["category"] = args["category"]
    if args.get("difficulty"):
        try:
            draft["difficulty"] = int(args["difficulty"])
        except (ValueError, TypeError):
            pass
    if args.get("skill_tree_path") or args.get("skill_path"):
        draft["skill_tree_path"] = args.get("skill_tree_path") or args.get("skill_path")
    if args.get("tags"):
        tags_val = args["tags"]
        if isinstance(tags_val, str):
            draft["tags"] = _parse_list_input(tags_val)
        elif isinstance(tags_val, list):
            draft["tags"] = tags_val


def _advance_to_next_missing(session: QuestComposeSession) -> None:
    """Advance session stage to the next field that needs input."""
    draft = session.draft
    
    # Check metadata fields
    if not draft.get("title"):
        session.stage = "metadata"
        session.substage = "title"
        return
    if not draft.get("category"):
        session.stage = "metadata"
        session.substage = "category"
        return
    if draft.get("difficulty") is None:
        session.stage = "metadata"
        session.substage = "difficulty"
        return
    
    # Optional metadata - skill_tree_path can be skipped
    # Move to objectives
    if not draft.get("objectives"):
        session.stage = "objectives"
        session.substage = ""
        return
    
    # Steps
    if not draft.get("steps"):
        session.stage = "steps"
        session.substage = ""
        return
    
    # Validation (optional, can have defaults)
    if not draft.get("validation"):
        session.stage = "validation"
        session.substage = ""
        return
    
    # Tags (optional)
    if not draft.get("tags"):
        session.stage = "tags"
        session.substage = ""
        return
    
    # All fields filled - go to confirm
    session.stage = "confirm"
    session.substage = ""


def _get_current_prompt(cmd_name: str, session: QuestComposeSession, kernel: Any = None) -> CommandResponse:
    """Get the appropriate prompt for the current wizard stage."""
    stage = session.stage
    substage = session.substage
    
    if stage == "metadata":
        prompt_key = f"metadata_{substage}"
        
        # Special handling for module prompt - need to list available modules
        if substage == "module" and kernel:
            module_list = _get_module_list(kernel)
            prompt_template = STAGE_PROMPTS.get(prompt_key, f"Unknown stage: {stage}/{substage}")
            prompt = prompt_template.format(module_list=module_list)
            return _base_response(cmd_name, prompt, {
                "wizard_active": True,
                "stage": stage,
                "substage": substage,
            })
    elif stage == "confirm":
        preview = _format_preview(session.draft)
        prompt = STAGE_PROMPTS["confirm"].format(preview=preview)
        return _base_response(cmd_name, prompt, {
            "wizard_active": True,
            "stage": "confirm",
        })
    elif stage == "edit":
        prompt = STAGE_PROMPTS["edit_select"]
        return _base_response(cmd_name, prompt, {
            "wizard_active": True,
            "stage": "edit",
        })
    # NEW: Domain review stage
    elif stage == "domain_review":
        # Check if waiting for manual input
        if session.awaiting_manual_domains:
            prompt = STAGE_PROMPTS["domain_manual_input"]
        else:
            # Format the domain list for display
            domain_list = _format_domain_list_for_review(session.candidate_domains)
            prompt = STAGE_PROMPTS["domain_review"].format(domain_list=domain_list)
        return _base_response(cmd_name, prompt, {
            "wizard_active": True,
            "stage": "domain_review",
            "candidate_domains": [d.get("name") for d in session.candidate_domains],
        })
    else:
        prompt_key = stage
    
    prompt = STAGE_PROMPTS.get(prompt_key, f"Unknown stage: {stage}/{substage}")
    
    return _base_response(cmd_name, prompt, {
        "wizard_active": True,
        "stage": stage,
        "substage": substage,
    })


def _get_module_list(kernel: Any) -> str:
    """Get a formatted list of available modules from the module store."""
    try:
        modules = _get_available_modules(kernel)
        
        if not modules:
            return "(No modules found)"
        
        # Format nicely (no markdown)
        lines = ["Available modules:"]
        for name in sorted(modules):
            lines.append(f"  - {name}")
        
        return "\n".join(lines)
        
    except Exception as e:
        print(f"[QuestCompose] Error formatting module list: {e}", flush=True)
        return "(Could not load modules)"


def _get_available_modules(kernel: Any) -> List[str]:
    """Get list of available module names from the module store."""
    try:
        # Modules are stored in kernel.module_store, not quest_engine
        module_store = getattr(kernel, 'module_store', None)
        if not module_store:
            print("[QuestCompose] No module_store on kernel", flush=True)
            return []
        
        # Use list_all() method on ModuleStore
        modules = []
        if hasattr(module_store, 'list_all'):
            modules = module_store.list_all()
        elif hasattr(module_store, '_modules'):
            modules = list(module_store._modules.values())
        
        if not modules:
            print("[QuestCompose] No modules found in store", flush=True)
            return []
        
        # Extract module names
        module_names = []
        for m in modules:
            if isinstance(m, str):
                module_names.append(m)
            elif hasattr(m, 'name'):
                module_names.append(m.name)
            elif hasattr(m, 'id'):
                module_names.append(m.id)
        
        print(f"[QuestCompose] Found {len(module_names)} modules: {module_names}", flush=True)
        return module_names
        
    except Exception as e:
        print(f"[QuestCompose] Error getting modules: {e}", flush=True)
        return []


def _process_wizard_input(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
    kernel: Any,
) -> CommandResponse:
    """Process user input for the current wizard stage."""
    stage = session.stage
    substage = session.substage
    draft = session.draft
    
    # Get engine from kernel
    engine = kernel.quest_engine if hasattr(kernel, 'quest_engine') else kernel
    
    # Handle confirm stage
    if stage == "confirm":
        return _handle_confirm_stage(cmd_name, session, user_input, session_id, engine)
    
    # Handle edit stage
    if stage == "edit":
        return _handle_edit_stage(cmd_name, session, user_input, session_id)
    
    # Handle metadata stages (needs kernel for module list)
    if stage == "metadata":
        return _handle_metadata_stage(cmd_name, session, user_input, session_id, kernel)
    
    # Handle objectives stage (needs kernel for domain extraction)
    if stage == "objectives":
        return _handle_objectives_stage(cmd_name, session, user_input, session_id, kernel)
    
    # NEW: Handle domain review stage
    if stage == "domain_review":
        return _handle_domain_review_stage(cmd_name, session, user_input, session_id, kernel)
    
    # Handle steps stage (needs kernel for LLM access)
    if stage == "steps":
        return _handle_steps_stage(cmd_name, session, user_input, session_id, kernel)
    
    # Handle tags stage
    if stage == "tags":
        return _handle_tags_stage(cmd_name, session, user_input, session_id)
    
    # Unknown stage - reset
    clear_compose_session(session_id)
    return _error_response(cmd_name, f"Unknown wizard stage: {stage}", "WIZARD_ERROR")


def _handle_metadata_stage(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
    kernel: Any = None,
) -> CommandResponse:
    """Handle metadata collection stages."""
    substage = session.substage
    draft = session.draft
    
    if substage == "title":
        if not user_input:
            return _base_response(
                cmd_name,
                "Please enter a quest title:",
                {"wizard_active": True, "stage": "metadata", "substage": "title"}
            )
        draft["title"] = user_input
        session.substage = "category"
        set_compose_session(session_id, session)
        return _get_current_prompt(cmd_name, session)
    
    elif substage == "category":
        if not user_input:
            return _base_response(
                cmd_name,
                "Please enter a category:",
                {"wizard_active": True, "stage": "metadata", "substage": "category"}
            )
        draft["category"] = user_input.lower()
        
        # Go to module selection
        session.substage = "module"
        set_compose_session(session_id, session)
        return _get_current_prompt(cmd_name, session, kernel)  # Pass kernel for module list
    
    elif substage == "module":
        # Handle module selection - REQUIRED (no skip)
        if user_input and user_input.lower() not in ("skip", "s", "none", ""):
            # Validate module exists
            available_modules = _get_available_modules(kernel)
            module_lower = user_input.lower()
            matched_module = None
            for m in available_modules:
                if m.lower() == module_lower:
                    matched_module = m
                    break
            
            if matched_module:
                draft["module_id"] = matched_module
            else:
                # Module not found - show error and re-prompt
                module_list = _get_module_list(kernel)
                return _base_response(
                    cmd_name,
                    f"Module '{user_input}' not found.\n\n{module_list}\n\nPlease select a valid module:",
                    {"wizard_active": True, "stage": "metadata", "substage": "module"}
                )
        else:
            # User tried to skip - not allowed
            clear_compose_session(session_id)
            return _base_response(
                cmd_name,
                "⚠️ Module selection is required.\n\n"
                "Quests must belong to a module. Please create one first:\n\n"
                "  #modules-add\n\n"
                "Then run #quest-compose again.",
                {"wizard_active": False}
            )
        
        # Auto-generate skill_tree_path
        draft["skill_tree_path"] = None
        
        # Skip directly to objectives
        session.stage = "objectives"
        session.substage = ""
        set_compose_session(session_id, session)
        return _get_current_prompt(cmd_name, session)
    
    return _error_response(cmd_name, f"Unknown metadata substage: {substage}", "WIZARD_ERROR")


def _handle_objectives_stage(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
    kernel: Any = None,
) -> CommandResponse:
    """Handle objectives collection."""
    if not user_input:
        return _base_response(
            cmd_name,
            "Please enter at least one learning objective:",
            {"wizard_active": True, "stage": "objectives"}
        )
    
    objectives = _parse_list_input(user_input)
    if not objectives:
        return _base_response(
            cmd_name,
            "Please enter at least one learning objective:",
            {"wizard_active": True, "stage": "objectives"}
        )
    
    session.draft["objectives"] = objectives[:5]  # Limit to 5
    
    # Store raw text for domain extraction
    session.draft["raw_text"] = user_input
    
    # NEW: Go to domain review instead of directly to steps
    # Extract domains and show for user confirmation
    session.stage = "domain_review"
    session.substage = ""
    set_compose_session(session_id, session)
    
    # Trigger domain extraction and show review prompt
    return _trigger_domain_extraction(cmd_name, session, session_id, kernel)


def _trigger_domain_extraction(
    cmd_name: str,
    session: QuestComposeSession,
    session_id: str,
    kernel: Any,
) -> CommandResponse:
    """
    Extract domains from objectives using LLM and show for review.
    
    This is Phase 1A - the ONLY domain extraction call.
    User will confirm before generation proceeds.
    """
    print(f"[QuestCompose] Phase 1: Extracting candidate domains...", flush=True)
    
    # Get LLM client from kernel
    llm_client = getattr(kernel, 'llm_client', None)
    if not llm_client:
        print(f"[QuestCompose] No LLM client, using fallback extraction", flush=True)
        # Fall back to structural extraction
        raw_text = session.draft.get("raw_text", "") or "\n".join(session.draft.get("objectives", []))
        session.candidate_domains = _structural_extract_domains(raw_text)
    else:
        # Use LLM semantic extraction (single call)
        raw_text = session.draft.get("raw_text", "") or "\n".join(session.draft.get("objectives", []))
        session.candidate_domains = _extract_domains_for_review(raw_text, llm_client)
    
    print(f"[QuestCompose] LLM domains: {[d.get('name', '?') for d in session.candidate_domains]}", flush=True)
    print(f"[QuestCompose] Domain review pending user confirmation...", flush=True)
    
    set_compose_session(session_id, session)
    return _get_current_prompt(cmd_name, session, kernel)


def _extract_domains_for_review(raw_text: str, llm_client: Any) -> List[Dict[str, Any]]:
    """
    Extract domains using two-pass pipeline.
    
    v4.0: Gemini draft → GPT polish → FINAL
    User only sees final polished result.
    """
    # ═══════════════════════════════════════════════════════════════════════
    # TWO-PASS PIPELINE: Gemini draft → GPT polish
    # ═══════════════════════════════════════════════════════════════════════
    if _HAS_GEMINI:
        print("[QuestCompose] Using two-pass domain extraction...", flush=True)
        domains = gemini_extract_domains(raw_text, llm_client)
        if domains:
            print(f"[QuestCompose] Two-pass extracted {len(domains)} domains", flush=True)
            return domains
        print("[QuestCompose] Two-pass failed, using legacy extraction...", flush=True)
    
    # ═══════════════════════════════════════════════════════════════════════
    # LEGACY FALLBACK (GPT-only if two-pass unavailable)
    # ═══════════════════════════════════════════════════════════════════════
    extract_system = """You are a curriculum architect.
The user will provide a phase description for a learning plan (cyber, cloud, etc.).

Your job is to extract a clean list of domains with optional subtopics.

Rules:
- Treat items like "Networking (routing, VLANs, DNS, segmentation)" as:
  "name": "Networking"
  "subtopics": ["routing", "VLANs", "DNS", "segmentation"]
- Do NOT split subtopics into separate domains.
- Ignore meta text like "Phase A1 — Fundamentals Repair", "Your goal: …", "Outputs: …", "Focus Areas".
- Include only meaningful technical or learning domains.

Output STRICT JSON:
{
  "domains": [
    {
      "name": "string",
      "subtopics": ["optional", "subtopics"]
    }
  ]
}

No comments, no extra fields, no markdown fences."""

    extract_user = f"""Extract learning domains from this phase description:

{raw_text}

JSON only:"""

    try:
        result = llm_client.complete_system(
            system=extract_system,
            user=extract_user,
            command="quest-compose-domain-review",
            think_mode=False,  # Fast extraction
        )
        
        result_text = result.get("text", "").strip()
        domains_raw = _parse_json_resilient(result_text, "domains")
        
        if not domains_raw:
            return []
        
        # Normalize to standard format
        domains = []
        for d in domains_raw:
            domains.append({
                "name": d.get("name", ""),
                "subtopics": d.get("subtopics", []),
            })
        
        return domains
        
    except Exception as e:
        print(f"[QuestCompose] Domain extraction LLM error: {e}", flush=True)
        # Fall back to structural extraction
        return _structural_extract_domains(raw_text)


def _format_domain_list_for_review(domains: List[Dict[str, Any]]) -> str:
    """Format domains for display in the review prompt (no markdown)."""
    if not domains:
        return "(No domains extracted)"
    
    lines = []
    for i, d in enumerate(domains, 1):
        name = d.get("name", "Unknown")
        subtopics = d.get("subtopics", [])
        
        if subtopics:
            subtopics_str = ", ".join(subtopics)
            lines.append(f"{i}. {name} — subtopics: {subtopics_str}")
        else:
            lines.append(f"{i}. {name}")
    
    return "\n".join(lines)


def _handle_domain_review_stage(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
    kernel: Any = None,
) -> CommandResponse:
    """
    Handle domain review stage - user confirms/edits extracted domains.
    
    Options:
    - accept: Use these domains AND auto-generate steps
    - regen: Re-extract from same text
    - manual: User types their own list
    """
    user_input_lower = user_input.lower().strip()
    
    # Check if we're waiting for manual domain input
    if session.awaiting_manual_domains:
        return _handle_manual_domain_input(cmd_name, session, user_input, session_id, kernel)
    
    # Handle accept - confirm domains AND auto-generate steps
    if user_input_lower in ("accept", "yes", "y", "ok", "confirm"):
        # Confirm domains
        session.draft["domains"] = session.candidate_domains
        session.domains_confirmed = True
        
        print(f"[QuestCompose] Domains accepted: {[d.get('name', '?') for d in session.candidate_domains]}", flush=True)
        print(f"[QuestCompose] Auto-generating steps...", flush=True)
        
        # Move to steps stage with "choice" substage so streaming can detect it
        session.stage = "steps"
        session.substage = "choice"
        set_compose_session(session_id, session)
        
        # Return a response indicating generation is about to start
        # The frontend will detect this state and trigger streaming
        return _base_response(
            cmd_name,
            "—— Step 3/4: Quest Steps ——\n\n"
            "Domains confirmed. Generating quest steps...\n\n"
            "Type generate to start, or manual to define steps yourself.",
            {
                "wizard_active": True,
                "stage": "steps",
                "substage": "choice",
                "auto_generate": True,  # Signal to frontend to auto-trigger generation
            }
        )
    
    # Handle regen
    elif user_input_lower in ("regen", "regenerate", "retry", "again"):
        print(f"[QuestCompose] Re-extracting domains...", flush=True)
        
        # Re-extract domains
        return _trigger_domain_extraction(cmd_name, session, session_id, kernel)
    
    # Handle manual
    elif user_input_lower in ("manual", "m", "custom", "edit"):
        session.awaiting_manual_domains = True
        set_compose_session(session_id, session)
        return _get_current_prompt(cmd_name, session, kernel)
    
    # Unknown input - show options again
    else:
        return _base_response(
            cmd_name,
            "Please type accept, regen, or manual.",
            {"wizard_active": True, "stage": "domain_review"}
        )


def _handle_manual_domain_input(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
    kernel: Any = None,
) -> CommandResponse:
    """
    Handle manual domain input from user.
    
    Expects one domain per line, with optional parenthetical subtopics:
    Networking (routing, VLANs, DNS)
    Active Directory (trusts, GPOs)
    """
    # Check for "done" to finish input
    if user_input.lower().strip() == "done":
        if not session.candidate_domains:
            return _base_response(
                cmd_name,
                "No domains entered yet. Please enter at least one domain.",
                {"wizard_active": True, "stage": "domain_review"}
            )
        
        # Show the parsed domains for confirmation
        session.awaiting_manual_domains = False
        set_compose_session(session_id, session)
        
        domain_list = _format_domain_list_for_review(session.candidate_domains)
        return _base_response(
            cmd_name,
            f"Your domains:\n\n{domain_list}\n\n"
            "Type accept to confirm or manual to re-enter.",
            {"wizard_active": True, "stage": "domain_review"}
        )
    
    # Parse domain lines
    domains = []
    lines = user_input.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or line.lower() == "done":
            continue
        
        # Use existing parser for "Topic (a, b, c)" format
        parsed = _parse_domain_with_subtopics(line)
        if parsed and parsed.get("name"):
            domains.append({
                "name": parsed["name"],
                "subtopics": parsed.get("subtopics", []),
            })
    
    if domains:
        session.candidate_domains = domains
        set_compose_session(session_id, session)
        
        return _base_response(
            cmd_name,
            f"Added {len(domains)} domain(s). Enter more or type done.",
            {"wizard_active": True, "stage": "domain_review"}
        )
    else:
        return _base_response(
            cmd_name,
            "Could not parse any domains. Please use format:\n"
            "Domain Name (subtopic1, subtopic2)\n\n"
            "Enter domains or type done.",
            {"wizard_active": True, "stage": "domain_review"}
        )


def _handle_steps_stage(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
    kernel: Any = None,
) -> CommandResponse:
    """Handle step definitions collection with auto-generation option."""
    substage = session.substage
    
    # Initial choice: generate or manual
    if substage == "" or substage == "choice":
        choice = user_input.lower().strip()
        
        if choice in ("generate", "gen", "g", "auto"):
            # Auto-generate steps using LLM
            if kernel is None:
                return _base_response(
                    cmd_name,
                    "Cannot generate steps: kernel not available. Please use manual mode.",
                    {"wizard_active": True, "stage": "steps", "substage": "manual"}
                )
            
            # Generate steps based on objectives
            generation_error = None
            generated_steps = []
            
            try:
                print(f"[QuestCompose] Starting generation for: {session.draft.get('title', 'Untitled')}", flush=True)
                print(f"[QuestCompose] Objectives count: {len(session.draft.get('objectives', []))}", flush=True)
                generated_steps = _generate_steps_with_llm(session.draft, kernel)
                print(f"[QuestCompose] Generation returned {len(generated_steps) if generated_steps else 0} steps", flush=True)
            except Exception as e:
                generation_error = str(e)
                print(f"[QuestCompose] Generation EXCEPTION: {e}", flush=True)
                import traceback
                traceback.print_exc()
            
            if generated_steps:
                session.draft["steps"] = generated_steps
                
                # Show generated steps with actions
                step_list = _format_steps_with_actions(generated_steps, verbose=True)
                
                session.substage = "confirm_generated"
                set_compose_session(session_id, session)
                
                return _base_response(
                    cmd_name,
                    f"Generated {len(generated_steps)} steps:\n\n{step_list}\n"
                    f"Type accept to use these, regenerate to try again, or manual to define your own.",
                    {"wizard_active": True, "stage": "steps", "substage": "confirm_generated"}
                )
            else:
                # Show error details if available
                error_msg = "Could not generate steps."
                if generation_error:
                    error_msg += f"\n\nError: {generation_error}"
                error_msg += "\n\nPlease define them manually.\n\n" + STAGE_PROMPTS["steps_manual"]
                
                return _base_response(
                    cmd_name,
                    error_msg,
                    {"wizard_active": True, "stage": "steps", "substage": "manual"}
                )
        
        elif choice in ("manual", "m", "custom"):
            session.substage = "manual"
            set_compose_session(session_id, session)
            return _base_response(
                cmd_name,
                STAGE_PROMPTS["steps_manual"],
                {"wizard_active": True, "stage": "steps", "substage": "manual"}
            )
        
        else:
            # Default to showing the choice prompt
            return _base_response(
                cmd_name,
                "Please type generate or manual.",
                {"wizard_active": True, "stage": "steps", "substage": "choice"}
            )
    
    # Confirm generated steps
    elif substage == "confirm_generated":
        choice = user_input.lower().strip()
        
        if choice in ("accept", "yes", "y", "ok", "good"):
            # Accept generated steps, set default validation, move to tags
            session.draft["validation"] = _get_default_validation(session.draft.get("steps", []))
            session.stage = "tags"
            session.substage = ""
            set_compose_session(session_id, session)
            return _get_current_prompt(cmd_name, session)
        
        elif choice in ("regenerate", "regen", "again", "retry"):
            # Try generating again
            if kernel:
                generated_steps = _generate_steps_with_llm(session.draft, kernel)
                if generated_steps:
                    session.draft["steps"] = generated_steps
                    step_list = _format_steps_with_actions(generated_steps, verbose=True)
                    set_compose_session(session_id, session)
                    return _base_response(
                        cmd_name,
                        f"Regenerated {len(generated_steps)} steps:\n\n{step_list}\n"
                        f"Type accept to use these, regenerate to try again, or manual to define your own.",
                        {"wizard_active": True, "stage": "steps", "substage": "confirm_generated"}
                    )
            return _base_response(
                cmd_name,
                "Could not regenerate. Type accept to use current steps or manual to define your own.",
                {"wizard_active": True, "stage": "steps", "substage": "confirm_generated"}
            )
        
        elif choice in ("manual", "m", "custom"):
            session.draft["steps"] = []  # Clear generated steps
            session.substage = "manual"
            set_compose_session(session_id, session)
            return _base_response(
                cmd_name,
                STAGE_PROMPTS["steps_manual"],
                {"wizard_active": True, "stage": "steps", "substage": "manual"}
            )
        
        else:
            return _base_response(
                cmd_name,
                "Please type accept, regenerate, or manual.",
                {"wizard_active": True, "stage": "steps", "substage": "confirm_generated"}
            )
    
    # Manual step entry
    elif substage == "manual":
        # Check for "done" signal
        if user_input.lower() == "done":
            if not session.draft.get("steps"):
                return _base_response(
                    cmd_name,
                    "Please define at least one step before typing 'done':",
                    {"wizard_active": True, "stage": "steps", "substage": "manual"}
                )
            # Set default validation and move to tags
            session.draft["validation"] = _get_default_validation(session.draft.get("steps", []))
            session.stage = "tags"
            session.substage = ""
            set_compose_session(session_id, session)
            return _get_current_prompt(cmd_name, session)
        
        if not user_input:
            return _base_response(
                cmd_name,
                "Please define quest steps. Type 'done' when finished:",
                {"wizard_active": True, "stage": "steps", "substage": "manual"}
            )
        
        # Parse steps from input
        steps = _parse_steps_input(user_input)
        
        if steps:
            # Append to existing steps (in case user adds more)
            existing = session.draft.get("steps", [])
            # Re-number step IDs
            for i, step in enumerate(steps, len(existing) + 1):
                step["id"] = f"step_{i}"
            session.draft["steps"] = existing + steps
        
        # Show current steps and ask for more or done
        current_steps = session.draft.get("steps", [])
        step_list = "\n".join([
            f"  {i}. [{s['type']}] {s.get('title', s['prompt'][:30])}"
            for i, s in enumerate(current_steps, 1)
        ])
        
        set_compose_session(session_id, session)
        
        return _base_response(
            cmd_name,
            f"Current steps:\n{step_list}\n\nAdd more steps or type done to continue.",
            {"wizard_active": True, "stage": "steps", "substage": "manual", "step_count": len(current_steps)}
        )
    
    # Unknown substage
    return _base_response(
        cmd_name,
        STAGE_PROMPTS["steps"],
        {"wizard_active": True, "stage": "steps"}
    )


# ═══════════════════════════════════════════════════════════════════════════════
# JSON PARSING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_json_resilient(text: str, list_key: str = None) -> Any:
    """
    Parse JSON from LLM response with multiple fallback strategies.
    
    Handles common LLM issues:
    - Markdown code fences
    - Leading/trailing text
    - Minor syntax errors
    
    Args:
        text: Raw LLM response
        list_key: If provided, extract this key from the parsed object
        
    Returns:
        Parsed JSON (or the value at list_key if provided)
    """
    import re
    
    if not text:
        raise ValueError("Empty response")
    
    # Strategy 1: Try direct parse
    try:
        data = json.loads(text)
        return data.get(list_key, data) if list_key else data
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Remove markdown fences
    cleaned = text
    cleaned = re.sub(r'^```json\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^```\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'```\s*$', '', cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    
    try:
        data = json.loads(cleaned)
        return data.get(list_key, data) if list_key else data
    except json.JSONDecodeError:
        pass
    
    # Strategy 3: Find JSON object/array in text
    # Look for outermost { } or [ ]
    obj_start = cleaned.find('{')
    obj_end = cleaned.rfind('}')
    arr_start = cleaned.find('[')
    arr_end = cleaned.rfind(']')
    
    # Try object first
    if obj_start != -1 and obj_end > obj_start:
        try:
            json_str = cleaned[obj_start:obj_end + 1]
            data = json.loads(json_str)
            return data.get(list_key, data) if list_key else data
        except json.JSONDecodeError:
            pass
    # Try array
    if arr_start != -1 and arr_end > arr_start:
        try:
            json_str = cleaned[arr_start:arr_end + 1]
            data = json.loads(json_str)
            return data
        except json.JSONDecodeError:
            pass
    
    # Strategy 4: Try to fix common issues
    # Remove trailing commas before } or ]
    fixed = re.sub(r',\s*([}\]])', r'\1', cleaned)
    
    try:
        data = json.loads(fixed)
        return data.get(list_key, data) if list_key else data
    except json.JSONDecodeError:
        pass
    
    # Give up
    raise ValueError(f"Could not parse JSON from response: {text[:200]}...")


# ═══════════════════════════════════════════════════════════════════════════════
# DOMAIN NOISE FILTERING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize_domain_name(name: str) -> str:
    """
    Normalize a domain name for comparison and scoring.
    
    - Lowercase
    - Strip whitespace
    - Replace multiple spaces with single space
    - Remove common edge punctuation
    """
    import re
    
    if not name:
        return ""
    
    # Lowercase
    normalized = name.lower()
    
    # Strip surrounding whitespace
    normalized = normalized.strip()
    
    # Replace multiple spaces with single space
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Remove common edge punctuation (but keep internal ones)
    normalized = re.sub(r'^[-—:;.,•*]+\s*', '', normalized)
    normalized = re.sub(r'\s*[-—:;.,•*]+$', '', normalized)
    
    return normalized


def _score_domain_candidate(domain_obj: Dict[str, Any]) -> float:
    """
    Score a domain candidate to determine if it's a real topical domain.
    
    Higher score = more likely to be a real topic
    Lower score = more likely to be meta/noise (phase names, goals, outputs)
    
    Scoring formula:
        score = base (0.5) + source_adj + meta_penalty + topic_boost + genericness_penalty + subtopic_boost
        
    Where:
        - source_adj: +0.15 (bullet) or -0.05 (heading)
        - meta_penalty: -0.2 per match, capped at -0.5 total
        - topic_boost: +0.2 per match, capped at +0.4 total
        - genericness_penalty: -0.15 to -0.4 for abstract phrases without topic hints
        - subtopic_boost: +0.15 if has real subtopics
    
    Returns a float score clamped to [0.0, 1.0]
    """
    import re
    
    name = domain_obj.get("name", "")
    subtopics = domain_obj.get("subtopics", [])
    source = domain_obj.get("source", "").lower()
    
    name_norm = _normalize_domain_name(name)
    words = name_norm.split()
    word_count = len(words)
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1: BASE SCORE
    # ─────────────────────────────────────────────────────────────────────────
    base_score = 0.5
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2: SOURCE-BASED ADJUSTMENT
    # ─────────────────────────────────────────────────────────────────────────
    bullet_like = ("bullet", "bullet_list", "list_item", "numbered_list", "focus_area")
    heading_like = ("heading", "paragraph", "section")
    
    source_adj = 0.0
    if source in bullet_like:
        source_adj = +0.15
    elif source in heading_like:
        source_adj = -0.05
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3: META-KEYWORD PENALTIES (-0.2 each, capped at -0.5 total)
    # ─────────────────────────────────────────────────────────────────────────
    meta_patterns = [
        r'\bphase\b',
        r'\bweek\s*\d',
        r'\bmonth\b',
        r'\d+[-–—]\d+\s*months?',  # "0-6 months", "6-12 months"
        r'\btimeline\b',
        r'\bplan\b',
        r'\byour\s+goal',
        r'\bgoals?\b',
        r'\bobjectives?\b',
        r'\boutputs?\b',
        r'\bsummary\b',
        r'\bintroduction\b',
        r'\boverview\b',
        r'\bprerequisites?\b',
        r'\brequirements?\b',
        r'\bwhat\s+you\s+will\b',
        r'\blearning\s+outcomes?\b',
        r'\brepair\b',  # "Fundamentals Repair" → meta
        r'\boffensive\s+base\b',  # "Offensive Base" → meta
    ]
    
    meta_penalty = 0.0
    for pattern in meta_patterns:
        if re.search(pattern, name_norm):
            meta_penalty -= 0.2
    
    # Cap at -0.5
    meta_penalty = max(meta_penalty, -0.5)
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4: TOPIC-KEYWORD BOOSTS (+0.2 each, capped at +0.4 total)
    # 
    # NOTE: "fundamentals" and "basics" are NOT here - they're too generic
    # and would rescue junk like "Fundamentals Repair". They only help
    # when combined with real topic words (handled by the domain itself).
    # ─────────────────────────────────────────────────────────────────────────
    topic_hints = [
        # Core technical domains
        r'\bnetwork(?:ing)?\b',
        r'\brouting\b',
        r'\bactive\s*directory\b',
        r'\bidentity\b',
        r'\baws\b',
        r'\bazure\b',
        r'\bgcp\b',
        r'\bcloud\b',
        r'\blogging\b',
        r'\bsiem\b',
        r'\bthreat\s+model',  # "threat modeling" specifically
        r'\bsecurity\b',
        # Auth/Identity
        r'\bauth(?:entication|orization)?\b',
        r'\boauth\b',
        r'\bsaml\b',
        r'\boidc\b',
        r'\biam\b',
        r'\brbac\b',
        r'\bmfa\b',
        r'\bjwt\b',
        # Infrastructure
        r'\bvlan\b',
        r'\bdns\b',
        r'\bgpo\b',
        r'\btrust(?:s)?\b',
        r'\bdelegation\b',
        r'\bkubernetes\b',
        r'\bdocker\b',
        r'\bcontainer(?:s)?\b',
        r'\bfirewall\b',
        r'\bvpn\b',
        r'\bmonitoring\b',
        r'\bsentinel\b',
        r'\bcloudtrail\b',
        r'\bdefender\b',
        # Programming
        r'\bpython\b',
        r'\bprogramming\b',
        r'\bapi\b',
        r'\bdatabase\b',
        r'\bsql\b',
        # OS/Platform
        r'\blinux\b',
        r'\bwindows\b',
        r'\bserver(?:s)?\b',
        r'\binfrastructure\b',
        r'\barchitecture\b',
        # Security specific
        r'\bprotocol(?:s)?\b',
        r'\bencryption\b',
        r'\bcrypto(?:graphy)?\b',
        r'\bpki\b',
        r'\bcertificate(?:s)?\b',
        r'\bstride\b',
        r'\battack\s+surface',
    ]
    
    topic_boost = 0.0
    topic_hint_count = 0
    for pattern in topic_hints:
        if re.search(pattern, name_norm):
            topic_boost += 0.2
            topic_hint_count += 1
    
    # Cap at +0.4
    topic_boost = min(topic_boost, 0.4)
    
    has_topic_hint = topic_hint_count > 0
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5: GENERICNESS PENALTY
    # Abstract phrases without topic hints get penalized
    # ─────────────────────────────────────────────────────────────────────────
    
    genericness_penalty = 0.0
    
    if not has_topic_hint:
        # No concrete topic hint found - might be generic/abstract
        
        # Single generic words get strong penalty
        generic_single_words = {
            "overview", "summary", "goals", "goal", "outputs", "output",
            "phase", "intro", "introduction", "objectives", "objective",
            "plan", "plans", "timeline", "schedule", "week", "month",
            "section", "part", "chapter", "module", "unit", "repair",
            "base", "core", "main", "primary", "secondary", "fundamentals",
            "basics", "essentials", "foundations"
        }
        
        if word_count == 1 and name_norm in generic_single_words:
            genericness_penalty = -0.4
        
        # Abstract 2-word phrases from headings/paragraphs
        # "Fundamentals Repair", "Offensive Base" → likely meta
        elif word_count == 2 and source in heading_like:
            genericness_penalty = -0.15
        
        # Very short names are suspicious
        elif len(name_norm) < 3:
            genericness_penalty = -0.3
    
    # Very long names (> 8 words) are often phase descriptions
    length_penalty = 0.0
    if word_count > 12:
        length_penalty = -0.35
    elif word_count > 8:
        length_penalty = -0.15
    
    # ─────────────────────────────────────────────────────────────────────────
    # STEP 6: SUBTOPIC BOOST
    # Only applies when domain has actual subtopics (from parenthetical parsing)
    # e.g., "Networking (routing, VLANs, DNS)" → subtopics = ["routing", "VLANs", "DNS"]
    # ─────────────────────────────────────────────────────────────────────────
    
    subtopic_boost = 0.0
    if isinstance(subtopics, list) and len(subtopics) >= 2:
        subtopic_boost = +0.15
    elif isinstance(subtopics, list) and len(subtopics) == 1:
        subtopic_boost = +0.10
    
    # ─────────────────────────────────────────────────────────────────────────
    # FINAL CALCULATION
    # ─────────────────────────────────────────────────────────────────────────
    
    score = base_score + source_adj + meta_penalty + topic_boost + genericness_penalty + length_penalty + subtopic_boost
    
    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, score))


def _filter_noise_domains(domains: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filter out meta/noise domains, keeping only real topical domains.
    
    Uses heuristic scoring to identify and remove:
    - Phase names ("Phase A1 — Fundamentals Repair")
    - Goal statements ("Your goal: eliminate weak points")
    - Section headers ("Outputs", "Summary")
    - Abstract labels ("Fundamentals Repair", "Offensive Base")
    
    Always preserves at least 1-2 domains to prevent empty results.
    """
    # Explicit threshold constant
    SCORE_THRESHOLD = 0.40
    MINIMUM_KEEP_THRESHOLD = 0.25  # For fallback keeping
    
    if not domains:
        return []
    
    # Score all candidates
    scored = []
    for d in domains:
        score = _score_domain_candidate(d)
        scored.append((score, d))
        print(f"[QuestCompose:Filter] Domain '{d.get('name', '?')[:50]}' score: {score:.2f}", flush=True)
    
    # Sort by score (highest first)
    scored.sort(key=lambda x: x[0], reverse=True)
    
    # Filter by threshold
    filtered = [d for score, d in scored if score >= SCORE_THRESHOLD]
    
    print(f"[QuestCompose:Filter] Threshold {SCORE_THRESHOLD}: {len(filtered)}/{len(scored)} domains passed", flush=True)
    
    # Ensure we keep at least 1-2 domains
    if len(filtered) == 0:
        # Keep top 2 by score (if they meet minimum threshold)
        fallback = [d for score, d in scored[:2] if score >= MINIMUM_KEEP_THRESHOLD]
        if fallback:
            filtered = fallback
            print(f"[QuestCompose:Filter] All below threshold, keeping top {len(filtered)} above {MINIMUM_KEEP_THRESHOLD}", flush=True)
        else:
            # Absolute fallback - keep top 1 regardless of score
            filtered = [scored[0][1]] if scored else []
            print(f"[QuestCompose:Filter] Emergency fallback: keeping top 1 domain", flush=True)
    
    print(f"[QuestCompose:Filter] Final: {len(filtered)} domains kept", flush=True)
    return filtered


def _refine_domains_with_llm(
    domains: List[Dict[str, Any]], 
    original_text: str,
    llm_client: Any
) -> List[Dict[str, Any]]:
    """
    Use LLM to classify domains as 'topic' vs 'meta'.
    
    This is a refinement pass after heuristic filtering.
    Falls back to input domains if LLM call fails.
    """
    if not domains:
        return domains
    
    # Only use LLM refinement if we have enough candidates to make it worthwhile
    if len(domains) <= 3:
        return domains
    
    # Build classification prompt
    domain_list = [
        {"name": d.get("name", ""), "source": d.get("source", "unknown")}
        for d in domains
    ]
    
    classify_system = """You are a curriculum classifier. Classify each domain name as either:
- "topic": A concrete subject area to learn (e.g., Networking, Identity basics, AWS fundamentals)
- "meta": A phase name, goal statement, output label, or organizational heading

Output ONLY valid JSON. No markdown fences."""

    classify_user = f"""Classify these domain candidates extracted from a learning roadmap.

Candidates:
{json.dumps(domain_list, indent=2)}

For each, determine if it's a real learning topic or a meta/organizational label.

Output JSON:
{{
  "classifications": [
    {{"name": "...", "type": "topic"}},
    {{"name": "...", "type": "meta"}}
  ]
}}

JSON only:"""

    try:
        result = llm_client.complete_system(
            system=classify_system,
            user=classify_user,
            command="quest-compose-classify",
            think_mode=False,
        )
        
        result_text = result.get("text", "").strip()
        classifications = _parse_json_resilient(result_text, "classifications")
        
        if not classifications:
            print(f"[QuestCompose:Filter] LLM classification returned no results", flush=True)
            return domains
        
        # Build lookup of classifications
        type_lookup = {}
        for c in classifications:
            name_norm = _normalize_domain_name(c.get("name", ""))
            type_lookup[name_norm] = c.get("type", "topic")
        
        # Filter to keep only "topic" types
        refined = []
        for d in domains:
            name_norm = _normalize_domain_name(d.get("name", ""))
            dtype = type_lookup.get(name_norm, "topic")  # Default to topic if not found
            
            if dtype == "topic":
                refined.append(d)
            else:
                print(f"[QuestCompose:Filter] LLM classified as meta: '{d.get('name', '?')[:50]}'", flush=True)
        
        # Ensure we keep at least 1 domain
        if len(refined) == 0 and len(domains) > 0:
            refined = domains[:2]
            print(f"[QuestCompose:Filter] LLM filtered all, keeping top 2", flush=True)
        
        print(f"[QuestCompose:Filter] LLM refinement: {len(domains)} → {len(refined)} domains", flush=True)
        return refined
        
    except Exception as e:
        print(f"[QuestCompose:Filter] LLM classification failed: {e}, keeping heuristic results", flush=True)
        return domains


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1A: LLM SEMANTIC EXTRACTION (Format-Agnostic)
# ═══════════════════════════════════════════════════════════════════════════════

def _llm_extract_domains(raw_text: str, llm_client: Any) -> List[Dict[str, Any]]:
    """
    Phase 1A: Use LLM to extract domains semantically, regardless of format.
    
    This works for ANY input format:
    - Bullet lists
    - Paragraphs like "I want to learn networking, IAM, AWS, and Azure"
    - Mixed formats
    - No specific headings required
    
    Returns list of DomainCandidate dicts:
    {
        "name": str,
        "subtopics": List[str],
        "source": "llm_semantic",
        "confidence_llm": float (0.0-1.0)
    }
    """
    if not llm_client or not raw_text:
        return []
    
    extract_system = """You are a learning domain extractor. Your job is to identify ALL distinct learning domains/skill areas from text, regardless of how they're expressed.

RULES:
1. Extract domains from ANY format:
   - Bullet lists
   - Paragraphs ("I want to learn X, Y, and Z")
   - Inline lists ("Topics: A, B, C")
   - Sentences ("Focus on networking, identity, and cloud")
   - Mixed formats
   
2. DO NOT assume any specific headings exist. Work with whatever text is given.

3. DOMAIN = Major skill/topic area needing multi-day learning
   Examples: "Networking", "Active Directory", "AWS", "Identity", "Logging", "Threat modeling"
   
4. SUBTOPIC = Specific concept within a domain
   Examples: "routing", "VLANs", "GPOs", "IAM policies"
   
5. Keep domains SEPARATE - don't merge "Networking" and "AWS" into one domain.

6. confidence = how certain you are this is a real learning domain (0.0-1.0)
   - 0.9-1.0: Clearly stated learning topic
   - 0.7-0.8: Likely a topic but somewhat ambiguous
   - 0.5-0.6: Might be a topic or might be meta/organizational
   - Below 0.5: Probably not a real learning domain

OUTPUT: Pure JSON only. No markdown fences. No comments. No text before/after."""

    extract_user = f"""Extract ALL learning domains from this text:

{raw_text}

Return JSON:
{{
  "domains": [
    {{
      "name": "Domain Name",
      "subtopics": ["subtopic1", "subtopic2"],
      "confidence": 0.85
    }}
  ]
}}

Extract every domain you can find, even from loose sentences. JSON only:"""

    try:
        result = llm_client.complete_system(
            system=extract_system,
            user=extract_user,
            command="quest-compose-domains-semantic",
            think_mode=True,
        )
        
        result_text = result.get("text", "").strip()
        domains_raw = _parse_json_resilient(result_text, "domains")
        
        if not domains_raw:
            return []
        
        # Normalize to our standard format
        domains = []
        for d in domains_raw:
            domains.append({
                "name": d.get("name", ""),
                "subtopics": d.get("subtopics", []),
                "source": "llm_semantic",
                "confidence_llm": d.get("confidence", 0.7),
            })
        
        return domains
        
    except Exception as e:
        print(f"[QuestCompose] LLM semantic extraction failed: {e}", flush=True)
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1B: STRUCTURAL EXTRACTION (Format-Aware but Generic)
# ═══════════════════════════════════════════════════════════════════════════════

def _structural_extract_domains(text: str) -> List[Dict[str, Any]]:
    """
    Phase 1B: Extract domains using structural patterns (no hardcoded headings).
    
    Detects:
    - Markdown headings (#, ##, ###)
    - Bullet points (-, *, +, •)
    - Numbered lists (1., 2), a., etc.)
    - Inline lists after colons ("Topics: X, Y, Z")
    - Parenthetical subtopics ("Networking (routing, VLANs)")
    
    Does NOT look for specific headings like "Focus Areas" or "Objectives".
    Uses pure structural cues only.
    
    Returns list of DomainCandidate dicts.
    """
    import re
    
    domains = []
    seen_names = set()
    
    lines = text.split('\n')
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        
        source = None
        content = None
        
        # Markdown headings (# ## ###)
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line_stripped)
        if heading_match:
            source = "heading"
            content = heading_match.group(2).strip()
        
        # Bullet points (-, *, +, •)
        elif re.match(r'^[-*+•]\s+', line_stripped):
            source = "bullet"
            content = re.sub(r'^[-*+•]\s+', '', line_stripped)
        
        # Numbered lists (1., 1), a., a))
        elif re.match(r'^(\d+[.)]|[a-z][.)])\s+', line_stripped, re.IGNORECASE):
            source = "numbered"
            content = re.sub(r'^(\d+[.)]|[a-z][.)])\s+', '', line_stripped, flags=re.IGNORECASE)
        
        # Inline lists after colons (e.g., "Topics: X, Y, Z" or "Focus: A, B, C")
        elif ':' in line_stripped:
            colon_match = re.match(r'^([^:]+):\s*(.+)$', line_stripped)
            if colon_match:
                after_colon = colon_match.group(2).strip()
                # Check if it looks like a list (has commas or "and")
                if ',' in after_colon or ' and ' in after_colon.lower():
                    source = "inline_list"
                    # Extract each item from the list
                    items = re.split(r',\s*|\s+and\s+', after_colon, flags=re.IGNORECASE)
                    for item in items:
                        item = item.strip()
                        if item and len(item) > 2:
                            parsed = _parse_domain_with_subtopics(item)
                            name_lower = parsed["name"].lower()
                            if name_lower not in seen_names:
                                seen_names.add(name_lower)
                                parsed["source"] = "inline_list"
                                parsed["confidence_llm"] = None
                                domains.append(parsed)
                    continue  # Already processed inline list items
        
        # Process the content if we found a structural element
        if source and content:
            parsed = _parse_domain_with_subtopics(content)
            name_lower = parsed["name"].lower()
            
            if name_lower not in seen_names and len(parsed["name"]) > 2:
                seen_names.add(name_lower)
                parsed["source"] = source
                parsed["confidence_llm"] = None
                domains.append(parsed)
    
    # Also scan for paragraph-embedded topics
    # Look for patterns like "learn X, Y, and Z" or "focus on A, B, C"
    paragraph_domains = _extract_from_paragraphs(text, seen_names)
    domains.extend(paragraph_domains)
    
    return domains


def _extract_from_paragraphs(text: str, seen_names: set) -> List[Dict[str, Any]]:
    """
    Extract domains from paragraph text (not structured as lists).
    
    Looks for patterns like:
    - "learn X, Y, and Z"
    - "focus on A, B, C"
    - "covering topics like X, Y, Z"
    - "including X, Y, and Z"
    """
    import re
    
    domains = []
    
    # Patterns that precede topic lists in prose
    trigger_patterns = [
        r'(?:learn|study|master|cover|focus\s+on|including|such\s+as|like|topics?:?)\s+([^.]+)',
        r'(?:fundamentals?\s+(?:of|in))\s+([^.]+)',
        r'(?:skills?\s+(?:in|like|such\s+as))\s+([^.]+)',
    ]
    
    for pattern in trigger_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            topic_text = match.group(1).strip()
            
            # Check if it looks like a list
            if ',' in topic_text or ' and ' in topic_text.lower():
                items = re.split(r',\s*|\s+and\s+', topic_text, flags=re.IGNORECASE)
                
                for item in items:
                    item = item.strip()
                    # Clean up common trailing words
                    item = re.sub(r'\s+(etc|basics?|fundamentals?)\s*\.?$', '', item, flags=re.IGNORECASE)
                    item = re.sub(r'[.,:;]+$', '', item)
                    
                    if item and len(item) > 2 and len(item.split()) <= 5:
                        name_lower = item.lower()
                        if name_lower not in seen_names:
                            seen_names.add(name_lower)
                            domains.append({
                                "name": item,
                                "subtopics": [],
                                "source": "paragraph",
                                "confidence_llm": None,
                            })
    
    return domains


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1C: MERGE + NOISE FILTERING (Dynamic, Format-Agnostic)
# ═══════════════════════════════════════════════════════════════════════════════

def _merge_domain_candidates(
    llm_domains: List[Dict[str, Any]], 
    structural_domains: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merge LLM and structural domain candidates.
    
    If two candidates have similar names, merge their subtopics and keep
    the best source/confidence info.
    """
    merged = {}
    
    def _name_key(name: str) -> str:
        """Normalize name for comparison."""
        return _normalize_domain_name(name)
    
    # Add LLM domains first (usually higher quality names)
    for d in llm_domains:
        key = _name_key(d.get("name", ""))
        if not key:
            continue
        
        if key not in merged:
            merged[key] = {
                "name": d.get("name", ""),
                "subtopics": list(d.get("subtopics", [])),
                "sources": [d.get("source", "llm_semantic")],
                "confidence_llm": d.get("confidence_llm"),
            }
        else:
            # Merge subtopics
            existing = merged[key]
            for st in d.get("subtopics", []):
                if st not in existing["subtopics"]:
                    existing["subtopics"].append(st)
            existing["sources"].append(d.get("source", "llm_semantic"))
            # Keep highest confidence
            if d.get("confidence_llm") and (not existing["confidence_llm"] or d["confidence_llm"] > existing["confidence_llm"]):
                existing["confidence_llm"] = d["confidence_llm"]
    
    # Add structural domains
    for d in structural_domains:
        key = _name_key(d.get("name", ""))
        if not key:
            continue
        
        if key not in merged:
            merged[key] = {
                "name": d.get("name", ""),
                "subtopics": list(d.get("subtopics", [])),
                "sources": [d.get("source", "structural")],
                "confidence_llm": d.get("confidence_llm"),
            }
        else:
            # Merge subtopics
            existing = merged[key]
            for st in d.get("subtopics", []):
                if st not in existing["subtopics"]:
                    existing["subtopics"].append(st)
            existing["sources"].append(d.get("source", "structural"))
    
    # Convert back to list with best source
    result = []
    for key, data in merged.items():
        # Pick best source (prefer bullet > numbered > inline_list > heading > paragraph > llm_semantic)
        source_priority = {"bullet": 1, "numbered": 2, "inline_list": 3, "heading": 4, "paragraph": 5, "llm_semantic": 6}
        best_source = min(data["sources"], key=lambda s: source_priority.get(s, 10))
        
        result.append({
            "name": data["name"],
            "subtopics": data["subtopics"],
            "source": best_source,
            "confidence_llm": data["confidence_llm"],
        })
    
    return result


def _count_structural_items(text: str) -> int:
    """
    Count distinct structural items in text (bullets, numbered items).
    
    This provides a baseline for how many domains we should expect.
    Focuses on TOP-LEVEL items, not parenthetical subtopics.
    """
    import re
    
    count = 0
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        
        # Bullet points (-, *, •) at line start
        if re.match(r'^[-*•]\s+\S', line):
            count += 1
            continue
        
        # Numbered items (1., 1), a., a))
        if re.match(r'^(\d+[.)]|[a-z][.)])\s+\S', line, re.IGNORECASE):
            count += 1
            continue
    
    return max(count, 1)


def _extract_domains_structurally(text: str) -> List[Dict[str, Any]]:
    """
    Extract domains using pure structural analysis (no LLM).
    
    Handles parenthetical subtopics correctly:
    - "Networking (routing, VLANs, DNS)" → domain "Networking" with subtopics
    
    This is a backup when LLM extraction fails.
    """
    import re
    
    domains = []
    seen_names = set()
    
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Extract from bullet points
        bullet_match = re.match(r'^[-*•]\s+(.+)$', line)
        if bullet_match:
            item_text = bullet_match.group(1).strip()
            domain = _parse_domain_with_subtopics(item_text)
            
            name_lower = domain["name"].lower()
            if name_lower not in seen_names and len(domain["name"]) > 2:
                seen_names.add(name_lower)
                domain["source"] = "bullet_list"
                domains.append(domain)
            continue
        
        # Extract from numbered items
        num_match = re.match(r'^(\d+[.)]|[a-z][.)])\s+(.+)$', line, re.IGNORECASE)
        if num_match:
            item_text = num_match.group(2).strip()
            domain = _parse_domain_with_subtopics(item_text)
            
            name_lower = domain["name"].lower()
            if name_lower not in seen_names and len(domain["name"]) > 2:
                seen_names.add(name_lower)
                domain["source"] = "numbered_list"
                domains.append(domain)
            continue
    
    return domains


def _parse_domain_with_subtopics(text: str) -> Dict[str, Any]:
    """
    Parse a domain string that may contain parenthetical subtopics.
    
    Examples:
    - "Networking (routing, VLANs, DNS)" → name="Networking", subtopics=["routing", "VLANs", "DNS"]
    - "Active Directory architecture" → name="Active Directory architecture", subtopics=[]
    """
    import re
    
    # Check for parenthetical subtopics
    paren_match = re.match(r'^([^(]+)\s*\(([^)]+)\)\s*$', text)
    
    if paren_match:
        name = paren_match.group(1).strip()
        subtopics_str = paren_match.group(2).strip()
        
        # Split subtopics by comma, semicolon, or "and"
        subtopics = re.split(r'[,;]|\s+and\s+', subtopics_str)
        subtopics = [s.strip() for s in subtopics if s.strip()]
        
        return {
            "name": name,
            "subtopics": subtopics,
            "priority": "high"
        }
    else:
        # No parentheses - just clean up the name
        name = re.sub(r'[.,:;!?]+$', '', text.strip())
        if len(name) > 60:
            name = name[:60].rsplit(' ', 1)[0]
        
        return {
            "name": name,
            "subtopics": [],
            "priority": "high"
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SUBTOPIC ENGINE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _get_domain_subtopic_map(domains: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    Build a flattened domain→subtopics map from confirmed domains.
    
    Args:
        domains: List of domain dicts with 'name' and 'subtopics' keys
        
    Returns:
        {
            "AWS": ["IAM escalation", "STS abuse", "CloudTrail evasion"],
            "Azure": ["Entra ID misconfig", "Hybrid identity"],
            ...
        }
        
    If subtopics is missing or not a list, returns empty list for that domain.
    """
    result = {}
    
    for d in domains:
        name = d.get("name", "").strip()
        if not name:
            continue
        
        subtopics = d.get("subtopics", [])
        
        # Handle various subtopic formats
        if isinstance(subtopics, list):
            # Normalize: strip whitespace from each subtopic
            clean_subtopics = [s.strip() for s in subtopics if isinstance(s, str) and s.strip()]
        elif isinstance(subtopics, str):
            # Single string - wrap in list
            clean_subtopics = [subtopics.strip()] if subtopics.strip() else []
        else:
            clean_subtopics = []
        
        result[name] = clean_subtopics
    
    return result


def _calculate_subtopic_aware_target_steps(domains: List[Dict[str, Any]], min_per_domain: int = 3) -> int:
    """
    Calculate target step count based on domains AND subtopics.
    
    Ensures enough steps to cover all subtopics while maintaining domain balance.
    
    Formula:
    - At least min_per_domain steps per domain
    - At least 1 step per subtopic
    - Whichever total is higher
    """
    num_domains = len(domains)
    total_subtopics = sum(len(d.get("subtopics", [])) for d in domains)
    
    # Minimum based on domains
    domain_minimum = num_domains * min_per_domain
    
    # Minimum based on subtopics (1 per subtopic)
    subtopic_minimum = total_subtopics
    
    # Use whichever is higher, with a floor of 12
    target = max(domain_minimum, subtopic_minimum, 12)
    
    return target


def _audit_subtopic_coverage(
    outline_steps: List[Dict[str, Any]], 
    domain_subtopic_map: Dict[str, List[str]]
) -> Dict[str, Dict[str, int]]:
    """
    Audit which subtopics are covered by outline steps.
    
    Args:
        outline_steps: List of step dicts (must have 'domain' and optionally 'subtopics')
        domain_subtopic_map: {domain_name: [subtopic1, subtopic2, ...]}
        
    Returns:
        {
            "AWS": {"IAM escalation": 2, "STS abuse": 1, "CloudTrail evasion": 0},
            "Azure": {"Entra ID misconfig": 1, "Hybrid identity": 0},
            ...
        }
        
    Zero means the subtopic was NOT covered by any step.
    """
    # Initialize coverage map with zeros
    coverage = {}
    for domain, subtopics in domain_subtopic_map.items():
        coverage[domain] = {st: 0 for st in subtopics}
    
    # Count coverage from steps
    for step in outline_steps:
        step_domain = step.get("domain", "").strip()
        step_subtopics = step.get("subtopics", [])
        
        # Normalize step_subtopics to list
        if isinstance(step_subtopics, str):
            step_subtopics = [step_subtopics]
        elif not isinstance(step_subtopics, list):
            step_subtopics = []
        
        # Match domain (fuzzy match for slight variations)
        matched_domain = None
        for domain in coverage.keys():
            if domain.lower() == step_domain.lower() or domain.lower() in step_domain.lower():
                matched_domain = domain
                break
        
        if matched_domain and step_subtopics:
            for st in step_subtopics:
                st_normalized = st.strip().lower()
                # Find matching subtopic in the coverage map
                for known_st in coverage[matched_domain]:
                    if known_st.lower() == st_normalized or st_normalized in known_st.lower() or known_st.lower() in st_normalized:
                        coverage[matched_domain][known_st] += 1
                        break
    
    return coverage


def _get_missing_subtopics(coverage: Dict[str, Dict[str, int]]) -> Dict[str, List[str]]:
    """
    Extract subtopics with zero coverage.
    
    Returns:
        {"AWS": ["CloudTrail evasion"], "Azure": ["Hybrid identity"], ...}
    """
    missing = {}
    for domain, subtopic_counts in coverage.items():
        uncovered = [st for st, count in subtopic_counts.items() if count == 0]
        if uncovered:
            missing[domain] = uncovered
    return missing


def _generate_subtopic_patch_steps(
    missing_subtopics: Dict[str, List[str]], 
    current_step_count: int
) -> List[Dict[str, Any]]:
    """
    Generate placeholder steps for missing subtopics.
    
    Each missing subtopic gets one patch step.
    
    Args:
        missing_subtopics: {domain: [uncovered_subtopics]}
        current_step_count: Current number of steps (for numbering)
        
    Returns:
        List of patch steps to append to outline
    """
    patch_steps = []
    day_counter = current_step_count + 1
    
    for domain, subtopics in missing_subtopics.items():
        for subtopic in subtopics:
            patch_steps.append({
                "day": day_counter,
                "domain": domain,
                "subtopics": [subtopic],
                "type": "info",
                "topic": f"{domain}: {subtopic}",
                "title": f"Day {day_counter}: {subtopic}",
                "prompt": f"Deep dive into {subtopic} within {domain}. Focus on understanding core concepts and practical applications.",
                "actions": [
                    f"Study 1–2 focused resources on {subtopic} and take notes.",
                    f"Write a short summary explaining how {subtopic} fits into {domain}.",
                    f"List at least 3 offensive or defensive implications you see."
                ],
                "_generation_mode": "subtopic_patch"
            })
            day_counter += 1
    
    return patch_steps


def _normalize_outline_step_subtopics(step: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure a step has a properly formatted subtopics field.
    
    - If missing, set to []
    - If string, wrap in list
    - If list, keep as-is
    """
    subtopics = step.get("subtopics")
    
    if subtopics is None:
        step["subtopics"] = []
    elif isinstance(subtopics, str):
        step["subtopics"] = [subtopics.strip()] if subtopics.strip() else []
    elif isinstance(subtopics, list):
        step["subtopics"] = [s.strip() for s in subtopics if isinstance(s, str) and s.strip()]
    else:
        step["subtopics"] = []
    
    return step


def _log_domain_subtopic_map(domain_subtopic_map: Dict[str, List[str]]) -> None:
    """Log the domain-subtopic map for debugging."""
    print(f"[QuestCompose] Domain-subtopic map:", flush=True)
    for domain, subtopics in domain_subtopic_map.items():
        print(f"[QuestCompose]   - {domain}: {len(subtopics)} subtopics", flush=True)


def _log_subtopic_coverage(coverage: Dict[str, Dict[str, int]], missing: Dict[str, List[str]]) -> None:
    """Log subtopic coverage details for debugging."""
    print(f"[QuestCompose] Subtopic coverage in outline:", flush=True)
    for domain, subtopic_counts in coverage.items():
        print(f"[QuestCompose]   - {domain}: {subtopic_counts}", flush=True)
    
    if missing:
        for domain, uncovered in missing.items():
            print(f"[QuestCompose] WARNING: Missing subtopics in outline for '{domain}': {uncovered}", flush=True)
    else:
        print(f"[QuestCompose] All subtopics covered!", flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
# BOSS STEP ENFORCEMENT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize_step_type(step: Dict[str, Any]) -> str:
    """
    Normalize and validate step_type field.
    
    Allowed values: INFO, APPLY, RECALL, BOSS
    Uses heuristics to classify if step_type is missing or invalid.
    
    Args:
        step: Step dict that may or may not have step_type
        
    Returns:
        Normalized step_type string (uppercase)
    """
    raw = (step.get("step_type") or step.get("type") or "").strip().upper()
    
    # If it's already one of the allowed values, keep it
    if raw in {"INFO", "APPLY", "RECALL", "BOSS"}:
        return raw
    
    # Handle legacy lowercase values
    if raw.lower() in {"info", "apply", "recall", "boss"}:
        return raw.upper()
    
    # Heuristics: classify based on content if missing/invalid
    title = (step.get("title") or step.get("topic") or "").lower()
    actions = step.get("actions", [])
    actions_text = " ".join(actions) if isinstance(actions, list) else str(actions)
    text_blob = f"{title} {actions_text}".lower()
    
    # Check for BOSS indicators
    if any(k in text_blob for k in ["boss", "capstone", "final project", "full-chain", "mini-project"]):
        return "BOSS"
    
    # Check for APPLY indicators
    if any(k in text_blob for k in ["lab", "ctf", "walkthrough", "practice", "hands-on", "exercise", "build", "deploy", "configure"]):
        return "APPLY"
    
    # Check for RECALL indicators
    if any(k in text_blob for k in ["review", "recall", "quiz", "flashcard", "cheat sheet", "summarize", "recap"]):
        return "RECALL"
    
    # Default to INFO
    return "INFO"


def _enforce_boss_per_domain(
    steps: List[Dict[str, Any]], 
    domains: List[Dict[str, Any]],
    domain_subtopic_map: Dict[str, List[str]]
) -> List[Dict[str, Any]]:
    """
    Ensure every domain gets exactly ONE BOSS step.
    
    Rules:
    - If a domain has multiple BOSS steps, demote all but the last to APPLY
    - If a domain has no BOSS step, promote the last step for that domain to BOSS
    - BOSS steps should reference multiple subtopics when possible
    
    Args:
        steps: List of outline steps (modified in place)
        domains: List of domain dicts with 'name' and 'subtopics'
        domain_subtopic_map: {domain_name: [subtopic1, subtopic2, ...]}
        
    Returns:
        The modified steps list (same reference, modified in place)
    """
    print(f"[QuestCompose:Boss] Enforcing one BOSS per domain...", flush=True)
    
    # 1) Normalize step_type for every step
    for step in steps:
        step["step_type"] = _normalize_step_type(step)
    
    domain_names = [d.get("name") for d in domains if d.get("name")]
    
    # 2) Group steps by domain (preserving order)
    steps_by_domain: Dict[str, List[Dict[str, Any]]] = {name: [] for name in domain_names}
    for step in steps:
        domain = step.get("domain")
        if domain in steps_by_domain:
            steps_by_domain[domain].append(step)
        elif domain:
            # Domain not in our list but exists - create entry
            if domain not in steps_by_domain:
                steps_by_domain[domain] = []
            steps_by_domain[domain].append(step)
    
    # 3) For each domain, enforce single BOSS with quality checks
    for domain in domain_names:
        domain_steps = steps_by_domain.get(domain, [])
        if not domain_steps:
            print(f"[QuestCompose:Boss] WARNING: No steps found for domain '{domain}'", flush=True)
            continue
        
        # Find all BOSS steps for this domain
        boss_indices = [i for i, s in enumerate(domain_steps) if s.get("step_type") == "BOSS"]
        domain_subtopics = domain_subtopic_map.get(domain, [])
        
        if not boss_indices:
            # No BOSS yet → need to promote, but check if candidate is worthy
            last_step = domain_steps[-1]
            last_subtopics = last_step.get("subtopics", [])
            
            # TIE-BREAK RULE: If last step is weak (INFO-only with <2 subtopics),
            # merge content from second-to-last step to create a stronger BOSS
            is_weak_candidate = (
                last_step.get("step_type") == "INFO" and 
                len(last_subtopics) < 2 and 
                len(domain_steps) >= 2
            )
            
            if is_weak_candidate:
                # Merge last two steps into a mega-BOSS
                second_last = domain_steps[-2]
                second_last_subtopics = second_last.get("subtopics", [])
                
                # Combine subtopics from both steps
                merged_subtopics = list(last_subtopics)
                for st in second_last_subtopics:
                    if st not in merged_subtopics:
                        merged_subtopics.append(st)
                
                # Update last step with merged content
                last_step["subtopics"] = merged_subtopics
                
                # Merge topic/title if helpful
                if second_last.get("topic"):
                    original_topic = last_step.get("topic", "")
                    last_step["topic"] = f"{domain} Capstone: {original_topic}"
                
                print(f"[QuestCompose:Boss] Weak BOSS candidate for '{domain}', merging subtopics from penultimate step.", flush=True)
            
            # Promote to BOSS
            last_step["step_type"] = "BOSS"
            last_step["type"] = "boss"  # Legacy field
            
            # Ensure BOSS has multiple subtopics (add more if needed)
            current_subtopics = last_step.get("subtopics", [])
            if domain_subtopics and len(current_subtopics) < 2:
                # Add more subtopics (up to 4 total)
                for st in domain_subtopics:
                    if st not in current_subtopics:
                        current_subtopics.append(st)
                        if len(current_subtopics) >= 4:
                            break
                last_step["subtopics"] = current_subtopics
                print(f"[QuestCompose:Boss] Enhanced BOSS with {len(current_subtopics)} subtopics.", flush=True)
            
            print(f"[QuestCompose:Boss] Promoted last step to BOSS for domain '{domain}'.", flush=True)
            
        elif len(boss_indices) > 1:
            # Too many BOSS steps → keep only the last one
            last_local_idx = boss_indices[-1]
            
            # Demote all earlier BOSS steps to APPLY
            for i in boss_indices[:-1]:
                domain_steps[i]["step_type"] = "APPLY"
                domain_steps[i]["type"] = "apply"  # Legacy field
                print(f"[QuestCompose:Boss] Demoting extra boss step for domain '{domain}' to APPLY.", flush=True)
            
            print(f"[QuestCompose:Boss] Keeping step as final boss for domain '{domain}'.", flush=True)
        else:
            # Exactly one BOSS - verify it has multiple subtopics
            boss_step = domain_steps[boss_indices[0]]
            boss_subtopics = boss_step.get("subtopics", [])
            
            if len(boss_subtopics) < 2 and domain_subtopics:
                # Enhance weak BOSS with more subtopics
                for st in domain_subtopics:
                    if st not in boss_subtopics:
                        boss_subtopics.append(st)
                        if len(boss_subtopics) >= 4:
                            break
                boss_step["subtopics"] = boss_subtopics
                print(f"[QuestCompose:Boss] Enhanced existing BOSS for '{domain}' with {len(boss_subtopics)} subtopics.", flush=True)
            else:
                print(f"[QuestCompose:Boss] Domain '{domain}' has exactly one BOSS step. ✓", flush=True)
    
    # 4) Log final boss distribution
    boss_count_by_domain = {}
    for step in steps:
        if step.get("step_type") == "BOSS":
            domain = step.get("domain", "Unknown")
            boss_count_by_domain[domain] = boss_count_by_domain.get(domain, 0) + 1
    
    print(f"[QuestCompose:Boss] Final BOSS distribution: {boss_count_by_domain}", flush=True)
    
    return steps


def _log_step_type_distribution(steps: List[Dict[str, Any]]) -> None:
    """Log the distribution of step types for debugging."""
    type_counts = {"INFO": 0, "APPLY": 0, "RECALL": 0, "BOSS": 0}
    
    for step in steps:
        step_type = step.get("step_type", "INFO")
        if step_type in type_counts:
            type_counts[step_type] += 1
    
    print(f"[QuestCompose:Boss] Step type distribution: {type_counts}", flush=True)


def _ensure_early_apply_step(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ensure at least one APPLY step appears in the first 5 days.
    
    This prevents INFO-heavy starts that can bore learners.
    If no APPLY in first 5, promote the most lab-appropriate INFO step.
    
    Args:
        steps: List of outline steps (modified in place)
        
    Returns:
        The modified steps list
    """
    if len(steps) < 5:
        return steps
    
    # Check first 5 steps for APPLY
    first_five = steps[:5]
    has_early_apply = any(s.get("step_type") == "APPLY" for s in first_five)
    
    if has_early_apply:
        print(f"[QuestCompose:Distribution] Early APPLY check passed. ✓", flush=True)
        return steps
    
    # No APPLY in first 5 - find best candidate to promote
    # Prefer steps with "hands-on" keywords in topic/title
    apply_keywords = ["lab", "practice", "hands-on", "configure", "build", "deploy", "exercise", "walkthrough"]
    
    best_candidate_idx = None
    best_score = -1
    
    for i, step in enumerate(first_five):
        if step.get("step_type") == "BOSS":
            continue  # Don't demote a BOSS
        
        topic = (step.get("topic") or step.get("title") or "").lower()
        score = sum(1 for kw in apply_keywords if kw in topic)
        
        # Prefer steps 2-4 over step 1 (don't make day 1 a lab)
        if i > 0 and score >= best_score:
            best_score = score
            best_candidate_idx = i
    
    # If no keyword match, just promote step 2 (second day)
    if best_candidate_idx is None and len(first_five) >= 2:
        best_candidate_idx = 1
    
    if best_candidate_idx is not None:
        steps[best_candidate_idx]["step_type"] = "APPLY"
        steps[best_candidate_idx]["type"] = "apply"  # Legacy field
        print(f"[QuestCompose:Distribution] No early APPLY found, promoting step {best_candidate_idx + 1} to APPLY.", flush=True)
    
    return steps


def _generate_programmatic_outline(domains: List[Dict[str, Any]], target_steps: int) -> List[Dict[str, Any]]:
    """
    Generate a subtopic-aware outline programmatically when LLM fails.
    
    This is a fallback that ensures all domains AND subtopics are covered
    with a reasonable distribution of steps, including exactly one BOSS per domain.
    """
    outline = []
    num_domains = len(domains)
    
    if num_domains == 0:
        return []
    
    # Step type rotation (INFO → APPLY pattern, then BOSS at end)
    step_type_rotation = ["INFO", "INFO", "APPLY", "APPLY", "RECALL", "INFO"]
    
    day = 1
    for domain in domains:
        domain_name = domain.get("name", "Unknown")
        subtopics = domain.get("subtopics", [])
        
        if subtopics:
            # Create at least one step per subtopic
            for i, subtopic in enumerate(subtopics):
                step_type = step_type_rotation[i % len(step_type_rotation)]
                
                outline.append({
                    "day": day,
                    "domain": domain_name,
                    "subtopics": [subtopic],
                    "topic": subtopic,
                    "type": step_type.lower(),  # Legacy field
                    "step_type": step_type,      # New canonical field
                    "_generation_mode": "programmatic"
                })
                day += 1
            
            # Add exactly one BOSS step at the end of this domain
            outline.append({
                "day": day,
                "domain": domain_name,
                "subtopics": subtopics[:4] if len(subtopics) > 4 else subtopics,  # Multi-subtopic capstone
                "topic": f"{domain_name} Capstone: Full-Chain Scenario",
                "type": "boss",
                "step_type": "BOSS",
                "_generation_mode": "programmatic"
            })
            day += 1
        else:
            # No subtopics - create minimum 3 steps with BOSS at end
            steps_per_domain = max(3, target_steps // num_domains)
            
            for i in range(steps_per_domain):
                topic = f"{domain_name} - Part {i + 1}"
                step_type = step_type_rotation[i % len(step_type_rotation)]
                
                # Last step of domain is BOSS
                if i == steps_per_domain - 1:
                    step_type = "BOSS"
                    topic = f"{domain_name} Capstone"
                
                outline.append({
                    "day": day,
                    "domain": domain_name,
                    "subtopics": [],
                    "topic": topic,
                    "type": step_type.lower(),
                    "step_type": step_type,
                    "_generation_mode": "programmatic"
                })
                day += 1
    
    return outline


def _generate_steps_with_llm(
    draft: Dict[str, Any], 
    kernel: Any,
    progress_callback: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """
    Generate quest steps using domain-balanced 3-phase architecture.
    
    v2.0: Try Gemini first (fast, cheap), fall back to GPT.
    
    v0.10.2: NEW ARCHITECTURE - Domain-first balanced generation
    
    PHASE 1: Domain Extraction
        - Parse ALL domains/topics from input (any format)
        - Ensure nothing is missed
        
    PHASE 2: Domain-Balanced Outline
        - Allocate 3-7 steps per domain
        - Ensure proportional coverage
        - Self-validate: all domains represented
        
    PHASE 3: Content Generation (per domain)
        - Generate steps for ONE domain at a time
        - Enforce micro-step constraints
        - Continue until ALL domains complete
    
    Args:
        draft: Quest draft dictionary with title, objectives, etc.
        kernel: NovaKernel instance
        progress_callback: Optional callback(message, percent) for progress updates
    
    Returns a list of step dicts, or empty list on failure.
    """
    def _progress(msg: str, pct: int):
        if progress_callback:
            try:
                progress_callback(msg, pct)
            except:
                pass
        print(f"[QuestCompose] {msg} ({pct}%)", flush=True)
    
    # Get LLM client from kernel (needed for GPT fallback in router)
    llm_client = getattr(kernel, 'llm_client', None)
    
    # ═══════════════════════════════════════════════════════════════════════
    # v1.0.0: LESSON ENGINE (Priority 1)
    # ═══════════════════════════════════════════════════════════════════════
    domains = draft.get("domains", [])
    
    if _HAS_LESSON_ENGINE and domains:
        _progress("Using Lesson Engine (3-phase retrieval-backed)...", 5)
        
        try:
            from kernel.lesson_engine import generate_lesson_plan
            
            quest_id = draft.get("id") or "quest_generated"
            title = draft.get("title", "Untitled Quest")
            
            lesson_steps = generate_lesson_plan(
                domains=domains,
                quest_id=quest_id,
                quest_title=title,
                kernel=kernel,
                user_constraints=None,
            )
            
            if lesson_steps:
                _progress(f"Lesson Engine succeeded: {len(lesson_steps)} steps", 95)
                return lesson_steps
            
            _progress("Lesson Engine returned no steps, falling back...", 10)
            
        except Exception as e:
            print(f"[QuestCompose] Lesson Engine error: {e}", flush=True)
            _progress("Lesson Engine failed, falling back...", 10)
    
    # ═══════════════════════════════════════════════════════════════════════
    # USE GEMINI ROUTER (handles Gemini + GPT fallback + validation)
    # ═══════════════════════════════════════════════════════════════════════
    if _HAS_GEMINI:
        _progress("Generating steps via router...", 5)
        router_steps = gemini_generate_quest_steps(draft, llm_client)
        if router_steps:
            _progress(f"Router succeeded: {len(router_steps)} validated steps", 95)
            return router_steps
        _progress("Router failed, using legacy generation...", 10)
    
    # ═══════════════════════════════════════════════════════════════════════
    # LEGACY FALLBACK - Original implementation
    # ═══════════════════════════════════════════════════════════════════════
    try:
        _progress("Starting domain-balanced generation...", 5)
        
        if not llm_client:
            print("[QuestCompose] No LLM client available", flush=True)
            return []
        
        title = draft.get("title", "Untitled Quest")
        category = draft.get("category", "general")
        objectives = draft.get("objectives", [])
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE 1: USE CONFIRMED DOMAINS (from Domain Review wizard step)
        # ═══════════════════════════════════════════════════════════════════════
        # 
        # The domain extraction now happens BEFORE this function is called,
        # during the Domain Review wizard step. The user has already confirmed
        # the domains, so we just use them directly.
        #
        # This is the key change from Option A: NO RE-EXTRACTION at generation time.
        
        _progress("Phase 1: Loading confirmed domains...", 10)
        
        # Get confirmed domains from draft
        domains = draft.get("domains", [])
        
        if domains:
            print(f"[QuestCompose] Using {len(domains)} confirmed domains from Domain Review", flush=True)
            print(f"[QuestCompose] Domains: {[d.get('name', '?') for d in domains]}", flush=True)
        else:
            # FALLBACK: If no confirmed domains, this phase wasn't run through Domain Review
            # This shouldn't happen in normal flow, but handle it gracefully
            print(f"[QuestCompose] WARNING: No confirmed domains in draft", flush=True)
            print(f"[QuestCompose] This phase should have gone through Domain Review first", flush=True)
            
            # Fall back to old extraction as safety net
            raw_text = "\n".join(objectives) if isinstance(objectives, list) else str(objectives)
            domains = _structural_extract_domains(raw_text)
            
            if not domains:
                print(f"[QuestCompose] No domains found, falling back to single-shot", flush=True)
                return _generate_steps_single_shot(draft, kernel, progress_callback)
        
        _progress(f"Using {len(domains)} domains", 15)
        
        # Log final domains with subtopic counts
        print(f"[QuestCompose] Domains for generation:", flush=True)
        for d in domains:
            subtopics = d.get('subtopics', [])
            print(f"[QuestCompose]   - {d.get('name', '?')} ({len(subtopics)} subtopics)", flush=True)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE 2: SUBTOPIC-AWARE BALANCED OUTLINE
        # ═══════════════════════════════════════════════════════════════════════
        # Creates an outline that covers ALL domains AND ALL subtopics
        # Every subtopic gets at least one step
        
        _progress("Phase 2: Creating subtopic-aware outline...", 20)
        
        # Build domain-subtopic map (single source of truth)
        domain_subtopic_map = _get_domain_subtopic_map(domains)
        _log_domain_subtopic_map(domain_subtopic_map)
        
        # Calculate target steps based on domains AND subtopics
        num_domains = len(domains)
        target_steps = _calculate_subtopic_aware_target_steps(domains, min_per_domain=3)
        
        print(f"[QuestCompose] Target steps: {target_steps} (domains: {num_domains}, subtopics: {sum(len(st) for st in domain_subtopic_map.values())})", flush=True)
        
        # Build subtopic-aware domain list for prompt
        domain_list_text = ""
        for i, d in enumerate(domains):
            name = d.get('name', f'Domain {i+1}')
            subtopics = d.get('subtopics', [])
            domain_list_text += f"\n{i+1}. **{name}**"
            if subtopics:
                domain_list_text += f"\n   Subtopics (EACH must appear in at least one step):"
                for st in subtopics:
                    domain_list_text += f"\n   - {st}"
            domain_list_text += "\n"
        
        # Subtopic-aware outline prompt with step_type and BOSS requirements
        outline_system = """You are a curriculum architect. Create a day-by-day learning outline.

═══════════════════════════════════════════════════════════════════════════════
JSON OUTPUT REQUIREMENTS - CRITICAL
═══════════════════════════════════════════════════════════════════════════════

You MUST output ONLY a valid JSON object. Nothing else.

DO NOT:
- Wrap in markdown code fences (no ```json)
- Add comments
- Add trailing commas
- Add any text before or after the JSON
- Use single quotes (use double quotes only)

DO:
- Output raw JSON starting with { and ending with }
- Use double quotes for all strings
- Ensure all arrays and objects are properly closed

═══════════════════════════════════════════════════════════════════════════════
SUBTOPIC-AWARE OUTLINE REQUIREMENTS
═══════════════════════════════════════════════════════════════════════════════

1. EVERY domain MUST have 3-7 steps (no domain gets 0, 1, or 2)
2. EVERY subtopic listed under a domain MUST appear in at least one step
3. Each step MUST include a "subtopics" array listing which subtopic(s) it covers
4. Each step = 60-90 minutes (working adult, not student)
5. One step = ONE focused micro-topic (1-2 subtopics max per step, except BOSS)
6. Distribute steps EVENLY across domains

═══════════════════════════════════════════════════════════════════════════════
STEP TYPES (step_type field) - REQUIRED
═══════════════════════════════════════════════════════════════════════════════

Each step MUST have a "step_type" field with ONE of these values:

- "INFO"   — Concept/reading/explanation day (learn theory, watch videos, read docs)
- "APPLY"  — Hands-on lab, walkthrough, CTF-style practice (build/configure/exploit)
- "RECALL" — Review day: quizzes, flashcards, cheat sheets, summarization
- "BOSS"   — Full-chain capstone lab/scenario that integrates multiple subtopics

═══════════════════════════════════════════════════════════════════════════════
STEP TYPE DISTRIBUTION RULES
═══════════════════════════════════════════════════════════════════════════════

- In the FIRST 5 DAYS, include at least ONE "APPLY" step (avoid all-INFO starts)
- Alternate INFO → APPLY patterns to keep engagement high
- Don't cluster too many INFO days in a row (max 2 consecutive INFO)
- Place RECALL steps after 3-4 learning days (not at the start)

═══════════════════════════════════════════════════════════════════════════════
BOSS STEP RULES - CRITICAL
═══════════════════════════════════════════════════════════════════════════════

- Each domain gets EXACTLY ONE "BOSS" step
- The BOSS step MUST be the LAST step for that domain
- The BOSS step should reference MULTIPLE subtopics (2-4) from that domain
- The BOSS step is a capstone that tests if the learner can chain skills together
- Do NOT create more than one BOSS per domain
- Do NOT create any domain without a BOSS step

VALIDATION BEFORE RESPONDING:
- Count steps per domain (must be >= 3)
- Check that EVERY domain has exactly ONE BOSS step as its last step
- Check that EVERY listed subtopic appears in at least one step's "subtopics" array
- Check that at least ONE APPLY step appears in days 1-5
- Ensure JSON is valid with no trailing commas"""

        outline_user = f"""Create a balanced {target_steps}-step outline for "{title}".

DOMAINS AND SUBTOPICS TO COVER:
{domain_list_text}

CRITICAL RULES:
1. Every subtopic listed above MUST appear in at least one step's "subtopics" array
2. Every domain MUST have exactly ONE BOSS step as its LAST step
3. BOSS steps should integrate 2-4 subtopics into a full-chain scenario

OUTPUT THIS EXACT JSON STRUCTURE:
{{
  "total_steps": {target_steps},
  "outline": [
    {{"day": 1, "domain": "Domain Name", "subtopics": ["Subtopic A"], "topic": "Intro to Subtopic A", "step_type": "INFO"}},
    {{"day": 2, "domain": "Domain Name", "subtopics": ["Subtopic A"], "topic": "Hands-on with Subtopic A", "step_type": "APPLY"}},
    {{"day": 3, "domain": "Domain Name", "subtopics": ["Subtopic B"], "topic": "Learn Subtopic B", "step_type": "INFO"}},
    {{"day": 4, "domain": "Domain Name", "subtopics": ["Subtopic A", "Subtopic B"], "topic": "Domain Capstone: Full Chain", "step_type": "BOSS"}},
    {{"day": 5, "domain": "Other Domain", "subtopics": ["Subtopic X"], "topic": "Intro to X", "step_type": "INFO"}}
  ]
}}

REMEMBER:
- "subtopics" is a LIST even if it has one item: ["single item"]
- "step_type" MUST be one of: "INFO", "APPLY", "RECALL", "BOSS" (uppercase)
- Every domain's LAST step must be step_type: "BOSS"
- Domain names must match exactly

JSON output only:"""

        print(f"[QuestCompose] Calling LLM for subtopic-aware outline (target: {target_steps} steps)...", flush=True)
        
        outline_steps = []
        outline_parse_attempts = 0
        max_attempts = 2
        
        while outline_parse_attempts < max_attempts and not outline_steps:
            outline_parse_attempts += 1
            
            try:
                outline_result = llm_client.complete_system(
                    system=outline_system,
                    user=outline_user,
                    command="quest-compose-outline",
                    think_mode=True,
                )
            except Exception as e:
                print(f"[QuestCompose] Outline LLM error (attempt {outline_parse_attempts}): {e}", flush=True)
                if outline_parse_attempts >= max_attempts:
                    _progress(f"Outline failed: {e}", 25)
                    return _generate_steps_single_shot(draft, kernel, progress_callback)
                continue
            
            outline_text = outline_result.get("text", "").strip()
            print(f"[QuestCompose] Outline response length: {len(outline_text)}", flush=True)
            
            # Parse outline with resilient parser
            try:
                outline_data = _parse_json_resilient(outline_text)
                
                if isinstance(outline_data, dict):
                    outline_steps = outline_data.get("outline", [])
                elif isinstance(outline_data, list):
                    outline_steps = outline_data
                
                if not outline_steps:
                    raise ValueError("No outline steps in response")
                
                # Normalize subtopics field for each step
                for step in outline_steps:
                    _normalize_outline_step_subtopics(step)
                
                print(f"[QuestCompose] Parsed {len(outline_steps)} outline steps", flush=True)
                
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[QuestCompose] Outline parse error (attempt {outline_parse_attempts}): {e}", flush=True)
                print(f"[QuestCompose] Raw outline: {outline_text[:500]}...", flush=True)
                
                if outline_parse_attempts >= max_attempts:
                    # Last resort: generate outline programmatically
                    print(f"[QuestCompose] Generating programmatic outline as fallback", flush=True)
                    outline_steps = _generate_programmatic_outline(domains, target_steps)
        
        if not outline_steps:
            print(f"[QuestCompose] No outline after {max_attempts} attempts, using single-shot", flush=True)
            return _generate_steps_single_shot(draft, kernel, progress_callback)
        
        _progress(f"Outline: {len(outline_steps)} steps planned", 30)
        
        # ═══════════════════════════════════════════════════════════════════════
        # DOMAIN COVERAGE VALIDATION (existing behavior)
        # ═══════════════════════════════════════════════════════════════════════
        
        covered_domains = set()
        domain_step_count = {}
        
        for step in outline_steps:
            domain = step.get("domain", "Unknown")
            covered_domains.add(domain.lower())
            domain_step_count[domain] = domain_step_count.get(domain, 0) + 1
        
        print(f"[QuestCompose] Domain coverage in outline: {domain_step_count}", flush=True)
        
        # Check for missing domains
        missing_domains = []
        for d in domains:
            d_name = d.get("name", "").lower()
            if not any(d_name in cd or cd in d_name for cd in covered_domains):
                missing_domains.append(d.get("name", "Unknown"))
        
        if missing_domains:
            print(f"[QuestCompose] WARNING: Missing domains in outline: {missing_domains}", flush=True)
            # Add placeholder steps for missing domains
            for missing in missing_domains:
                domain_subtopics = domain_subtopic_map.get(missing, [])
                if domain_subtopics:
                    # Create one step per subtopic for missing domain
                    for st in domain_subtopics:
                        outline_steps.append({
                            "day": len(outline_steps) + 1,
                            "domain": missing,
                            "subtopics": [st],
                            "topic": f"{missing}: {st}",
                            "type": "info",
                            "_generation_mode": "domain_patch"
                        })
                else:
                    # No subtopics - create 3 generic steps
                    for i in range(3):
                        outline_steps.append({
                            "day": len(outline_steps) + 1,
                            "domain": missing,
                            "subtopics": [],
                            "topic": f"{missing} - Part {i+1}",
                            "type": "info" if i == 0 else "apply" if i == 1 else "boss",
                            "_generation_mode": "domain_patch"
                        })
            _progress(f"Added steps for {len(missing_domains)} missing domains", 33)
        
        # ═══════════════════════════════════════════════════════════════════════
        # SUBTOPIC COVERAGE VALIDATION (NEW)
        # ═══════════════════════════════════════════════════════════════════════
        # Ensure every subtopic is covered by at least one step
        
        _progress("Validating subtopic coverage...", 35)
        
        # Only do subtopic audit if we have subtopics
        total_subtopics = sum(len(st) for st in domain_subtopic_map.values())
        
        if total_subtopics > 0:
            # Audit subtopic coverage
            subtopic_coverage = _audit_subtopic_coverage(outline_steps, domain_subtopic_map)
            missing_subtopics = _get_missing_subtopics(subtopic_coverage)
            
            # Log coverage details
            _log_subtopic_coverage(subtopic_coverage, missing_subtopics)
            
            # Patch missing subtopics
            if missing_subtopics:
                patch_steps = _generate_subtopic_patch_steps(missing_subtopics, len(outline_steps))
                outline_steps.extend(patch_steps)
                
                total_patched = sum(len(st) for st in missing_subtopics.values())
                print(f"[QuestCompose] Added {total_patched} patch step(s) for missing subtopics.", flush=True)
                _progress(f"Patched {total_patched} missing subtopics", 37)
        else:
            print(f"[QuestCompose] No subtopics defined, skipping subtopic coverage audit", flush=True)
        
        # ═══════════════════════════════════════════════════════════════════════
        # BOSS STEP ENFORCEMENT
        # ═══════════════════════════════════════════════════════════════════════
        # Ensure exactly one BOSS per domain, positioned as the last step
        
        _progress("Enforcing boss steps...", 38)
        
        # Enforce one BOSS per domain (normalizes step_type and fixes violations)
        outline_steps = _enforce_boss_per_domain(outline_steps, domains, domain_subtopic_map)
        
        # Ensure at least one APPLY in first 5 days (prevents INFO-heavy starts)
        outline_steps = _ensure_early_apply_step(outline_steps)
        
        # Log step type distribution
        _log_step_type_distribution(outline_steps)
        
        print(f"[QuestCompose:Boss] Boss normalization complete.", flush=True)
        
        # Renumber days sequentially
        for i, step in enumerate(outline_steps):
            step["day"] = i + 1
        
        print(f"[QuestCompose] Final outline: {len(outline_steps)} steps", flush=True)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE 3: SUBTOPIC-AWARE CONTENT GENERATION (PER DOMAIN)
        # ═══════════════════════════════════════════════════════════════════════
        # Generate detailed content one domain at a time, using subtopics
        
        _progress("Phase 3: Generating subtopic-aware content by domain...", 40)
        
        all_steps = []
        
        # Group outline steps by domain
        domain_groups = {}
        for step in outline_steps:
            domain = step.get("domain", "General")
            if domain not in domain_groups:
                domain_groups[domain] = []
            domain_groups[domain].append(step)
        
        total_domains = len(domain_groups)
        
        for domain_idx, (domain_name, domain_outline) in enumerate(domain_groups.items()):
            # Calculate progress (40% to 90% for content generation)
            domain_progress = int(40 + (50 * (domain_idx + 1) / total_domains))
            
            # Get subtopics for this domain
            domain_subtopics = domain_subtopic_map.get(domain_name, [])
            
            _progress(f"Generating {domain_name} ({len(domain_outline)} steps, {len(domain_subtopics)} subtopics)...", domain_progress)
            print(f"[QuestCompose] Generating content for domain '{domain_name}' (subtopics: {domain_subtopics})", flush=True)
            
            # Build subtopic-aware outline context for this domain with step_type
            domain_outline_text = ""
            for s in domain_outline:
                step_subtopics = s.get('subtopics', [])
                step_type = s.get('step_type', 'INFO')
                subtopics_str = f" [Subtopics: {', '.join(step_subtopics)}]" if step_subtopics else ""
                domain_outline_text += f"- Day {s['day']}: {s.get('topic', 'TBD')} (step_type: {step_type}){subtopics_str}\n"
                
                # Debug log with step_type
                print(f"[QuestCompose] Step {s['day']} ({domain_name} / {step_type}) subtopics: {step_subtopics}", flush=True)
            
            # Build subtopics context for prompt
            subtopics_context = ""
            if domain_subtopics:
                subtopics_context = f"""
**Domain Subtopics (for reference):**
{chr(10).join(['- ' + st for st in domain_subtopics])}

Each step below has specific subtopic(s) it must focus on. Ensure the content deeply covers those subtopics.
"""
            
            content_system = """You are a micro-learning content designer.

═══════════════════════════════════════════════════════════════════════════════
HARD CONSTRAINTS - EVERY STEP MUST FOLLOW THESE
═══════════════════════════════════════════════════════════════════════════════

1. Each step = 60-90 minutes (tired working adult)
2. EXACTLY 3-4 actions per step
3. Each action = 15-25 minutes, specific and completable
4. ONE theme per step (never mix reading + lab + reflection)
5. Each step's content MUST focus on its assigned subtopic(s)

═══════════════════════════════════════════════════════════════════════════════
STEP TYPE GUIDANCE
═══════════════════════════════════════════════════════════════════════════════

Generate content appropriate to the step_type:

**INFO** (concept/reading day):
- Actions: Read docs, watch videos, study diagrams, take notes
- Focus on understanding theory and concepts

**APPLY** (hands-on lab day):
- Actions: Configure, build, deploy, exploit, defend, test
- Focus on practical skills, walkthroughs, CTF-style exercises

**RECALL** (review day):
- Actions: Create flashcards, take quizzes, write cheat sheets, summarize
- Focus on retention and self-testing

**BOSS** (capstone day):
- This is a BOSS FIGHT - a full-chain capstone lab
- Actions should chain multiple skills into a realistic scenario
- The learner must combine knowledge from multiple subtopics
- Make it challenging but achievable in 90 minutes
- Include multi-step attack/defense flows or integrated projects
- Example: "Complete a full privilege escalation chain from S3 → IAM → persistence"

BAD actions (NEVER use):
- "Set up complete environment" ❌
- "Research thoroughly" ❌
- "Master the fundamentals" ❌
- "Build and deploy" ❌

GOOD actions:
- "Read pages 10-20 on X" ✓
- "Watch 15-min video" ✓
- "Install tool Y" ✓
- "Write 3-bullet summary" ✓
- "Complete CTF challenge: exploit X to gain Y" ✓

Output ONLY JSON array. No markdown. Include "subtopics" and "step_type" fields from input."""

            content_user = f"""Generate micro-step content for the "{domain_name}" domain.

**Quest:** {title}
{subtopics_context}
**Steps to generate (with their step_type and assigned subtopics):**
{domain_outline_text}

Generate a JSON array with EXACTLY {len(domain_outline)} steps.
PRESERVE the subtopics and step_type fields from each step.

[
  {{
    "step_type": "INFO",
    "title": "Day X: [Micro-Topic focused on subtopic]",
    "prompt": "Today you will [ONE focused goal related to subtopic]. (2-3 sentences max)",
    "actions": ["[15-25 min task about subtopic]", "[15-25 min task]", "[15-25 min task]"],
    "subtopics": ["copy from input"]
  }},
  {{
    "step_type": "BOSS",
    "title": "Day Y: {domain_name} Boss Fight",
    "prompt": "Today is your capstone challenge. You will chain together [multiple subtopics] into a full scenario.",
    "actions": ["[Multi-step challenge action 1]", "[Challenge action 2]", "[Challenge action 3]", "[Final validation]"],
    "subtopics": ["multiple", "subtopics", "from input"]
  }}
]

REMEMBER: 
- 3-4 actions each, 60-90 min total, ONE theme per step
- Content MUST focus on the listed subtopics
- BOSS steps should be challenging capstone scenarios
- Copy the subtopics and step_type from input to output

JSON array only:"""

            try:
                content_result = llm_client.complete_system(
                    system=content_system,
                    user=content_user,
                    command="quest-compose-content",
                    think_mode=True,
                )
                
                content_text = content_result.get("text", "").strip()
                
                # Parse content
                start_idx = content_text.find('[')
                end_idx = content_text.rfind(']') + 1
                
                if start_idx != -1 and end_idx > 0:
                    content_json = content_text[start_idx:end_idx]
                    content_steps = json.loads(content_json)
                    
                    # Normalize and add steps, preserving subtopics and step_type from outline
                    for step_idx, step_data in enumerate(content_steps):
                        if not isinstance(step_data, dict):
                            continue
                        
                        # Get step_type - prefer from outline (authoritative)
                        if step_idx < len(domain_outline):
                            outline_step = domain_outline[step_idx]
                            step_type = outline_step.get("step_type", "INFO")
                        else:
                            step_type = _normalize_step_type(step_data)
                        
                        # Legacy type field for backwards compatibility
                        legacy_type = step_type.lower()
                        if legacy_type not in {"info", "recall", "apply", "reflect", "boss"}:
                            legacy_type = "info"
                        
                        actions = step_data.get("actions", [])
                        if not isinstance(actions, list):
                            actions = []
                        actions = [str(a) for a in actions if a]
                        
                        # ENFORCE MICRO-STEP CONSTRAINTS
                        if len(actions) > 4:
                            actions = actions[:4]
                        if len(actions) < 2:
                            actions.append("Review what you learned today")
                        
                        # Get subtopics - prefer from outline (authoritative)
                        if step_idx < len(domain_outline):
                            step_subtopics = domain_outline[step_idx].get("subtopics", [])
                        else:
                            step_subtopics = step_data.get("subtopics", [])
                        
                        # Normalize subtopics
                        if isinstance(step_subtopics, str):
                            step_subtopics = [step_subtopics] if step_subtopics else []
                        elif not isinstance(step_subtopics, list):
                            step_subtopics = []
                        
                        step = {
                            "id": f"step_{len(all_steps) + 1}",
                            "type": legacy_type,        # Legacy field for backwards compat
                            "step_type": step_type,     # New canonical field
                            "prompt": step_data.get("prompt", ""),
                            "title": step_data.get("title", f"Day {len(all_steps) + 1}"),
                            "actions": actions,
                            "domain": domain_name,
                            "subtopics": step_subtopics,
                        }
                        
                        if step["prompt"]:
                            all_steps.append(step)
                    
            except Exception as e:
                _progress(f"Domain {domain_name} error: {e}", domain_progress)
                # Create placeholder steps for failed domain, preserving subtopics and step_type
                for outline_step in domain_outline:
                    step_subtopics = outline_step.get("subtopics", [])
                    step_type = outline_step.get("step_type", "INFO")
                    all_steps.append({
                        "id": f"step_{len(all_steps) + 1}",
                        "type": step_type.lower(),
                        "step_type": step_type,
                        "prompt": f"Complete: {outline_step.get('topic', domain_name)}",
                        "title": f"Day {len(all_steps) + 1}: {outline_step.get('topic', domain_name)}",
                        "actions": [
                            f"Study {outline_step.get('topic', domain_name)}",
                            "Take notes on key concepts",
                            "Review and summarize",
                        ],
                        "domain": domain_name,
                        "subtopics": step_subtopics,
                    })
                continue
        
        # ═══════════════════════════════════════════════════════════════════════
        # FINAL COVERAGE VALIDATION
        # ═══════════════════════════════════════════════════════════════════════
        
        final_domain_count = {}
        final_subtopic_count = 0
        final_boss_count = {}
        
        # Validate and count all steps
        for step in all_steps:
            # ENSURE ALL REQUIRED FIELDS ARE PRESENT (Bug fix #2)
            if "domain" not in step or not step["domain"]:
                step["domain"] = "Unknown"
                print(f"[QuestCompose] WARNING: Step '{step.get('title', '?')}' missing domain, set to 'Unknown'", flush=True)
            
            if "subtopics" not in step:
                step["subtopics"] = []
            
            if "step_type" not in step:
                step["step_type"] = _normalize_step_type(step)
            
            # Count for stats
            d = step.get("domain", "Unknown")
            final_domain_count[d] = final_domain_count.get(d, 0) + 1
            final_subtopic_count += len(step.get("subtopics", []))
            if step.get("step_type") == "BOSS":
                final_boss_count[d] = final_boss_count.get(d, 0) + 1
        
        print(f"[QuestCompose] Final coverage: {final_domain_count}", flush=True)
        print(f"[QuestCompose] Steps with subtopics: {final_subtopic_count} subtopic references", flush=True)
        print(f"[QuestCompose:Boss] Final BOSS steps per domain: {final_boss_count}", flush=True)
        print(f"[QuestCompose:MultiPhase] SUCCESS - {len(all_steps)} steps across {len(final_domain_count)} domains", flush=True)
        
        if all_steps:
            _progress(f"Complete: {len(all_steps)} steps across {len(final_domain_count)} domains", 95)
            
            # Add generation mode metadata to each step for debugging
            for step in all_steps:
                step["_generation_mode"] = "multiphase"
            
            return all_steps
        else:
            print(f"[QuestCompose:MultiPhase] No steps generated, falling back to SingleShot", flush=True)
            _progress("No steps generated, using fallback", 50)
            return _generate_steps_single_shot(draft, kernel, progress_callback)
        
    except Exception as e:
        print(f"[QuestCompose:MultiPhase] EXCEPTION: {e}", flush=True)
        import traceback
        traceback.print_exc()
        print(f"[QuestCompose:MultiPhase] Falling back to SingleShot due to exception", flush=True)
        return _generate_steps_single_shot(draft, kernel, progress_callback)


def _generate_steps_single_shot(
    draft: Dict[str, Any], 
    kernel: Any,
    progress_callback: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """
    Original single-shot step generation (fallback).
    
    Used when chunked generation fails or for simple quests.
    """
    def _progress(msg: str, pct: int):
        if progress_callback:
            try:
                progress_callback(msg, pct)
            except:
                pass
        print(f"[QuestCompose:SingleShot] {msg} ({pct}%)", flush=True)
    
    try:
        print(f"[QuestCompose:SingleShot] Starting fallback generation...", flush=True)
        
        llm_client = getattr(kernel, 'llm_client', None)
        if not llm_client:
            print(f"[QuestCompose:SingleShot] ERROR: No LLM client", flush=True)
            return []
        
        title = draft.get("title", "Untitled Quest")
        category = draft.get("category", "general")
        objectives = draft.get("objectives", [])
        
        print(f"[QuestCompose:SingleShot] Title: {title}, Objectives: {len(objectives)}", flush=True)
        
        objectives_text = "\n".join([f"- {obj}" for obj in objectives]) if objectives else "- Complete the quest"
        
        system_prompt = """You are a micro-learning architect for NovaOS.

═══════════════════════════════════════════════════════════════════════════════
CRITICAL: ONE STEP = ONE DAY = 60-90 MINUTES FOR A WORKING ADULT
═══════════════════════════════════════════════════════════════════════════════

HARD RULES:
1. Each step = 60-90 minutes MAX (tired adult after work, not full-time student)
2. EXACTLY 3-4 actions per step (not 6, not 8, not 10)
3. ONE theme per step (info OR apply, NEVER both combined)
4. Actions must be atomic and completable in 15-25 minutes each

DECOMPOSITION:
- Multi-hour topic → split into multiple days
- Reading + lab → separate days
- Multiple concepts → separate days
- MORE DAYS = BETTER

BAD ACTIONS (never use):
- "Set up complete environment" ❌
- "Research thoroughly" ❌  
- "Build and deploy" ❌
- "Master fundamentals" ❌

GOOD ACTIONS:
- "Read pages 10-20 on X" ✓
- "Watch 15-min video on Y" ✓
- "Install Z tool" ✓
- "Write 3 bullet summary" ✓

Respond ONLY with valid JSON array. No markdown."""
        
        user_prompt = f"""Create ATOMIC MICRO-STEPS for this quest.

**Quest Title:** {title}
**Category:** {category}

**Learning Objectives:**
{objectives_text}

Generate 10-30 micro-steps. Each step:
- 60-90 minutes max
- EXACTLY 3-4 actions  
- ONE focused theme
- Builds on previous day

JSON array:
[
  {{
    "type": "info|apply|recall|reflect|boss",
    "title": "Day X: [Single Micro-Topic]",
    "prompt": "Today's focused micro-goal (2-3 sentences max)",
    "actions": ["[15-25 min task]", "[15-25 min task]", "[15-25 min task]"]
  }}
]

JSON only:"""

        print(f"[QuestCompose:SingleShot] Calling LLM...", flush=True)
        
        try:
            result = llm_client.complete_system(
                system=system_prompt,
                user=user_prompt,
                command="quest-compose",
                think_mode=True,
            )
            print(f"[QuestCompose:SingleShot] LLM call complete", flush=True)
        except Exception as api_error:
            print(f"[QuestCompose:SingleShot] LLM ERROR: {api_error}", flush=True)
            import traceback
            traceback.print_exc()
            return []
        
        response_text = result.get("text", "").strip()
        print(f"[QuestCompose:SingleShot] Response length: {len(response_text)}", flush=True)
        print(f"[QuestCompose:SingleShot] Response preview: {response_text[:300] if response_text else 'EMPTY'}", flush=True)
        
        if not response_text:
            print(f"[QuestCompose:SingleShot] Empty response from LLM", flush=True)
            return []
        
        # Find JSON array in response
        start_idx = response_text.find('[')
        end_idx = response_text.rfind(']') + 1
        
        if start_idx == -1 or end_idx == 0:
            return []
        
        json_text = response_text[start_idx:end_idx]
        steps_data = json.loads(json_text)
        
        if not isinstance(steps_data, list):
            return []
        
        # Normalize steps
        steps = []
        valid_types = {"info", "recall", "apply", "reflect", "boss", "action", "transfer", "mini_boss"}
        
        for i, step_data in enumerate(steps_data, 1):
            if not isinstance(step_data, dict):
                continue
            
            step_type = step_data.get("type", "info").lower()
            if step_type not in valid_types:
                step_type = "info"
            
            actions = step_data.get("actions", [])
            if not isinstance(actions, list):
                actions = []
            actions = [str(a) for a in actions if a]
            
            # ═══════════════════════════════════════════════════════
            # ENFORCE MICRO-STEP CONSTRAINTS
            # ═══════════════════════════════════════════════════════
            
            # Limit to 4 actions max (micro-step constraint)
            if len(actions) > 4:
                print(f"[QuestCompose] Trimming actions from {len(actions)} to 4", flush=True)
                actions = actions[:4]
            
            # Ensure at least 2 actions
            if len(actions) < 2:
                actions.append("Review what you learned today")
            
            step = {
                "id": f"step_{i}",
                "type": step_type,
                "prompt": step_data.get("prompt", step_data.get("description", "")),
                "title": step_data.get("title", f"Step {i}"),
                "actions": actions,
                "_generation_mode": "singleshot",  # Mark as fallback-generated
            }
            
            if step["prompt"]:
                steps.append(step)
        
        print(f"[QuestCompose:SingleShot] SUCCESS - Generated {len(steps)} steps", flush=True)
        _progress(f"Complete: {len(steps)} steps", 95)
        return steps if steps else []
        
    except json.JSONDecodeError as e:
        print(f"[QuestCompose:SingleShot] JSON parse error: {e}", flush=True)
        return []
    except Exception as e:
        print(f"[QuestCompose] Single-shot error: {e}", flush=True)
        return []


# =============================================================================
# v0.10.3: STREAMING SUPPORT FOR QUEST COMPOSE
# =============================================================================

def _generate_steps_with_llm_streaming(
    draft: Dict[str, Any], 
    kernel: Any,
    session_id: str,
) -> Generator[Dict[str, Any], None, None]:
    """
    Streaming version of step generation that yields progress events.
    
    v0.10.4: Gemini-first routing with GPT streaming fallback.
    
    Instead of blocking until all steps are generated, this yields events:
    - {"type": "log", "message": "..."} - Log messages
    - {"type": "progress", "message": "...", "percent": N} - Progress updates
    - {"type": "update", "content": "..."} - Partial content previews
    - {"type": "steps", "steps": [...]} - Final generated steps
    - {"type": "error", "message": "..."} - Error occurred
    
    This allows the frontend to show real-time progress during the heavy
    LLM generation phases (outline + content), avoiding Cloudflare 524 timeouts.
    
    Args:
        draft: Quest draft dictionary with title, objectives, domains, etc.
        kernel: NovaKernel instance
        session_id: Session ID for logging
    
    Yields:
        Dict events with type and payload
    """
    def _log(msg: str):
        return {"type": "log", "message": f"[QuestCompose] {msg}"}
    
    def _progress(msg: str, pct: int):
        return {"type": "progress", "message": msg, "percent": pct}
    
    def _update(content: str):
        return {"type": "update", "content": content}
    
    def _steps(steps_list: List[Dict[str, Any]]):
        return {"type": "steps", "steps": steps_list}
    
    def _error(msg: str):
        return {"type": "error", "message": msg}
    
    try:
        yield _log("Starting step generation...")
        yield _progress("Initializing...", 5)
        
        # Get LLM client from kernel
        llm_client = getattr(kernel, 'llm_client', None)
        if not llm_client:
            yield _error("No LLM client available")
            return
        
        # ═══════════════════════════════════════════════════════════════════════
        # v1.0.0: LESSON ENGINE (Priority 1)
        # ═══════════════════════════════════════════════════════════════════════
        # 3-phase retrieval-backed generation:
        #   Phase A: Gemini + web grounding for real resources
        #   Phase B: Gemini for atomic step building (60-120 min each)  
        #   Phase C: GPT-5.1 for sequencing and polish
        # ═══════════════════════════════════════════════════════════════════════
        
        domains = draft.get("domains", [])
        
        if _HAS_LESSON_ENGINE and domains:
            yield _log("Lesson Engine available - using 3-phase retrieval-backed generation")
            yield _progress("Lesson Engine starting...", 10)
            
            quest_id = draft.get("id") or f"quest_{session_id}"
            title = draft.get("title", "Untitled Quest")
            
            engine_success = False
            try:
                for event in generate_lesson_plan_streaming(
                    domains=domains,
                    quest_id=quest_id,
                    quest_title=title,
                    kernel=kernel,
                    user_constraints=None,
                ):
                    if event.get("type") == "steps":
                        yield _log(f"Lesson Engine SUCCESS: {len(event.get('steps', []))} steps")
                        yield _progress("Lesson Engine complete!", 95)
                        yield event
                        engine_success = True
                        break
                    elif event.get("type") == "error":
                        yield _log(f"Lesson Engine error: {event.get('message', '')}")
                        break
                    else:
                        yield event
                
                if engine_success:
                    return  # Done - skip Gemini router and GPT fallback
                
            except Exception as e:
                yield _log(f"Lesson Engine exception: {e}")
            
            yield _log("Lesson Engine did not succeed, falling back...")
        
        elif _HAS_LESSON_ENGINE and not domains:
            yield _log("Lesson Engine available but no domains - skipping to Gemini router")
        else:
            yield _log("Lesson Engine not loaded - using Gemini router")
        
        
        # ═══════════════════════════════════════════════════════════════════════
        # TRY GEMINI ROUTER FIRST (fast, validated)
        # ═══════════════════════════════════════════════════════════════════════
        yield _log("Trying Gemini router...")
        yield _progress("Gemini generation...", 10)
        
        if _HAS_GEMINI:
            router_steps = gemini_generate_quest_steps(draft, llm_client)
            if router_steps:
                yield _log(f"Gemini router SUCCESS: {len(router_steps)} validated steps")
                yield _progress("Gemini complete!", 95)
                yield _steps(router_steps)
                return
            yield _log("Gemini router failed, falling back to streaming GPT...")
        else:
            yield _log("Gemini not available, using streaming GPT...")
        
        # ═══════════════════════════════════════════════════════════════════════
        # GPT STREAMING FALLBACK (original implementation)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("GPT streaming generation...", 15)
        
        title = draft.get("title", "Untitled Quest")
        category = draft.get("category", "general")
        objectives = draft.get("objectives", [])
        
        yield _log(f"Quest: {title}")
        yield _log(f"Objectives: {len(objectives)}")
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE 1: USE CONFIRMED DOMAINS
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase 1: Loading confirmed domains...", 20)
        
        domains = draft.get("domains", [])
        
        if domains:
            yield _log(f"Using {len(domains)} confirmed domains")
            for d in domains:
                domain_name = d.get("name", "?")
                subtopics = d.get("subtopics", [])
                yield _log(f"  - {domain_name}: {len(subtopics)} subtopics")
        else:
            # Fallback: extract from objectives
            yield _log("No confirmed domains, extracting from objectives...")
            yield _progress("Phase 1: Extracting domains from objectives...", 22)
            
            raw_text = "\n".join(objectives) if isinstance(objectives, list) else str(objectives)
            domains = _structural_extract_domains(raw_text)
            yield _log(f"Extracted {len(domains)} domains")
        
        if not domains:
            yield _log("Warning: No domains found, using single-shot fallback")
            yield _progress("Using fallback generation...", 15)
            
            # Use single-shot fallback (non-streaming)
            steps = _generate_steps_single_shot(draft, kernel)
            if steps:
                yield _steps(steps)
            else:
                yield _error("Could not generate steps")
            return
        
        # Calculate target steps
        total_subtopics = sum(len(d.get("subtopics", [])) for d in domains)
        steps_per_subtopic = 2
        boss_steps = len(domains)
        target_steps = max(10, (total_subtopics * steps_per_subtopic) + boss_steps)
        target_steps = min(target_steps, 45)
        
        yield _log(f"Target: {target_steps} steps across {len(domains)} domains")
        yield _progress("Phase 1 complete", 20)
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE 2: GENERATE SUBTOPIC-AWARE OUTLINE
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase 2: Generating outline...", 25)
        yield _log("Creating subtopic-aware outline with LLM...")
        
        # Build domain list text for prompt
        domain_list_text = ""
        for d in domains:
            domain_name = d.get("name", "Unknown")
            subtopics = d.get("subtopics", [])
            if subtopics:
                subtopic_str = ", ".join(subtopics)
                domain_list_text += f"- {domain_name}: [{subtopic_str}]\n"
            else:
                domain_list_text += f"- {domain_name}: (general coverage)\n"
        
        outline_system = """You are a curriculum architect for NovaOS micro-learning.
Create a detailed day-by-day outline that ensures ALL subtopics are covered.

RULES:
1. Every subtopic MUST appear in at least one step
2. Each domain ends with exactly ONE BOSS step
3. BOSS steps integrate 2-4 subtopics into a capstone
4. Distribute subtopics evenly across the timeline

Output ONLY valid JSON. No markdown."""

        outline_user = f"""Create a {target_steps}-step outline for "{title}".

DOMAINS AND SUBTOPICS TO COVER:
{domain_list_text}

OUTPUT THIS EXACT JSON STRUCTURE:
{{
  "total_steps": {target_steps},
  "outline": [
    {{"day": 1, "domain": "Domain Name", "subtopics": ["Subtopic A"], "topic": "Intro to Subtopic A", "step_type": "INFO"}},
    {{"day": 2, "domain": "Domain Name", "subtopics": ["Subtopic A"], "topic": "Hands-on with Subtopic A", "step_type": "APPLY"}},
    {{"day": 3, "domain": "Domain Name", "subtopics": ["Subtopic B"], "topic": "Learn Subtopic B", "step_type": "INFO"}},
    {{"day": 4, "domain": "Domain Name", "subtopics": ["Subtopic A", "Subtopic B"], "topic": "Domain Capstone", "step_type": "BOSS"}}
  ]
}}

JSON only:"""

        yield _log("Calling LLM for outline generation...")
        
        outline_steps = []
        try:
            # Check if streaming is available
            if hasattr(llm_client, 'stream_complete_system'):
                # Use streaming LLM call for outline
                outline_text = ""
                chunk_count = 0
                for chunk in llm_client.stream_complete_system(
                    system=outline_system,
                    user=outline_user,
                    command="quest-compose-outline-stream",
                    think_mode=True,
                ):
                    outline_text += chunk
                    chunk_count += 1
                    # Yield periodic updates so connection stays alive
                    if chunk_count % 20 == 0:
                        yield _log(f"Generating outline... ({len(outline_text)} chars)")
            else:
                # Fallback to non-streaming
                yield _log("Using non-streaming LLM call for outline...")
                result = llm_client.complete_system(
                    system=outline_system,
                    user=outline_user,
                    command="quest-compose-outline",
                    think_mode=True,
                )
                outline_text = result.get("text", "").strip()
            
            yield _progress("Phase 2: Parsing outline...", 35)
            
            # Parse the outline JSON
            start_idx = outline_text.find('{')
            end_idx = outline_text.rfind('}') + 1
            
            if start_idx != -1 and end_idx > 0:
                outline_json = outline_text[start_idx:end_idx]
                parsed = json.loads(outline_json)
                outline_steps = parsed.get("outline", [])
                yield _log(f"Parsed {len(outline_steps)} outline steps")
            
        except Exception as e:
            yield _log(f"Outline LLM error: {e}")
            yield _log("Using programmatic outline fallback...")
            outline_steps = _generate_programmatic_outline(domains, target_steps)
        
        if not outline_steps:
            yield _log("Using programmatic outline fallback...")
            outline_steps = _generate_programmatic_outline(domains, target_steps)
        
        yield _progress("Phase 2 complete", 40)
        yield _update(f"Outline: {len(outline_steps)} steps planned")
        
        # ═══════════════════════════════════════════════════════════════════════
        # PHASE 3: GENERATE CONTENT PER DOMAIN (STREAMING)
        # ═══════════════════════════════════════════════════════════════════════
        yield _progress("Phase 3: Generating step content...", 45)
        
        # Group outline by domain
        domain_outlines = {}
        for step in outline_steps:
            domain = step.get("domain", "Unknown")
            if domain not in domain_outlines:
                domain_outlines[domain] = []
            domain_outlines[domain].append(step)
        
        all_steps = []
        domain_count = len(domain_outlines)
        processed_domains = 0
        
        for domain_name, domain_outline in domain_outlines.items():
            processed_domains += 1
            base_percent = 45 + int((processed_domains / domain_count) * 45)
            
            yield _log(f"Generating content for domain: {domain_name}")
            yield _progress(f"Domain {processed_domains}/{domain_count}: {domain_name}", base_percent)
            
            # Get subtopics for this domain
            domain_info = next((d for d in domains if d.get("name") == domain_name), {})
            subtopics = domain_info.get("subtopics", [])
            
            # Build outline text for this domain
            domain_outline_text = ""
            for i, step in enumerate(domain_outline, 1):
                step_type = step.get("step_type", "INFO")
                topic = step.get("topic", f"Step {i}")
                step_subtopics = step.get("subtopics", [])
                domain_outline_text += f"{i}. [{step_type}] {topic} (subtopics: {step_subtopics})\n"
            
            content_system = """You are a micro-learning content designer.

HARD CONSTRAINTS:
1. Each step = 60-90 minutes (tired working adult)
2. EXACTLY 3-4 actions per step
3. Each action = 15-25 minutes, specific and completable
4. ONE theme per step

STEP TYPES:
- INFO: Reading, videos, studying concepts
- APPLY: Hands-on labs, building, testing
- RECALL: Flashcards, quizzes, summaries
- BOSS: Capstone challenge, multi-step scenario

Output ONLY JSON array. No markdown."""

            content_user = f"""Generate micro-step content for "{domain_name}".

**Quest:** {title}
**Subtopics to cover:** {subtopics}

**Steps to generate:**
{domain_outline_text}

Generate a JSON array with EXACTLY {len(domain_outline)} steps:
[
  {{
    "step_type": "INFO",
    "title": "Day X: Topic",
    "prompt": "Today's goal (2-3 sentences)",
    "actions": ["15-25 min task", "15-25 min task", "15-25 min task"],
    "subtopics": ["from input"]
  }}
]

JSON array only:"""

            try:
                # Stream content generation if available
                if hasattr(llm_client, 'stream_complete_system'):
                    content_text = ""
                    chunk_count = 0
                    for chunk in llm_client.stream_complete_system(
                        system=content_system,
                        user=content_user,
                        command="quest-compose-content-stream",
                        think_mode=True,
                    ):
                        content_text += chunk
                        chunk_count += 1
                        # Keep connection alive
                        if chunk_count % 30 == 0:
                            yield _log(f"  Generating content... ({len(content_text)} chars)")
                else:
                    # Fallback to non-streaming
                    result = llm_client.complete_system(
                        system=content_system,
                        user=content_user,
                        command="quest-compose-content",
                        think_mode=True,
                    )
                    content_text = result.get("text", "").strip()
                
                # Parse content
                start_idx = content_text.find('[')
                end_idx = content_text.rfind(']') + 1
                
                if start_idx != -1 and end_idx > 0:
                    content_json = content_text[start_idx:end_idx]
                    content_steps = json.loads(content_json)
                    
                    # Normalize and add steps
                    step_num = len(all_steps) + 1
                    for step_data in content_steps:
                        if not isinstance(step_data, dict):
                            continue
                        
                        step_type = step_data.get("step_type", step_data.get("type", "info"))
                        step_type = str(step_type).lower()
                        valid_types = {"info", "recall", "apply", "reflect", "boss", "action", "transfer", "mini_boss"}
                        if step_type not in valid_types:
                            step_type = "info"
                        
                        actions = step_data.get("actions", [])
                        if not isinstance(actions, list):
                            actions = []
                        actions = [str(a) for a in actions if a][:4]  # Max 4 actions
                        
                        step = {
                            "id": f"step_{step_num}",
                            "type": step_type,
                            "prompt": step_data.get("prompt", step_data.get("description", "")),
                            "title": step_data.get("title", f"Step {step_num}"),
                            "actions": actions,
                            "subtopics": step_data.get("subtopics", []),
                            "_domain": domain_name,
                            "_generation_mode": "streaming",
                        }
                        
                        if step["prompt"]:
                            all_steps.append(step)
                            step_num += 1
                    
                    yield _log(f"  Generated {len(content_steps)} steps for {domain_name}")
                
            except Exception as e:
                yield _log(f"  Content generation error for {domain_name}: {e}")
                # Continue with other domains
        
        yield _progress("Phase 3 complete", 95)
        
        # ═══════════════════════════════════════════════════════════════════════
        # FINALIZE
        # ═══════════════════════════════════════════════════════════════════════
        if all_steps:
            yield _log(f"Generation complete: {len(all_steps)} total steps")
            yield _progress("Complete!", 100)
            yield _steps(all_steps)
        else:
            yield _log("No steps generated, trying single-shot fallback...")
            yield _progress("Using fallback...", 98)
            
            fallback_steps = _generate_steps_single_shot(draft, kernel)
            if fallback_steps:
                yield _steps(fallback_steps)
            else:
                yield _error("Could not generate steps after all attempts")
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield _error(f"Generation failed: {str(e)}")


def _handle_validation_stage(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
) -> CommandResponse:
    """Handle validation criteria collection."""
    if not user_input or user_input.lower() in ("skip", "s"):
        # Use default validation criteria
        session.draft["validation"] = ["Complete all steps", "Pass boss challenge (if present)"]
    else:
        criteria = _parse_list_input(user_input)
        session.draft["validation"] = criteria if criteria else ["Complete all steps"]
    
    session.stage = "tags"
    session.substage = ""
    set_compose_session(session_id, session)
    return _get_current_prompt(cmd_name, session)


def _handle_tags_stage(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
) -> CommandResponse:
    """Handle tags collection."""
    if user_input and user_input.lower() not in ("skip", "s"):
        tags = _parse_list_input(user_input)
        session.draft["tags"] = tags
    else:
        # Default tag based on category
        session.draft["tags"] = ["learning"]
    
    # Move to confirm
    session.stage = "confirm"
    session.substage = ""
    set_compose_session(session_id, session)
    return _get_current_prompt(cmd_name, session)


def _handle_confirm_stage(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
    engine: Any,
) -> CommandResponse:
    """Handle confirmation stage."""
    choice = user_input.lower()
    
    if choice in ("confirm", "yes", "y", "save"):
        # Build and save the quest
        existing_ids = list(engine._quests.keys())
        quest_dict = _build_quest_dict(session.draft, existing_ids)
        
        try:
            quest = engine.create_quest_from_spec(quest_dict)
            clear_compose_session(session_id)
            
            return _base_response(
                cmd_name,
                f"Quest saved: {quest.title}\n\n"
                f"Quest ID: {quest.id}\n\n"
                f"View it with #quest-inspect id={quest.id}\n"
                f"Start it with #quest id={quest.id}",
                {
                    "wizard_active": False,
                    "quest_id": quest.id,
                    "saved": True,
                }
            )
        except Exception as e:
            return _error_response(
                cmd_name,
                f"Error saving quest: {str(e)}",
                "SAVE_ERROR"
            )
    
    elif choice in ("edit", "e", "modify"):
        session.stage = "edit"
        set_compose_session(session_id, session)
        return _get_current_prompt(cmd_name, session)
    
    elif choice in ("cancel", "no", "n", "discard"):
        clear_compose_session(session_id)
        return _base_response(
            cmd_name,
            "Quest composition cancelled.",
            {"wizard_active": False}
        )
    
    else:
        return _base_response(
            cmd_name,
            "Please type confirm, edit, or cancel.",
            {"wizard_active": True, "stage": "confirm"}
        )


def _handle_edit_stage(
    cmd_name: str,
    session: QuestComposeSession,
    user_input: str,
    session_id: str,
) -> CommandResponse:
    """Handle edit field selection and re-collection."""
    field_map = {
        "title": ("metadata", "title"),
        "category": ("metadata", "category"),
        "difficulty": ("metadata", "difficulty"),
        "skill_path": ("metadata", "skill_path"),
        "skill_tree_path": ("metadata", "skill_path"),
        "objectives": ("objectives", ""),
        "steps": ("steps", ""),
        "validation": ("validation", ""),
        "tags": ("tags", ""),
    }
    
    field_name = user_input.lower().strip()
    
    if field_name in field_map:
        stage, substage = field_map[field_name]
        session.stage = stage
        session.substage = substage
        
        # Clear the field being edited (for steps, clear all)
        if field_name == "steps":
            session.draft["steps"] = []
        
        set_compose_session(session_id, session)
        return _get_current_prompt(cmd_name, session)
    
    else:
        return _base_response(
            cmd_name,
            "Invalid field. Please choose from: title, category, difficulty, "
            "skill_path, objectives, steps, validation, tags",
            {"wizard_active": True, "stage": "edit"}
        )


def _handle_noninteractive(
    cmd_name: str,
    args: Dict[str, Any],
    engine: Any,
) -> CommandResponse:
    """
    Handle non-interactive mode - create quest immediately if all required fields present.
    """
    required_fields = ["title", "category", "difficulty"]
    missing = [f for f in required_fields if not args.get(f)]
    
    if missing:
        return _error_response(
            cmd_name,
            f"Non-interactive mode requires: {', '.join(missing)}\n\n"
            f"Usage: #quest-compose mode=noninteractive title=\"...\" category=... difficulty=1-5",
            "MISSING_FIELDS"
        )
    
    # Build draft from args
    draft = {
        "id": args.get("id"),
        "title": args["title"],
        "category": args["category"],
        "difficulty": int(args["difficulty"]),
        "skill_tree_path": args.get("skill_tree_path") or args.get("skill_path"),
        "objectives": _parse_list_input(args.get("objectives", "")) or [],
        "steps": [],
        "validation": _parse_list_input(args.get("validation", "")) or ["Complete all steps"],
        "tags": _parse_list_input(args.get("tags", "")) or ["learning"],
    }
    
    # Parse steps if provided
    if args.get("steps"):
        draft["steps"] = _parse_steps_input(args["steps"])
    
    # Must have at least one step
    if not draft["steps"]:
        draft["steps"] = [{
            "id": "step_1",
            "type": "info",
            "prompt": f"Complete the {draft['title']} quest.",
            "title": "Quest Step",
        }]
    
    # Build and save
    existing_ids = list(engine._quests.keys())
    quest_dict = _build_quest_dict(draft, existing_ids)
    
    try:
        quest = engine.create_quest_from_spec(quest_dict)
        return _base_response(
            cmd_name,
            f"Quest created: {quest.title}\n\n"
            f"Quest ID: {quest.id}",
            {
                "quest_id": quest.id,
                "saved": True,
            }
        )
    except Exception as e:
        return _error_response(
            cmd_name,
            f"Error creating quest: {str(e)}",
            "CREATE_ERROR"
        )


# =============================================================================
# INTEGRATION HELPER
# =============================================================================

def is_compose_wizard_active(session_id: str) -> bool:
    """Check if a quest-compose wizard is active for this session."""
    return has_active_compose_session(session_id)


def process_compose_wizard_input(
    session_id: str,
    user_input: str,
    kernel: Any,
) -> Optional[CommandResponse]:
    """
    Process input for an active compose wizard.
    
    Called by the kernel when a wizard is active.
    Returns None if no wizard is active.
    """
    session = get_compose_session(session_id)
    if not session:
        return None
    
    # Check for cancel at any time
    if user_input.strip().lower() == "cancel":
        clear_compose_session(session_id)
        return _base_response(
            "quest-compose",
            "Quest composition cancelled.",
            {"wizard_active": False}
        )
    
    return _process_wizard_input(
        "quest-compose",
        session,
        user_input,
        session_id,
        kernel,  # Pass full kernel for LLM access
    )
