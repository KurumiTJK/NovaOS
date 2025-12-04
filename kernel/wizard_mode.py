# kernel/wizard_mode.py
"""
v0.6 — Wizard Mode Commands

Interactive wizards for commands called with no arguments.
Prompts user step-by-step for required fields.

Wizard-enabled commands:
- #flow (workflow start)
- #remind-add (reminders)
- #store (memory)
- #identity-set
- #mode
- #compose

Wizard logic remains INSIDE handlers; UI does NOT change.
"""

from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field


# -----------------------------------------------------------------------------
# Wizard State Management
# -----------------------------------------------------------------------------

@dataclass
class WizardStep:
    """A single step in a wizard."""
    key: str
    prompt: str
    required: bool = True
    default: Optional[str] = None
    options: Optional[List[str]] = None  # Valid options if constrained
    validator: Optional[Callable[[str], bool]] = None


@dataclass
class WizardDefinition:
    """Definition of a complete wizard."""
    command: str
    title: str
    description: str
    steps: List[WizardStep]


@dataclass
class WizardSession:
    """Active wizard session state."""
    command: str
    current_step: int
    collected: Dict[str, str] = field(default_factory=dict)
    
    def is_complete(self, wizard_def: WizardDefinition) -> bool:
        return self.current_step >= len(wizard_def.steps)
    
    def get_current_step(self, wizard_def: WizardDefinition) -> Optional[WizardStep]:
        if self.current_step < len(wizard_def.steps):
            return wizard_def.steps[self.current_step]
        return None


class WizardManager:
    """
    Manages active wizard sessions per user session.
    """
    
    def __init__(self):
        self._sessions: Dict[str, WizardSession] = {}  # session_id -> WizardSession
    
    def start(self, session_id: str, command: str) -> WizardSession:
        """Start a new wizard session."""
        self._sessions[session_id] = WizardSession(command=command, current_step=0)
        return self._sessions[session_id]
    
    def get(self, session_id: str) -> Optional[WizardSession]:
        """Get active wizard session."""
        return self._sessions.get(session_id)
    
    def clear(self, session_id: str) -> None:
        """Clear active wizard session."""
        self._sessions.pop(session_id, None)
    
    def advance(self, session_id: str, value: str) -> Optional[WizardSession]:
        """Record a value and advance to next step."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        
        # Store value (get key from wizard def)
        wizard_def = WIZARD_DEFINITIONS.get(session.command)
        if wizard_def and session.current_step < len(wizard_def.steps):
            step = wizard_def.steps[session.current_step]
            session.collected[step.key] = value
            session.current_step += 1
            
            # =============================================================
            # COMPOSE WIZARD BRANCHING:
            # When step_mode=2 (auto), skip the manual_steps step
            # =============================================================
            if session.command == "compose" and step.key == "step_mode" and value == "2":
                # User chose auto-generate, skip manual_steps step
                # Find and skip the manual_steps step
                while session.current_step < len(wizard_def.steps):
                    next_step = wizard_def.steps[session.current_step]
                    if next_step.key == "manual_steps":
                        # Skip this step by setting empty value and advancing
                        session.collected["manual_steps"] = ""
                        session.current_step += 1
                    else:
                        break
        
        return session
    
    def is_active(self, session_id: str) -> bool:
        """Check if wizard is active."""
        return session_id in self._sessions


# Global wizard manager
_wizard_manager = WizardManager()


# -----------------------------------------------------------------------------
# Wizard Definitions
# -----------------------------------------------------------------------------

WIZARD_DEFINITIONS: Dict[str, WizardDefinition] = {
    # =========================================================================
    # GROUP A: Strong Wizard Candidates (must have)
    # =========================================================================
    
    "store": WizardDefinition(
        command="store",
        title="Store Memory",
        description="Store a new memory item.",
        steps=[
            WizardStep(
                key="payload",
                prompt="What would you like to remember?",
                required=True,
            ),
            WizardStep(
                key="type",
                prompt="What type of memory is this?\n(Options: semantic, procedural, episodic)\n[Default: semantic]",
                required=False,
                default="semantic",
                options=["semantic", "procedural", "episodic"],
            ),
            WizardStep(
                key="tags",
                prompt="Tags for this memory?\n(Comma-separated, e.g., 'work, project')\n[Press Enter to skip]",
                required=False,
                default="",
            ),
        ],
    ),
    
    "remind-add": WizardDefinition(
        command="remind-add",
        title="Add Reminder",
        description="Create a new reminder.",
        steps=[
            WizardStep(
                key="title",
                prompt="What should I remind you about?",
                required=True,
            ),
            WizardStep(
                key="when",
                prompt="When should I remind you?\n(Examples: 'tomorrow 9am', 'in 30 minutes', 'friday 3pm')",
                required=True,
            ),
        ],
    ),
    
    "log-state": WizardDefinition(
        command="log-state",
        title="Log State",
        description="Update your current state.",
        steps=[
            WizardStep(
                key="energy",
                prompt="How is your energy level?\n(Options: depleted, low, moderate, good, high)",
                required=False,
                options=["depleted", "low", "moderate", "good", "high"],
            ),
            WizardStep(
                key="stress",
                prompt="What is your stress level?\n(Options: overwhelmed, high, moderate, low, calm)",
                required=False,
                options=["overwhelmed", "high", "moderate", "low", "calm"],
            ),
            WizardStep(
                key="momentum",
                prompt="How is your momentum?\n(Options: stalled, slow, steady, building, flowing)",
                required=False,
                options=["stalled", "slow", "steady", "building", "flowing"],
            ),
        ],
    ),
    
    "identity-set": WizardDefinition(
        command="identity-set",
        title="Set Identity",
        description="Update identity traits.",
        steps=[
            WizardStep(
                key="trait",
                prompt="Which trait would you like to set?\n(Options: name, goals, values, context, roles, strengths, growth_areas)",
                required=True,
                options=["name", "goals", "values", "context", "roles", "strengths", "growth_areas"],
            ),
            WizardStep(
                key="value",
                prompt="What value should this trait have?\n(For lists like goals/values, separate with commas)",
                required=True,
            ),
        ],
    ),
    
    "flow": WizardDefinition(
        command="flow",
        title="Workflow Start",
        description="Select a workflow to start or resume.",
        steps=[
            WizardStep(
                key="selection",
                prompt="(Workflow list will be shown above)\n\nType a number to select:",
                required=True,
            ),
        ],
    ),
    
    "advance": WizardDefinition(
        command="advance",
        title="Advance Workflow",
        description="Select a workflow to advance to the next step.",
        steps=[
            WizardStep(
                key="selection",
                prompt="(Workflow list will be shown above)\n\nType a number to select:",
                required=True,
            ),
        ],
    ),
    
    "halt": WizardDefinition(
        command="halt",
        title="Halt Workflow",
        description="Select a workflow to pause or halt.",
        steps=[
            WizardStep(
                key="selection",
                prompt="(Workflow list will be shown above)\n\nType a number to select:",
                required=True,
            ),
        ],
    ),
    
    "compose": WizardDefinition(
        command="compose",
        title="Compose Workflow",
        description="Create a new workflow with LLM assistance.",
        steps=[
            WizardStep(
                key="name",
                prompt="What do you want to call this workflow?\n(Example: \"Morning Routine\", \"Weekly Review\", \"Deep Work Block\")",
                required=True,
            ),
            WizardStep(
                key="goal",
                prompt="In 1-2 sentences, what is this workflow for?\n(Example: \"Make sure I start every weekday with focus and energy.\")",
                required=True,
            ),
            WizardStep(
                key="step_mode",
                prompt="Do you want to:\n  1. List the main steps yourself\n  2. Have Nova propose a starter set of steps\n\nEnter 1 or 2:",
                required=True,
                options=["1", "2"],
            ),
            WizardStep(
                key="manual_steps",
                prompt="List your steps as short bullet lines (one per line).\nExample:\n- wake up\n- drink water\n- 10-minute stretch\n\nWhen you're done, send all steps in one message.",
                required=True,  # Required when shown (manual mode only)
            ),
            WizardStep(
                key="confirm",
                prompt="Create this workflow? (yes / no)",
                required=True,
                options=["yes", "no", "y", "n"],
            ),
        ],
    ),
    
    "snapshot": WizardDefinition(
        command="snapshot",
        title="Create Snapshot",
        description="Create a snapshot of NovaOS state.",
        steps=[
            WizardStep(
                key="label",
                prompt="Label for this snapshot?\n[Press Enter to skip]",
                required=False,
                default="",
            ),
            WizardStep(
                key="notes",
                prompt="Any notes for this snapshot?\n[Press Enter to skip]",
                required=False,
                default="",
            ),
        ],
    ),
    
    "forge": WizardDefinition(
        command="forge",
        title="Forge Module",
        description="Create a new module.",
        steps=[
            WizardStep(
                key="key",
                prompt="Module key (unique identifier, e.g., 'finance', 'health')?",
                required=True,
            ),
            WizardStep(
                key="name",
                prompt="Module name (display name)?\n[Press Enter to use key as name]",
                required=False,
                default="",
            ),
            WizardStep(
                key="mission",
                prompt="Module mission (what does this module do)?\n[Press Enter to skip]",
                required=False,
                default="",
            ),
        ],
    ),
    
    "restore": WizardDefinition(
        command="restore",
        title="Restore Snapshot",
        description="Restore NovaOS state from a snapshot.",
        steps=[
            WizardStep(
                key="file",
                prompt="Which snapshot file to restore?\n(e.g., 'snapshot_20251203T120000Z.json')",
                required=True,
            ),
        ],
    ),
    
    "command-add": WizardDefinition(
        command="command-add",
        title="Add Custom Command",
        description="Create a new custom command.",
        steps=[
            WizardStep(
                key="name",
                prompt="Command name (e.g., 'daily-review')?",
                required=True,
            ),
            WizardStep(
                key="kind",
                prompt="Command type?\n(Options: prompt, macro)\n[Default: prompt]",
                required=False,
                default="prompt",
                options=["prompt", "macro"],
            ),
            WizardStep(
                key="prompt",
                prompt="What should this command do?\n(Describe the prompt or action)",
                required=True,
            ),
        ],
    ),
    
    "forget": WizardDefinition(
        command="forget",
        title="Forget Memory",
        description="Delete memory items.",
        steps=[
            WizardStep(
                key="forget_by",
                prompt="Forget by what?\n(Options: id, tags, type)",
                required=True,
                options=["id", "tags", "type"],
            ),
            WizardStep(
                key="forget_value",
                prompt="Enter the value:\n(ID number, comma-separated tags, or type name)",
                required=True,
            ),
        ],
    ),
    
    "bind": WizardDefinition(
        command="bind",
        title="Bind Memories",
        description="Bind memory items into a cluster.",
        steps=[
            WizardStep(
                key="ids",
                prompt="Which memory IDs to bind?\n(Comma-separated, e.g., '1, 2, 3')",
                required=True,
            ),
        ],
    ),
    
    "workflow-delete": WizardDefinition(
        command="workflow-delete",
        title="Delete Workflow",
        description="Delete a workflow.",
        steps=[
            WizardStep(
                key="id",
                prompt="Which workflow ID to delete?",
                required=True,
            ),
        ],
    ),
    
    "remind-update": WizardDefinition(
        command="remind-update",
        title="Update Reminder",
        description="Update an existing reminder.",
        steps=[
            WizardStep(
                key="id",
                prompt="Which reminder ID to update?",
                required=True,
            ),
            WizardStep(
                key="title",
                prompt="New title?\n[Press Enter to keep current]",
                required=False,
                default="",
            ),
            WizardStep(
                key="when",
                prompt="New time?\n[Press Enter to keep current]",
                required=False,
                default="",
            ),
        ],
    ),
    
    "remind-delete": WizardDefinition(
        command="remind-delete",
        title="Delete Reminder",
        description="Delete a reminder.",
        steps=[
            WizardStep(
                key="id",
                prompt="Which reminder ID to delete?",
                required=True,
            ),
        ],
    ),
    
    # =========================================================================
    # GROUP B: Optional Wizards (nice to have)
    # =========================================================================
    
    "mode": WizardDefinition(
        command="mode",
        title="Set Mode",
        description="Change NovaOS operating mode.",
        steps=[
            WizardStep(
                key="mode",
                prompt="Which mode?\n(Options: normal, deep_work, reflection, debug)",
                required=True,
                options=["normal", "deep_work", "reflection", "debug"],
            ),
        ],
    ),
    
    "setenv": WizardDefinition(
        command="setenv",
        title="Set Environment",
        description="Set an environment variable.",
        steps=[
            WizardStep(
                key="key",
                prompt="Which environment key to set?",
                required=True,
            ),
            WizardStep(
                key="value",
                prompt="What value?",
                required=True,
            ),
        ],
    ),
    
    "memory-salience": WizardDefinition(
        command="memory-salience",
        title="Set Memory Salience",
        description="Update the importance of a memory.",
        steps=[
            WizardStep(
                key="id",
                prompt="Which memory ID?",
                required=True,
            ),
            WizardStep(
                key="salience",
                prompt="New salience value?\n(0.0 to 1.0, where 1.0 = most important)",
                required=True,
            ),
        ],
    ),
    
    "memory-status": WizardDefinition(
        command="memory-status",
        title="Set Memory Status",
        description="Update the status of a memory.",
        steps=[
            WizardStep(
                key="id",
                prompt="Which memory ID?",
                required=True,
            ),
            WizardStep(
                key="status",
                prompt="New status?\n(Options: active, stale, archived, pending_confirmation)",
                required=True,
                options=["active", "stale", "archived", "pending_confirmation"],
            ),
        ],
    ),
    
    "memory-reconfirm": WizardDefinition(
        command="memory-reconfirm",
        title="Reconfirm Memory",
        description="Re-confirm a memory to restore it to active status.",
        steps=[
            WizardStep(
                key="id",
                prompt="Which memory ID to reconfirm?",
                required=True,
            ),
            WizardStep(
                key="salience",
                prompt="New salience value?\n[Press Enter to keep current]",
                required=False,
                default="",
            ),
        ],
    ),
    
    "bind-module": WizardDefinition(
        command="bind-module",
        title="Bind Modules",
        description="Bind two modules together.",
        steps=[
            WizardStep(
                key="a",
                prompt="First module key?",
                required=True,
            ),
            WizardStep(
                key="b",
                prompt="Second module key?",
                required=True,
            ),
        ],
    ),
    
    "dismantle": WizardDefinition(
        command="dismantle",
        title="Dismantle Module",
        description="Remove a module.",
        steps=[
            WizardStep(
                key="key",
                prompt="Which module key to dismantle?",
                required=True,
            ),
        ],
    ),
    
    "identity-restore": WizardDefinition(
        command="identity-restore",
        title="Restore Identity",
        description="Restore identity from a historical snapshot.",
        steps=[
            WizardStep(
                key="id",
                prompt="Snapshot ID or timestamp to restore?\n(e.g., 'profile-20251203-abc123' or '2025-12-03T12:00:00')",
                required=True,
            ),
        ],
    ),
    
    "trace": WizardDefinition(
        command="trace",
        title="Trace Memory",
        description="Show lineage and trace info for a memory.",
        steps=[
            WizardStep(
                key="id",
                prompt="Which memory ID to trace?",
                required=True,
            ),
        ],
    ),
    
    "inspect": WizardDefinition(
        command="inspect",
        title="Inspect Module",
        description="Inspect a module's metadata.",
        steps=[
            WizardStep(
                key="key",
                prompt="Which module key to inspect?",
                required=True,
            ),
        ],
    ),
    
    "command-inspect": WizardDefinition(
        command="command-inspect",
        title="Inspect Command",
        description="Inspect a custom command's metadata.",
        steps=[
            WizardStep(
                key="name",
                prompt="Which command name to inspect?",
                required=True,
            ),
        ],
    ),
    
    "command-remove": WizardDefinition(
        command="command-remove",
        title="Remove Command",
        description="Remove a custom command.",
        steps=[
            WizardStep(
                key="name",
                prompt="Which command name to remove?",
                required=True,
            ),
        ],
    ),
    
    "command-toggle": WizardDefinition(
        command="command-toggle",
        title="Toggle Command",
        description="Enable or disable a custom command.",
        steps=[
            WizardStep(
                key="name",
                prompt="Which command name to toggle?",
                required=True,
            ),
        ],
    ),
    
    "recall": WizardDefinition(
        command="recall",
        title="Recall Memories",
        description="Recall memory items with filters.",
        steps=[
            WizardStep(
                key="type",
                prompt="Filter by type?\n(Options: semantic, procedural, episodic)\n[Press Enter for all]",
                required=False,
                default="",
                options=["semantic", "procedural", "episodic", ""],
            ),
            WizardStep(
                key="tags",
                prompt="Filter by tags?\n(Comma-separated, or press Enter for all)",
                required=False,
                default="",
            ),
        ],
    ),
}


# -----------------------------------------------------------------------------
# Wizard Helpers
# -----------------------------------------------------------------------------

def is_wizard_command(command: str) -> bool:
    """Check if a command has wizard mode."""
    return command in WIZARD_DEFINITIONS


def start_wizard(session_id: str, command: str) -> Dict[str, Any]:
    """
    Start a wizard for a command.
    
    Returns the initial prompt response.
    """
    wizard_def = WIZARD_DEFINITIONS.get(command)
    if not wizard_def:
        return {
            "ok": False,
            "summary": f"No wizard available for command '{command}'.",
        }
    
    # Start session
    session = _wizard_manager.start(session_id, command)
    
    # Get first step
    step = wizard_def.steps[0]
    
    lines = [
        f"╔══ {wizard_def.title} Wizard ══╗",
        "",
        wizard_def.description,
        "",
        f"Step 1/{len(wizard_def.steps)}:",
        step.prompt,
        "",
        "(Type 'cancel' to exit wizard)",
    ]
    
    return {
        "ok": True,
        "command": "wizard",
        "summary": "\n".join(lines),
        "extra": {
            "wizard_active": True,
            "wizard_command": command,
            "step": 1,
            "total_steps": len(wizard_def.steps),
        },
    }


def process_wizard_input(session_id: str, user_input: str) -> Dict[str, Any]:
    """
    Process input during an active wizard.
    
    Returns either:
    - Next step prompt
    - Final command to execute
    - Cancellation message
    """
    session = _wizard_manager.get(session_id)
    if not session:
        return {
            "ok": False,
            "summary": "No active wizard session.",
        }
    
    wizard_def = WIZARD_DEFINITIONS.get(session.command)
    if not wizard_def:
        _wizard_manager.clear(session_id)
        return {
            "ok": False,
            "summary": "Wizard definition not found.",
        }
    
    # Check for cancel
    if user_input.lower().strip() in ("cancel", "exit", "quit"):
        _wizard_manager.clear(session_id)
        return {
            "ok": True,
            "command": "wizard_cancel",
            "summary": "Wizard cancelled.",
            "extra": {"cancelled": True},
        }
    
    # Get current step
    step = session.get_current_step(wizard_def)
    if not step:
        _wizard_manager.clear(session_id)
        return {
            "ok": False,
            "summary": "Wizard step not found.",
        }
    
    # Validate input
    value = user_input.strip()
    
    # =================================================================
    # v0.7.10: Handle workflow selection wizards
    # Convert number selection to workflow ID
    # =================================================================
    if is_workflow_selection_wizard(session_id) and step.key == "selection":
        resolved_id = resolve_workflow_selection(session_id, value)
        if not resolved_id:
            workflows = get_workflow_selection_list(session_id)
            max_num = len(workflows)
            return {
                "ok": True,
                "command": "wizard",
                "summary": f"Invalid selection. Please enter a number from 1 to {max_num}.",
                "extra": {"wizard_active": True, "validation_error": True},
            }
        # Use the resolved workflow ID as the value
        value = resolved_id
        # Clear the selection cache
        clear_workflow_selection_cache(session_id)
    
    # Use default if empty and step has default
    if not value and step.default is not None:
        value = step.default
    
    # Check required
    if step.required and not value:
        return {
            "ok": True,
            "command": "wizard",
            "summary": f"This field is required. Please enter a value:\n\n{step.prompt}",
            "extra": {"wizard_active": True, "validation_error": True},
        }
    
    # Check options constraint
    if step.options and value and value.lower() not in [o.lower() for o in step.options]:
        return {
            "ok": True,
            "command": "wizard",
            "summary": f"Invalid option. Please choose from: {', '.join(step.options)}\n\n{step.prompt}",
            "extra": {"wizard_active": True, "validation_error": True},
        }
    
    # Advance session
    _wizard_manager.advance(session_id, value)
    
    # Check if complete
    if session.is_complete(wizard_def):
        # Build final command args
        collected = session.collected
        _wizard_manager.clear(session_id)
        
        return {
            "ok": True,
            "command": "wizard_complete",
            "summary": f"Wizard complete. Executing #{session.command}...",
            "extra": {
                "wizard_complete": True,
                "target_command": session.command,
                "collected_args": collected,
            },
        }
    
    # Show next step
    next_step = session.get_current_step(wizard_def)
    step_num = session.current_step + 1
    
    # =================================================================
    # SPECIAL HANDLING: Compose wizard confirmation step
    # Show summary before asking for confirmation
    # =================================================================
    if session.command == "compose" and next_step.key == "confirm":
        name = session.collected.get("name", "Untitled")
        goal = session.collected.get("goal", "No goal specified")
        step_mode = session.collected.get("step_mode", "2")
        manual_steps = session.collected.get("manual_steps", "")
        
        # Calculate effective step count (auto mode skips manual_steps)
        effective_total = 4 if step_mode == "2" else 5
        effective_step = 4 if step_mode == "2" else 5
        
        lines = [
            "━" * 40,
            "Here's the workflow I'm about to create:",
            "━" * 40,
            "",
            f"Name: {name}",
            f"Purpose: {goal}",
            "",
        ]
        
        if step_mode == "1" and manual_steps:
            # Count and show manual steps
            step_count = 0
            step_lines = []
            for line in manual_steps.split("\n"):
                line = line.strip()
                if line:
                    # Clean up bullet markers
                    for prefix in ["-", "*", "•", "→"]:
                        if line.startswith(prefix):
                            line = line[len(prefix):].strip()
                            break
                    import re
                    line = re.sub(r"^\d+[\.\)]\s*", "", line)
                    if line:
                        step_count += 1
                        step_lines.append(f"  • {line}")
            
            lines.append(f"Steps ({step_count} steps, manual):")
            lines.extend(step_lines)
        else:
            lines.append("Steps: auto-generate with Nova")
        
        lines.append("")
        lines.append("━" * 40)
        lines.append("")
        lines.append(f"Step {effective_step}/{effective_total}:")
        lines.append(next_step.prompt)
        lines.append("")
        lines.append("(Type 'cancel' to exit wizard)")
        
        return {
            "ok": True,
            "command": "wizard",
            "summary": "\n".join(lines),
            "extra": {
                "wizard_active": True,
                "wizard_command": session.command,
                "step": effective_step,
                "total_steps": effective_total,
            },
        }
    
    lines = [
        f"Step {step_num}/{len(wizard_def.steps)}:",
        next_step.prompt,
        "",
        "(Type 'cancel' to exit wizard)",
    ]
    
    return {
        "ok": True,
        "command": "wizard",
        "summary": "\n".join(lines),
        "extra": {
            "wizard_active": True,
            "wizard_command": session.command,
            "step": step_num,
            "total_steps": len(wizard_def.steps),
        },
    }


def is_wizard_active(session_id: str) -> bool:
    """Check if a wizard is active for this session."""
    return _wizard_manager.is_active(session_id)


def cancel_wizard(session_id: str) -> None:
    """Cancel any active wizard for this session."""
    _wizard_manager.clear(session_id)


def build_command_args_from_wizard(command: str, collected: Dict[str, str]) -> Dict[str, Any]:
    """
    Build command arguments from wizard-collected values.
    
    This transforms wizard output into the format expected by syscommand handlers.
    """
    # =========================================================================
    # GROUP A: Strong Wizard Candidates
    # =========================================================================
    
    if command == "store":
        args = {
            "payload": collected.get("payload", ""),
            "type": collected.get("type", "semantic"),
        }
        if collected.get("tags"):
            args["tags"] = collected["tags"]
        return args
    
    elif command == "remind-add":
        return {
            "title": collected.get("title", ""),
            "when": collected.get("when", ""),
        }
    
    elif command == "log-state":
        args = {}
        for key in ["energy", "stress", "momentum"]:
            if collected.get(key):
                args[key] = collected[key]
        return args
    
    elif command == "identity-set":
        trait = collected.get("trait", "")
        value = collected.get("value", "")
        return {trait: value} if trait else {}
    
    elif command == "flow":
        # v0.7.10: Selection wizard provides "selection" which maps to "id"
        if collected.get("selection"):
            return {"id": collected["selection"], "_from_wizard": True}
        return {"id": collected.get("id", ""), "_from_wizard": True}
    
    elif command == "compose":
        # Full wizard data: name, goal, step_mode, manual_steps, confirm
        return {
            "name": collected.get("name", ""),
            "goal": collected.get("goal", ""),
            "step_mode": collected.get("step_mode", "2"),  # Default to auto
            "manual_steps": collected.get("manual_steps", ""),
            "confirm": collected.get("confirm", "no"),
            "_from_wizard": True,  # Flag to indicate wizard origin
        }
    
    elif command == "snapshot":
        args = {}
        if collected.get("label"):
            args["label"] = collected["label"]
        if collected.get("notes"):
            args["notes"] = collected["notes"]
        return args
    
    elif command == "forge":
        args = {"key": collected.get("key", "")}
        if collected.get("name"):
            args["name"] = collected["name"]
        if collected.get("mission"):
            args["mission"] = collected["mission"]
        return args
    
    elif command == "restore":
        return {"file": collected.get("file", "")}
    
    elif command == "command-add":
        return {
            "name": collected.get("name", ""),
            "kind": collected.get("kind", "prompt"),
            "prompt": collected.get("prompt", ""),
        }
    
    elif command == "forget":
        # Special handling: forget_by determines which key to use
        forget_by = collected.get("forget_by", "id")
        forget_value = collected.get("forget_value", "")
        
        if forget_by == "id":
            return {"id": forget_value}
        elif forget_by == "tags":
            return {"tags": forget_value}
        elif forget_by == "type":
            return {"type": forget_value}
        return {"id": forget_value}
    
    elif command == "bind":
        return {"ids": collected.get("ids", "")}
    
    elif command == "workflow-delete":
        return {"id": collected.get("id", "")}
    
    elif command == "remind-update":
        args = {"id": collected.get("id", "")}
        if collected.get("title"):
            args["title"] = collected["title"]
        if collected.get("when"):
            args["when"] = collected["when"]
        return args
    
    elif command == "remind-delete":
        return {"id": collected.get("id", "")}
    
    # =========================================================================
    # GROUP B: Optional Wizards
    # =========================================================================
    
    elif command == "mode":
        return {"mode": collected.get("mode", "normal")}
    
    elif command == "setenv":
        # Build key=value pair
        key = collected.get("key", "")
        value = collected.get("value", "")
        return {key: value} if key else {}
    
    elif command == "memory-salience":
        return {
            "id": collected.get("id", ""),
            "salience": collected.get("salience", ""),
        }
    
    elif command == "memory-status":
        return {
            "id": collected.get("id", ""),
            "status": collected.get("status", ""),
        }
    
    elif command == "memory-reconfirm":
        args = {"id": collected.get("id", "")}
        if collected.get("salience"):
            args["salience"] = collected["salience"]
        return args
    
    elif command == "bind-module":
        return {
            "a": collected.get("a", ""),
            "b": collected.get("b", ""),
        }
    
    elif command == "dismantle":
        return {"key": collected.get("key", "")}
    
    elif command == "identity-restore":
        return {"id": collected.get("id", "")}
    
    elif command == "trace":
        return {"id": collected.get("id", "")}
    
    elif command == "inspect":
        return {"key": collected.get("key", "")}
    
    elif command == "advance":
        # v0.7.10: Selection wizard provides "selection" which maps to "id"
        if collected.get("selection"):
            return {"id": collected["selection"], "_from_wizard": True}
        return {"id": collected.get("id", ""), "_from_wizard": True}
    
    elif command == "halt":
        # v0.7.10: Selection wizard provides "selection" which maps to "id"
        args = {"_from_wizard": True}
        if collected.get("selection"):
            args["id"] = collected["selection"]
        elif collected.get("id"):
            args["id"] = collected["id"]
        if collected.get("status"):
            args["status"] = collected["status"]
        return args
    
    elif command == "command-inspect":
        return {"name": collected.get("name", "")}
    
    elif command == "command-remove":
        return {"name": collected.get("name", "")}
    
    elif command == "command-toggle":
        return {"name": collected.get("name", "")}
    
    elif command == "recall":
        args = {}
        if collected.get("type"):
            args["type"] = collected["type"]
        if collected.get("tags"):
            args["tags"] = collected["tags"]
        return args
    
    # Default: pass through as-is
    return collected


# =============================================================================
# v0.7.10: Workflow Selection Wizards
# =============================================================================

# Storage for workflow lists during selection wizards
_workflow_selection_cache: Dict[str, List[Dict[str, Any]]] = {}


def start_workflow_selection_wizard(
    session_id: str, 
    command: str, 
    workflows: List[Dict[str, Any]],
    title: str,
    description: str,
) -> Dict[str, Any]:
    """
    Start a workflow selection wizard.
    
    Shows a numbered list of workflows for user to select from.
    
    Args:
        session_id: User session ID
        command: The command being wizarded (flow, advance, halt)
        workflows: List of workflow dicts with at least 'id' and 'name'
        title: Wizard title
        description: Wizard description
    
    Returns:
        Wizard prompt response dict
    """
    if not workflows:
        return {
            "ok": False,
            "command": command,
            "summary": "No workflows available. Create one first with #compose.",
            "extra": {"no_workflows": True},
        }
    
    # Cache the workflow list for this session
    _workflow_selection_cache[session_id] = workflows
    
    # Start wizard session
    session = _wizard_manager.start(session_id, command)
    
    # Build numbered list with enhanced display
    lines = [
        f"╔══ {title} Wizard ══╗",
        "",
        description,
        "",
        "Available workflows:",
        "",
    ]
    
    for idx, wf in enumerate(workflows, start=1):
        wf_id = wf.get("id", "?")
        wf_name = wf.get("name", "Untitled")
        wf_status = wf.get("status", "unknown")
        total_steps = wf.get("total_steps", 0)
        current_step_idx = wf.get("current_step_index", 0)
        active_step_title = wf.get("active_step_title", "")
        
        # Format workflow entry
        lines.append(f"  {idx}) {wf_name}")
        lines.append(f"     ID: {wf_id}")
        
        # Format status line with step info
        if wf_status == "completed":
            lines.append(f"     Status: completed ({total_steps} steps)")
        elif wf_status == "active" and active_step_title:
            lines.append(f"     Status: active at step {current_step_idx + 1}/{total_steps}")
            lines.append(f"     Current: {active_step_title}")
        elif wf_status == "paused" and active_step_title:
            lines.append(f"     Status: paused at step {current_step_idx + 1}/{total_steps}")
            lines.append(f"     Current: {active_step_title}")
        elif wf_status == "pending":
            lines.append(f"     Status: not started ({total_steps} steps)")
        else:
            lines.append(f"     Status: {wf_status}")
        
        lines.append("")  # Blank line between entries
    
    lines.append("Step 1/1:")
    lines.append("Type a number to select:")
    lines.append("")
    lines.append("(Type 'cancel' to exit wizard)")
    
    return {
        "ok": True,
        "command": "wizard",
        "summary": "\n".join(lines),
        "extra": {
            "wizard_active": True,
            "wizard_command": command,
            "wizard_type": "selection",
            "step": 1,
            "total_steps": 1,
            "workflow_count": len(workflows),
        },
    }


def resolve_workflow_selection(session_id: str, selection: str) -> Optional[str]:
    """
    Convert a selection number to a workflow ID.
    
    Args:
        session_id: User session ID
        selection: The user's input (should be a number)
    
    Returns:
        Workflow ID if valid selection, None otherwise
    """
    workflows = _workflow_selection_cache.get(session_id, [])
    if not workflows:
        return None
    
    try:
        idx = int(selection.strip())
        if 1 <= idx <= len(workflows):
            return workflows[idx - 1].get("id")
    except (ValueError, TypeError):
        pass
    
    return None


def clear_workflow_selection_cache(session_id: str) -> None:
    """Clear the cached workflow list for a session."""
    _workflow_selection_cache.pop(session_id, None)


def is_workflow_selection_wizard(session_id: str) -> bool:
    """Check if current wizard is a workflow selection wizard."""
    session = _wizard_manager.get(session_id)
    if not session:
        return False
    return session.command in ("flow", "advance", "halt")


def get_workflow_selection_list(session_id: str) -> List[Dict[str, Any]]:
    """Get the cached workflow list for a session."""
    return _workflow_selection_cache.get(session_id, [])
