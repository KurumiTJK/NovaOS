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
from typing import Any, Dict, List, Optional, Tuple

from .command_types import CommandResponse


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
    })
    
    # For edit mode
    edit_field: Optional[str] = None
    
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
        Formatted string for display
    """
    lines = []
    for i, step in enumerate(steps, 1):
        step_type = step.get('type', 'info')
        title = step.get('title', step.get('prompt', '')[:50])
        
        # Step header with extra spacing
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"**{i}. [{step_type.upper()}] {title}**")
        lines.append("")
        
        if verbose:
            # Show full prompt (no italic underscores)
            prompt = step.get('prompt', '')
            if prompt:
                lines.append(prompt)
                lines.append("")
            
            # Show actions with better formatting and spacing
            actions = step.get('actions', [])
            if actions:
                lines.append("**📋 Actions:**")
                lines.append("")
                for j, action in enumerate(actions, 1):
                    lines.append(f"   {j}. {action}")
                    lines.append("")  # Add blank line after each action
        
        lines.append("")  # Extra blank line between steps
    
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def _format_preview(draft: Dict[str, Any]) -> str:
    """Format the draft quest as a preview for the user."""
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
        f"**ID:** {draft.get('id') or '(auto-generated)'}",
        f"**Title:** {draft.get('title')}",
        f"**Category:** {draft.get('category')}",
        f"**Module:** {draft.get('module_id') or '(standalone)'}",
        f"**Difficulty:** {'⭐' * difficulty}{'☆' * (5 - difficulty)} ({difficulty_label})",
    ]
    
    if draft.get('skill_tree_path'):
        lines.append(f"**Skill Path:** {draft['skill_tree_path']}")
    
    if draft.get('tags'):
        lines.append(f"**Tags:** [{', '.join(draft['tags'])}]")
    
    lines.append("")
    
    # Objectives
    if draft.get('objectives'):
        lines.append("**Objectives:**")
        for i, obj in enumerate(draft['objectives'], 1):
            lines.append(f"  {i}. {obj}")
        lines.append("")
    
    # Steps (simple list without actions)
    steps = draft.get('steps', [])
    if steps:
        lines.append(f"**Steps:** ({len(steps)} total)")
        for i, step in enumerate(steps, 1):
            step_type = step.get('type', 'info')
            title = step.get('title') or step.get('prompt', '')[:50]
            lines.append(f"  {i}. [{step_type}] {title}")
        lines.append("")
    
    # Validation
    if draft.get('validation'):
        lines.append("**Completion Criteria:**")
        for criterion in draft['validation']:
            lines.append(f"  • {criterion}")
        lines.append("")
    
    # XP Rewards
    xp = len(steps) * 5 if steps else 0
    lines.append("**Rewards:**")
    lines.append(f"  💎 {xp} XP")
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
        "**Step 1/4: Quest Metadata**\n"
        "\n"
        "What's the quest title?\n"
        "(e.g., 'JWT Basics – Intro Quest')\n"
        "\n"
        "_Type 'cancel' at any time to exit._"
    ),
    "metadata_category": (
        "**Category?**\n"
        "\n"
        "Common categories: cyber, finance, meta, learning, personal\n"
        "(Or type your own category name)"
    ),
    "metadata_module": (
        "**Module?** (optional)\n"
        "\n"
        "Which module should this quest belong to?\n"
        "\n"
        "{module_list}\n"
        "\n"
        "_Type a module name or **skip** for none_"
    ),
    "objectives": (
        "**Step 2/4: Learning Objectives**\n"
        "\n"
        "What should the learner accomplish?\n"
        "List 1-3 objectives:\n"
        "\n"
        "(e.g., '1. Understand JWT structure\\n2. Identify common vulnerabilities')"
    ),
    "steps": (
        "**Step 3/4: Quest Steps**\n"
        "\n"
        "How would you like to define the steps?\n"
        "\n"
        "• Type **generate** — Auto-generate steps based on your objectives (recommended)\n"
        "• Type **manual** — Define steps yourself\n"
    ),
    "steps_manual": (
        "**Define steps manually**\n"
        "\n"
        "For each step, specify: **type: description**\n"
        "\n"
        "Step types:\n"
        "  • info – Information/reading\n"
        "  • recall – Knowledge check\n"
        "  • apply – Hands-on practice\n"
        "  • reflect – Reflection prompt\n"
        "  • boss – Final challenge\n"
        "\n"
        "Example:\n"
        "```\n"
        "info: Read the JWT overview notes\n"
        "recall: Describe the 3 parts of a JWT\n"
        "apply: Decode a sample token\n"
        "boss: Identify a JWT vulnerability\n"
        "```\n"
        "\n"
        "Type your steps (one per line), then type **done**:"
    ),
    "steps_generating": (
        "**Generating quest steps...**\n"
        "\n"
        "Creating steps based on your objectives. One moment..."
    ),
    "validation": (
        "**Step 4/4: Final Details**\n"
        "\n"
        "How do we know the quest is complete?\n"
        "List 1-3 criteria:\n"
        "\n"
        "(e.g., 'All steps answered', 'Boss challenge passed')\n"
        "\n"
        "_Type **skip** for default criteria_"
    ),
    "tags": (
        "**Tags** (optional)\n"
        "\n"
        "Add tags for organization (comma-separated):\n"
        "\n"
        "(e.g., 'learning, security, jwt')\n"
        "\n"
        "_Type **skip** to use default tags_"
    ),
    "confirm": (
        "{preview}\n"
        "\n"
        "═══════════════════════\n"
        "\n"
        "Does this look good?\n"
        "\n"
        "• Type **confirm** to save\n"
        "• Type **edit** to modify a field\n"
        "• Type **cancel** to discard"
    ),
    "edit_select": (
        "Which field would you like to edit?\n"
        "\n"
        "• title\n"
        "• category\n"
        "• difficulty\n"
        "• skill_path\n"
        "• objectives\n"
        "• steps\n"
        "• validation\n"
        "• tags\n"
        "\n"
        "Type the field name:"
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
    else:
        prompt_key = stage
    
    prompt = STAGE_PROMPTS.get(prompt_key, f"Unknown stage: {stage}/{substage}")
    
    return _base_response(cmd_name, prompt, {
        "wizard_active": True,
        "stage": stage,
        "substage": substage,
    })


def _get_module_list(kernel: Any) -> str:
    """Get a formatted list of available modules from the quest engine."""
    try:
        quest_engine = getattr(kernel, 'quest_engine', None)
        if not quest_engine:
            return "_(No modules found)_"
        
        # Try to get modules from the quest engine
        modules = []
        
        # Method 1: Try get_modules() method
        if hasattr(quest_engine, 'get_modules'):
            modules = quest_engine.get_modules()
        # Method 2: Try modules property
        elif hasattr(quest_engine, 'modules'):
            modules = quest_engine.modules
        # Method 3: Try to get from registry
        elif hasattr(quest_engine, 'registry') and hasattr(quest_engine.registry, 'modules'):
            modules = list(quest_engine.registry.modules.keys())
        
        if not modules:
            return "_(No modules found - quest will be standalone)_"
        
        # Format as a list
        if isinstance(modules, dict):
            module_names = list(modules.keys())
        elif isinstance(modules, list):
            # Handle list of module objects or strings
            module_names = []
            for m in modules:
                if isinstance(m, str):
                    module_names.append(m)
                elif hasattr(m, 'id'):
                    module_names.append(m.id)
                elif hasattr(m, 'name'):
                    module_names.append(m.name)
        else:
            module_names = []
        
        if not module_names:
            return "_(No modules found - quest will be standalone)_"
        
        # Format nicely
        lines = ["**Available modules:**"]
        for name in sorted(module_names):
            lines.append(f"  • {name}")
        
        return "\n".join(lines)
        
    except Exception as e:
        print(f"[QuestCompose] Error getting modules: {e}", flush=True)
        return "_(Could not load modules)_"


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
    
    # Handle objectives stage
    if stage == "objectives":
        return _handle_objectives_stage(cmd_name, session, user_input, session_id)
    
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
        # Handle module selection
        if user_input and user_input.lower() not in ("skip", "s", "none", ""):
            draft["module_id"] = user_input
        else:
            draft["module_id"] = None  # No module
        
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
    session.stage = "steps"
    session.substage = ""
    set_compose_session(session_id, session)
    return _get_current_prompt(cmd_name, session)


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
            generated_steps = _generate_steps_with_llm(session.draft, kernel)
            
            if generated_steps:
                session.draft["steps"] = generated_steps
                
                # Show generated steps with actions
                step_list = _format_steps_with_actions(generated_steps, verbose=True)
                
                session.substage = "confirm_generated"
                set_compose_session(session_id, session)
                
                return _base_response(
                    cmd_name,
                    f"**Generated {len(generated_steps)} steps:**\n\n{step_list}\n"
                    f"Type **accept** to use these, **regenerate** to try again, or **manual** to define your own:",
                    {"wizard_active": True, "stage": "steps", "substage": "confirm_generated"}
                )
            else:
                return _base_response(
                    cmd_name,
                    "Could not generate steps. Please define them manually.\n\n" + STAGE_PROMPTS["steps_manual"],
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
                "Please type **generate** or **manual**:",
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
                        f"**Regenerated {len(generated_steps)} steps:**\n\n{step_list}\n"
                        f"Type **accept** to use these, **regenerate** to try again, or **manual** to define your own:",
                        {"wizard_active": True, "stage": "steps", "substage": "confirm_generated"}
                    )
            return _base_response(
                cmd_name,
                "Could not regenerate. Type **accept** to use current steps or **manual** to define your own:",
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
                "Please type **accept**, **regenerate**, or **manual**:",
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
            f"Current steps:\n{step_list}\n\nAdd more steps or type **done** to continue:",
            {"wizard_active": True, "stage": "steps", "substage": "manual", "step_count": len(current_steps)}
        )
    
    # Unknown substage
    return _base_response(
        cmd_name,
        STAGE_PROMPTS["steps"],
        {"wizard_active": True, "stage": "steps"}
    )


def _generate_steps_with_llm(draft: Dict[str, Any], kernel: Any) -> List[Dict[str, Any]]:
    """
    Generate quest steps using the LLM based on quest metadata and objectives.
    
    Returns a list of step dicts, or empty list on failure.
    """
    try:
        print(f"[QuestCompose] Starting step generation...", flush=True)
        print(f"[QuestCompose] Kernel type: {type(kernel)}", flush=True)
        
        # Get LLM client from kernel
        llm_client = getattr(kernel, 'llm_client', None)
        if not llm_client:
            print("[QuestCompose] No LLM client available for step generation", flush=True)
            print(f"[QuestCompose] Kernel attributes: {dir(kernel)}", flush=True)
            return []
        
        print(f"[QuestCompose] LLM client found: {type(llm_client)}", flush=True)
        
        # Build prompt for step generation
        title = draft.get("title", "Untitled Quest")
        category = draft.get("category", "general")
        objectives = draft.get("objectives", [])
        
        objectives_text = "\n".join([f"- {obj}" for obj in objectives]) if objectives else "- Complete the quest"
        
        system_prompt = """You are an expert instructional designer creating detailed, engaging learning quests.

Your steps should be SPECIFIC and ACTIONABLE - not generic templates. Each step should:
- Reference actual concepts from the learning objectives
- Include specific tasks, questions, or content relevant to the topic
- Build progressively toward mastery
- Feel like a real lesson plan, not a template
- Include actionable sub-steps that guide the learner through completion

IMPORTANT STRUCTURE RULE: Each step represents ONE FULL DAY of learning. Do NOT split days into morning/afternoon/evening. One step = one day. If the quest is "learn X in 10 days", generate 10 steps (one per day). Each day's step should contain ALL the activities for that entire day.

The difficulty will be auto-calculated based on the steps you create. Create appropriately challenging content based on the objectives.

Respond ONLY with a valid JSON array. No markdown, no explanation, just the JSON."""
        
        user_prompt = f"""Create a detailed learning quest with specific, actionable steps.

**Quest Title:** {title}
**Category:** {category}

**Learning Objectives:**
{objectives_text}

---

CRITICAL: Each step = ONE FULL DAY. Do not split days into morning/afternoon/evening segments.

Generate as many steps as needed, where each step represents a complete day of learning:
- If the quest mentions a timeframe (e.g., "10 days", "2 weeks"), match that number of steps
- If no timeframe, estimate based on complexity: simple topic = 3-5 days, moderate = 5-10 days, comprehensive = 10-20 days
- Each day should have enough content to fill a meaningful learning session (not too light, not overwhelming)

Each step needs:
- `type`: one of [info, recall, apply, reflect, boss]
- `title`: "Day X: [Descriptive Title]" format (e.g., "Day 1: Setting Up Your Environment")
- `prompt`: detailed description of what the learner will accomplish THIS ENTIRE DAY (several sentences covering the full day's learning)
- `actions`: array of ALL specific tasks to complete that day (typically 4-8 actions per day)

**Step type guidelines:**
- `info`: Teaching days focused on learning new concepts
- `recall`: Review/checkpoint days to verify understanding
- `apply`: Hands-on practice days building something
- `reflect`: Reflection days to consolidate learning
- `boss`: Final challenge/project days (usually the last day or last few days)

**Example of GOOD day-based steps:**
[
  {{
    "type": "info",
    "title": "Day 1: Environment Setup and First Program",
    "prompt": "Today you'll set up your development environment and write your first working program. By the end of the day, you'll have all tools installed, understand the basic workflow, and have successfully run code that produces output.",
    "actions": [
      "Install Python 3.x from python.org and verify with 'python --version'",
      "Install VS Code and the Python extension",
      "Create a project folder called 'my_first_project'",
      "Write a hello world program and run it from the terminal",
      "Modify the program to print 3 different messages",
      "Learn about print() syntax and string formatting basics"
    ]
  }},
  {{
    "type": "info", 
    "title": "Day 2: Variables, Data Types, and Basic Operations",
    "prompt": "Today focuses entirely on understanding how to store and manipulate data. You'll learn about variables, the four basic data types, and how to perform operations on them. By the end of the day, you'll be comfortable creating variables and using them in expressions.",
    "actions": [
      "Learn what variables are and Python's naming rules",
      "Practice creating variables of each type: int, float, str, bool",
      "Understand arithmetic operators: +, -, *, /, //, %, **",
      "Learn string operations: concatenation, repetition, f-strings",
      "Write a program that uses all four data types",
      "Complete 5 small exercises combining variables and operators"
    ]
  }},
  {{
    "type": "boss",
    "title": "Day 10: Final Project - Build Your Complete Application",
    "prompt": "Today is your capstone day. You'll design, implement, and test a complete application that uses everything you've learned. This project demonstrates your ability to combine all concepts into working software.",
    "actions": [
      "Choose your project from the provided options or propose your own",
      "Write pseudocode planning out the structure and features",
      "Create the project folder and file structure",
      "Implement core functionality with functions and data structures",
      "Add user input handling and menu system",
      "Implement file save/load for data persistence",
      "Test thoroughly and fix any bugs",
      "Document your code with comments"
    ]
  }}
]

**BAD examples (don't do this):**
- "Day 1 Morning: Setup" and "Day 1 Afternoon: First Code" ← WRONG, split days
- Generic titles like "Introduction" or "Step 3" ← WRONG, not descriptive

Now generate SPECIFIC day-based steps for the quest "{title}" with objectives: {objectives_text}

JSON array only:"""

        # Call LLM using complete_system with think_mode=True for quality
        print(f"[QuestCompose] Generating steps via LLM (gpt-5.1)...", flush=True)
        
        try:
            result = llm_client.complete_system(
                system=system_prompt,
                user=user_prompt,
                command="quest-compose",
                think_mode=True,  # Use gpt-5.1 for quality step generation
            )
        except Exception as api_error:
            print(f"[QuestCompose] LLM API call failed: {api_error}", flush=True)
            return []
        
        print(f"[QuestCompose] LLM call completed, result type: {type(result)}", flush=True)
        
        response_text = result.get("text", "").strip()
        
        if not response_text:
            print("[QuestCompose] Empty response from LLM", flush=True)
            return []
        
        print(f"[QuestCompose] LLM response length: {len(response_text)}", flush=True)
        
        # Find JSON array in response
        start_idx = response_text.find('[')
        end_idx = response_text.rfind(']') + 1
        
        if start_idx == -1 or end_idx == 0:
            print(f"[QuestCompose] No JSON array found in LLM response", flush=True)
            print(f"[QuestCompose] Response preview: {response_text[:200]}", flush=True)
            return []
        
        json_text = response_text[start_idx:end_idx]
        steps_data = json.loads(json_text)
        
        if not isinstance(steps_data, list):
            print(f"[QuestCompose] LLM response is not a list", flush=True)
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
            
            # Get actions if present
            actions = step_data.get("actions", [])
            if not isinstance(actions, list):
                actions = []
            # Ensure actions are strings
            actions = [str(a) for a in actions if a]
            
            step = {
                "id": f"step_{i}",
                "type": step_type,
                "prompt": step_data.get("prompt", step_data.get("description", "")),
                "title": step_data.get("title", f"Step {i}"),
                "actions": actions,
            }
            
            if step["prompt"]:
                steps.append(step)
        
        print(f"[QuestCompose] Generated {len(steps)} steps", flush=True)
        return steps if steps else []
        
    except json.JSONDecodeError as e:
        print(f"[QuestCompose] JSON parse error: {e}", flush=True)
        return []
    except Exception as e:
        print(f"[QuestCompose] Error generating steps: {e}", flush=True)
        return []


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
                f"✓ Quest **{quest.title}** saved!\n\n"
                f"Quest ID: `{quest.id}`\n\n"
                f"View it with `#quest-inspect id={quest.id}`\n"
                f"Start it with `#quest id={quest.id}`",
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
            "Please type **confirm**, **edit**, or **cancel**:",
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
            f"Usage: `#quest-compose mode=noninteractive title=\"...\" category=... difficulty=1-5`",
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
            f"✓ Quest **{quest.title}** created.\n\n"
            f"Quest ID: `{quest.id}`",
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
    
    return _process_wizard_input(
        "quest-compose",
        session,
        user_input,
        session_id,
        kernel,  # Pass full kernel for LLM access
    )
