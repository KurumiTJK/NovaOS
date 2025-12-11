# kernel/syscommands.py
"""
NovaOS v0.11.0 — System Command Handlers

This module contains all syscommand handlers for NovaOS.

v0.11.0: Removed inbox, continuity sections; updated timerhythm (removed pulse/presence/align, added daily-review)
         Removed mode and assistant-mode from system section
v0.9.0: Added handle_shutdown for dual-mode architecture.

Handler signature:
    def handle_<name>(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse

All handlers return a dict-like response via _base_response().
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from .command_types import CommandRequest, CommandResponse
from .formatting import OutputFormatter as F
from .section_defs import SECTION_DEFS, get_section

# v0.7: Working Memory imports
from .nova_wm import (
    get_wm,
    wm_update,
    wm_record_response,
    wm_get_context,
    wm_get_context_string,
    wm_answer_reference,
    wm_clear,
)

# v0.7.2: Behavior Layer imports
try:
    from .behavior_layer import (
        get_behavior,
        behavior_clear,
    )
except ImportError:
    def get_behavior(session_id): return None
    def behavior_clear(session_id): pass

# Type alias
KernelResponse = Dict[str, Any]


# =============================================================================
# v0.8.0: Optional Feature Imports
# =============================================================================

# Quest Engine
try:
    from .quest_handlers import get_quest_handlers
    _HAS_QUEST_ENGINE = True
except ImportError:
    _HAS_QUEST_ENGINE = False
    def get_quest_handlers(): return {}

# v0.11.0: Inbox removed

# Player Profile
try:
    from .player_profile_handlers import get_player_profile_handlers
    _HAS_PLAYER_PROFILE = True
except ImportError:
    _HAS_PLAYER_PROFILE = False
    def get_player_profile_handlers(): return {}

# Module Manager
try:
    from .module_handlers import get_module_handlers
    _HAS_MODULE_MANAGER = True
except ImportError:
    _HAS_MODULE_MANAGER = False
    def get_module_handlers(): return {}

# v0.11.0: Assistant Mode removed

# Time Rhythm
try:
    from .time_rhythm_handlers import get_time_rhythm_handlers
    _HAS_TIME_RHYTHM = True
except ImportError:
    _HAS_TIME_RHYTHM = False
    def get_time_rhythm_handlers(): return {}

# v0.11.0: Memory Syscommand Handlers
try:
    from .memory_syscommands import get_memory_syscommand_handlers
    _HAS_MEMORY_SYSCOMMANDS = True
except ImportError:
    _HAS_MEMORY_SYSCOMMANDS = False
    def get_memory_syscommand_handlers(): return {}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _base_response(
    cmd_name: str,
    summary: str,
    extra: Dict[str, Any] | None = None,
) -> CommandResponse:
    """Build a standard CommandResponse object."""
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=extra or {},
        type="syscommand",
    )


def _error_response(
    cmd_name: str,
    message: str,
    code: str = "ERROR",
) -> CommandResponse:
    """Build an error CommandResponse object."""
    return CommandResponse(
        ok=False,
        command=cmd_name,
        summary=message,
        error_code=code,
        error_message=message,
        type="error",
    )


# =============================================================================
# SECTION MENU STATE
# =============================================================================

_section_menu_state: Dict[str, str] = {}  # session_id -> active_section


def get_active_section(session_id: str) -> Optional[str]:
    """Get the active section menu for a session."""
    return _section_menu_state.get(session_id)


def clear_active_section(session_id: str) -> None:
    """Clear the active section menu for a session."""
    _section_menu_state.pop(session_id, None)


def get_section_command_names(section_key: str) -> List[str]:
    """Get command names for a section."""
    section = get_section(section_key)
    if section:
        return [cmd.name for cmd in section.commands]
    return []


# =============================================================================
# CORE HANDLERS
# =============================================================================

def handle_why(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """State NovaOS purpose, philosophy, and identity."""
    summary = (
        "NovaOS is your AI operating system: a stable, first-principles companion that "
        "turns your life into structured modules, workflows, and long-term roadmaps."
    )
    return _base_response(cmd_name, summary)


def handle_boot(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Initialize NovaOS kernel and persona."""
    kernel.context_manager.mark_booted(session_id)
    summary = "NovaOS kernel booted. Persona loaded. Modules and memory initialized."
    return _base_response(cmd_name, summary)


def handle_shutdown(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Shutdown NovaOS and return to Persona mode.
    
    v0.9.0: Added for dual-mode architecture.
    
    Usage:
        #shutdown
    
    Note: The actual mode switch is handled by mode_router.py.
    This handler exists for completeness and direct kernel calls,
    and performs cleanup tasks like resetting the session.
    """
    # Reset the booted flag and clear session state
    kernel.context_manager.reset_session(session_id)
    
    # Clear working memory
    wm_clear(session_id)
    
    # Clear behavior layer
    behavior_clear(session_id)
    
    summary = "NovaOS shutting down. Returning to Persona mode."
    return _base_response(cmd_name, summary, {"event": "shutdown"})


def handle_reset(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Reset session context, working memory, and behavior layer."""
    # v0.7: Clear Working Memory on reset
    wm_clear(session_id)
    # v0.7.2: Clear Behavior Layer on reset
    behavior_clear(session_id)
    kernel.context_manager.reset_session(session_id)
    summary = "Session context reset. Working memory and behavior layer cleared. Modules and workflows reloaded from disk."
    return _base_response(cmd_name, summary)


def handle_status(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Display system state."""
    mem_health = kernel.memory_manager.get_health()
    modules = kernel.context_manager.get_module_summary()
    ctx = kernel.context_manager.get_context(session_id)

    if hasattr(modules, "__len__"):
        modules_count = len(modules)
    else:
        modules_count = 0

    summary_lines = [
        F.key_value("Booted", ctx.get("booted", False)),
        F.key_value("Modules loaded", modules_count),
        F.key_value("Memory health", mem_health),
    ]
    summary = F.header("NovaOS Status") + "\n".join(summary_lines)

    extra = {
        "memory_health": mem_health,
        "modules": modules,
        "booted": ctx.get("booted", False),
    }
    return _base_response(cmd_name, summary, extra)


# =============================================================================
# HELP HANDLER
# =============================================================================

def handle_help(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    v0.9.0 — Section-based help command.
    
    Shows the 13 NovaOS sections in a clean overview.
    Optionally drill down into a specific section with #help <section>.
    
    Usage:
        #help              — Show section overview
        #help memory       — Show commands in the MEMORY section
    """
    # Canonical section order for display (v0.11.0: 11 sections)
    SECTION_ORDER = [
        "core",
        "memory",
        "human_state",
        "modules",
        "identity",
        "system",
        "workflow",
        "timerhythm",
        "reminders",
        "commands",
        "debug",
    ]
    
    # RPG-style section descriptions
    SECTION_DESCRIPTIONS = {
        "core": "Nova's heart & OS control center",
        "memory": "Lore & knowledge store (semantic/procedural/episodic)",
        "human_state": "HP / stamina / stress / mood tracking",
        "modules": "World map: regions & domains you create",
        "identity": "Player Profile: level, XP, domains, titles",
        "system": "Environment, snapshots, and runtime config",
        "workflow": "Quest Engine: quests, XP, skills, streaks",
        "timerhythm": "Daily and weekly reviews",
        "reminders": "Time-based reminders & pins",
        "commands": "Custom commands & macros (abilities)",
        "debug": "Diagnostics & dev tools",
    }
    
    # Parse optional section argument
    target_section = None
    if isinstance(args, dict):
        target_section = args.get("section")
        positional = args.get("_", [])
        if not target_section and positional:
            target_section = str(positional[0]).lower()
    elif isinstance(args, str) and args.strip():
        target_section = args.strip().lower()
    
    # ─────────────────────────────────────────────────────────────────────
    # DRILL-DOWN: Show specific section's commands
    # ─────────────────────────────────────────────────────────────────────
    if target_section:
        section = get_section(target_section)
        if not section:
            lines = [
                f"Unknown section '{target_section}'.",
                "",
                "Available sections:",
            ]
            for key in SECTION_ORDER:
                lines.append(f"  • {key}")
            lines.append("")
            lines.append("Usage: #help <section>  (e.g., #help memory)")
            
            return _base_response(cmd_name, "\n".join(lines), {"ok": False, "error": "unknown_section"})
        
        # Build section detail view
        lines = [
            f"══════════════════════════════════════",
            f"  {section.title.upper()}",
            f"══════════════════════════════════════",
            "",
            section.description,
            "",
            "Commands:",
            "",
        ]
        
        for cmd in section.commands:
            lines.append(f"  #{cmd.name}")
            lines.append(f"    {cmd.description}")
            if cmd.example:
                lines.append(f"    Example: {cmd.example}")
            lines.append("")
        
        lines.append(f"Enter this section: #{target_section}")
        lines.append(f"Back to overview: #help")
        
        return _base_response(cmd_name, "\n".join(lines), {
            "section": target_section,
            "commands": [cmd.name for cmd in section.commands],
        })
    
    # ─────────────────────────────────────────────────────────────────────
    # GLOBAL OVERVIEW: Show all sections
    # ─────────────────────────────────────────────────────────────────────
    lines = [
        "╔════════════════════════════════════════════════════════╗",
        "║           NovaOS Help — Section Overview               ║",
        "╚════════════════════════════════════════════════════════╝",
        "",
        "NovaOS is organized into 11 sections. Type the section",
        "name to enter its menu, or use #help <section> for details.",
        "",
    ]
    
    max_key_len = max(len(key) for key in SECTION_ORDER)
    
    for key in SECTION_ORDER:
        desc = SECTION_DESCRIPTIONS.get(key, "")
        padded_key = key.ljust(max_key_len)
        lines.append(f"  {padded_key}  —  {desc}")
        lines.append(f"  {''.ljust(max_key_len)}     Run: #{key}")
        lines.append("")
    
    lines.append("─────────────────────────────────────────────────────────")
    lines.append("Tip: #help <section> shows commands in that section.")
    lines.append("     Example: #help workflow")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "sections": SECTION_ORDER,
        "count": len(SECTION_ORDER),
    })


# =============================================================================
# MEMORY HANDLERS
# =============================================================================

def handle_store(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Store a memory item."""
    mm = kernel.memory_manager
    mem_type = "semantic"
    tags = None
    payload = None

    if isinstance(args, dict):
        mem_type = args.get("type", "semantic")
        tags = args.get("tags")
        payload = args.get("payload") or args.get("content") or args.get("_", [""])[0]
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

    if not payload:
        return _base_response(cmd_name, "No content to store.", {"ok": False})

    item = mm.store(
        payload=payload,
        mem_type=mem_type,
        tags=tags,
        trace={"source": "syscommand"},
    )

    summary = f"Stored memory #{item.id} ({item.type}) with tags {item.tags}."
    extra = {
        "id": item.id,
        "type": item.type,
        "tags": item.tags,
        "timestamp": item.timestamp,
    }
    return _base_response(cmd_name, summary, extra)


def handle_recall(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Recall memory items."""
    mm = kernel.memory_manager
    mem_type = None
    tags = None
    limit = 20

    if isinstance(args, dict):
        mem_type = args.get("type")
        tags = args.get("tags")
        raw_limit = args.get("limit")
        if isinstance(raw_limit, int):
            limit = raw_limit
        elif isinstance(raw_limit, str) and raw_limit.isdigit():
            limit = int(raw_limit)

        if isinstance(tags, str):
            tags = [tags]

    items = mm.recall(mem_type=mem_type, tags=tags, limit=limit)
    if not items:
        summary = F.header("No matching memories found.")
        extra = {"items": []}
    else:
        formatted_items = []
        for item in items[:5]:
            tag_str = ", ".join(item.tags) if item.tags else "none"
            payload_str = item.payload
            formatted_items.append(
                F.item(
                    id=item.id,
                    label=f"{item.type} (tags: {tag_str})",
                    details=f"\"{payload_str}\"",
                )
            )

        header = F.header(f"Found {len(items)} memories")
        body = F.list(formatted_items)
        if len(items) > 5:
            body += f"\n…and {len(items) - 5} more."

        summary = header + body
        extra = {"items": [item.__dict__ for item in items]}

    return _base_response(cmd_name, summary, extra)


def handle_forget(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Delete memory items by id, tag, type, or all.
    
    Usage:
        #forget id=<id>           — Delete a specific memory
        #forget ids=1,2,3         — Delete multiple memories
        #forget tags=<tag>        — Delete all memories with tag
        #forget type=<type>       — Delete all memories of type
        #forget all               — Delete ALL memories (use with caution!)
    
    v0.11.0-fix5: Added 'all' action to clear entire memory store.
    """
    mm = kernel.memory_manager
    ids = None
    tags = None
    mem_type = None

    if isinstance(args, dict):
        # ─────────────────────────────────────────────────────────────────
        # v0.11.0-fix5: Check for "all" action first
        # ─────────────────────────────────────────────────────────────────
        positional = args.get("_", [])
        if positional and str(positional[0]).lower() == "all":
            # Get all memories
            all_memories = mm.recall(limit=10000)
            if not all_memories:
                return _base_response(cmd_name, "No memories to forget.", {"removed": 0})
            
            all_ids = [m.id for m in all_memories]
            removed = mm.forget(ids=all_ids)
            return _base_response(
                cmd_name, 
                f"⚠ Forgot ALL {removed} memory item(s). Memory store is now empty.",
                {"removed": removed, "action": "forget_all"}
            )
        
        # ─────────────────────────────────────────────────────────────────
        # Standard forget by id/ids/tags/type
        # ─────────────────────────────────────────────────────────────────
        raw_ids = args.get("ids") or args.get("id")
        
        if raw_ids is None and "_" in args and args["_"]:
            raw_ids = args["_"][0]
        
        if raw_ids is not None:
            if isinstance(raw_ids, int):
                ids = [raw_ids]
            elif isinstance(raw_ids, str):
                ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
            else:
                try:
                    ids = [int(x) for x in raw_ids]
                except (ValueError, TypeError):
                    ids = None
        
        if "tags" in args:
            raw_tags = args["tags"]
            if isinstance(raw_tags, str):
                tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            else:
                tags = list(raw_tags)
        mem_type = args.get("type")

    removed = mm.forget(ids=ids, tags=tags, mem_type=mem_type)
    summary = (
        f"Forgot {removed} memory item(s)."
        if removed
        else "No memories matched the forget filters."
    )
    extra = {"removed": removed}
    return _base_response(cmd_name, summary, extra)


def handle_trace(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Inspect lineage of a memory item."""
    mm = kernel.memory_manager
    mem_id = None
    if isinstance(args, dict):
        value = args.get("id")
        if value is not None:
            try:
                mem_id = int(value)
            except ValueError:
                mem_id = None
    if mem_id is None:
        return _base_response(cmd_name, "No memory id provided for trace.", {"ok": False})

    info = mm.trace(mem_id)
    if not info:
        summary = f"No memory found with id {mem_id}."
        extra = {}
    else:
        summary = (
            f"Memory #{info['id']} [{info['type']}] tags={info['tags']} "
            f"stored at {info['timestamp']} via {info['trace'].get('source', 'unknown')}, "
            f"cluster={info['cluster_id']}."
        )
        extra = info
    return _base_response(cmd_name, summary, extra)


def handle_bind(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Bind multiple memory items into a cluster."""
    mm = kernel.memory_manager
    ids = None

    if isinstance(args, dict):
        raw_ids = args.get("ids")
        if isinstance(raw_ids, str):
            ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
        elif isinstance(raw_ids, list):
            ids = [int(x) for x in raw_ids if str(x).isdigit()]

    if not ids or len(ids) < 2:
        return _base_response(cmd_name, "bind requires at least 2 memory ids.", {"ok": False})

    cluster_id = mm.bind_cluster(ids)
    summary = f"Bound {len(ids)} memories into cluster #{cluster_id}."
    extra = {"cluster_id": cluster_id, "ids": ids}
    return _base_response(cmd_name, summary, extra)


# =============================================================================
# WORKING MEMORY DEBUG HANDLERS
# =============================================================================

def handle_wm_debug(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Show current Working Memory state."""
    try:
        wm = get_wm(session_id)
        state = wm.to_dict()
        
        lines = [
            F.header("Working Memory State"),
            F.key_value("Session", state['session_id']),
            F.key_value("Turn count", state['turn_count']),
            F.key_value("Emotional tone", state['emotional_tone']),
        ]
        
        current_mod = getattr(wm, 'current_module', None)
        if current_mod:
            lines.append(F.key_value("Current Module", current_mod))
        lines.append("")
        
        if state['entities']:
            lines.append(F.subheader("Entities"))
            for eid, entity in state['entities'].items():
                lines.append(f"  {eid}: {entity}")
        
        if state.get('topics'):
            lines.append("")
            lines.append(F.subheader("Topics"))
            for topic in state['topics']:
                lines.append(f"  • {topic}")
        
        summary = "\n".join(lines)
        return _base_response(cmd_name, summary, state)
    except Exception as e:
        return _base_response(cmd_name, f"WM debug error: {e}", {"ok": False})


def handle_wm_clear_cmd(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Clear working memory for this session."""
    wm_clear(session_id)
    return _base_response(cmd_name, "Working memory cleared.", {"session_id": session_id})


def handle_behavior_debug(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Show Behavior Layer state."""
    behavior = get_behavior(session_id)
    if behavior is None:
        return _base_response(cmd_name, "Behavior layer not available.", {"ok": False})
    
    state = behavior.to_dict() if hasattr(behavior, 'to_dict') else {"status": "active"}
    summary = F.header("Behavior Layer State") + json.dumps(state, indent=2)
    return _base_response(cmd_name, summary, state)


# =============================================================================
# ENVIRONMENT / MODE HANDLERS
# =============================================================================

def handle_env(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Show current environment state."""
    env = getattr(kernel, "env_state", {})
    if not isinstance(env, dict):
        env = {}

    lines = []
    for k, v in env.items():
        lines.append(F.key_value(k, v))

    if not lines:
        summary = F.header("Environment state") + "No environment keys set."
    else:
        summary = F.header("Environment state") + "\n".join(lines)

    return _base_response(cmd_name, summary, {"env": env})


def handle_setenv(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Set one or more environment keys."""
    if not isinstance(args, dict) or not args:
        return _base_response(cmd_name, "Usage: setenv key=value", {"ok": False})

    updates = {}
    for key, value in args.items():
        if key == "_":
            continue
        if hasattr(kernel, "set_env"):
            new_val = kernel.set_env(key, value)
        else:
            new_val = value
            if not hasattr(kernel, "env_state") or not isinstance(kernel.env_state, dict):
                kernel.env_state = {}
            kernel.env_state[key] = new_val
        updates[key] = new_val

    if not updates:
        return _base_response(cmd_name, "No valid key=value pairs provided.", {"ok": False})

    lines = [F.key_value(k, v) for k, v in updates.items()]
    summary = F.header("Environment updated") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"updated": updates})


# v0.11.0: handle_mode removed - mode command no longer supported


# =============================================================================
# SNAPSHOT / RESTORE HANDLERS
# =============================================================================

def handle_snapshot(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Create a snapshot of core OS state."""
    from datetime import datetime, timezone

    snapshot_dir = kernel.config.data_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"snapshot_{timestamp}.json"
    path = snapshot_dir / filename

    state: Dict[str, Any] = {
        "version": "0.9.0",
        "created_at": timestamp,
        "memory": kernel.memory_manager.export_state(),
        "modules": kernel.module_registry.export_state()
        if hasattr(kernel, "module_registry")
        else {},
    }
    if hasattr(kernel, "context_manager") and hasattr(kernel.context_manager, "export_state"):
        try:
            state["context"] = kernel.context_manager.export_state()
        except Exception:
            state["context"] = {"error": "failed_to_export"}

    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    summary = f"Snapshot created: {filename}"
    return _base_response(cmd_name, summary, {"file": filename, "path": str(path)})


def handle_restore(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Restore OS state from a snapshot file."""
    if not isinstance(args, dict) or "file" not in args:
        return _base_response(cmd_name, "restore requires file=<snapshot_filename>.", {"ok": False})

    snapshot_dir = kernel.config.data_dir / "snapshots"
    path = snapshot_dir / args["file"]
    if not path.exists():
        return _base_response(cmd_name, f"Snapshot file not found: {args['file']}", {"ok": False})

    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)

    mem_state = state.get("memory")
    if mem_state is not None:
        kernel.memory_manager.import_state(mem_state)

    mod_state = state.get("modules")
    if mod_state is not None and hasattr(kernel, "module_registry"):
        kernel.module_registry.import_state(mod_state)

    summary = f"Restored from snapshot {args['file']}."
    return _base_response(cmd_name, summary, {"file": args["file"], "ok": True})


# =============================================================================
# REMINDER HANDLERS
# =============================================================================

def handle_remind_add(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Create a reminder."""
    title = None
    when = None
    repeat = None

    if isinstance(args, dict):
        title = args.get("title") or args.get("_", [None])[0]
        when = args.get("when")
        repeat = args.get("repeat")

    if not title or not when:
        return _base_response(cmd_name, "Missing title or when.", {"ok": False})

    r = kernel.reminders.add(title=title, when=when, repeat=repeat)
    data = r.to_dict()

    summary = F.header("Reminder added") + f"I'll remind you at {data.get('when')}:\n    \"{data.get('title')}\""
    return _base_response(cmd_name, summary, data)


def handle_remind_list(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """List reminders."""
    items = [r.to_dict() for r in kernel.reminders.list()]

    if not items:
        return _base_response(cmd_name, F.header("No active reminders."), {"reminders": []})

    formatted = []
    for r in items:
        formatted.append(F.item(r.get("id", "?"), r.get("when", "?"), f"\"{r.get('title', '')}\""))

    summary = F.header(f"Active reminders ({len(items)})") + F.list(formatted)
    return _base_response(cmd_name, summary, {"reminders": items})


def handle_remind_update(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Update an existing reminder."""
    rid = None
    if isinstance(args, dict):
        rid = args.get("id") or args.get("_", [None])[0]
    if not rid:
        return _base_response(cmd_name, "Missing id.", {"ok": False})

    fields = {k: v for k, v in args.items() if k not in ("id", "_")}
    r = kernel.reminders.update(rid, fields)
    if not r:
        return _base_response(cmd_name, f"No reminder '{rid}'.", {"ok": False})

    data = r.to_dict()
    summary = F.header("Reminder updated") + f"#{data.get('id')} — {data.get('when')}\n    \"{data.get('title')}\""
    return _base_response(cmd_name, summary, data)


def handle_remind_delete(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Delete a reminder."""
    rid = None
    if isinstance(args, dict):
        rid = args.get("id") or args.get("_", [None])[0]

    if not rid:
        return _base_response(cmd_name, "Missing id.", {"ok": False})

    ok = kernel.reminders.delete(rid)
    if not ok:
        return _base_response(cmd_name, f"No reminder '{rid}'.", {"ok": False})

    return _base_response(cmd_name, f"Reminder '{rid}' deleted.", {"id": rid})


# =============================================================================
# CUSTOM COMMAND HANDLERS
# =============================================================================

def handle_prompt_command(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Execute a custom prompt command."""
    template = meta.get("prompt_template")
    if not template:
        return _base_response(cmd_name, f"Custom command '{cmd_name}' missing prompt_template.", {"ok": False})

    full_input = args.get("full_input", "") if isinstance(args, dict) else ""
    user_prompt = template.replace("{{full_input}}", full_input)

    result = kernel.llm_client.complete(
        system="You are Nova, a helpful AI assistant.",
        user=user_prompt,
        session_id=session_id,
    )

    output_text = result.get("text", "")
    summary = F.header(f"Custom command: {cmd_name}") + output_text.strip()
    return _base_response(cmd_name, summary, {"result": output_text})


def handle_command_add(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Add a new custom command."""
    if not isinstance(args, dict):
        return _base_response(cmd_name, "command-add requires structured arguments.", {"ok": False})

    name = args.get("name")
    kind = args.get("kind", "prompt")
    prompt_template = args.get("prompt_template")

    if not name:
        return _base_response(cmd_name, "command-add requires name=<name>.", {"ok": False})

    if kind == "prompt" and not prompt_template:
        return _base_response(cmd_name, "Prompt commands require prompt_template=<template>.", {"ok": False})

    entry = {
        "kind": kind,
        "prompt_template": prompt_template,
        "enabled": True,
        "description": args.get("description", ""),
    }

    kernel.custom_registry.add(name, entry)
    summary = F.header("Custom Command Added") + f"Created '{name}' ({kind})."
    return _base_response(cmd_name, summary, {"name": name, "kind": kind})


def handle_command_list(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """List all custom commands."""
    commands = kernel.custom_registry.list()

    if not commands:
        return _base_response(cmd_name, "No custom commands defined.", {"commands": []})

    lines = [F.header("Custom Commands")]
    for name, entry in commands.items():
        status = "✓" if entry.get("enabled", True) else "✗"
        kind = entry.get("kind", "prompt")
        lines.append(f"  {status} #{name} ({kind})")

    return _base_response(cmd_name, "\n".join(lines), {"commands": list(commands.keys())})


def handle_command_inspect(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Inspect a custom command's metadata."""
    name = None
    if isinstance(args, dict):
        name = args.get("name") or args.get("_", [None])[0]

    if not name:
        return _base_response(cmd_name, "Usage: command-inspect name=<cmd>", {"ok": False})

    entry = kernel.custom_registry.get(name)
    if not entry:
        return _base_response(cmd_name, f"No such custom command '{name}'.", {"ok": False})

    summary = F.header(f"Command: #{name}") + json.dumps(entry, indent=2)
    return _base_response(cmd_name, summary, {"command": entry})


def handle_command_remove(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Remove a custom command."""
    name = None
    if isinstance(args, dict):
        name = args.get("name") or args.get("_", [None])[0]

    if not name:
        return _base_response(cmd_name, "Usage: command-remove name=<cmd>", {"ok": False})

    ok = kernel.custom_registry.remove(name)
    if not ok:
        return _base_response(cmd_name, f"No such custom command '{name}'.", {"ok": False})

    return _base_response(cmd_name, f"'{name}' removed.", {"ok": True})


def handle_command_toggle(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Enable or disable a custom command."""
    name = None
    if isinstance(args, dict):
        name = args.get("name") or args.get("_", [None])[0]

    if not name:
        return _base_response(cmd_name, "Usage: command-toggle name=<cmd>", {"ok": False})

    ok = kernel.custom_registry.toggle(name)
    if not ok:
        return _base_response(cmd_name, f"No such custom command '{name}'.", {"ok": False})

    status = "enabled" if kernel.custom_registry.get(name).get("enabled", True) else "disabled"
    return _base_response(cmd_name, f"'{name}' → {status}", {"name": name, "status": status})


def handle_command_wizard(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Start the command creation wizard."""
    return _base_response(cmd_name, "Command wizard not yet implemented.", {"ok": False})


# =============================================================================
# SELF-TEST / DIAGNOSTICS
# =============================================================================

def handle_self_test(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Run internal diagnostics."""
    results = []
    pass_count = 0
    warn_count = 0
    fail_count = 0

    # Test 1: Memory Manager
    try:
        health = kernel.memory_manager.get_health()
        results.append({"name": "Memory Manager", "status": "pass", "note": f"Health: {health}"})
        pass_count += 1
    except Exception as e:
        results.append({"name": "Memory Manager", "status": "fail", "note": str(e)})
        fail_count += 1

    # Test 2: Context Manager
    try:
        ctx = kernel.context_manager.get_context(session_id)
        results.append({"name": "Context Manager", "status": "pass", "note": f"Booted: {ctx.get('booted', False)}"})
        pass_count += 1
    except Exception as e:
        results.append({"name": "Context Manager", "status": "fail", "note": str(e)})
        fail_count += 1

    # Test 3: Working Memory
    try:
        wm = get_wm(session_id)
        results.append({"name": "Working Memory", "status": "pass", "note": f"Turn count: {wm.turn_count}"})
        pass_count += 1
    except Exception as e:
        results.append({"name": "Working Memory", "status": "warn", "note": str(e)})
        warn_count += 1

    # Build summary
    lines = [F.header("NovaOS Self-Test Results"), ""]
    for r in results:
        icon = "✓" if r["status"] == "pass" else ("⚠" if r["status"] == "warn" else "✗")
        lines.append(f"  {icon} [{r['status']}] {r['name']}")
        lines.append(f"      {r['note']}")

    lines.append("")
    all_passed = fail_count == 0
    if all_passed and warn_count == 0:
        lines.append("✅ All tests passed.")
    elif all_passed:
        lines.append(f"✅ All tests passed with {warn_count} warning(s).")
    else:
        lines.append(f"⚠️ {fail_count} test(s) failed.")

    return _base_response(cmd_name, "\n".join(lines), {
        "results": results,
        "pass": pass_count,
        "warn": warn_count,
        "fail": fail_count,
        "all_passed": all_passed,
    })


def handle_diagnostics(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Alias for self-test."""
    return handle_self_test("self-test", args, session_id, context, kernel, meta)


# =============================================================================
# SECTION MENU HANDLERS
# =============================================================================

def _handle_section_menu(section_key, cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """Generic section menu handler."""
    section = get_section(section_key)
    if not section:
        return _base_response(cmd_name, f"Unknown section '{section_key}'.", {"ok": False})

    # Set active section
    _section_menu_state[session_id] = section_key

    lines = [
        f"╔══ {section.title} ══╗",
        "",
        section.description,
        "",
        "Which command would you like to run?",
        "",
    ]

    for i, cmd in enumerate(section.commands, 1):
        lines.append(f"{i}) {cmd.name}")
        lines.append(f"   Description: {cmd.description}")
        lines.append(f"   Example: {cmd.example}")
        lines.append("")

    example_cmd = section.commands[0].name if section.commands else "command"
    lines.append(f'Please type the command name exactly (e.g., "{example_cmd}").')

    return _base_response(cmd_name, "\n".join(lines), {
        "section": section_key,
        "commands": [cmd.name for cmd in section.commands],
        "menu_active": True,
    })


def handle_section_core(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("core", cmd_name, args, session_id, context, kernel, meta)

def handle_section_memory(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("memory", cmd_name, args, session_id, context, kernel, meta)

# v0.11.0: handle_section_continuity removed

def handle_section_human_state(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("human_state", cmd_name, args, session_id, context, kernel, meta)

def handle_section_modules(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("modules", cmd_name, args, session_id, context, kernel, meta)

def handle_section_identity(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("identity", cmd_name, args, session_id, context, kernel, meta)

def handle_section_system(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("system", cmd_name, args, session_id, context, kernel, meta)

def handle_section_workflow(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("workflow", cmd_name, args, session_id, context, kernel, meta)

def handle_section_timerhythm(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("timerhythm", cmd_name, args, session_id, context, kernel, meta)

def handle_section_reminders(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("reminders", cmd_name, args, session_id, context, kernel, meta)

def handle_section_commands(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("commands", cmd_name, args, session_id, context, kernel, meta)

def handle_section_debug(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _handle_section_menu("debug", cmd_name, args, session_id, context, kernel, meta)

# v0.11.0: handle_section_inbox removed


# =============================================================================
# TIME RHYTHM HANDLERS (v0.11.0)
# =============================================================================

def handle_daily_review(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Start or complete daily review.
    
    v0.11.0: Added as part of simplified timerhythm section.
    
    Daily review prompts reflection on:
    - What did I accomplish today?
    - What's still on my mind?
    - What's my intention for tomorrow?
    
    Usage:
        #daily-review         — Start daily review wizard
        #daily-review start   — Same as above
        #daily-review done    — Mark today's review as complete
    """
    from datetime import datetime, timezone
    
    action = None
    if isinstance(args, dict):
        action = args.get("action")
        positional = args.get("_", [])
        if not action and positional:
            action = str(positional[0]).lower()
    elif isinstance(args, str) and args.strip():
        action = args.strip().lower()
    
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    
    if action == "done":
        # Mark review as complete
        if hasattr(kernel, "set_env"):
            kernel.set_env("last_daily_review", today)
        
        summary = (
            "✓ Daily review complete!\n\n"
            f"Logged for {today}.\n"
            "See you tomorrow."
        )
        return _base_response(cmd_name, summary, {"date": today, "status": "complete"})
    
    # Start review (default)
    lines = [
        "╔══ Daily Review ══╗",
        "",
        "Take a moment to reflect on your day.",
        "",
        "1) What did you accomplish today?",
        "2) What's still on your mind?",
        "3) What's your intention for tomorrow?",
        "",
        "When you're done reflecting, run: #daily-review done",
    ]
    
    return _base_response(cmd_name, "\n".join(lines), {
        "date": today,
        "status": "started",
    })


def handle_weekly_review(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Start or complete weekly review.
    
    Weekly review prompts reflection on:
    - What were this week's wins?
    - What challenges did I face?
    - What do I want to focus on next week?
    
    Usage:
        #weekly-review         — Start weekly review wizard
        #weekly-review start   — Same as above
        #weekly-review done    — Mark this week's review as complete
    """
    from datetime import datetime, timezone
    
    action = None
    if isinstance(args, dict):
        action = args.get("action")
        positional = args.get("_", [])
        if not action and positional:
            action = str(positional[0]).lower()
    elif isinstance(args, str) and args.strip():
        action = args.strip().lower()
    
    now = datetime.now(timezone.utc)
    week = now.strftime("%Y-W%W")
    
    if action == "done":
        # Mark review as complete
        if hasattr(kernel, "set_env"):
            kernel.set_env("last_weekly_review", week)
        
        summary = (
            "✓ Weekly review complete!\n\n"
            f"Logged for {week}.\n"
            "Have a great week ahead!"
        )
        return _base_response(cmd_name, summary, {"week": week, "status": "complete"})
    
    # Start review (default)
    lines = [
        "╔══ Weekly Review ══╗",
        "",
        "Take time to reflect on your week.",
        "",
        "1) What were this week's wins?",
        "2) What challenges did you face?",
        "3) What do you want to focus on next week?",
        "",
        "When you're done reflecting, run: #weekly-review done",
    ]
    
    return _base_response(cmd_name, "\n".join(lines), {
        "week": week,
        "status": "started",
    })


# =============================================================================
# PLACEHOLDER HANDLERS (for handlers referenced but not fully implemented)
# =============================================================================

def handle_wm_clear_topic(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM topic clearing not yet implemented.", {"ok": False})

def handle_behavior_mode(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Behavior mode not yet implemented.", {"ok": False})

def handle_wm_snapshot(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM snapshot not yet implemented.", {"ok": False})

def handle_wm_topics(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM topics not yet implemented.", {"ok": False})

def handle_wm_switch(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM switch not yet implemented.", {"ok": False})

def handle_wm_restore(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM restore not yet implemented.", {"ok": False})

def handle_wm_mode(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM mode not yet implemented.", {"ok": False})

def handle_wm_load(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM load not yet implemented.", {"ok": False})

def handle_wm_bridge(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM bridge not yet implemented.", {"ok": False})

def handle_wm_groups(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM groups not yet implemented.", {"ok": False})

def handle_wm_status(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "WM status not yet implemented.", {"ok": False})

def handle_episodic_list(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Episodic list not yet implemented.", {"ok": False})

def handle_episodic_debug(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Episodic debug not yet implemented.", {"ok": False})

def handle_bind_module(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Bind module not yet implemented.", {"ok": False})

def handle_model_info(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Model info not yet implemented.", {"ok": False})

def handle_memory_stats(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory stats not yet implemented.", {"ok": False})

def handle_memory_salience(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory salience not yet implemented.", {"ok": False})

def handle_memory_status(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory status not yet implemented.", {"ok": False})

def handle_memory_high_salience(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory high salience not yet implemented.", {"ok": False})

def handle_identity_show(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Identity show not yet implemented.", {"ok": False})

def handle_identity_set(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Identity set not yet implemented.", {"ok": False})

def handle_identity_snapshot(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Identity snapshot not yet implemented.", {"ok": False})

def handle_identity_history(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Identity history not yet implemented.", {"ok": False})

def handle_identity_restore(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Identity restore not yet implemented.", {"ok": False})

def handle_identity_clear_history(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Identity clear history not yet implemented.", {"ok": False})

def handle_memory_decay(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory decay not yet implemented.", {"ok": False})

def handle_memory_drift(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory drift not yet implemented.", {"ok": False})

def handle_memory_reconfirm(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory reconfirm not yet implemented.", {"ok": False})

def handle_memory_stale(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory stale not yet implemented.", {"ok": False})

def handle_memory_archive_stale(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory archive stale not yet implemented.", {"ok": False})

def handle_decay_preview(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Decay preview not yet implemented.", {"ok": False})

def handle_memory_policy(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory policy not yet implemented.", {"ok": False})

def handle_memory_policy_test(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory policy test not yet implemented.", {"ok": False})

def handle_memory_mode_filter(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Memory mode filter not yet implemented.", {"ok": False})

# v0.11.0: handle_preferences, handle_projects, handle_continuity_context removed (continuity section removed)

def handle_reconfirm_prompts(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Reconfirm prompts not yet implemented.", {"ok": False})

def handle_evolution_status(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Evolution status not yet implemented.", {"ok": False})

def handle_log_state(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Log state not yet implemented.", {"ok": False})

def handle_state_history(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "State history not yet implemented.", {"ok": False})

def handle_capacity_check(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Capacity check not yet implemented.", {"ok": False})

def handle_macro(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    return _base_response(cmd_name, "Macro not yet implemented.", {"ok": False})


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

SYS_HANDLERS: Dict[str, Callable[..., CommandResponse]] = {
    # Core
    "handle_why": handle_why,
    "handle_boot": handle_boot,
    "handle_shutdown": handle_shutdown,  # v0.9.0: Dual-mode architecture
    "handle_reset": handle_reset,
    "handle_status": handle_status,
    "handle_help": handle_help,
    
    # Memory
    "handle_store": handle_store,
    "handle_recall": handle_recall,
    "handle_forget": handle_forget,
    "handle_trace": handle_trace,
    "handle_bind": handle_bind,
    
    # Working Memory
    "handle_wm_debug": handle_wm_debug,
    "handle_wm_clear_cmd": handle_wm_clear_cmd,
    "handle_wm_clear_topic": handle_wm_clear_topic,
    "handle_wm_snapshot": handle_wm_snapshot,
    "handle_wm_topics": handle_wm_topics,
    "handle_wm_switch": handle_wm_switch,
    "handle_wm_restore": handle_wm_restore,
    "handle_wm_mode": handle_wm_mode,
    "handle_wm_load": handle_wm_load,
    "handle_wm_bridge": handle_wm_bridge,
    "handle_wm_groups": handle_wm_groups,
    "handle_wm_status": handle_wm_status,
    
    # Behavior
    "handle_behavior_debug": handle_behavior_debug,
    "handle_behavior_mode": handle_behavior_mode,
    
    # Episodic
    "handle_episodic_list": handle_episodic_list,
    "handle_episodic_debug": handle_episodic_debug,
    
    # Environment (v0.11.0: handle_mode removed)
    "handle_env": handle_env,
    "handle_setenv": handle_setenv,
    
    # Model
    "handle_model_info": handle_model_info,
    
    # Memory Engine
    "handle_memory_stats": handle_memory_stats,
    "handle_memory_salience": handle_memory_salience,
    "handle_memory_status": handle_memory_status,
    "handle_memory_high_salience": handle_memory_high_salience,
    "handle_memory_decay": handle_memory_decay,
    "handle_memory_drift": handle_memory_drift,
    "handle_memory_reconfirm": handle_memory_reconfirm,
    "handle_memory_stale": handle_memory_stale,
    "handle_memory_archive_stale": handle_memory_archive_stale,
    "handle_decay_preview": handle_decay_preview,
    "handle_memory_policy": handle_memory_policy,
    "handle_memory_policy_test": handle_memory_policy_test,
    "handle_memory_mode_filter": handle_memory_mode_filter,
    
    # Identity
    "handle_identity_show": handle_identity_show,
    "handle_identity_set": handle_identity_set,
    "handle_identity_snapshot": handle_identity_snapshot,
    "handle_identity_history": handle_identity_history,
    "handle_identity_restore": handle_identity_restore,
    "handle_identity_clear_history": handle_identity_clear_history,
    
    # v0.11.0: Continuity handlers removed (preferences, projects, continuity_context)
    "handle_reconfirm_prompts": handle_reconfirm_prompts,
    
    # Time Rhythm (v0.11.0)
    "handle_daily_review": handle_daily_review,
    "handle_weekly_review": handle_weekly_review,
    
    # Human State
    "handle_evolution_status": handle_evolution_status,
    "handle_log_state": handle_log_state,
    "handle_state_history": handle_state_history,
    "handle_capacity_check": handle_capacity_check,
    
    # Modules
    "handle_bind_module": handle_bind_module,
    
    # Snapshot / Restore
    "handle_snapshot": handle_snapshot,
    "handle_restore": handle_restore,
    
    # Reminders
    "handle_remind_add": handle_remind_add,
    "handle_remind_list": handle_remind_list,
    "handle_remind_update": handle_remind_update,
    "handle_remind_delete": handle_remind_delete,
    
    # Custom Commands
    "handle_prompt_command": handle_prompt_command,
    "handle_command_add": handle_command_add,
    "handle_command_list": handle_command_list,
    "handle_command_inspect": handle_command_inspect,
    "handle_command_remove": handle_command_remove,
    "handle_command_toggle": handle_command_toggle,
    "handle_command_wizard": handle_command_wizard,
    "handle_macro": handle_macro,
    
    # Self-Test
    "handle_self_test": handle_self_test,
    "handle_diagnostics": handle_diagnostics,
    
    # Section Menus (v0.11.0: removed continuity, inbox)
    "handle_section_core": handle_section_core,
    "handle_section_memory": handle_section_memory,
    "handle_section_human_state": handle_section_human_state,
    "handle_section_modules": handle_section_modules,
    "handle_section_identity": handle_section_identity,
    "handle_section_system": handle_section_system,
    "handle_section_workflow": handle_section_workflow,
    "handle_section_timerhythm": handle_section_timerhythm,
    "handle_section_reminders": handle_section_reminders,
    "handle_section_commands": handle_section_commands,
    "handle_section_debug": handle_section_debug,
}


# =============================================================================
# v0.8.0: FEATURE MODULE INTEGRATION (v0.11.0: removed inbox, assistant mode)
# =============================================================================

# Quest Engine handlers
if _HAS_QUEST_ENGINE:
    SYS_HANDLERS.update(get_quest_handlers())

# v0.11.0: Inbox handlers removed

# Player Profile handlers
if _HAS_PLAYER_PROFILE:
    SYS_HANDLERS.update(get_player_profile_handlers())

# Module Manager handlers
if _HAS_MODULE_MANAGER:
    SYS_HANDLERS.update(get_module_handlers())

# v0.11.0: Assistant Mode handlers removed

# Time Rhythm handlers
if _HAS_TIME_RHYTHM:
    SYS_HANDLERS.update(get_time_rhythm_handlers())

# v0.11.0: Memory Syscommand handlers
if _HAS_MEMORY_SYSCOMMANDS:
    SYS_HANDLERS.update(get_memory_syscommand_handlers())
