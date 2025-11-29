# kernel/syscommands.py
import json
from typing import Dict, Any, Callable

from .command_types import CommandResponse

KernelResponse = CommandResponse


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


# -------------------- Core v0.1 / v0.2 handlers --------------------


def handle_why(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    summary = (
        "NovaOS is your AI operating system: a stable, first-principles companion that "
        "turns your life into structured modules, workflows, and long-term roadmaps."
    )
    return _base_response(cmd_name, summary)


def handle_boot(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    kernel.context_manager.mark_booted(session_id)
    summary = "NovaOS kernel booted. Persona loaded. Modules and memory initialized."
    return _base_response(cmd_name, summary)


def handle_status(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    mem_health = kernel.memory_manager.get_health()
    modules = kernel.context_manager.get_module_summary()
    ctx = kernel.context_manager.get_context(session_id)
    summary = "System status snapshot."
    extra = {
        "memory_health": mem_health,
        "modules": modules,
        "booted": ctx.get("booted", False),
    }
    return _base_response(cmd_name, summary, extra)


def handle_help(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    cmds = []
    for name, info in kernel.commands.items():
        cmds.append(
            {
                "name": name,
                "category": info.get("category", "misc"),
                "description": info.get("description", ""),
            }
        )
    summary = "Available syscommands (dynamic registry)."
    extra = {"commands": cmds}
    return _base_response(cmd_name, summary, extra)


def handle_reset(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    kernel.context_manager.reset_session(session_id)
    summary = "Session context reset. Modules and workflows reloaded from disk."
    return _base_response(cmd_name, summary)


# ------------------------ Memory v0.3 handlers ------------------------


def handle_store(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Store a memory item via MemoryManager v0.3."""
    mm = kernel.memory_manager
    payload = ""
    mem_type = "semantic"
    tags: Any = ["general"]

    if isinstance(args, dict):
        payload = args.get("payload") or args.get("raw") or ""
        mem_type = args.get("type", mem_type)
        tags = args.get("tags", tags)
    else:
        payload = str(args)

    if isinstance(tags, str):
        tags = [tags]
    if tags is None:
        tags = ["general"]

    trace = {
        "source": f"syscommand:{cmd_name}",
        "session_id": session_id,
    }
    item = mm.store(payload=payload, mem_type=mem_type, tags=tags, trace=trace)
    summary = f"Stored {item.type} memory #{item.id} with tags {item.tags}."
    extra = {
        "id": item.id,
        "type": item.type,
        "tags": item.tags,
        "timestamp": item.timestamp,
    }
    return _base_response(cmd_name, summary, extra)


def handle_recall(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Recall memory items from MemoryManager v0.3."""
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
        summary = "No matching memories found."
        extra = {"items": []}
    else:
        lines = [f"Found {len(items)} memory item(s):"]
        for item in items[:5]:
            lines.append(f"- #{item.id} [{item.type}] tags={item.tags} :: {item.payload[:80]}")
        if len(items) > 5:
            lines.append(f"...and {len(items) - 5} more.")
        summary = "\n".join(lines)
        extra = {"items": [item.__dict__ for item in items]}

    return _base_response(cmd_name, summary, extra)


def handle_forget(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Delete memory items by id, tag, or type."""
    mm = kernel.memory_manager
    ids = None
    tags = None
    mem_type = None

    if isinstance(args, dict):
        if "ids" in args:
            raw_ids = args["ids"]
            if isinstance(raw_ids, int):
                ids = [raw_ids]
            elif isinstance(raw_ids, str):
                ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
            else:
                # assume iterable
                ids = [int(x) for x in raw_ids]
        if "tags" in args:
            raw_tags = args["tags"]
            if isinstance(raw_tags, str):
                tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            else:
                tags = list(raw_tags)
        mem_type = args.get("type")

    removed = mm.forget(ids=ids, tags=tags, mem_type=mem_type)
    summary = f"Forgot {removed} memory item(s)." if removed else "No memories matched the forget filters."
    extra = {"removed": removed}
    return _base_response(cmd_name, summary, extra)


def handle_trace(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
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


def handle_bind(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Bind multiple memory items into a cluster."""
    mm = kernel.memory_manager
    ids: Any = []
    if isinstance(args, dict):
        raw_ids = args.get("ids") or []
        if isinstance(raw_ids, int):
            ids = [raw_ids]
        elif isinstance(raw_ids, str):
            ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
        else:
            ids = [int(x) for x in raw_ids]
    if not ids:
        return _base_response(cmd_name, "No memory IDs provided for binding.", {"ok": False})

    cluster_id = mm.bind_cluster(ids)
    summary = f"Bound memories {ids} into cluster {cluster_id}."
    extra = {"cluster_id": cluster_id, "ids": ids}
    return _base_response(cmd_name, summary, extra)


# ------------------------ Modules v0.3 handlers ------------------------


def handle_map(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """List registered modules from ModuleRegistry."""
    mr = kernel.module_registry
    mods = mr.list_modules()
    if not mods:
        summary = "No modules registered."
        extra = {"modules": []}
    else:
        lines = ["Registered modules:"]
        for m in mods:
            lines.append(f"- {m.key} ({m.state}) :: {m.mission}")
        summary = "\n".join(lines)
        extra = {"modules": [m.__dict__ for m in mods]}
    return _base_response(cmd_name, summary, extra)


def handle_forge(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Create a new module entry."""
    mr = kernel.module_registry
    if not isinstance(args, dict):
        return _base_response(cmd_name, "forge requires key=<key> at minimum.", {"ok": False})

    key = args.get("key")
    if not key:
        return _base_response(cmd_name, "Missing required argument: key=<module_key>.", {"ok": False})

    name = args.get("name", key)
    mission = args.get("mission", "")
    state = args.get("state", "inactive")
    try:
        meta_obj = mr.forge(key=key, name=name, mission=mission, state=state)
    except ValueError as e:
        return _base_response(cmd_name, str(e), {"ok": False})

    summary = f"Forged module '{meta_obj.key}' ({meta_obj.state}): {meta_obj.mission}"
    return _base_response(cmd_name, summary, meta_obj.__dict__)


def handle_dismantle(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Remove a module by key."""
    mr = kernel.module_registry
    key = None
    if isinstance(args, dict):
        key = args.get("key")
    if not key:
        return _base_response(cmd_name, "Missing required argument: key=<module_key>.", {"ok": False})

    ok = mr.dismantle(key)
    if not ok:
        summary = f"No such module '{key}' to dismantle."
        extra = {"ok": False}
    else:
        summary = f"Dismantled module '{key}'."
        extra = {"key": key, "ok": True}
    return _base_response(cmd_name, summary, extra)


def handle_inspect(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Inspect a module's metadata."""
    mr = kernel.module_registry
    key = None
    if isinstance(args, dict):
        key = args.get("key")
    if not key:
        return _base_response(cmd_name, "Missing required argument: key=<module_key>.", {"ok": False})

    meta_obj = mr.get(key)
    if not meta_obj:
        return _base_response(cmd_name, f"No such module '{key}'.", {"ok": False})
    summary = (
        f"Module '{meta_obj.key}' ({meta_obj.state}): {meta_obj.mission}\n"
        f"Workflows: {len(meta_obj.workflows)} | Routines: {len(meta_obj.routines)} | "
        f"Bindings: {meta_obj.bindings}"
    )
    return _base_response(cmd_name, summary, meta_obj.__dict__)


def handle_bind_module(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Bind two modules together for cross-domain interaction."""
    mr = kernel.module_registry
    a = b = None
    if isinstance(args, dict):
        a = args.get("a")
        b = args.get("b")
    if not a or not b:
        return _base_response(
            cmd_name,
            "bind-module requires a=<module_key> and b=<module_key>.",
            {"ok": False},
        )
    ok = mr.bind_modules(a, b)
    if not ok:
        summary = f"Failed to bind modules '{a}' and '{b}' (one or both missing)."
        extra = {"ok": False}
    else:
        summary = f"Bound modules '{a}' <-> '{b}'."
        extra = {"a": a, "b": b, "ok": True}
    return _base_response(cmd_name, summary, extra)


# ------------------------ Snapshot v0.3 handlers ------------------------


def handle_snapshot(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Create a snapshot of core OS state (memory + modules; context if available)."""
    from datetime import datetime, timezone

    snapshot_dir = kernel.config.data_dir / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"snapshot_{timestamp}.json"
    path = snapshot_dir / filename

    state: Dict[str, Any] = {
        "version": "0.3",
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
    extra = {"file": filename, "path": str(path)}
    return _base_response(cmd_name, summary, extra)


def handle_restore(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Restore OS state from a snapshot file."""
    if not isinstance(args, dict) or "file" not in args:
        return _base_response(
            cmd_name,
            "restore requires file=<snapshot_filename>.",
            {"ok": False},
        )

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

    if "context" in state and hasattr(kernel, "context_manager") and hasattr(kernel.context_manager, "import_state"):
        try:
            kernel.context_manager.import_state(state["context"])
        except Exception:
            pass

    summary = f"Restored from snapshot {args['file']}."
    extra = {"file": args["file"], "ok": True}
    return _base_response(cmd_name, summary, extra)


# ------------------------ Handler registry ------------------------

SYS_HANDLERS: Dict[str, Callable[..., KernelResponse]] = {
    "handle_why": handle_why,
    "handle_boot": handle_boot,
    "handle_status": handle_status,
    "handle_help": handle_help,
    "handle_reset": handle_reset,
    "handle_store": handle_store,
    "handle_recall": handle_recall,
    "handle_forget": handle_forget,
    "handle_trace": handle_trace,
    "handle_bind": handle_bind,
    "handle_map": handle_map,
    "handle_forge": handle_forge,
    "handle_dismantle": handle_dismantle,
    "handle_inspect": handle_inspect,
    "handle_bind_module": handle_bind_module,
    "handle_snapshot": handle_snapshot,
    "handle_restore": handle_restore,
}
