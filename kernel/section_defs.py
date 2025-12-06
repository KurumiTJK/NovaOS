# kernel/section_defs.py
"""
v0.8.0 — Section Definitions for NovaOS

Defines the help sections and their associated commands.
Updated to use Quest Engine commands instead of legacy workflow commands.

IMPORTANT: Quest commands are EXPLICIT only - no NL auto-routing.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CommandInfo:
    """Command metadata for section display."""
    name: str
    description: str
    example: str = ""


@dataclass
class Section:
    """Section definition with title, description, and commands."""
    title: str
    description: str
    commands: List[CommandInfo] = field(default_factory=list)


# =============================================================================
# SECTION DEFINITIONS
# =============================================================================

SECTION_DEFS: Dict[str, Section] = {
    "core": Section(
        title="Core",
        description="Essential NovaOS commands for system interaction.",
        commands=[
            CommandInfo("why", "State NovaOS purpose, philosophy, and identity", "#why"),
            CommandInfo("boot", "Initialize NovaOS kernel and persona", "#boot"),
            CommandInfo("reset", "Reload system memory and modules", "#reset"),
            CommandInfo("status", "Display system state", "#status"),
            CommandInfo("help", "Show command sections and help", "#help"),
        ]
    ),
    "memory": Section(
        title="Memory",
        description="Store, recall, and manage memory items.",
        commands=[
            CommandInfo("store", "Store a memory item (semantic/procedural/episodic) with tags", "#store type=semantic tags=work content=\"...\""),
            CommandInfo("recall", "Recall memory items filtered by type and/or tags", "#recall tags=work"),
            CommandInfo("forget", "Forget memory items by id, tag, or type", "#forget id=123"),
            CommandInfo("trace", "Show lineage/trace info for a memory item", "#trace id=123"),
            CommandInfo("bind", "Bind multiple memory items into a cluster", "#bind ids=1,2,3"),
        ]
    ),
    "continuity": Section(
        title="Continuity",
        description="Manage preferences, projects, and session state.",
        commands=[
            CommandInfo("preferences", "Show or set user preferences", "#preferences"),
            CommandInfo("projects", "List active projects", "#projects"),
            CommandInfo("context", "Show current session context", "#context"),
        ]
    ),
    "human_state": Section(
        title="Human State",
        description="Track energy, stress, momentum, and capacity.",
        commands=[
            CommandInfo("log-state", "Log current human state", "#log-state energy=high stress=low"),
            CommandInfo("evolution-status", "Show state evolution over time", "#evolution-status"),
            CommandInfo("capacity", "Check current capacity", "#capacity"),
        ]
    ),
    "modules": Section(
        title="Modules",
        description="Create, inspect, and manage modules.",
        commands=[
            CommandInfo("map", "List all registered modules", "#map"),
            CommandInfo("forge", "Forge (create) a new module with mission and state", "#forge key=mymod mission=\"...\""),
            CommandInfo("dismantle", "Dismantle (delete) a module", "#dismantle key=mymod"),
            CommandInfo("inspect", "Inspect a module's metadata and bindings", "#inspect key=mymod"),
            CommandInfo("bind-module", "Bind two modules for cross-domain interaction", "#bind-module a=mod1 b=mod2"),
        ]
    ),
    "identity": Section(
        title="Identity",
        description="Manage Nova's identity traits and values.",
        commands=[
            CommandInfo("identity-show", "Show current identity configuration", "#identity-show"),
            CommandInfo("identity-set", "Set an identity trait", "#identity-set trait=value"),
            CommandInfo("identity-clear", "Clear identity configuration", "#identity-clear"),
        ]
    ),
    "system": Section(
        title="System",
        description="Environment, mode, snapshots, and system state.",
        commands=[
            CommandInfo("env", "Show current environment state", "#env"),
            CommandInfo("setenv", "Set environment keys", "#setenv debug=true"),
            CommandInfo("mode", "Set NovaOS mode", "#mode deep_work"),
            CommandInfo("snapshot", "Create a snapshot of core OS state", "#snapshot"),
            CommandInfo("restore", "Restore OS state from a snapshot", "#restore id=123"),
        ]
    ),
    "workflow": Section(
        title="Quest Engine",
        description="Gamified learning quests with XP, skills, and progress tracking.",
        commands=[
            CommandInfo("quest", "Open the Quest Board to list, start, or resume a quest", "#quest"),
            CommandInfo("next", "Submit your answer and advance to the next step", "#next"),
            CommandInfo("pause", "Pause the active quest and save progress", "#pause"),
            CommandInfo("quest-log", "View progress, XP, skills, and learning streak", "#quest-log"),
            CommandInfo("quest-reset", "Reset a quest's progress to replay from start", "#quest-reset id=jwt_intro"),
            CommandInfo("quest-compose", "Compose a new questline with LLM assistance", "#quest-compose"),
            CommandInfo("quest-delete", "Delete a questline and its saved progress", "#quest-delete id=myquest"),
            CommandInfo("quest-list", "List all quest definitions", "#quest-list"),
            CommandInfo("quest-inspect", "Inspect a quest definition and all its steps", "#quest-inspect id=jwt_intro"),
            CommandInfo("quest-debug", "Show raw quest engine state for debugging", "#quest-debug"),
        ]
    ),
    "timerhythm": Section(
        title="Time Rhythm",
        description="Time-based presence, alignment, and pulse.",
        commands=[
            CommandInfo("presence", "Show time rhythm presence snapshot", "#presence"),
            CommandInfo("pulse", "Quest pulse diagnostics", "#pulse"),
            CommandInfo("align", "Alignment suggestions based on time + quests", "#align"),
        ]
    ),
    "reminders": Section(
        title="Reminders",
        description="Create and manage time-based reminders.",
        commands=[
            CommandInfo("remind-add", "Create a reminder", "#remind-add msg=\"Call mom\" at=\"5pm\""),
            CommandInfo("remind-list", "List reminders", "#remind-list"),
            CommandInfo("remind-update", "Update a reminder", "#remind-update id=1 msg=\"...\""),
            CommandInfo("remind-delete", "Delete a reminder", "#remind-delete id=1"),
        ]
    ),
    "commands": Section(
        title="Custom Commands",
        description="Create and manage custom commands.",
        commands=[
            CommandInfo("command-add", "Add a new custom command (prompt or macro)", "#command-add"),
            CommandInfo("command-list", "List core and custom commands", "#command-list"),
            CommandInfo("command-inspect", "Inspect a custom command's metadata", "#command-inspect name=mycommand"),
            CommandInfo("command-remove", "Remove a custom command by name", "#command-remove name=mycommand"),
            CommandInfo("command-toggle", "Enable or disable a custom command", "#command-toggle name=mycommand"),
        ]
    ),
    "interpretation": Section(
        title="Interpretation",
        description="Deep analysis and reasoning commands.",
        commands=[
            CommandInfo("interpret", "Explain what an input means", "#interpret \"...\""),
            CommandInfo("derive", "Break a topic down into first principles", "#derive \"...\""),
            CommandInfo("synthesize", "Integrate ideas into a coherent structure", "#synthesize \"...\""),
            CommandInfo("frame", "Reframe the problem or direction", "#frame \"...\""),
            CommandInfo("forecast", "Generate plausible future outcomes", "#forecast \"...\""),
        ]
    ),
    "debug": Section(
        title="Debug",
        description="Debugging and diagnostic commands.",
        commands=[
            CommandInfo("wm-debug", "Show current Working Memory state", "#wm-debug"),
            CommandInfo("wm-clear", "Clear working memory for this session", "#wm-clear"),
            CommandInfo("behavior-debug", "Show Behavior Layer state", "#behavior-debug"),
            CommandInfo("self-test", "Run internal diagnostics", "#self-test"),
            CommandInfo("quest-debug", "Show raw quest engine state", "#quest-debug"),
        ]
    ),
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_section_keys() -> List[str]:
    """Get all section keys."""
    return list(SECTION_DEFS.keys())


def get_section(key: str) -> Optional[Section]:
    """Get a section by key."""
    return SECTION_DEFS.get(key)


def get_section_commands(key: str) -> List[CommandInfo]:
    """Get commands for a section."""
    section = SECTION_DEFS.get(key)
    if section:
        return section.commands
    return []


def get_section_title(key: str) -> str:
    """Get section title."""
    section = SECTION_DEFS.get(key)
    if section:
        return section.title
    return key.title()


def get_section_description(key: str) -> str:
    """Get section description."""
    section = SECTION_DEFS.get(key)
    if section:
        return section.description
    return ""


def find_section_for_command(command: str) -> Optional[str]:
    """Find which section a command belongs to."""
    for section_key, section in SECTION_DEFS.items():
        for cmd in section.commands:
            if cmd.name == command:
                return section_key
    return None
