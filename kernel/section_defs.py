# kernel/section_defs.py
"""
v0.11.0 — Section Definitions for NovaOS Life RPG

Defines the 11 canonical sections and their associated commands.

v0.11.0 CHANGES:
- Removed inbox section (all inbox commands removed)
- Removed continuity section (preferences, projects, context removed)
- Moved snapshot/restore to system section
- Removed mode and assistant-mode from system section
- Updated timerhythm: removed pulse, presence, align; added daily-review
- Section count: 13 -> 11

Sections:
1. core          — Nova's heart & OS control center
2. memory        — Lore / knowledge store
3. human_state   — HP / stamina / stress / mood
4. modules       — Regions/domains on the world map
5. identity      — Player Profile: level, XP, domains, titles
6. system        — Environment, snapshots, runtime config
7. workflow      — Quest Engine (quests, steps, XP, streaks, bosses)
8. timerhythm    — Daily/weekly reviews and rhythm
9. reminders     — Time-based reminders / quest pins
10. commands     — Abilities/macros
11. debug        — Diagnostics & dev tools
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
        description="Nova's heart & OS control center.",
        commands=[
            CommandInfo("why", "State NovaOS purpose, philosophy, and identity", "#why"),
            CommandInfo("boot", "Initialize NovaOS kernel and persona", "#boot"),
            CommandInfo("shutdown", "Shutdown NovaOS and return to Persona mode", "#shutdown"),
            CommandInfo("reset", "Reload system memory and modules", "#reset"),
            CommandInfo("status", "Display system state", "#status"),
            CommandInfo("help", "Show command sections and help", "#help"),
        ]
    ),
    "memory": Section(
        title="Memory",
        description="Lore & knowledge store (semantic/procedural/episodic).",
        commands=[
            CommandInfo("store", "Store a memory item with tags", "#store type=semantic tags=work content=\"...\""),
            CommandInfo("recall", "Recall memory items by type and/or tags", "#recall tags=work"),
            CommandInfo("forget", "Forget memory items by id, tag, or type", "#forget id=123"),
            CommandInfo("trace", "Show lineage/trace info for a memory item", "#trace id=123"),
            CommandInfo("bind", "Bind multiple memory items into a cluster", "#bind ids=1,2,3"),
        ]
    ),
    "human_state": Section(
        title="Human State",
        description="HP / stamina / stress / mood tracking.",
        commands=[
            CommandInfo("log-state", "Log current human state", "#log-state energy=high stress=low"),
            CommandInfo("evolution-status", "Show state evolution over time", "#evolution-status"),
            CommandInfo("capacity", "Check current capacity", "#capacity"),
        ]
    ),
    "modules": Section(
        title="Modules",
        description="Regions/domains on the world map. User-created, no defaults.",
        commands=[
            CommandInfo("modules", "List all modules/regions", "#modules"),
            CommandInfo("module-create", "Create a new module/region", "#module-create id=\"cyber\" name=\"Cybersecurity\""),
            CommandInfo("module-delete", "Delete a module/region", "#module-delete cyber"),
            CommandInfo("module-inspect", "Inspect a module's details", "#module-inspect cyber"),
        ]
    ),
    "identity": Section(
        title="Identity",
        description="Player Profile: level, XP, domains, titles, unlocks.",
        commands=[
            CommandInfo("identity-show", "Show player profile (level, XP, titles)", "#identity-show"),
            CommandInfo("identity-set", "Set an identity trait", "#identity-set trait=value"),
            CommandInfo("identity-clear", "Clear identity configuration", "#identity-clear"),
        ]
    ),
    "system": Section(
        title="System",
        description="Environment, snapshots, and runtime config.",
        commands=[
            CommandInfo("env", "Show current environment state", "#env"),
            CommandInfo("setenv", "Set environment keys", "#setenv debug=true"),
            CommandInfo("snapshot", "Create a snapshot of core OS state", "#snapshot"),
            CommandInfo("restore", "Restore OS state from a snapshot", "#restore id=123"),
        ]
    ),
    "workflow": Section(
        title="Quest Engine",
        description="Gamified learning quests with XP, skills, streaks, and boss battles. Use #quest to start wizard, #complete to finish lessons.",
        commands=[
            CommandInfo("quest", "Open quest wizard to choose and start a quest", "#quest"),
            CommandInfo("complete", "Finish today's lesson, save progress, preview tomorrow", "#complete"),
            CommandInfo("halt", "Pause quest mode and return to normal NovaOS", "#halt"),
            CommandInfo("next", "(Legacy) Alias for #complete", "#next"),
            CommandInfo("pause", "Pause the active quest outside quest mode", "#pause"),
            CommandInfo("quest-log", "View player progress: level, XP, skills, streak", "#quest-log"),
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
        description="Daily and weekly reviews for reflection and planning.",
        commands=[
            CommandInfo("daily-review", "Start or complete daily review", "#daily-review"),
            CommandInfo("weekly-review", "Start or complete weekly review", "#weekly-review"),
        ]
    ),
    "reminders": Section(
        title="Reminders",
        description="Time-based reminders and quest pins.",
        commands=[
            CommandInfo("remind-add", "Create a reminder", "#remind-add msg=\"Call mom\" at=\"5pm\""),
            CommandInfo("remind-list", "List reminders", "#remind-list"),
            CommandInfo("remind-update", "Update a reminder", "#remind-update id=1 msg=\"...\""),
            CommandInfo("remind-delete", "Delete a reminder", "#remind-delete id=1"),
        ]
    ),
    "commands": Section(
        title="Custom Commands",
        description="Abilities/macros you can unlock and reuse.",
        commands=[
            CommandInfo("command-add", "Add a new custom command (prompt or macro)", "#command-add"),
            CommandInfo("command-list", "List core and custom commands", "#command-list"),
            CommandInfo("command-inspect", "Inspect a custom command's metadata", "#command-inspect name=mycommand"),
            CommandInfo("command-remove", "Remove a custom command by name", "#command-remove name=mycommand"),
            CommandInfo("command-toggle", "Enable or disable a custom command", "#command-toggle name=mycommand"),
        ]
    ),
    "debug": Section(
        title="Debug",
        description="Diagnostics and dev tools.",
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


def get_all_command_names() -> List[str]:
    """Get all command names across all sections."""
    names = []
    for section in SECTION_DEFS.values():
        for cmd in section.commands:
            names.append(cmd.name)
    return names
