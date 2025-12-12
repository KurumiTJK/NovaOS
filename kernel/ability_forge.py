"""
NovaOS Ability Forge — v1.0.0

The Ability Forge is the ONLY custom command system in NovaOS.
It replaces all legacy command/macro/alias systems.

Commands (Commands Section):
- #commands-list         List all saved abilities
- #commands-forge        Start forging a new ability (or edit existing)
- #commands-edit         Edit an existing ability
- #commands-preview      Preview current draft
- #commands-diff         Show changes from last saved version
- #commands-confirm      Save draft and exit forge mode
- #commands-cancel       Discard draft and exit forge mode
- #commands-delete       Delete a saved ability

Forge Mode:
- Any plain text (not starting with #) is treated as an edit instruction
- Only allowed commands: #commands-confirm, #commands-cancel, #commands-preview, #commands-diff, #help commands
- All other #commands are blocked

Ability Structure:
- name: Unique identifier
- description: What it does
- type: "ability"
- enabled: bool
- pipeline: [fetch, reason, write] stages
- schema: {signals: [...], derived: [...]}
- output_style: "boxed_os"
- permissions: {allow_web: true}
- version: int
- updated_at: ISO timestamp
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import command types
try:
    from .command_types import CommandResponse
except ImportError:
    # Fallback for standalone testing
    @dataclass
    class CommandResponse:
        ok: bool = True
        command: str = ""
        summary: str = ""
        data: Dict = field(default_factory=dict)
        error_code: str = ""
        error_message: str = ""
        type: str = "syscommand"


# =============================================================================
# CONSTANTS
# =============================================================================

# Allowed commands during forge mode
FORGE_MODE_ALLOWED_COMMANDS = {
    "commands-confirm",
    "commands-cancel", 
    "commands-preview",
    "commands-diff",
    "help",
}

# Default pipeline structure
DEFAULT_PIPELINE = [
    {
        "stage": "fetch",
        "executor": "gemini",
        "web": True,
        "prompt": "Search for current information about: {topic}\n\nReturn JSON with these signals: {signals}"
    },
    {
        "stage": "reason", 
        "executor": "dualgpt",
        "web": False,
        "prompt": "Analyze the fetched data and derive insights.\n\nInput signals: {signals}\nDerive: {derived}\n\nReturn JSON with derived fields."
    },
    {
        "stage": "write",
        "executor": "dualgpt", 
        "web": False,
        "prompt": "Generate a NovaOS boxed output report.\n\nUse this data:\n{all_data}\n\nFormat as boxed OS output."
    }
]

# Default schema
DEFAULT_SCHEMA = {
    "signals": [],
    "derived": []
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PipelineStage:
    """A single stage in the ability pipeline."""
    stage: str  # fetch, reason, write
    executor: str  # gemini, dualgpt
    web: bool = False
    prompt: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PipelineStage":
        return cls(
            stage=data.get("stage", ""),
            executor=data.get("executor", ""),
            web=data.get("web", False),
            prompt=data.get("prompt", ""),
        )


@dataclass
class AbilitySchema:
    """Schema defining signals and derived fields."""
    signals: List[str] = field(default_factory=list)
    derived: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "AbilitySchema":
        return cls(
            signals=data.get("signals", []),
            derived=data.get("derived", []),
        )


@dataclass
class Ability:
    """A saved ability (custom command)."""
    name: str
    description: str = ""
    type: str = "ability"
    enabled: bool = True
    pipeline: List[PipelineStage] = field(default_factory=list)
    schema: AbilitySchema = field(default_factory=AbilitySchema)
    output_style: str = "boxed_os"
    permissions: Dict[str, Any] = field(default_factory=lambda: {"allow_web": True})
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "type": self.type,
            "enabled": self.enabled,
            "pipeline": [p.to_dict() if isinstance(p, PipelineStage) else p for p in self.pipeline],
            "schema": self.schema.to_dict() if isinstance(self.schema, AbilitySchema) else self.schema,
            "output_style": self.output_style,
            "permissions": self.permissions,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Ability":
        pipeline_data = data.get("pipeline", [])
        pipeline = [
            PipelineStage.from_dict(p) if isinstance(p, dict) else p 
            for p in pipeline_data
        ]
        
        schema_data = data.get("schema", {})
        schema = AbilitySchema.from_dict(schema_data) if isinstance(schema_data, dict) else AbilitySchema()
        
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            type=data.get("type", "ability"),
            enabled=data.get("enabled", True),
            pipeline=pipeline,
            schema=schema,
            output_style=data.get("output_style", "boxed_os"),
            permissions=data.get("permissions", {"allow_web": True}),
            version=data.get("version", 1),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class EditHistoryEntry:
    """A single edit in the forge history."""
    at: str  # ISO timestamp
    user_edit: str  # What the user said
    changes_summary: str  # One-liner of what changed
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ForgeDraft:
    """Current forge mode draft."""
    ability: Ability
    history: List[EditHistoryEntry] = field(default_factory=list)
    original_name: Optional[str] = None  # For edit mode - track original
    
    def to_dict(self) -> Dict:
        return {
            "ability": self.ability.to_dict(),
            "history": [h.to_dict() for h in self.history],
            "original_name": self.original_name,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ForgeDraft":
        ability_data = data.get("ability", {})
        ability = Ability.from_dict(ability_data)
        
        history_data = data.get("history", [])
        history = [
            EditHistoryEntry(**h) if isinstance(h, dict) else h
            for h in history_data
        ]
        
        return cls(
            ability=ability,
            history=history,
            original_name=data.get("original_name"),
        )


@dataclass
class AbilityRunState:
    """Snapshot of last ability run."""
    last_run_at: str
    signals: Dict[str, Any] = field(default_factory=dict)
    derived: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return asdict(self)


# =============================================================================
# FORGE STATE (Session-based)
# =============================================================================

# Session -> ForgeDraft mapping
_forge_sessions: Dict[str, ForgeDraft] = {}


def is_forge_mode_active(session_id: str) -> bool:
    """Check if forge mode is active for this session."""
    return session_id in _forge_sessions


def get_forge_draft(session_id: str) -> Optional[ForgeDraft]:
    """Get the current forge draft for a session."""
    return _forge_sessions.get(session_id)


def set_forge_draft(session_id: str, draft: ForgeDraft) -> None:
    """Set the forge draft for a session."""
    _forge_sessions[session_id] = draft


def clear_forge_draft(session_id: str) -> None:
    """Clear forge mode for a session."""
    _forge_sessions.pop(session_id, None)


# =============================================================================
# DATA LAYER - FILE OPERATIONS
# =============================================================================

def _get_data_dir(kernel: Any) -> Path:
    """Get the data directory from kernel config."""
    if hasattr(kernel, 'config') and hasattr(kernel.config, 'data_dir'):
        return Path(kernel.config.data_dir)
    # Fallback
    return Path("data")


def _load_custom_commands(kernel: Any) -> Dict[str, Ability]:
    """Load all abilities from custom_commands.json."""
    data_dir = _get_data_dir(kernel)
    file_path = data_dir / "custom_commands.json"
    
    if not file_path.exists():
        return {}
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Handle both formats: {"version": 1, "commands": [...]} or direct dict
        if isinstance(data, dict):
            if "commands" in data and isinstance(data["commands"], list):
                # New format
                commands = {}
                for cmd in data["commands"]:
                    if isinstance(cmd, dict) and "name" in cmd:
                        ability = Ability.from_dict(cmd)
                        commands[ability.name] = ability
                return commands
            else:
                # Legacy format - dict of name -> meta
                commands = {}
                for name, meta in data.items():
                    if name in ("version",):
                        continue
                    if isinstance(meta, dict):
                        meta["name"] = name
                        ability = Ability.from_dict(meta)
                        commands[name] = ability
                return commands
        
        return {}
        
    except Exception as e:
        print(f"[AbilityForge] Error loading custom_commands.json: {e}", flush=True)
        return {}


def _save_custom_commands(kernel: Any, commands: Dict[str, Ability]) -> bool:
    """Save all abilities to custom_commands.json."""
    data_dir = _get_data_dir(kernel)
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "custom_commands.json"
    
    try:
        data = {
            "version": 1,
            "commands": [ability.to_dict() for ability in commands.values()]
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return True
        
    except Exception as e:
        print(f"[AbilityForge] Error saving custom_commands.json: {e}", flush=True)
        return False


def _load_forge_draft_file(kernel: Any) -> Optional[ForgeDraft]:
    """Load draft from command_draft.json (for persistence across restarts)."""
    data_dir = _get_data_dir(kernel)
    file_path = data_dir / "command_draft.json"
    
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        if data.get("mode") == "forge" and "draft" in data:
            return ForgeDraft.from_dict(data["draft"])
        
        return None
        
    except Exception as e:
        print(f"[AbilityForge] Error loading command_draft.json: {e}", flush=True)
        return None


def _save_forge_draft_file(kernel: Any, draft: Optional[ForgeDraft]) -> bool:
    """Save draft to command_draft.json."""
    data_dir = _get_data_dir(kernel)
    data_dir.mkdir(parents=True, exist_ok=True)
    file_path = data_dir / "command_draft.json"
    
    try:
        if draft is None:
            data = {"mode": None, "draft": None, "history": []}
        else:
            data = {
                "mode": "forge",
                "draft": draft.to_dict(),
                "history": [h.to_dict() for h in draft.history]
            }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        return True
        
    except Exception as e:
        print(f"[AbilityForge] Error saving command_draft.json: {e}", flush=True)
        return False


def _load_ability_state(kernel: Any, name: str) -> Optional[AbilityRunState]:
    """Load last run state for an ability."""
    data_dir = _get_data_dir(kernel)
    state_dir = data_dir / "ability_state"
    file_path = state_dir / f"{name}.json"
    
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AbilityRunState(**data)
    except Exception as e:
        print(f"[AbilityForge] Error loading ability state for {name}: {e}", flush=True)
        return None


def _save_ability_state(kernel: Any, name: str, state: AbilityRunState) -> bool:
    """Save run state for an ability."""
    data_dir = _get_data_dir(kernel)
    state_dir = data_dir / "ability_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    file_path = state_dir / f"{name}.json"
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[AbilityForge] Error saving ability state for {name}: {e}", flush=True)
        return False


# =============================================================================
# RESPONSE HELPERS
# =============================================================================

def _base_response(cmd_name: str, summary: str, data: Optional[Dict] = None) -> CommandResponse:
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=data or {},
        type="syscommand",
    )


def _error_response(cmd_name: str, message: str, error_code: str = "ERROR") -> CommandResponse:
    return CommandResponse(
        ok=False,
        command=cmd_name,
        summary=message,
        error_code=error_code,
        error_message=message,
        type="error",
    )


# =============================================================================
# PREVIEW FORMATTING
# =============================================================================

def _format_ability_preview(ability: Ability) -> str:
    """Format ability for preview display."""
    lines = [
        f"╔══ Ability Forge: {ability.name} ══╗",
        "",
        "Preview Output:",
        "┌─────────────────────────────────────┐",
        f"│  {ability.name.upper()}",
        "│  (Simulated output preview)",
        "│",
    ]
    
    # Add schema fields preview
    if ability.schema.signals:
        lines.append(f"│  Signals: {', '.join(ability.schema.signals)}")
    if ability.schema.derived:
        lines.append(f"│  Derived: {', '.join(ability.schema.derived)}")
    
    lines.extend([
        "│",
        "│  [Output will appear here when run]",
        "└─────────────────────────────────────┘",
        "",
        "Spec Summary:",
    ])
    
    # Pipeline summary
    for stage in ability.pipeline:
        if isinstance(stage, PipelineStage):
            web_tag = " (web)" if stage.web else ""
            lines.append(f"  - {stage.stage}: {stage.executor}{web_tag}")
        elif isinstance(stage, dict):
            web_tag = " (web)" if stage.get("web") else ""
            lines.append(f"  - {stage.get('stage', '?')}: {stage.get('executor', '?')}{web_tag}")
    
    # Schema summary
    sig_count = len(ability.schema.signals) if isinstance(ability.schema, AbilitySchema) else 0
    der_count = len(ability.schema.derived) if isinstance(ability.schema, AbilitySchema) else 0
    lines.append(f"  - schema: {sig_count} signals / {der_count} derived")
    
    lines.extend([
        "",
        "Edit by typing plain text.",
        "Confirm: #commands-confirm",
        "Cancel:  #commands-cancel",
    ])
    
    return "\n".join(lines)


# =============================================================================
# FORGE MODE EDIT APPLICATION
# =============================================================================

def _apply_edit_to_draft(
    draft: ForgeDraft,
    user_edit: str,
    kernel: Any,
) -> Tuple[ForgeDraft, str]:
    """
    Apply a plain-text edit instruction to the draft using dualgpt.
    Returns (updated_draft, changes_summary).
    """
    ability = draft.ability
    
    # Build prompt for dualgpt to interpret the edit
    system_prompt = """You are an Ability Forge assistant. The user wants to modify an ability spec.

Current ability spec:
- Name: {name}
- Description: {description}
- Pipeline stages:
{pipeline}
- Schema signals: {signals}
- Schema derived: {derived}
- Output style: {output_style}

The user's edit instruction is below. Interpret it and return a JSON object with ONLY the fields that should change.
Valid fields to modify:
- description: string
- pipeline: array of {{stage, executor, web, prompt}}
- schema: {{signals: [...], derived: [...]}}
- output_style: string

Return ONLY valid JSON. No explanation.
If the edit is unclear, make a reasonable interpretation.
"""
    
    # Format pipeline for prompt
    pipeline_str = ""
    for i, stage in enumerate(ability.pipeline):
        if isinstance(stage, PipelineStage):
            pipeline_str += f"  {i+1}. {stage.stage} (executor={stage.executor}, web={stage.web})\n"
            pipeline_str += f"     prompt: {stage.prompt[:100]}...\n"
        elif isinstance(stage, dict):
            pipeline_str += f"  {i+1}. {stage.get('stage')} (executor={stage.get('executor')}, web={stage.get('web')})\n"
    
    signals = ability.schema.signals if isinstance(ability.schema, AbilitySchema) else []
    derived = ability.schema.derived if isinstance(ability.schema, AbilitySchema) else []
    
    formatted_system = system_prompt.format(
        name=ability.name,
        description=ability.description,
        pipeline=pipeline_str,
        signals=signals,
        derived=derived,
        output_style=ability.output_style,
    )
    
    # Call LLM to interpret edit
    changes_summary = "Edit applied"
    
    try:
        llm_client = getattr(kernel, 'llm_client', None)
        if llm_client:
            result = llm_client.complete_system(
                system=formatted_system,
                user=f"User edit instruction: {user_edit}",
                command="ability-forge-edit",
                think_mode=False,
            )
            
            response_text = result.get("text", "").strip()
            
            # Try to parse as JSON
            try:
                # Strip markdown code fences if present
                if response_text.startswith("```"):
                    lines = response_text.split("\n")
                    response_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                
                changes = json.loads(response_text)
                
                # Apply changes
                if "description" in changes:
                    ability.description = changes["description"]
                    changes_summary = "Updated description"
                
                if "pipeline" in changes and isinstance(changes["pipeline"], list):
                    ability.pipeline = [
                        PipelineStage.from_dict(p) if isinstance(p, dict) else p
                        for p in changes["pipeline"]
                    ]
                    changes_summary = "Updated pipeline"
                
                if "schema" in changes and isinstance(changes["schema"], dict):
                    ability.schema = AbilitySchema.from_dict(changes["schema"])
                    changes_summary = f"Updated schema: {len(ability.schema.signals)} signals, {len(ability.schema.derived)} derived"
                
                if "output_style" in changes:
                    ability.output_style = changes["output_style"]
                    changes_summary = "Updated output style"
                    
            except json.JSONDecodeError:
                # LLM didn't return valid JSON - try to interpret naturally
                changes_summary = f"Interpreted edit: {user_edit[:50]}"
                
    except Exception as e:
        print(f"[AbilityForge] Edit interpretation error: {e}", flush=True)
        changes_summary = f"Edit recorded (manual review needed)"
    
    # Update timestamp
    ability.updated_at = datetime.now(timezone.utc).isoformat()
    
    # Add to history
    entry = EditHistoryEntry(
        at=datetime.now(timezone.utc).isoformat(),
        user_edit=user_edit,
        changes_summary=changes_summary,
    )
    draft.history.append(entry)
    draft.ability = ability
    
    return draft, changes_summary


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_commands_list(cmd_name: str, args: Dict, session_id: str, context: Dict, kernel: Any, meta: Dict) -> CommandResponse:
    """List all saved abilities."""
    print(f"[AbilityForge] handle_commands_list called", flush=True)
    
    try:
        commands = _load_custom_commands(kernel)
        
        if not commands:
            lines = [
                "╔══ Abilities ══╗",
                "",
                "No abilities defined yet.",
                "",
                "Create your first ability with:",
                '  #commands-forge name="my-ability"',
                "",
                "Or use the default:",
                "  #quadrant-status",
            ]
            return _base_response(cmd_name, "\n".join(lines), {"abilities": [], "count": 0})
        
        lines = [
            "╔══ Abilities ══╗",
            "",
        ]
        
        for name, ability in sorted(commands.items()):
            status = "✓" if ability.enabled else "✗"
            desc = ability.description[:40] + "..." if len(ability.description) > 40 else ability.description
            lines.append(f"  {status} #{name}")
            if desc:
                lines.append(f"      {desc}")
            lines.append(f"      v{ability.version} · {len(ability.pipeline)} stages")
            lines.append("")
        
        lines.extend([
            "─────────────────────────────────",
            "Commands:",
            "  #commands-forge name=<n>  — Create/edit ability",
            "  #commands-delete name=<n> — Delete ability",
            "  #<ability-name>           — Run ability",
        ])
        
        return _base_response(cmd_name, "\n".join(lines), {
            "abilities": list(commands.keys()),
            "count": len(commands),
        })
        
    except Exception as e:
        print(f"[AbilityForge] Error in commands-list: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_commands_forge(cmd_name: str, args: Dict, session_id: str, context: Dict, kernel: Any, meta: Dict) -> CommandResponse:
    """Start forging a new ability or edit existing one."""
    print(f"[AbilityForge] handle_commands_forge called", flush=True)
    
    try:
        # Check if already in forge mode
        if is_forge_mode_active(session_id):
            draft = get_forge_draft(session_id)
            return _base_response(
                cmd_name,
                f"Already forging '{draft.ability.name}'.\n\nUse #commands-confirm to save or #commands-cancel to discard.",
                {"forge_active": True, "name": draft.ability.name}
            )
        
        # Get name from args
        name = None
        if isinstance(args, dict):
            name = args.get("name")
            positional = args.get("_", [])
            if not name and positional:
                name = str(positional[0])
        
        if not name:
            # Show usage
            lines = [
                "╔══ Ability Forge ══╗",
                "",
                "Create a new ability:",
                '  #commands-forge name="my-ability"',
                "",
                "Edit existing ability:",
                '  #commands-edit name="existing-ability"',
                "",
                "Example:",
                '  #commands-forge name="market-scan"',
                "",
                "This starts an interactive forge session where you",
                "can refine the ability by typing plain text edits.",
            ]
            return _base_response(cmd_name, "\n".join(lines), {"usage": True})
        
        # Clean the name
        name = name.lower().replace(" ", "-").strip()
        
        # Check if ability already exists
        commands = _load_custom_commands(kernel)
        
        if name in commands:
            # Edit existing
            existing = commands[name]
            draft = ForgeDraft(
                ability=existing,
                history=[],
                original_name=name,
            )
        else:
            # Create new with default pipeline
            ability = Ability(
                name=name,
                description=f"Custom ability: {name}",
                pipeline=[PipelineStage.from_dict(p) for p in DEFAULT_PIPELINE],
                schema=AbilitySchema(
                    signals=["topic", "data_points"],
                    derived=["analysis", "recommendation"],
                ),
            )
            draft = ForgeDraft(
                ability=ability,
                history=[],
                original_name=None,
            )
        
        # Enter forge mode
        set_forge_draft(session_id, draft)
        _save_forge_draft_file(kernel, draft)
        
        preview = _format_ability_preview(draft.ability)
        
        return _base_response(cmd_name, preview, {
            "forge_active": True,
            "name": name,
            "is_new": draft.original_name is None,
        })
        
    except Exception as e:
        print(f"[AbilityForge] Error in commands-forge: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_commands_edit(cmd_name: str, args: Dict, session_id: str, context: Dict, kernel: Any, meta: Dict) -> CommandResponse:
    """Edit an existing ability (alias for forge with existing name)."""
    print(f"[AbilityForge] handle_commands_edit called", flush=True)
    
    # Get name
    name = None
    if isinstance(args, dict):
        name = args.get("name")
        positional = args.get("_", [])
        if not name and positional:
            name = str(positional[0])
    
    if not name:
        return _error_response(cmd_name, "Usage: #commands-edit name=<ability-name>", "MISSING_NAME")
    
    # Check if exists
    commands = _load_custom_commands(kernel)
    name_lower = name.lower().replace(" ", "-").strip()
    
    if name_lower not in commands:
        return _error_response(cmd_name, f"Ability '{name}' not found. Use #commands-list to see available abilities.", "NOT_FOUND")
    
    # Delegate to forge
    args["name"] = name_lower
    return handle_commands_forge(cmd_name, args, session_id, context, kernel, meta)


def handle_commands_preview(cmd_name: str, args: Dict, session_id: str, context: Dict, kernel: Any, meta: Dict) -> CommandResponse:
    """Preview the current forge draft."""
    print(f"[AbilityForge] handle_commands_preview called", flush=True)
    
    if not is_forge_mode_active(session_id):
        return _error_response(cmd_name, "No active forge session. Use #commands-forge to start.", "NO_FORGE")
    
    draft = get_forge_draft(session_id)
    preview = _format_ability_preview(draft.ability)
    
    return _base_response(cmd_name, preview, {
        "forge_active": True,
        "name": draft.ability.name,
    })


def handle_commands_diff(cmd_name: str, args: Dict, session_id: str, context: Dict, kernel: Any, meta: Dict) -> CommandResponse:
    """Show changes from the original/last saved version."""
    print(f"[AbilityForge] handle_commands_diff called", flush=True)
    
    if not is_forge_mode_active(session_id):
        return _error_response(cmd_name, "No active forge session. Use #commands-forge to start.", "NO_FORGE")
    
    draft = get_forge_draft(session_id)
    
    if not draft.history:
        return _base_response(cmd_name, "No changes made yet.", {"changes": []})
    
    lines = [
        f"╔══ Changes to: {draft.ability.name} ══╗",
        "",
    ]
    
    for i, entry in enumerate(draft.history, 1):
        lines.append(f"{i}. [{entry.at[:16]}] {entry.changes_summary}")
        lines.append(f"   Edit: \"{entry.user_edit[:50]}{'...' if len(entry.user_edit) > 50 else ''}\"")
        lines.append("")
    
    lines.extend([
        "─────────────────────────────────",
        "#commands-confirm to save all changes",
        "#commands-cancel to discard all changes",
    ])
    
    return _base_response(cmd_name, "\n".join(lines), {
        "changes": [e.to_dict() for e in draft.history],
        "count": len(draft.history),
    })


def handle_commands_confirm(cmd_name: str, args: Dict, session_id: str, context: Dict, kernel: Any, meta: Dict) -> CommandResponse:
    """Save the draft and exit forge mode."""
    print(f"[AbilityForge] handle_commands_confirm called", flush=True)
    
    if not is_forge_mode_active(session_id):
        return _error_response(cmd_name, "No active forge session.", "NO_FORGE")
    
    try:
        draft = get_forge_draft(session_id)
        ability = draft.ability
        
        # Increment version if editing existing
        if draft.original_name:
            ability.version += 1
        
        ability.updated_at = datetime.now(timezone.utc).isoformat()
        
        # Load existing commands
        commands = _load_custom_commands(kernel)
        
        # If renamed, remove old
        if draft.original_name and draft.original_name != ability.name:
            commands.pop(draft.original_name, None)
        
        # Save new/updated
        commands[ability.name] = ability
        
        if not _save_custom_commands(kernel, commands):
            return _error_response(cmd_name, "Failed to save ability.", "SAVE_ERROR")
        
        # Clear forge mode
        clear_forge_draft(session_id)
        _save_forge_draft_file(kernel, None)
        
        action = "Updated" if draft.original_name else "Created"
        lines = [
            f"✅ {action} ability: **{ability.name}**",
            "",
            f"Version: {ability.version}",
            f"Pipeline: {len(ability.pipeline)} stages",
            "",
            f"Run it with: #{ability.name}",
        ]
        
        return _base_response(cmd_name, "\n".join(lines), {
            "saved": True,
            "name": ability.name,
            "version": ability.version,
        })
        
    except Exception as e:
        print(f"[AbilityForge] Error in commands-confirm: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_commands_cancel(cmd_name: str, args: Dict, session_id: str, context: Dict, kernel: Any, meta: Dict) -> CommandResponse:
    """Discard the draft and exit forge mode."""
    print(f"[AbilityForge] handle_commands_cancel called", flush=True)
    
    if not is_forge_mode_active(session_id):
        return _error_response(cmd_name, "No active forge session.", "NO_FORGE")
    
    draft = get_forge_draft(session_id)
    name = draft.ability.name
    
    # Clear forge mode
    clear_forge_draft(session_id)
    _save_forge_draft_file(kernel, None)
    
    return _base_response(cmd_name, f"Forge cancelled. Draft for '{name}' discarded.", {
        "cancelled": True,
        "name": name,
    })


def handle_commands_delete(cmd_name: str, args: Dict, session_id: str, context: Dict, kernel: Any, meta: Dict) -> CommandResponse:
    """Delete a saved ability."""
    print(f"[AbilityForge] handle_commands_delete called", flush=True)
    
    try:
        # Get name
        name = None
        if isinstance(args, dict):
            name = args.get("name")
            positional = args.get("_", [])
            if not name and positional:
                name = str(positional[0])
        
        if not name:
            return _error_response(cmd_name, "Usage: #commands-delete name=<ability-name>", "MISSING_NAME")
        
        name_lower = name.lower().replace(" ", "-").strip()
        
        # Load commands
        commands = _load_custom_commands(kernel)
        
        if name_lower not in commands:
            return _error_response(cmd_name, f"Ability '{name}' not found.", "NOT_FOUND")
        
        # Delete
        del commands[name_lower]
        
        if not _save_custom_commands(kernel, commands):
            return _error_response(cmd_name, "Failed to delete ability.", "SAVE_ERROR")
        
        return _base_response(cmd_name, f"✅ Deleted ability: **{name_lower}**", {
            "deleted": True,
            "name": name_lower,
        })
        
    except Exception as e:
        print(f"[AbilityForge] Error in commands-delete: {e}", flush=True)
        traceback.print_exc()
        return _error_response(cmd_name, f"Error: {e}", "INTERNAL_ERROR")


def handle_forge_mode_input(user_input: str, session_id: str, kernel: Any) -> CommandResponse:
    """
    Handle plain text input during forge mode.
    This is called when forge mode is active and user sends non-# input.
    """
    print(f"[AbilityForge] handle_forge_mode_input: {user_input[:50]}...", flush=True)
    
    if not is_forge_mode_active(session_id):
        return None  # Not in forge mode, let normal processing continue
    
    draft = get_forge_draft(session_id)
    
    # Apply the edit
    updated_draft, changes_summary = _apply_edit_to_draft(draft, user_input, kernel)
    
    # Save updated draft
    set_forge_draft(session_id, updated_draft)
    _save_forge_draft_file(kernel, updated_draft)
    
    # Show preview with changes
    preview = _format_ability_preview(updated_draft.ability)
    
    lines = [
        f"✏️ {changes_summary}",
        "",
        preview,
    ]
    
    return _base_response("forge-edit", "\n".join(lines), {
        "forge_active": True,
        "name": updated_draft.ability.name,
        "changes": changes_summary,
    })


def check_forge_mode_blocking(cmd_name: str, session_id: str) -> Optional[CommandResponse]:
    """
    Check if a command should be blocked during forge mode.
    Returns a blocking response if blocked, None if allowed.
    """
    if not is_forge_mode_active(session_id):
        return None
    
    # Check if command is allowed
    if cmd_name in FORGE_MODE_ALLOWED_COMMANDS:
        return None
    
    # Block other commands
    return _error_response(
        cmd_name,
        f"Forge mode active. Cannot run #{cmd_name}.\n\n"
        "Use #commands-confirm to save or #commands-cancel to discard.",
        "FORGE_MODE_BLOCKED"
    )


# =============================================================================
# ABILITY EXECUTION
# =============================================================================

def execute_ability(name: str, args: Dict, session_id: str, kernel: Any) -> CommandResponse:
    """
    Execute a saved ability by running its pipeline.
    
    Pipeline:
    1. fetch (gemini, web=true) → signals JSON
    2. reason (dualgpt) → derived JSON
    3. write (dualgpt) → final boxed output
    """
    print(f"[AbilityForge] execute_ability: {name}", flush=True)
    
    try:
        commands = _load_custom_commands(kernel)
        
        if name not in commands:
            return _error_response(name, f"Ability '{name}' not found.", "NOT_FOUND")
        
        ability = commands[name]
        
        if not ability.enabled:
            return _error_response(name, f"Ability '{name}' is disabled.", "DISABLED")
        
        # Get user input for the ability
        user_input = ""
        if isinstance(args, dict):
            user_input = args.get("full_input", "") or args.get("_", [""])[0] if args.get("_") else ""
        
        # Load previous state for comparison
        prev_state = _load_ability_state(kernel, name)
        
        # Execute pipeline stages
        context_data = {
            "topic": user_input or ability.name,
            "signals": ability.schema.signals,
            "derived": ability.schema.derived,
        }
        
        fetch_result = {}
        reason_result = {}
        final_output = ""
        
        llm_client = getattr(kernel, 'llm_client', None)
        
        for stage in ability.pipeline:
            if isinstance(stage, dict):
                stage = PipelineStage.from_dict(stage)
            
            stage_prompt = stage.prompt.format(**context_data, all_data=json.dumps({**fetch_result, **reason_result}))
            
            if stage.stage == "fetch":
                # TODO: Implement Gemini web fetch
                # For now, use dualgpt as fallback
                if llm_client:
                    result = llm_client.complete_system(
                        system="You are a data fetcher. Return JSON with the requested signals.",
                        user=stage_prompt,
                        command=f"ability-{name}-fetch",
                        think_mode=False,
                    )
                    try:
                        fetch_result = json.loads(result.get("text", "{}"))
                    except:
                        fetch_result = {"raw": result.get("text", "")}
                context_data["fetch_data"] = fetch_result
                
            elif stage.stage == "reason":
                if llm_client:
                    result = llm_client.complete_system(
                        system="You are an analyst. Derive insights from the data. Return JSON.",
                        user=stage_prompt,
                        command=f"ability-{name}-reason",
                        think_mode=True,
                    )
                    try:
                        reason_result = json.loads(result.get("text", "{}"))
                    except:
                        reason_result = {"analysis": result.get("text", "")}
                context_data["reason_data"] = reason_result
                
            elif stage.stage == "write":
                if llm_client:
                    result = llm_client.complete_system(
                        system="You are a report writer. Generate a clean NovaOS boxed output.",
                        user=stage_prompt,
                        command=f"ability-{name}-write",
                        think_mode=False,
                    )
                    final_output = result.get("text", "")
        
        # Save new state
        new_state = AbilityRunState(
            last_run_at=datetime.now(timezone.utc).isoformat(),
            signals=fetch_result,
            derived=reason_result,
        )
        _save_ability_state(kernel, name, new_state)
        
        # Build output
        if not final_output:
            final_output = f"╔══ {ability.name.upper()} ══╗\n\n"
            final_output += json.dumps({**fetch_result, **reason_result}, indent=2)
        
        # Add "what changed" if previous state exists
        if prev_state:
            final_output += "\n\n─────────────────────────────\n"
            final_output += f"Last run: {prev_state.last_run_at[:16]}"
        
        return _base_response(name, final_output, {
            "ability": name,
            "signals": fetch_result,
            "derived": reason_result,
        })
        
    except Exception as e:
        print(f"[AbilityForge] Error executing ability {name}: {e}", flush=True)
        traceback.print_exc()
        return _error_response(name, f"Error: {e}", "EXECUTION_ERROR")


# =============================================================================
# DEFAULT ABILITIES
# =============================================================================

def ensure_default_abilities(kernel: Any) -> None:
    """Ensure default abilities exist (called on startup)."""
    commands = _load_custom_commands(kernel)
    
    if "quadrant-status" not in commands:
        # Create default quadrant-status ability
        quadrant = Ability(
            name="quadrant-status",
            description="Show current life quadrant status with confidence and drivers",
            pipeline=[
                PipelineStage(
                    stage="fetch",
                    executor="gemini",
                    web=True,
                    prompt="Analyze the user's recent context and goals. Return JSON with: quadrant (career/health/relationships/growth), confidence (0-1), key_drivers (list of 3).",
                ),
                PipelineStage(
                    stage="reason",
                    executor="dualgpt",
                    web=False,
                    prompt="Given the fetched data, derive: momentum (rising/stable/declining), watchlist (3 items to monitor), recommendation.",
                ),
                PipelineStage(
                    stage="write",
                    executor="dualgpt",
                    web=False,
                    prompt="Generate a NovaOS boxed output showing:\n- Quadrant\n- Confidence\n- Drivers\n- Changes since last run\n- Watchlist",
                ),
            ],
            schema=AbilitySchema(
                signals=["quadrant", "confidence", "key_drivers"],
                derived=["momentum", "watchlist", "recommendation"],
            ),
        )
        
        commands["quadrant-status"] = quadrant
        _save_custom_commands(kernel, commands)
        print("[AbilityForge] Created default ability: quadrant-status", flush=True)


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

ABILITY_FORGE_HANDLERS = {
    "commands-list": handle_commands_list,
    "commands-forge": handle_commands_forge,
    "commands-edit": handle_commands_edit,
    "commands-preview": handle_commands_preview,
    "commands-diff": handle_commands_diff,
    "commands-confirm": handle_commands_confirm,
    "commands-cancel": handle_commands_cancel,
    "commands-delete": handle_commands_delete,
}


def get_ability_forge_handlers() -> Dict[str, Any]:
    """Get all ability forge handlers for registration."""
    return ABILITY_FORGE_HANDLERS


# =============================================================================
# SECTION MENU HANDLER
# =============================================================================

def handle_section_commands(cmd_name: str, args: Dict, session_id: str, context: Dict, kernel: Any, meta: Dict) -> CommandResponse:
    """Show the Commands section menu."""
    print(f"[AbilityForge] handle_section_commands called", flush=True)
    
    # Check if in forge mode
    if is_forge_mode_active(session_id):
        draft = get_forge_draft(session_id)
        preview = _format_ability_preview(draft.ability)
        return _base_response(cmd_name, f"Forge mode active.\n\n{preview}", {
            "forge_active": True,
            "name": draft.ability.name,
        })
    
    commands = _load_custom_commands(kernel)
    ability_count = len(commands)
    
    lines = [
        "╔══ Commands (Ability Forge) ══╗",
        "Custom abilities built by conversation refinement.",
        "",
        f"You have {ability_count} ability(ies).",
        "",
        "1) commands-list",
        "   List all saved abilities",
        "   Example: `#commands-list`",
        "",
        "2) commands-forge",
        "   Create or edit an ability",
        '   Example: `#commands-forge name="market-scan"`',
        "",
        "3) commands-edit",
        "   Edit an existing ability",
        '   Example: `#commands-edit name="quadrant-status"`',
        "",
        "4) commands-preview",
        "   Preview current draft (forge mode)",
        "   Example: `#commands-preview`",
        "",
        "5) commands-diff",
        "   Show changes from last saved version",
        "   Example: `#commands-diff`",
        "",
        "6) commands-confirm",
        "   Save draft and exit forge mode",
        "   Example: `#commands-confirm`",
        "",
        "7) commands-cancel",
        "   Discard draft and exit forge mode",
        "   Example: `#commands-cancel`",
        "",
        "8) commands-delete",
        "   Delete a saved ability",
        '   Example: `#commands-delete name="old-ability"`',
        "",
    ]
    
    return _base_response(cmd_name, "\n".join(lines), {
        "section": "commands",
        "commands": list(ABILITY_FORGE_HANDLERS.keys()),
        "ability_count": ability_count,
        "menu_active": True,
    })
