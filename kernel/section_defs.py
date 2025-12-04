# kernel/section_defs.py
"""
v0.6 — Section Definitions

Central source of truth for syscommand organization.
Used by:
- #help (sectioned display)
- Section menu commands (#core, #memory, etc.)
- Section router (#memory store → store)

DO NOT modify syscommand handlers. This is purely organizational.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class CommandDef:
    """Definition of a single command."""
    name: str
    description: str
    example: str
    aliases: List[str] = field(default_factory=list)


@dataclass
class SectionDef:
    """Definition of a command section."""
    key: str
    title: str
    description: str
    commands: List[CommandDef]


# -----------------------------------------------------------------------------
# Official Section Definitions
# -----------------------------------------------------------------------------

SECTION_DEFS: List[SectionDef] = [
    SectionDef(
        key="core",
        title="CORE",
        description="Core system commands for NovaOS operation.",
        commands=[
            CommandDef(
                name="why",
                description="State NovaOS purpose, philosophy, and identity.",
                example="#why",
            ),
            CommandDef(
                name="boot",
                description="Initialize NovaOS kernel and persona.",
                example="#boot",
            ),
            CommandDef(
                name="reset",
                description="Reset the current session state.",
                example="#reset",
            ),
            CommandDef(
                name="status",
                description="Show system status including memory, workflows, and health.",
                example="#status",
            ),
            CommandDef(
                name="help",
                description="Show available commands organized by section.",
                example="#help",
            ),
        ],
    ),
    SectionDef(
        key="memory",
        title="MEMORY",
        description="Memory storage, recall, and lifecycle management.",
        commands=[
            CommandDef(
                name="store",
                description="Store a memory item with type and tags.",
                example='#store type=semantic tags=work "Meeting notes from today"',
            ),
            CommandDef(
                name="recall",
                description="Recall memory items filtered by type and/or tags.",
                example="#recall type=semantic tags=work",
            ),
            CommandDef(
                name="forget",
                description="Forget memory items by id, tag, or type.",
                example="#forget ids=5",
            ),
            CommandDef(
                name="trace",
                description="Show lineage/trace info for a memory item.",
                example="#trace id=5",
            ),
            CommandDef(
                name="bind",
                description="Bind multiple memory items into a cluster.",
                example="#bind ids=1,2,3",
            ),
            CommandDef(
                name="memory-stats",
                description="Show detailed memory statistics.",
                example="#memory-stats",
            ),
            CommandDef(
                name="memory-salience",
                description="Update the salience (importance) of a memory item.",
                example="#memory-salience id=5 salience=0.9",
            ),
            CommandDef(
                name="memory-status",
                description="Update the status of a memory item (active, stale, archived).",
                example="#memory-status id=5 status=stale",
            ),
            CommandDef(
                name="memory-important",
                description="List high-importance memories.",
                example="#memory-important",
            ),
            CommandDef(
                name="memory-decay",
                description="Run decay analysis on memories (apply=true to commit changes).",
                example="#memory-decay apply=true",
            ),
            CommandDef(
                name="memory-drift",
                description="Detect drifted/stale memories.",
                example="#memory-drift",
            ),
            CommandDef(
                name="memory-reconfirm",
                description="Re-confirm a memory (restore to active status).",
                example="#memory-reconfirm id=5",
            ),
            CommandDef(
                name="memory-stale",
                description="List stale memories.",
                example="#memory-stale",
            ),
            CommandDef(
                name="memory-archive-stale",
                description="Archive all stale memories.",
                example="#memory-archive-stale",
            ),
            CommandDef(
                name="decay-preview",
                description="Preview decay trajectory for a memory type.",
                example="#decay-preview type=episodic salience=0.8",
            ),
            CommandDef(
                name="memory-policy",
                description="Show memory policy configuration.",
                example="#memory-policy",
            ),
            CommandDef(
                name="memory-policy-test",
                description="Test memory policy pre-store validation.",
                example='#memory-policy-test payload="Test" type=semantic',
            ),
            CommandDef(
                name="memory-mode-filter",
                description="Show memory recall filters for current or specified mode.",
                example="#memory-mode-filter mode=deep_work",
            ),
        ],
    ),
    SectionDef(
        key="continuity",
        title="CONTINUITY",
        description="Memory-based continuity without identity binding.",
        commands=[
            CommandDef(
                name="preferences",
                description="Show user preferences extracted from memory and identity.",
                example="#preferences",
            ),
            CommandDef(
                name="projects",
                description="Show active projects and goals.",
                example="#projects",
            ),
            CommandDef(
                name="continuity-context",
                description="Show full continuity context (preferences + projects + identity).",
                example="#continuity-context",
            ),
            CommandDef(
                name="reconfirm-prompts",
                description="Show gentle re-confirmation prompts for stale items.",
                example="#reconfirm-prompts",
            ),
            CommandDef(
                name="suggest-workflow",
                description="Suggest a workflow for a goal.",
                example='#suggest-workflow goal="Learn ML"',
            ),
        ],
    ),
    SectionDef(
        key="human_state",
        title="HUMAN STATE",
        description="Track biology, load, and aspiration for safer suggestions.",
        commands=[
            CommandDef(
                name="evolution-status",
                description="Show evolution status (human state summary with trends).",
                example="#evolution-status",
            ),
            CommandDef(
                name="log-state",
                description="Guided check-in for updating human state.",
                example="#log-state energy=good stress=low",
            ),
            CommandDef(
                name="state-history",
                description="Show human state history.",
                example="#state-history",
            ),
            CommandDef(
                name="capacity",
                description="Quick capacity check with recommendations.",
                example="#capacity",
            ),
        ],
    ),
    SectionDef(
        key="modules",
        title="MODULES",
        description="Life domain modules for focused work.",
        commands=[
            CommandDef(
                name="map",
                description="List all registered modules.",
                example="#map",
            ),
            CommandDef(
                name="forge",
                description="Forge (create) a new module with mission and state.",
                example='#forge key=finance mission="Manage personal finances"',
            ),
            CommandDef(
                name="dismantle",
                description="Dismantle (delete) a module.",
                example="#dismantle key=finance",
            ),
            CommandDef(
                name="inspect",
                description="Inspect a module's metadata and bindings.",
                example="#inspect key=finance",
            ),
            CommandDef(
                name="bind-module",
                description="Bind two modules for cross-domain interaction.",
                example="#bind-module a=finance b=real_estate",
            ),
        ],
    ),
    SectionDef(
        key="identity",
        title="IDENTITY",
        description="Versioned identity profile management.",
        commands=[
            CommandDef(
                name="identity-show",
                description="Show current identity profile.",
                example="#identity-show",
            ),
            CommandDef(
                name="identity-set",
                description="Set identity traits (name, goals, values, roles, etc.).",
                example='#identity-set name="Vant" goals="Build NovaOS,Learn ML"',
            ),
            CommandDef(
                name="identity-snapshot",
                description="Create a snapshot of current identity.",
                example='#identity-snapshot notes="Before career change"',
            ),
            CommandDef(
                name="identity-history",
                description="Show identity version history.",
                example="#identity-history",
            ),
            CommandDef(
                name="identity-restore",
                description="Restore identity from a historical snapshot.",
                example="#identity-restore id=profile-20250101-abc123",
            ),
            CommandDef(
                name="identity-clear-history",
                description="Clear identity history.",
                example="#identity-clear-history",
            ),
        ],
    ),
    SectionDef(
        key="system",
        title="SYSTEM",
        description="System configuration and snapshots.",
        commands=[
            CommandDef(
                name="snapshot",
                description="Create a snapshot of core OS state.",
                example="#snapshot",
            ),
            CommandDef(
                name="restore",
                description="Restore OS state from a snapshot.",
                example="#restore id=1",
            ),
            CommandDef(
                name="env",
                description="Show current environment variables.",
                example="#env",
            ),
            CommandDef(
                name="setenv",
                description="Set an environment variable.",
                example="#setenv key=debug value=true",
            ),
            CommandDef(
                name="mode",
                description="Set the current NovaOS mode (normal, deep_work, reflection, debug).",
                example="#mode deep_work",
            ),
            CommandDef(
                name="model-info",
                description="Show model routing information and available tiers.",
                example="#model-info",
            ),
            CommandDef(
                name="command-wizard",
                description="Interactive wizard for creating custom commands.",
                example="#command-wizard",
            ),
        ],
    ),
    SectionDef(
        key="workflow",
        title="WORKFLOW",
        description="Multi-step workflow creation and execution.",
        commands=[
            CommandDef(
                name="flow",
                description="Start or resume a workflow.",
                example="#flow name=morning_routine",
            ),
            CommandDef(
                name="advance",
                description="Advance the current workflow to the next step.",
                example="#advance",
            ),
            CommandDef(
                name="halt",
                description="Pause or stop the current workflow.",
                example="#halt",
            ),
            CommandDef(
                name="compose",
                description="Compose a new workflow with LLM assistance.",
                example='#compose name="Weekly Review"',
            ),
            CommandDef(
                name="workflow-delete",
                description="Delete a workflow.",
                example="#workflow-delete id=3",
            ),
            CommandDef(
                name="workflow-list",
                description="List all workflows.",
                example="#workflow-list",
            ),
        ],
    ),
    SectionDef(
        key="timerhythm",
        title="TIME RHYTHM",
        description="Temporal awareness and alignment.",
        commands=[
            CommandDef(
                name="presence",
                description="Show current time presence and context.",
                example="#presence",
            ),
            CommandDef(
                name="pulse",
                description="Quick temporal pulse check.",
                example="#pulse",
            ),
            CommandDef(
                name="align",
                description="Suggest next actions based on time and state.",
                example="#align",
            ),
        ],
    ),
    SectionDef(
        key="reminders",
        title="REMINDERS",
        description="Time-based reminder management.",
        commands=[
            CommandDef(
                name="remind-add",
                description="Add a new reminder.",
                example='#remind-add at="9:00 AM" msg="Stand up meeting"',
            ),
            CommandDef(
                name="remind-list",
                description="List all reminders.",
                example="#remind-list",
            ),
            CommandDef(
                name="remind-update",
                description="Update a reminder.",
                example='#remind-update id=1 msg="Updated message"',
            ),
            CommandDef(
                name="remind-delete",
                description="Delete a reminder.",
                example="#remind-delete id=1",
            ),
        ],
    ),
    SectionDef(
        key="commands",
        title="CUSTOM COMMANDS",
        description="Create and manage custom commands.",
        commands=[
            CommandDef(
                name="command-add",
                description="Add a custom command.",
                example='#command-add name=daily-reflect kind=prompt prompt_template="Reflect on today"',
            ),
            CommandDef(
                name="command-list",
                description="List all custom commands.",
                example="#command-list",
            ),
            CommandDef(
                name="command-inspect",
                description="Inspect a custom command.",
                example="#command-inspect name=daily-reflect",
            ),
            CommandDef(
                name="command-remove",
                description="Remove a custom command.",
                example="#command-remove name=daily-reflect",
            ),
            CommandDef(
                name="command-toggle",
                description="Enable or disable a custom command.",
                example="#command-toggle name=daily-reflect enabled=false",
            ),
        ],
    ),
    SectionDef(
        key="interpretation",
        title="INTERPRETATION",
        description="LLM-powered analysis and reasoning commands.",
        commands=[
            CommandDef(
                name="interpret",
                description="Interpret and analyze input with LLM.",
                example='#interpret "What does this error mean?"',
            ),
            CommandDef(
                name="derive",
                description="Derive first-principles analysis.",
                example='#derive "Why is the sky blue?"',
            ),
            CommandDef(
                name="synthesize",
                description="Synthesize information from multiple sources.",
                example='#synthesize "Combine these ideas..."',
            ),
            CommandDef(
                name="frame",
                description="Reframe a problem or situation.",
                example='#frame "I keep procrastinating on..."',
            ),
            CommandDef(
                name="forecast",
                description="Forecast outcomes or scenarios.",
                example='#forecast "What if I pursue this path?"',
            ),
        ],
    ),
    # v0.7.2: Debug section for diagnostics and introspection
    SectionDef(
        key="debug",
        title="DEBUG",
        description="Diagnostics and introspection tools.",
        commands=[
            CommandDef(
                name="wm-debug",
                description="Show working memory entities, pronouns, and topics.",
                example="#wm-debug",
            ),
            CommandDef(
                name="behavior-debug",
                description="Show behavior layer state (goals, open questions, user state).",
                example="#behavior-debug",
            ),
        ],
    ),
]


# -----------------------------------------------------------------------------
# Section Routing Table
# -----------------------------------------------------------------------------
# Maps (section, subcommand) → existing syscommand name

SECTION_ROUTES: Dict[str, Dict[str, str]] = {
    "memory": {
        "store": "store",
        "recall": "recall",
        "forget": "forget",
        "trace": "trace",
        "bind": "bind",
        "stats": "memory-stats",
        "salience": "memory-salience",
        "status": "memory-status",
        "important": "memory-important",
        "decay": "memory-decay",
        "drift": "memory-drift",
        "reconfirm": "memory-reconfirm",
        "stale": "memory-stale",
        "archive-stale": "memory-archive-stale",
        "policy": "memory-policy",
    },
    "workflow": {
        "start": "flow",
        "flow": "flow",
        "advance": "advance",
        "next": "advance",
        "halt": "halt",
        "stop": "halt",
        "pause": "halt",
        "compose": "compose",
        "create": "compose",
        "delete": "workflow-delete",
        "list": "workflow-list",
    },
    "reminders": {
        "add": "remind-add",
        "create": "remind-add",
        "list": "remind-list",
        "show": "remind-list",
        "update": "remind-update",
        "edit": "remind-update",
        "delete": "remind-delete",
        "remove": "remind-delete",
    },
    "identity": {
        "show": "identity-show",
        "set": "identity-set",
        "snapshot": "identity-snapshot",
        "history": "identity-history",
        "restore": "identity-restore",
        "clear-history": "identity-clear-history",
    },
    "modules": {
        "list": "map",
        "map": "map",
        "forge": "forge",
        "create": "forge",
        "dismantle": "dismantle",
        "delete": "dismantle",
        "inspect": "inspect",
        "bind": "bind-module",
    },
    "system": {
        "snapshot": "snapshot",
        "restore": "restore",
        "env": "env",
        "setenv": "setenv",
        "mode": "mode",
        "model-info": "model-info",
    },
    "continuity": {
        "preferences": "preferences",
        "projects": "projects",
        "context": "continuity-context",
        "reconfirm": "reconfirm-prompts",
        "suggest": "suggest-workflow",
    },
    "human_state": {
        "status": "evolution-status",
        "evolution": "evolution-status",
        "log": "log-state",
        "history": "state-history",
        "capacity": "capacity",
    },
    "timerhythm": {
        "presence": "presence",
        "pulse": "pulse",
        "align": "align",
    },
    "interpretation": {
        "interpret": "interpret",
        "derive": "derive",
        "synthesize": "synthesize",
        "frame": "frame",
        "forecast": "forecast",
    },
    "commands": {
        "add": "command-add",
        "list": "command-list",
        "inspect": "command-inspect",
        "remove": "command-remove",
        "toggle": "command-toggle",
    },
    # v0.7.2: Debug section routes
    "debug": {
        "wm-debug": "wm-debug",
        "wm": "wm-debug",
        "memory": "wm-debug",
        "behavior-debug": "behavior-debug",
        "behavior": "behavior-debug",
    },
}


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def get_section(key: str) -> Optional[SectionDef]:
    """Get a section by key."""
    for section in SECTION_DEFS:
        if section.key == key:
            return section
    return None


def get_section_keys() -> List[str]:
    """Get all section keys."""
    return [s.key for s in SECTION_DEFS]


def get_all_commands() -> Dict[str, CommandDef]:
    """Get all commands as a flat dict."""
    commands = {}
    for section in SECTION_DEFS:
        for cmd in section.commands:
            commands[cmd.name] = cmd
    return commands


def find_command_section(command_name: str) -> Optional[str]:
    """Find which section a command belongs to."""
    for section in SECTION_DEFS:
        for cmd in section.commands:
            if cmd.name == command_name:
                return section.key
    return None


def resolve_section_route(section: str, subcommand: str) -> Optional[str]:
    """
    Resolve a section route to the underlying syscommand.
    
    Example: resolve_section_route("memory", "store") → "store"
    """
    section_routes = SECTION_ROUTES.get(section, {})
    return section_routes.get(subcommand)


def get_section_command_names(section_key: str) -> List[str]:
    """Get all command names in a section."""
    section = get_section(section_key)
    if section:
        return [cmd.name for cmd in section.commands]
    return []
