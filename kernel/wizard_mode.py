# kernel/wizard_mode.py
"""
v0.6 — Wizard Mode Commands (Updated v1.0.0)

Interactive wizards for commands called with no arguments.
Prompts user step-by-step for required fields.

v1.0.0 CHANGES:
- Updated #identity-set wizard for new Identity Section system
- New wizard options: name, theme, vibe, goal, title, equip

v0.11.0 CHANGES:
- Removed #mode wizard (mode command removed from system)

Wizard-enabled commands (using THIS system):
- #flow (workflow start)
- #remind-add (reminders)
- #store (memory)
- #identity-set (updated v1.0.0)
- #compose
- #log-state

Commands with SEPARATE wizard implementations (NOT using this system):
- #command-add → uses 9-step v2 wizard in custom_command_handlers.py

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
        
        wizard_def = WIZARD_DEFINITIONS.get(session.command)
        if not wizard_def:
            return None
        
        step = session.get_current_step(wizard_def)
        if step:
            session.collected[step.key] = value
        
        session.current_step += 1
        return session
    
    def is_active(self, session_id: str) -> bool:
        """Check if a wizard is active for this session."""
        return session_id in self._sessions


# Global manager instance
_wizard_manager = WizardManager()


# -----------------------------------------------------------------------------
# Wizard Definitions
# -----------------------------------------------------------------------------

WIZARD_DEFINITIONS: Dict[str, WizardDefinition] = {
    "flow": WizardDefinition(
        command="flow",
        title="Start Workflow",
        description="Start a workflow by name.",
        steps=[
            WizardStep(
                key="name",
                prompt="Which workflow would you like to start?",
                required=True,
            ),
        ],
    ),
    "remind-add": WizardDefinition(
        command="remind-add",
        title="Add Reminder",
        description="Create a new reminder.",
        steps=[
            WizardStep(
                key="msg",
                prompt="What would you like to be reminded about?",
                required=True,
            ),
            WizardStep(
                key="at",
                prompt="When should I remind you?\n(Examples: '9:00 AM', 'in 30 minutes', 'tomorrow 2pm')",
                required=True,
            ),
        ],
    ),
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
                prompt="What tags should this memory have?\n(Comma-separated, e.g., 'work,project,meeting')\n[Default: general]",
                required=False,
                default="general",
            ),
        ],
    ),
    # v1.0.0: Updated identity-set wizard for new Identity Section
    "identity-set": WizardDefinition(
        command="identity-set",
        title="Set Identity",
        description="Update your character profile. Choose what to set:",
        steps=[
            WizardStep(
                key="field",
                prompt=(
                    "What would you like to update?\n\n"
                    "• **name** — Your display name\n"
                    "• **theme** — Your archetype base theme (e.g., 'Cloud Rogue', 'Shadow Sentinel')\n"
                    "• **vibe** — Your vibe tags (comma-separated, e.g., 'analytical, calm, cyber-ethereal')\n"
                    "• **goal** — Add a new goal\n"
                    "• **title** — Add a custom title\n"
                    "• **equip** — Equip an existing title\n\n"
                    "(Options: name, theme, vibe, goal, title, equip)"
                ),
                required=True,
                options=["name", "theme", "vibe", "goal", "title", "equip"],
            ),
            WizardStep(
                key="value",
                prompt="Enter the value:",
                required=True,
            ),
        ],
    ),
    # v0.11.0: mode wizard removed
    "compose": WizardDefinition(
        command="compose",
        title="Compose Workflow",
        description="Create a new workflow with LLM assistance.",
        steps=[
            WizardStep(
                key="name",
                prompt="What should this workflow be called?",
                required=True,
            ),
            WizardStep(
                key="description",
                prompt="Describe what this workflow should accomplish.\n(The more detail, the better the generated steps)",
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
                prompt="How's your energy level?\n(Options: high, medium, low)\n[Press Enter to skip]",
                required=False,
                options=["high", "medium", "low"],
            ),
            WizardStep(
                key="stress",
                prompt="How's your stress level?\n(Options: high, medium, low)\n[Press Enter to skip]",
                required=False,
                options=["high", "medium", "low"],
            ),
            WizardStep(
                key="momentum",
                prompt="How's your momentum?\n(Options: high, medium, low)\n[Press Enter to skip]",
                required=False,
                options=["high", "medium", "low"],
            ),
        ],
    ),
}


# Commands that use separate wizard implementations (not this system)
_EXCLUDED_FROM_OLD_WIZARD = {"command-add"}


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def is_wizard_command(command: str) -> bool:
    """
    Check if a command should use wizard mode when called with no args.
    
    Note: command-add is explicitly excluded because it uses the new
    9-step v2 wizard in custom_command_handlers.py instead.
    """
    if command in _EXCLUDED_FROM_OLD_WIZARD:
        return False
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
    
    # Use default if empty and step has default
    if not value and step.default:
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
    if command == "store":
        return {
            "payload": collected.get("payload", ""),
            "type": collected.get("type", "semantic"),
            "tags": collected.get("tags", "general"),
        }
    
    elif command == "remind-add":
        return {
            "msg": collected.get("msg", ""),
            "at": collected.get("at", ""),
        }
    
    elif command == "flow":
        return {
            "name": collected.get("name", ""),
        }
    
    elif command == "identity-set":
        # v1.0.0: Updated for new Identity Section format
        # Wizard collects: field (name/theme/vibe/goal/title/equip), value
        # Handler expects: name="...", theme="...", vibe="...", goal="...", title="...", equip="..."
        field = collected.get("field", "").lower()
        value = collected.get("value", "")
        
        # Map the field to the correct argument name
        if field in ("name", "theme", "vibe", "goal", "title", "equip"):
            return {field: value}
        
        # Legacy fallback for old trait names
        trait = collected.get("trait", field)
        return {trait: value}
    
    # v0.11.0: mode case removed
    
    elif command == "compose":
        return {
            "name": collected.get("name", ""),
            "description": collected.get("description", ""),
        }
    
    elif command == "log-state":
        args = {}
        for key in ["energy", "stress", "momentum"]:
            if collected.get(key):
                args[key] = collected[key]
        return args
    
    # Default: pass through as-is
    return collected
