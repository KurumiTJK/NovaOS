# kernel/command_add_wizard.py
"""
v0.7.17 — Command-Add Interactive Wizard

This module provides an interactive wizard for #command-add when called without arguments.

Two modes:
1. DIRECT MODE: #command-add name=foo kind=prompt prompt_template="..." → immediate creation
2. WIZARD MODE: #command-add → step-by-step interactive flow

The wizard walks through all v0.7.16 enhanced fields:
- name
- kind
- prompt_template
- intensive (model selection)
- output_style
- strict
- persona_mode
- examples (few-shot)
- enabled

Usage:
    from .command_add_wizard import handle_command_add_with_wizard
    
    # In SYS_HANDLERS or custom_command_handlers.py:
    "handle_command_add": handle_command_add_with_wizard
"""

from __future__ import annotations

from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field

from .command_types import CommandResponse
from .formatting import OutputFormatter as F
from .custom_command_v2 import (
    normalize_custom_command_v2,
    OUTPUT_STYLES,
    PERSONA_MODES,
)


# =============================================================================
# WIZARD STATE
# =============================================================================

@dataclass
class CommandAddWizardState:
    """State for the command-add wizard."""
    stage: str = "start"
    name: str = ""
    kind: str = "prompt"
    prompt_template: str = ""
    intensive: bool = False
    output_style: str = "natural"
    strict: bool = False
    persona_mode: str = "nova"
    examples: List[Dict[str, str]] = field(default_factory=list)
    enabled: bool = True
    
    # Temporary state for example collection
    collecting_example: bool = False
    current_example_input: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to command config dict."""
        return {
            "name": self.name,
            "kind": self.kind,
            "prompt_template": self.prompt_template,
            "intensive": self.intensive,
            "output_style": self.output_style,
            "strict": self.strict,
            "persona_mode": self.persona_mode,
            "examples": self.examples,
            "enabled": self.enabled,
        }


# Global wizard state storage (per session)
_wizard_sessions: Dict[str, CommandAddWizardState] = {}


# =============================================================================
# WIZARD STAGES
# =============================================================================

STAGES = [
    "start",
    "ask_name",
    "ask_kind", 
    "ask_template",
    "ask_intensive",
    "ask_style",
    "ask_strict",
    "ask_persona",
    "ask_examples",
    "ask_example_input",
    "ask_example_output", 
    "ask_more_examples",
    "ask_enabled",
    "confirm",
    "complete",
]


# =============================================================================
# WIZARD LOGIC
# =============================================================================

def _get_wizard_state(session_id: str) -> Optional[CommandAddWizardState]:
    """Get active wizard state for session."""
    return _wizard_sessions.get(session_id)


def _set_wizard_state(session_id: str, state: CommandAddWizardState) -> None:
    """Set wizard state for session."""
    _wizard_sessions[session_id] = state


def _clear_wizard_state(session_id: str) -> None:
    """Clear wizard state for session."""
    if session_id in _wizard_sessions:
        del _wizard_sessions[session_id]


def _wizard_prompt(title: str, message: str, stage_num: int, total: int = 9) -> str:
    """Format a wizard prompt."""
    return (
        f"╔══ Add Custom Command ══╗\n"
        f"Step {stage_num}/{total}: {title}\n\n"
        f"{message}\n\n"
        f"(Type 'cancel' to exit wizard)"
    )


def _validate_command_name(name: str, kernel: Any) -> tuple[bool, str]:
    """Validate a command name."""
    name = name.strip().lower()
    
    # Remove # prefix if provided
    if name.startswith("#"):
        name = name[1:]
    
    # Check for spaces
    if " " in name:
        return False, "Command name cannot contain spaces. Use hyphens instead (e.g., 'daily-reflect')."
    
    # Check for reserved prefixes
    if name.startswith("command-"):
        return False, "Command name cannot start with 'command-' (reserved for system commands)."
    
    # Check length
    if len(name) < 2:
        return False, "Command name must be at least 2 characters."
    
    if len(name) > 50:
        return False, "Command name must be 50 characters or less."
    
    # Check for collision with core commands
    if name in kernel.commands:
        return False, f"'{name}' is already a core system command. Choose a different name."
    
    # Check for collision with existing custom commands
    existing = kernel.custom_registry.get(name)
    if existing:
        return False, f"'{name}' already exists as a custom command. Use #command-remove to delete it first."
    
    return True, name


def process_wizard_stage(
    session_id: str,
    user_input: str,
    kernel: Any,
) -> CommandResponse:
    """
    Process wizard input and return the next prompt or completion.
    
    This is the main state machine for the command-add wizard.
    """
    state = _get_wizard_state(session_id)
    if not state:
        # Start new wizard
        state = CommandAddWizardState(stage="ask_name")
        _set_wizard_state(session_id, state)
        return CommandResponse(
            ok=True,
            command="command-add",
            summary=_wizard_prompt(
                "Command Name",
                "What should this command be called?\n\n"
                "Examples: daily-reflect, summarize, translate-korean\n\n"
                "Rules:\n"
                "• No spaces (use hyphens)\n"
                "• Cannot start with 'command-'\n"
                "• Must be unique",
                1,
            ),
            data={"wizard_active": True, "stage": "ask_name"},
        )
    
    # Handle cancel
    if user_input.strip().lower() == "cancel":
        _clear_wizard_state(session_id)
        return CommandResponse(
            ok=True,
            command="command-add",
            summary="✗ Wizard cancelled. No command was created.",
            data={"wizard_active": False},
        )
    
    stage = state.stage
    text = user_input.strip()
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_name
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_name":
        valid, result = _validate_command_name(text, kernel)
        if not valid:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Command Name",
                    f"⚠️ {result}\n\nPlease try another name:",
                    1,
                ),
                data={"wizard_active": True, "stage": "ask_name"},
            )
        
        state.name = result
        state.stage = "ask_kind"
        _set_wizard_state(session_id, state)
        
        return CommandResponse(
            ok=True,
            command="command-add",
            summary=_wizard_prompt(
                "Command Kind",
                "What kind of command is this?\n\n"
                "• **prompt** — Sends text to the AI with your template\n"
                "• **macro** — Chains multiple commands together\n\n"
                "Type: prompt or macro",
                2,
            ),
            data={"wizard_active": True, "stage": "ask_kind"},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_kind
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_kind":
        kind = text.lower()
        if kind not in ("prompt", "macro"):
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Command Kind",
                    "Please type either **prompt** or **macro**:",
                    2,
                ),
                data={"wizard_active": True, "stage": "ask_kind"},
            )
        
        state.kind = kind
        state.stage = "ask_template"
        _set_wizard_state(session_id, state)
        
        if kind == "prompt":
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Prompt Template",
                    "Write the prompt template for this command.\n\n"
                    "Use **{{full_input}}** where the user's text should go.\n\n"
                    "Examples:\n"
                    "• Summarize this: {{full_input}}\n"
                    "• Translate to Korean: {{full_input}}\n"
                    "• Give me 3 bullet points about: {{full_input}}",
                    3,
                ),
                data={"wizard_active": True, "stage": "ask_template"},
            )
        else:
            # Macro - skip to simpler flow (not fully implemented here)
            state.stage = "ask_enabled"
            _set_wizard_state(session_id, state)
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Enable Command",
                    "Macro commands require manual step configuration.\n"
                    "Enable this command now? (y/n, default: y)",
                    8,
                ),
                data={"wizard_active": True, "stage": "ask_enabled"},
            )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_template
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_template":
        if not text:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Prompt Template",
                    "Please enter a prompt template (cannot be empty):",
                    3,
                ),
                data={"wizard_active": True, "stage": "ask_template"},
            )
        
        state.prompt_template = text
        state.stage = "ask_intensive"
        _set_wizard_state(session_id, state)
        
        return CommandResponse(
            ok=True,
            command="command-add",
            summary=_wizard_prompt(
                "Model Selection",
                "Should this command use the **deep reasoning model** (GPT-5.1)?\n\n"
                "• **y** — Use GPT-5.1 (slower, better for complex analysis)\n"
                "• **n** — Use GPT-4.1-mini (faster, good for simple tasks)\n\n"
                "Type: y or n (default: n)",
                4,
            ),
            data={"wizard_active": True, "stage": "ask_intensive"},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_intensive
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_intensive":
        answer = text.lower()
        if answer in ("y", "yes"):
            state.intensive = True
        elif answer in ("n", "no", ""):
            state.intensive = False
        else:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Model Selection",
                    "Please type **y** (yes) or **n** (no):",
                    4,
                ),
                data={"wizard_active": True, "stage": "ask_intensive"},
            )
        
        state.stage = "ask_style"
        _set_wizard_state(session_id, state)
        
        return CommandResponse(
            ok=True,
            command="command-add",
            summary=_wizard_prompt(
                "Output Style",
                "Choose an output style:\n\n"
                "1. **natural** — Conversational (default)\n"
                "2. **bullets** — Bullet point list\n"
                "3. **numbered** — Numbered list\n"
                "4. **short** — Brief, 1-2 sentences\n"
                "5. **verbose** — Detailed explanation\n"
                "6. **json** — Structured JSON only\n\n"
                "Type a number (1-6) or name (default: natural):",
                5,
            ),
            data={"wizard_active": True, "stage": "ask_style"},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_style
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_style":
        style_map = {
            "1": "natural", "2": "bullets", "3": "numbered",
            "4": "short", "5": "verbose", "6": "json",
            "natural": "natural", "bullets": "bullets", "numbered": "numbered",
            "short": "short", "verbose": "verbose", "json": "json",
        }
        
        answer = text.lower() if text else "1"
        if answer not in style_map:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Output Style",
                    "Please type a number (1-6) or style name:",
                    5,
                ),
                data={"wizard_active": True, "stage": "ask_style"},
            )
        
        state.output_style = style_map[answer]
        state.stage = "ask_strict"
        _set_wizard_state(session_id, state)
        
        return CommandResponse(
            ok=True,
            command="command-add",
            summary=_wizard_prompt(
                "Strict Mode",
                "Enable **strict mode**?\n\n"
                "When enabled, the AI will:\n"
                "• Follow instructions exactly\n"
                "• Not add extra commentary\n"
                "• Not improvise or elaborate\n\n"
                "Type: y or n (default: n)",
                6,
            ),
            data={"wizard_active": True, "stage": "ask_strict"},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_strict
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_strict":
        answer = text.lower()
        if answer in ("y", "yes"):
            state.strict = True
        elif answer in ("n", "no", ""):
            state.strict = False
        else:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Strict Mode",
                    "Please type **y** (yes) or **n** (no):",
                    6,
                ),
                data={"wizard_active": True, "stage": "ask_strict"},
            )
        
        state.stage = "ask_persona"
        _set_wizard_state(session_id, state)
        
        return CommandResponse(
            ok=True,
            command="command-add",
            summary=_wizard_prompt(
                "Persona Mode",
                "Choose a persona mode:\n\n"
                "1. **nova** — Warm, helpful Nova voice (default)\n"
                "2. **neutral** — Professional, no personality\n"
                "3. **professional** — Formal, business-like\n\n"
                "Type a number (1-3) or name (default: nova):",
                7,
            ),
            data={"wizard_active": True, "stage": "ask_persona"},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_persona
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_persona":
        persona_map = {
            "1": "nova", "2": "neutral", "3": "professional",
            "nova": "nova", "neutral": "neutral", "professional": "professional",
        }
        
        answer = text.lower() if text else "1"
        if answer not in persona_map:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Persona Mode",
                    "Please type a number (1-3) or persona name:",
                    7,
                ),
                data={"wizard_active": True, "stage": "ask_persona"},
            )
        
        state.persona_mode = persona_map[answer]
        state.stage = "ask_examples"
        _set_wizard_state(session_id, state)
        
        return CommandResponse(
            ok=True,
            command="command-add",
            summary=_wizard_prompt(
                "Few-Shot Examples",
                "Would you like to add **example input/output pairs**?\n\n"
                "Examples help the AI understand exactly how to respond.\n"
                "This is optional but can improve consistency.\n\n"
                "Type: y or n (default: n)",
                8,
            ),
            data={"wizard_active": True, "stage": "ask_examples"},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_examples
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_examples":
        answer = text.lower()
        if answer in ("y", "yes"):
            state.stage = "ask_example_input"
            state.collecting_example = True
            _set_wizard_state(session_id, state)
            
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Example Input",
                    f"Example #{len(state.examples) + 1}\n\n"
                    "Enter an example **input** (what the user might type):",
                    8,
                ),
                data={"wizard_active": True, "stage": "ask_example_input"},
            )
        else:
            state.stage = "ask_enabled"
            _set_wizard_state(session_id, state)
            
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Enable Command",
                    "Enable this command now? (y/n, default: y)",
                    9,
                ),
                data={"wizard_active": True, "stage": "ask_enabled"},
            )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_example_input
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_example_input":
        if not text:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Example Input",
                    "Please enter an example input (cannot be empty):",
                    8,
                ),
                data={"wizard_active": True, "stage": "ask_example_input"},
            )
        
        state.current_example_input = text
        state.stage = "ask_example_output"
        _set_wizard_state(session_id, state)
        
        return CommandResponse(
            ok=True,
            command="command-add",
            summary=_wizard_prompt(
                "Example Output",
                f"Example #{len(state.examples) + 1}\n\n"
                f"Input: {text[:50]}{'...' if len(text) > 50 else ''}\n\n"
                "Now enter the expected **output** for this input:",
                8,
            ),
            data={"wizard_active": True, "stage": "ask_example_output"},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_example_output
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_example_output":
        if not text:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Example Output",
                    "Please enter an example output (cannot be empty):",
                    8,
                ),
                data={"wizard_active": True, "stage": "ask_example_output"},
            )
        
        # Save the example
        state.examples.append({
            "input": state.current_example_input,
            "output": text,
        })
        state.current_example_input = ""
        state.stage = "ask_more_examples"
        _set_wizard_state(session_id, state)
        
        return CommandResponse(
            ok=True,
            command="command-add",
            summary=_wizard_prompt(
                "More Examples",
                f"✓ Example #{len(state.examples)} added.\n\n"
                "Add another example? (y/n)",
                8,
            ),
            data={"wizard_active": True, "stage": "ask_more_examples"},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_more_examples
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_more_examples":
        answer = text.lower()
        if answer in ("y", "yes"):
            state.stage = "ask_example_input"
            _set_wizard_state(session_id, state)
            
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Example Input",
                    f"Example #{len(state.examples) + 1}\n\n"
                    "Enter an example **input**:",
                    8,
                ),
                data={"wizard_active": True, "stage": "ask_example_input"},
            )
        else:
            state.stage = "ask_enabled"
            _set_wizard_state(session_id, state)
            
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Enable Command",
                    "Enable this command now? (y/n, default: y)",
                    9,
                ),
                data={"wizard_active": True, "stage": "ask_enabled"},
            )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: ask_enabled
    # ─────────────────────────────────────────────────────────────────────
    if stage == "ask_enabled":
        answer = text.lower()
        if answer in ("y", "yes", ""):
            state.enabled = True
        elif answer in ("n", "no"):
            state.enabled = False
        else:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=_wizard_prompt(
                    "Enable Command",
                    "Please type **y** (yes) or **n** (no):",
                    9,
                ),
                data={"wizard_active": True, "stage": "ask_enabled"},
            )
        
        state.stage = "confirm"
        _set_wizard_state(session_id, state)
        
        # Build summary
        model_str = "GPT-5.1 (thinking)" if state.intensive else "GPT-4.1-mini (fast)"
        examples_str = f"{len(state.examples)} examples" if state.examples else "None"
        
        summary_lines = [
            "╔══ Command Summary ══╗",
            "",
            f"**Name:** #{state.name}",
            f"**Kind:** {state.kind}",
            f"**Model:** {model_str}",
            f"**Output Style:** {state.output_style}",
            f"**Strict Mode:** {'Yes' if state.strict else 'No'}",
            f"**Persona:** {state.persona_mode}",
            f"**Examples:** {examples_str}",
            f"**Enabled:** {'Yes' if state.enabled else 'No'}",
            "",
            f"**Template:**",
            f"```",
            f"{state.prompt_template[:200]}{'...' if len(state.prompt_template) > 200 else ''}",
            f"```",
            "",
            "Create this command? (y/n)",
        ]
        
        return CommandResponse(
            ok=True,
            command="command-add",
            summary="\n".join(summary_lines),
            data={"wizard_active": True, "stage": "confirm"},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Stage: confirm
    # ─────────────────────────────────────────────────────────────────────
    if stage == "confirm":
        answer = text.lower()
        if answer in ("y", "yes"):
            # Create the command
            config = state.to_dict()
            normalized = normalize_custom_command_v2(state.name, config)
            kernel.custom_registry.add(state.name, normalized)
            
            _clear_wizard_state(session_id)
            
            model_str = "GPT-5.1" if state.intensive else "GPT-4.1-mini"
            return CommandResponse(
                ok=True,
                command="command-add",
                summary=(
                    f"✓ **Custom command created!**\n\n"
                    f"**#{state.name}** is ready to use.\n\n"
                    f"• Model: {model_str}\n"
                    f"• Style: {state.output_style}\n"
                    f"• Examples: {len(state.examples)}\n\n"
                    f"Try it: `#{state.name} <your text>`"
                ),
                data={"wizard_active": False, "created": state.name},
            )
        elif answer in ("n", "no"):
            _clear_wizard_state(session_id)
            return CommandResponse(
                ok=True,
                command="command-add",
                summary="✗ Command creation cancelled.",
                data={"wizard_active": False},
            )
        else:
            return CommandResponse(
                ok=True,
                command="command-add",
                summary="Create this command? Please type **y** (yes) or **n** (no):",
                data={"wizard_active": True, "stage": "confirm"},
            )
    
    # Fallback
    _clear_wizard_state(session_id)
    return CommandResponse(
        ok=False,
        command="command-add",
        summary="Wizard error. Please try again with #command-add",
        data={"wizard_active": False},
    )


# =============================================================================
# MAIN HANDLER
# =============================================================================

def handle_command_add_with_wizard(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    v0.7.17 — Command-add with wizard support.
    
    Two modes:
    1. DIRECT MODE: If args contain 'name' or other fields → immediate creation
    2. WIZARD MODE: If no args (or wizard in progress) → interactive wizard
    """
    # Check if wizard is already active for this session
    active_wizard = _get_wizard_state(session_id)
    
    # Check if args were provided (direct mode)
    has_args = False
    if isinstance(args, dict):
        # Check for any meaningful args beyond raw_text
        meaningful_keys = {"name", "kind", "prompt_template", "intensive", "output_style", 
                          "strict", "persona_mode", "examples", "enabled", "description"}
        has_args = bool(set(args.keys()) & meaningful_keys)
    
    # If wizard is active, continue wizard flow
    if active_wizard:
        # Get user input from args
        user_input = ""
        if isinstance(args, dict):
            user_input = args.get("full_input", "") or args.get("raw_text", "") or ""
        if not user_input and context:
            user_input = context.get("raw_text", "")
        
        return process_wizard_stage(session_id, user_input, kernel)
    
    # If args provided, use direct mode (existing behavior)
    if has_args:
        return _direct_create_command(cmd_name, args, session_id, kernel)
    
    # No args, no active wizard → start wizard
    return process_wizard_stage(session_id, "", kernel)


def _direct_create_command(cmd_name, args, session_id, kernel) -> CommandResponse:
    """
    Direct command creation (non-wizard mode).
    
    This preserves the existing behavior when args are provided.
    """
    import json
    
    if not isinstance(args, dict):
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="command-add requires structured arguments.",
            error_code="INVALID_ARGS",
            error_message="Expected dictionary arguments",
        )
    
    name = args.get("name")
    if not name:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Missing required field: name",
            error_code="MISSING_NAME",
            error_message="Command name is required",
        )
    
    # Parse examples if provided as JSON string
    if "examples" in args and isinstance(args["examples"], str):
        try:
            args["examples"] = json.loads(args["examples"])
        except json.JSONDecodeError:
            return CommandResponse(
                ok=False,
                command=cmd_name,
                summary="Invalid JSON in 'examples' field",
                error_code="INVALID_EXAMPLES",
                error_message="Examples must be valid JSON array",
            )
    
    # Normalize with v0.7.16 fields
    normalized = normalize_custom_command_v2(name, args)
    
    # Add to registry
    kernel.custom_registry.add(name, normalized)
    
    # Build confirmation message
    tier = "GPT-5.1 (thinking)" if normalized.get("intensive") else "GPT-4.1-mini"
    style = normalized.get("output_style", "natural")
    
    lines = [
        F.header("Custom Command Added"),
        F.key_value("Name", f"#{name}"),
        F.key_value("Kind", normalized.get("kind")),
        F.key_value("Model", tier),
        F.key_value("Output Style", style),
    ]
    
    if normalized.get("strict"):
        lines.append(F.key_value("Strict Mode", "enabled"))
    
    if normalized.get("examples"):
        lines.append(F.key_value("Examples", f"{len(normalized['examples'])} configured"))
    
    summary = "\n".join(lines)
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=normalized,
    )


# =============================================================================
# WIZARD STATE CHECK (for nova_kernel.py integration)
# =============================================================================

def is_command_add_wizard_active(session_id: str) -> bool:
    """Check if command-add wizard is active for session."""
    return session_id in _wizard_sessions


def clear_command_add_wizard(session_id: str) -> None:
    """Clear command-add wizard state."""
    _clear_wizard_state(session_id)
