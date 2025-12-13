# kernel/routing/section_defs.py
"""
v2.1.1 — Section Definitions for NovaOS Life RPG

v2.1.1 COMMANDS FEATURE REMOVED:
- Removed "commands" section entirely (Ability Forge feature removed)
- Section count: 10 -> 9

v2.1.0 ABILITY FORGE UPDATE:
- Commands section completely replaced with Ability Forge
- New commands: commands-list, commands-forge, commands-edit, commands-preview, 
  commands-diff, commands-confirm, commands-cancel, commands-delete
- Forge mode: conversational ability creation and refinement

v2.0.0 HUMAN STATE UPDATE:
- Rewrote human_state section with new canonical commands
- Commands: human-show, human-checkin, human-event, human-clear
- Removed legacy: log-state, evolution-status, capacity

v0.11.0 CHANGES:
- Removed inbox section (all inbox commands removed)
- Removed continuity section (preferences, projects, context removed)
- Moved snapshot/restore to system section
- Removed mode and assistant-mode from system section
- Updated timerhythm: removed pulse, presence, align; added daily-review

Sections:
1. core          — Nova's heart & OS control center
2. memory        — Lore / knowledge store
3. modules       — Regions/domains on the world map
4. identity      — Character sheet: name, archetype, goals, level, XP, domains, titles
5. system        — Environment, snapshots, runtime config
6. workflow      — Quest Engine (quests, steps, XP, streaks, bosses)
7. timerhythm    — Daily/weekly reviews, HP, readiness, habits
8. reminders     — Time-based reminders / quest pins
9. debug         — Diagnostics & dev tools
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
            CommandInfo("dashboard", "Display system dashboard (compact/full view)", "#dashboard"),
            CommandInfo("dashboard-view", "Toggle or set dashboard view mode", "#dashboard-view full"),
            CommandInfo("reminders-settings", "Configure notification settings (ntfy push, in-app)", "#reminders-settings"),
        ]
    ),
    "memory": Section(
        title="Memory",
        description="Long-term memory with auto-extraction, profile memories, keyword search, and decay. Say 'remember this' to save manually.",
        commands=[
            CommandInfo("store", "Store a memory item with tags", "#store type=semantic tags=work content=\"...\""),
            CommandInfo("recall", "Recall memory items by type and/or tags", "#recall tags=work"),
            CommandInfo("forget", "Forget memory items by id, tag, or type", "#forget id=123"),
            CommandInfo("trace", "Show lineage/trace info for a memory item", "#trace id=123"),
            CommandInfo("bind", "Bind multiple memory items into a cluster", "#bind ids=1,2,3"),
            CommandInfo("profile", "View/edit/delete profile memories (identity & preferences)", "#profile"),
            CommandInfo("memories", "Full memory management UI (list/view/edit/delete)", "#memories"),
            CommandInfo("search-mem", "Search memories by keywords", "#search-mem query=\"Steven project\""),
            CommandInfo("memory-maintain", "Run decay/archiving maintenance", "#memory-maintain"),
            CommandInfo("session-end", "End session: save WM to LTM and clear", "#session-end"),
        ]
    ),
    "modules": Section(
        title="Modules",
        description="World map: regions of your life (Cybersecurity, Business, Health, etc.). Modules are structural metadata; XP lives in Identity.",
        commands=[
            CommandInfo("modules-list", "List all modules with status, phase, and Domain Level", "#modules-list"),
            CommandInfo("modules-add", "Create a new module", '#modules-add name="Cybersecurity" category=career'),
            CommandInfo("modules-show", "Show details for a specific module", "#modules-show name=Cybersecurity"),
            CommandInfo("modules-update", "Update module metadata (status, phase, description, tags)", "#modules-update name=Cybersecurity phase=growth"),
            CommandInfo("modules-archive", "Archive a module (keep history, remove from active focus)", "#modules-archive name=Cybersecurity"),
            CommandInfo("modules-delete", "Delete a module (hard removal, with safety checks)", "#modules-delete name=Cybersecurity"),
        ]
    ),
    "identity": Section(
        title="Identity",
        description="Character sheet: name, archetype, goals, level, XP, domains, titles. Your player profile in the Life RPG.",
        commands=[
            CommandInfo("identity-show", "Show character sheet (name, archetype, goals, level, XP, titles, domains)", "#identity-show"),
            CommandInfo("identity-set", "Set profile values: name, theme, vibe, goals, titles", '#identity-set name="Vant" theme="Cloud Rogue"'),
            CommandInfo("identity-clear", "Reset progression (soft keeps profile, hard clears all)", "#identity-clear confirm=yes"),
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
        description="Daily reviews (morning/evening/night) track HP, readiness, and habits. Weekly reviews for macro goals.",
        commands=[
            CommandInfo("daily-review", "Three-phase daily review: morning (sleep+goal), evening (energy), night (reflection)", "#daily-review morning"),
            CommandInfo("weekly-review", "Weekly review with macro goals, habits, and XP", "#weekly-review"),
            CommandInfo("time-clear", "DEV: Clear all timerhythm data (streaks, reviews, logs)", "#time-clear confirm"),
        ]
    ),
    "reminders": Section(
        title="Reminders",
        description="Time-based reminders with recurrence, windows, snooze, and pinning.",
        commands=[
            CommandInfo("reminders-list", "List all reminders (grouped by status)", "#reminders-list"),
            CommandInfo("reminders-due", "Show reminders that are due now + today + pinned", "#reminders-due"),
            CommandInfo("reminders-show", "Show full details for a reminder", "#reminders-show id=rem_001"),
            CommandInfo("reminders-add", "Create a new reminder", '#reminders-add title="Call mom" due="5pm"'),
            CommandInfo("reminders-update", "Update a reminder's fields", "#reminders-update id=rem_001 title=\"...\""),
            CommandInfo("reminders-done", "Mark reminder as done (advances recurrence if recurring)", "#reminders-done id=rem_001"),
            CommandInfo("reminders-snooze", "Snooze a reminder for a duration (10m, 1h, 3h, 1d)", "#reminders-snooze id=rem_001 duration=1h"),
            CommandInfo("reminders-delete", "Delete a reminder", "#reminders-delete id=rem_001"),
            CommandInfo("reminders-pin", "Pin a reminder", "#reminders-pin id=rem_001"),
            CommandInfo("reminders-unpin", "Unpin a reminder", "#reminders-unpin id=rem_001"),
        ]
    ),
    # v2.1.1: "commands" section REMOVED (Ability Forge feature removed)
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
