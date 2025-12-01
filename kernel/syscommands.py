# kernel/syscommands.py
import json
from typing import Dict, Any, Callable

from .command_types import CommandResponse
from .formatting import OutputFormatter as F

KernelResponse = CommandResponse

# kernel/syscommands.py (add near top, after imports)

def _llm_with_policy(
    *,
    kernel,
    session_id: str,
    system: str,
    user: str,
    meta: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    v0.5.1 - Centralized LLM call with PolicyEngine hooks.

    - Pre-LLM: policy.pre_llm(user_text, meta) → sanitized user text.
    - Post-LLM: policy.post_llm(output_text, meta) → normalized text.
    - Returns a dict with at least {"text": <final_text>}.
    """
    policy = getattr(kernel, "policy_engine", None)
    meta_full: Dict[str, Any] = dict(meta or {})
    meta_full.setdefault("session_id", session_id)
    meta_full.setdefault("source", meta_full.get("command", "syscommand"))

    # ---- Pre-LLM on the user text only ----
    safe_user = user
    if policy and hasattr(policy, "pre_llm"):
        try:
            safe_user = policy.pre_llm(user, meta_full)
        except Exception:
            # Fail-safe: ignore policy errors, continue with original user text
            safe_user = user

    # ---- Core LLM call ----
    result = kernel.llm_client.complete(
        system=system,
        user=safe_user,
        session_id=session_id,
    )

    raw_text = result.get("text", "")

    # ---- Post-LLM normalization on the output text ----
    final_text = raw_text
    if policy and hasattr(policy, "post_llm"):
        try:
            final_text = policy.post_llm(raw_text, meta_full)
        except Exception:
            final_text = raw_text

    return {"text": final_text}

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

# ---------------------------------------------------------------------
# v0.5 — Interpretation Commands
# ---------------------------------------------------------------------

def _extract_input_arg(args: Any) -> str:
    """
    Small helper to extract the main input string for interpretation commands.
    Supports:
      - args["input"]
      - args["_"][0]
      - args["full_input"]
    """
    if isinstance(args, dict):
        if "input" in args and isinstance(args["input"], str):
            return args["input"]
        if "_" in args and isinstance(args["_"], list) and args["_"]:
            return str(args["_"][0])
        if "full_input" in args and isinstance(args["full_input"], str):
            return args["full_input"]
    return ""


def handle_interpret(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Explain what the given text means in a clear, structured way.
    """
    text = _extract_input_arg(args)
    if not text:
        return _base_response(cmd_name, "Nothing to interpret (no input provided).", {"ok": False})

    system = (
        "You are the Interpretation Engine of NovaOS. "
        "Your job is to read the user's input and explain:\n"
        "1) What it means\n"
        "2) What the user is probably trying to do or ask\n"
        "3) Any hidden assumptions or ambiguities\n"
        "Be concise but structured."
    )
    user = text

    result = _llm_with_policy(
        kernel=kernel,
        session_id=session_id,
        system=system,
        user=user,
        meta={"command": "interpret"},
    )

    out = result.get("text", "").strip()
    summary = F.header("Interpretation") + out
    return _base_response(cmd_name, summary, {"result": out})


def handle_derive(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Break a topic down into first principles.
    """
    text = _extract_input_arg(args)
    if not text:
        return _base_response(cmd_name, "Nothing to derive (no input provided).", {"ok": False})

    system = (
        "You are the First Principles Engine of NovaOS. "
        "Given the user's topic or question, you must:\n"
        "- Identify core assumptions\n"
        "- Reduce it to first principles\n"
        "- Rebuild the reasoning from those basics\n"
        "Return a structured breakdown."
    )
    user = text

    result = _llm_with_policy(
        kernel=kernel,
        session_id=session_id,
        system=system,
        user=user,
        meta={"command": "derive"},
    )

    out = result.get("text", "").strip()
    summary = F.header("First Principles Derivation") + out
    return _base_response(cmd_name, summary, {"result": out})


def handle_synthesize(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Integrate several ideas into a coherent structure.
    """
    text = _extract_input_arg(args)
    if not text:
        return _base_response(cmd_name, "Nothing to synthesize (no input provided).", {"ok": False})

    system = (
        "You are the Synthesis Engine of NovaOS. "
        "The user is giving you multiple ideas, notes, or signals. "
        "Your job:\n"
        "- Identify the main themes\n"
        "- Group related ideas\n"
        "- Produce a coherent, high-level structure\n"
        "- Highlight tensions or trade-offs"
    )
    user = text

    result = _llm_with_policy(
        kernel=kernel,
        session_id=session_id,
        system=system,
        user=user,
        meta={"command": "synthesize"},
    )

    out = result.get("text", "").strip()
    summary = F.header("Synthesis") + out
    return _base_response(cmd_name, summary, {"result": out})


def handle_frame(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Reframe a problem or direction.
    """
    text = _extract_input_arg(args)
    if not text:
        return _base_response(cmd_name, "Nothing to frame (no input provided).", {"ok": False})

    system = (
        "You are the Framing Engine of NovaOS. "
        "The user is stuck in one perspective. "
        "Your job:\n"
        "- Identify the current frame\n"
        "- Offer 2–3 alternative frames (e.g., risk vs opportunity, short vs long term)\n"
        "- For each frame, briefly say what changes in decisions."
    )
    user = text

    result = _llm_with_policy(
        kernel=kernel,
        session_id=session_id,
        system=system,
        user=user,
        meta={"command": "frame"},
    )

    out = result.get("text", "").strip()
    summary = F.header("Reframing") + out
    return _base_response(cmd_name, summary, {"result": out})


def handle_forecast(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Generate plausible future outcomes based on current state.
    """
    text = _extract_input_arg(args)
    if not text:
        return _base_response(cmd_name, "Nothing to forecast (no input provided).", {"ok": False})

    system = (
        "You are the Forecast Engine of NovaOS. "
        "Given the user's situation or plan, you must:\n"
        "- Identify key variables and uncertainties\n"
        "- Sketch 2–3 plausible future paths (e.g., base, upside, downside)\n"
        "- For each path, note leading indicators the user can watch."
    )
    user = text

    result = _llm_with_policy(
        kernel=kernel,
        session_id=session_id,
        system=system,
        user=user,
        meta={"command": "forecast"},
    )

    out = result.get("text", "").strip()
    summary = F.header("Forecast") + out
    return _base_response(cmd_name, summary, {"result": out})



# ---------------------------------------------------------------------
# v0.5 — Prompt Command Executor
# ---------------------------------------------------------------------

def handle_prompt_command(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Execute a prompt-based custom command.
    Schema (commands_custom.json):
      {
        "name": "analyze_code",
        "kind": "prompt",
        "prompt_template": "... {{full_input}} ...",
        "input_mapping": {"full_input": "full_input"}
      }

    Behavior:
    - Extract template vars from args
    - Render template
    - Send to LLM
    - Optionally trigger post_actions
    """

    # Safety: require prompt_template
    template = meta.get("prompt_template")
    if not template:
        return _base_response(
            cmd_name,
            f"Custom command '{cmd_name}' missing prompt_template.",
            {"ok": False}
        )

    # Extract input vars from args using meta["input_mapping"]
    input_map = meta.get("input_mapping", {})
    rendered_vars = {}

    for var, source in input_map.items():
        if source == "full_input":
            rendered_vars[var] = args.get("full_input", "")
        elif source in args:
            rendered_vars[var] = args[source]
        else:
            rendered_vars[var] = ""

    # Render the template manually (simple replace)
    prompt = template
    for var, val in rendered_vars.items():
        placeholder = "{{" + var + "}}"
        prompt = prompt.replace(placeholder, str(val))

    # LLM call
    llm_result = kernel.llm_client.complete(
        system="You are executing a NovaOS custom prompt command.",
        user=prompt,
        session_id=session_id
    )
    output_text = llm_result.get("text", "")

    # placeholder: post-actions (v0.5 later step)
    # TODO: implement module/workflow triggers

    summary = (
        F.header(f"Custom command: {cmd_name}") +
        output_text.strip()
    )

    return _base_response(cmd_name, summary, {"result": output_text})

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

    # Presentation-only: pretty status summary
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


def handle_help(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    cmds = []
    formatted = []
    for name, info in kernel.commands.items():
        entry = {
            "name": name,
            "category": info.get("category", "misc"),
            "description": info.get("description", ""),
        }
        cmds.append(entry)
        formatted.append(
            F.item(
                id=name,
                label=entry["category"],
                details=entry["description"],
            )
        )

    summary = F.header("Available syscommands") + F.list(formatted)
    extra = {"commands": cmds}
    return _base_response(cmd_name, summary, extra)


def handle_reset(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    kernel.context_manager.reset_session(session_id)
    summary = "Session context reset. Modules and workflows reloaded from disk."
    return _base_response(cmd_name, summary)

# ---------------------------------------------------------------------
# v0.5.1 — Environment / Mode handlers
# ---------------------------------------------------------------------

def handle_env(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show current environment state (mode, debug, verbosity, etc.).
    """
    env = getattr(kernel, "env_state", {})

    # Fallback if env_state is missing
    if not isinstance(env, dict):
        env = {}

    lines = []
    for k, v in env.items():
        lines.append(F.key_value(k, v))

    if not lines:
        summary = F.header("Environment state") + "No environment keys set."
    else:
        summary = F.header("Environment state") + "\n".join(lines)

    extra = {"env": env}
    return _base_response(cmd_name, summary, extra)


def handle_setenv(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Set one or more environment keys.
    Usage examples:
        setenv mode=deep_work
        setenv debug=true verbosity=verbose
    """
    if not isinstance(args, dict) or not args:
        return _base_response(
            cmd_name,
            "Usage: setenv key=value [other_key=other_value] …",
            {"ok": False},
        )

    # Ignore positional "_" bucket
    updates = {}
    for key, value in args.items():
        if key == "_":
            continue
        # Use kernel.set_env if available to get consistent coercion
        if hasattr(kernel, "set_env"):
            new_val = kernel.set_env(key, value)
        else:
            new_val = value
            if not hasattr(kernel, "env_state") or not isinstance(kernel.env_state, dict):
                kernel.env_state = {}
            kernel.env_state[key] = new_val
        updates[key] = new_val

    if not updates:
        return _base_response(
            cmd_name,
            "No valid key=value pairs provided.",
            {"ok": False},
        )

    lines = [F.key_value(k, v) for k, v in updates.items()]
    summary = F.header("Environment updated") + "\n".join(lines)
    extra = {"updated": updates}
    return _base_response(cmd_name, summary, extra)


def handle_mode(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Set the current NovaOS mode.
    Allowed: normal | deep_work | reflection | debug

    Usage:
        mode deep_work
        mode mode=reflection
    """
    allowed = {"normal", "deep_work", "reflection", "debug"}
    desired = None

    if isinstance(args, dict):
        # Prefer explicit mode=<name>
        raw = args.get("mode")
        if isinstance(raw, str):
            desired = raw.strip().lower()
        # Fallback: first positional argument
        if not desired:
            positional = args.get("_")
            if isinstance(positional, list) and positional:
                desired = str(positional[0]).strip().lower()

    if not desired:
        return _base_response(
            cmd_name,
            f"Usage: mode <name> where name is one of {', '.join(sorted(allowed))}.",
            {"ok": False},
        )

    if desired not in allowed:
        return _base_response(
            cmd_name,
            f"Invalid mode '{desired}'. Allowed: {', '.join(sorted(allowed))}.",
            {"ok": False, "requested": desired},
        )

    # Update kernel env_state in a consistent way
    if hasattr(kernel, "set_env"):
        kernel.set_env("mode", desired)
    else:
        if not hasattr(kernel, "env_state") or not isinstance(kernel.env_state, dict):
            kernel.env_state = {}
        kernel.env_state["mode"] = desired

    current_env = getattr(kernel, "env_state", {})
    lines = [F.key_value("mode", desired)]
    summary = F.header("Mode updated") + "\n".join(lines)
    extra = {"mode": desired, "env": current_env}
    return _base_response(cmd_name, summary, extra)

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
    summary = (
        f"Forgot {removed} memory item(s)."
        if removed
        else "No memories matched the forget filters."
    )
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
        summary = F.header("No modules registered.")
        extra = {"modules": []}
    else:
        formatted = []
        for m in mods:
            formatted.append(
                F.item(
                    id=m.key,
                    label=m.state,
                    details=m.mission,
                )
            )
        summary = F.header(f"Modules ({len(mods)})") + F.list(formatted)
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


# ---------------------------------------------------------------------
# v0.4 — Workflow Engine handlers
# ---------------------------------------------------------------------


def handle_flow(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Start or restart a workflow.
    Usage:
        flow id=<workflow_id> steps='[{"title": "..."}]'
    Or minimal:
        flow id=mywf
    """
    wf_engine = kernel.workflow_engine

    wf_id = None
    name = None
    steps_raw = None

    if isinstance(args, dict):
        wf_id = args.get("id") or args.get("workflow") or args.get("_", [None])[0]
        name = args.get("name")
        steps_raw = args.get("steps")

    if not wf_id:
        return _base_response(cmd_name, "Missing workflow id (id=<id>).", {"ok": False})

    steps = []
    if isinstance(steps_raw, str):
        try:
            steps = json.loads(steps_raw)
        except Exception:
            return _base_response(cmd_name, "Invalid steps JSON.", {"ok": False})
    elif isinstance(steps_raw, list):
        steps = steps_raw

    wf = wf_engine.start(workflow_id=wf_id, name=name, steps=steps)
    summary = f"Started workflow '{wf.id}' with {len(wf.steps)} step(s)."
    extra = wf.to_dict()
    return _base_response(cmd_name, summary, extra)


def handle_advance(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Advance a workflow by one step.
    Usage:
        advance id=<workflow_id>
    """
    wf_engine = kernel.workflow_engine
    wf_id = None

    if isinstance(args, dict):
        wf_id = args.get("id") or args.get("_", [None])[0]

    if not wf_id:
        return _base_response(cmd_name, "Missing workflow id (id=<id>).", {"ok": False})

    wf = wf_engine.advance(wf_id)
    if not wf:
        return _base_response(cmd_name, f"No such workflow '{wf_id}'.", {"ok": False})

    summary = f"Advanced workflow '{wf_id}' to step {wf.current_step + 1}."
    extra = wf.to_dict()
    return _base_response(cmd_name, summary, extra)


def handle_halt(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Pause or halt a workflow.
    Usage:
        halt id=<workflow_id> status=paused
    """
    wf_engine = kernel.workflow_engine
    wf_id = None
    new_status = "paused"

    if isinstance(args, dict):
        wf_id = args.get("id") or args.get("_", [None])[0]
        new_status = args.get("status", "paused")

    if not wf_id:
        return _base_response(cmd_name, "Missing workflow id (id=<id>).", {"ok": False})

    wf = wf_engine.halt(wf_id, status=new_status)
    if not wf:
        return _base_response(cmd_name, f"No such workflow '{wf_id}'.", {"ok": False})

    summary = f"Workflow '{wf_id}' set to status '{new_status}'."
    return _base_response(cmd_name, summary, wf.to_dict())


def handle_workflow_delete(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Hard-delete a workflow from kernel.workflow_engine by id.

    Usage:
        workflow-delete id=<workflow_id>

    This operates purely on the in-memory WorkflowEngine state.
    Persistence is handled via snapshot/restore, not direct files.
    """
    wf_engine = kernel.workflow_engine

    wf_id = None
    if isinstance(args, dict):
        wf_id = args.get("id") or args.get("_", [None])[0]

    if not wf_id:
        return _base_response(
            cmd_name,
            "You need to specify a workflow id to delete. Example: workflow-delete id=3.",
            {"ok": False},
        )

    wf_id_str = str(wf_id)

    existing = wf_engine.get(wf_id_str)
    if not existing:
        return _base_response(
            cmd_name,
            f"I couldn’t find a workflow with id {wf_id_str}.",
            {"ok": False},
        )

    deleted = wf_engine.delete(wf_id_str)
    if not deleted:
        return _base_response(
            cmd_name,
            f"Workflow '{wf_id_str}' was found but could not be deleted.",
            {"ok": False},
        )

    name = existing.name or wf_id_str
    summary = (
        F.header("Workflow deleted") +
        F.item(wf_id_str, name)
    )
    extra = {
        "ok": True,
        "id": wf_id_str,
        "workflow": existing.to_dict(),
    }
    return _base_response(cmd_name, summary, extra)


def handle_workflow_list(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    List all workflows currently tracked in kernel.workflow_engine.

    Uses the in-memory WorkflowEngine state (snapshot-friendly),
    no direct file access.
    """
    wf_engine = kernel.workflow_engine
    summaries = wf_engine.summarize_all()  # list[dict] via WorkflowEngine._summary_dict

    if not summaries:
        summary = F.header("There are no workflows yet.")
        return _base_response(
            cmd_name,
            summary,
            {"ok": False, "count": 0, "workflows": []},
        )

    formatted = []
    for wf in summaries:
        wid = wf.get("id")
        name = wf.get("name") or f"Workflow {wid}"
        status = wf.get("status", "unknown")
        active_title = wf.get("active_step_title") or ""
        details = status
        if active_title:
            details = f"{status} → {active_title}"
        formatted.append(F.item(wid, name, details))

    summary = F.header(f"Workflows ({len(summaries)})") + F.list(formatted)
    extra = {
        "ok": True,
        "count": len(summaries),
        "workflows": summaries,
    }
    return _base_response(cmd_name, summary, extra)


def handle_compose(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Ask the LLM to generate a workflow spec for a goal.

    Usage:
        compose goal="improve cybersecurity"
        compose id="wf-1" goal="improve cybersecurity"   # v0.4.4: also creates a workflow
    """
    goal = None
    wf_id = None

    if isinstance(args, dict):
        goal = args.get("goal") or args.get("_", [None])[0]
        wf_id = args.get("id") or args.get("workflow")

    if not goal:
        return _base_response(cmd_name, "compose requires goal=<text>.", {"ok": False})

    prompt = (
        "Generate a workflow plan as a JSON list of steps. "
        "Each step must have: title, description. "
        f"Goal: {goal}"
    )

    llm_result = kernel.llm_client.complete(
        system="You generate structured workflow plans in JSON.",
        user=prompt,
        session_id=session_id,
    )

    text = llm_result.get("text", "").strip()

    try:
        steps = json.loads(text)
    except Exception:
        summary = (
            "LLM returned non-JSON. Inspect 'raw' field. "
            "You may need to edit manually."
        )
        extra = {"raw": text}
        return _base_response(cmd_name, summary, extra)

    # v0.4.6: build a human-readable steps block (dynamic step count)
    formatted_steps = []
    for idx, step in enumerate(steps, start=1):
        title = step.get("title", f"Step {idx}")
        desc = step.get("description", "")
        formatted_steps.append(F.item(idx, title, desc))

    steps_block = F.list(formatted_steps)

    # If no id is provided, keep behavior: just show the plan (but now pretty)
    if not wf_id:
        header = F.header(f"Workflow plan for: {goal} ({len(steps)} steps)")
        summary = header + steps_block
        extra = {"steps": steps}
        return _base_response(cmd_name, summary, extra)

    # v0.4.4: if id is provided, also create a real workflow in the engine.
    wf_engine = kernel.workflow_engine
    wf_id_str = str(wf_id)

    wf = wf_engine.start(
        workflow_id=wf_id_str,
        name=str(goal),
        steps=steps,
        meta={
            "source": "compose",
            "session_id": session_id,
        },
    )

    header = F.header(
        f"Created workflow '{wf.id}' for goal: {goal} ({len(wf.steps)} steps)"
    )
    summary = header + steps_block
    extra = {
        "workflow": wf.to_dict(),
        "steps_count": len(wf.steps),
    }
    return _base_response(cmd_name, summary, extra)


# ---------------------------------------------------------------------
# v0.4 — Time Rhythm Engine handlers
# ---------------------------------------------------------------------


def handle_presence(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show global time-rhythm state:
    day of week, ISO week, cycle phase(s).
    """
    info = kernel.time_rhythm_engine.presence()
    summary = F.header("Time rhythm presence snapshot.")
    return _base_response(cmd_name, summary, info)


def handle_pulse(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Diagnose workflow health:
    stalled workflows, counts by status.
    """
    wf_summaries = kernel.workflow_engine.summarize_all()
    info = kernel.time_rhythm_engine.pulse(wf_summaries)
    summary = F.header("Workflow pulse diagnostics.")
    return _base_response(cmd_name, summary, info)


def handle_align(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Suggest alignment actions based on:
    - active workflows
    - stalled workflows
    - current time phase
    v0.4 refined heuristic.
    """
    presence = kernel.time_rhythm_engine.presence()
    wf_summaries = kernel.workflow_engine.summarize_all()
    pulse = kernel.time_rhythm_engine.pulse(wf_summaries)

    suggestions: list[str] = []

    # 1) No workflows at all
    if not wf_summaries:
        suggestions.append("No workflows active. Consider starting one with 'flow' for today's focus.")
    else:
        # 2) Active workflows: highlight current steps
        active_wfs = [wf for wf in wf_summaries if wf.get("status") in ("active", "pending")]
        if active_wfs:
            top = active_wfs[0]  # simple v0.4: just pick the first
            step_title = top.get("active_step_title") or "(unnamed step)"
            suggestions.append(
                f"Focus workflow: '{top.get('name')}'. Current step: {step_title}."
            )

        # 3) All completed
        if all(wf.get("status") == "completed" for wf in wf_summaries):
            suggestions.append("All workflows are completed. Define a new one aligned to your next 30–60 day goal.")

    # 4) Stalled workflows
    for stalled in pulse.get("stalled", []):
        wid = stalled.get("id")
        suggestions.append(f"Workflow '{wid}' appears stalled. Try 'advance id={wid}' or 'halt id={wid}' to reset.")

    # 5) Week boundary hint
    if presence.get("day_of_week") == 1:  # Monday
        suggestions.append("New week detected. Review weekly goals and align workflows to this week's top 1–3 outcomes.")

    extra = {
        "presence": presence,
        "pulse": pulse,
        "suggestions": suggestions,
    }
    summary = F.header("Alignment analysis.")
    return _base_response(cmd_name, summary, extra)


# ---------------------------------------------------------------------
# v0.4.1 — Reminder Subsystem handlers
# ---------------------------------------------------------------------


def handle_remind_add(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Create a reminder.
    Usage:
        remind-add title="Check dashboard" when="2025-11-30T09:00:00Z"
    """
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
    rid = data.get("id", "?")
    when_str = data.get("when", when)
    title_str = data.get("title", title)

    summary = (
        F.header("Reminder added") +
        f"I’ll remind you at {when_str}:\n    \"{title_str}\""
    )

    # keep id in extra exactly as before
    data.setdefault("id", rid)
    return _base_response(cmd_name, summary, data)


def handle_remind_list(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    List reminders.
    """
    items = [r.to_dict() for r in kernel.reminders.list()]

    if not items:
        summary = F.header("No active reminders.")
        return _base_response(cmd_name, summary, {"reminders": []})

    formatted = []
    for r in items:
        rid = r.get("id", "?")
        when = r.get("when", "?")
        title = r.get("title", "")
        formatted.append(F.item(rid, when, f"\"{title}\""))

    summary = F.header(f"Active reminders ({len(items)})") + F.list(formatted)
    return _base_response(cmd_name, summary, {"reminders": items})


def handle_remind_update(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Update an existing reminder.
    Usage:
        remind-update id=<id> title="New title"
    """
    rid = None
    if isinstance(args, dict):
        rid = args.get("id") or args.get("_", [None])[0]
    if not rid:
        return _base_response(cmd_name, "Missing id.", {"ok": False})

    fields = {k: v for k, v in args.items() if k != "id"}
    r = kernel.reminders.update(rid, fields)
    if not r:
        return _base_response(cmd_name, f"No reminder '{rid}'.", {"ok": False})

    data = r.to_dict()
    title = data.get("title", fields.get("title", ""))
    when = data.get("when", fields.get("when", "?"))

    summary = (
        F.header("Reminder updated") +
        f"#{data.get('id', rid)} — {when}\n    \"{title}\""
    )
    return _base_response(cmd_name, summary, data)


def handle_remind_delete(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Delete a reminder.
    """
    rid = None
    if isinstance(args, dict):
        rid = args.get("id") or args.get("_", [None])[0]

    if not rid:
        return _base_response(cmd_name, "Missing id.", {"ok": False})

    ok = kernel.reminders.delete(rid)
    if not ok:
        return _base_response(cmd_name, f"No reminder '{rid}'.", {"ok": False})

    summary = (
        F.header("Reminder deleted") +
        F.item(rid, "removed")
    )
    return _base_response(cmd_name, summary, {"ok": True})

def handle_command_list(cmd_name, args, session_id, context, kernel, meta):
    custom = kernel.custom_registry.list()
    core = kernel.commands

    formatted_core = []
    formatted_custom = []

    for name, m in core.items():
        formatted_core.append(F.item(name, "core", m.get("description", "")))

    for name, m in custom.items():
        status = "enabled" if m.get("enabled", True) else "disabled"
        kind = m.get("kind", "prompt")
        formatted_custom.append(F.item(name, f"{kind} ({status})", m.get("description", "")))

    summary = (
        F.header("Commands") +
        F.subheader("Core Commands") +
        F.list(formatted_core) +
        F.subheader("Custom Commands") +
        F.list(formatted_custom)
    )

    return _base_response(cmd_name, summary, {"custom": custom, "core": core})

def handle_command_inspect(cmd_name, args, session_id, context, kernel, meta):
    name = None
    if isinstance(args, dict):
        name = args.get("name") or args.get("_", [None])[0]

    if not name:
        return _base_response(cmd_name, "Usage: command-inspect name=<cmd>", {"ok": False})

    entry = kernel.custom_registry.get(name)
    if not entry:
        return _base_response(cmd_name, f"No custom command '{name}'.", {"ok": False})

    pretty = json.dumps(entry, indent=2, ensure_ascii=False)
    summary = F.header(f"Inspect: {name}") + f"\n```json\n{pretty}\n```"
    return _base_response(cmd_name, summary, {"command": entry})

def handle_command_wizard(cmd_name, args, session_id, context, kernel, meta):
    """
    v0.5.2 — Multi-step command wizard.
    Operates as a deterministic state machine.
    Only final stage uses the LLM to generate the JSON spec.
    """
    interp = kernel.interpreter

    # Try to get wizard state either from args or from interpreter
    state = {}
    if isinstance(args, dict) and "wizard" in args:
        state = args["wizard"] or {}
    else:
        state = interp.pending_custom_commands.get(session_id, {}) or {}

    stage = state.get("stage", "start")

    # ----------------------------
    # Stage: start → ask_kind
    # ----------------------------
    if stage == "start":
        state["stage"] = "ask_kind"
        interp.pending_custom_commands[session_id] = state
        return CommandResponse(
            ok=True,
            command="command-wizard",
            summary="Do you want to create a **prompt command** or a **macro command**?",
        )

    # ----------------------------
    # Stage: ask_kind
    # ----------------------------
    if stage == "ask_kind":
        # Safe universal user text extractor for wizard
        user_text = ""
        if isinstance(args, dict):
            user_text = args.get("raw_text", "") or context.get("raw_text", "") or ""
        user = user_text.lower().strip()
        if "prompt" in user:
            state["kind"] = "prompt"
            state["stage"] = "ask_description"
        elif "macro" in user:
            state["kind"] = "macro"
            state["stage"] = "ask_chain"
        else:
            return CommandResponse(
                ok=True,
                command="command-wizard",
                summary="Please answer: **prompt** or **macro**?"
            )

        interp.pending_custom_commands[session_id] = state
        if state["kind"] == "prompt":
            return CommandResponse(
                ok=True,
                command="command-wizard",
                summary="Write a description for this command."
            )
        else:
            return CommandResponse(
                ok=True,
                command="command-wizard",
                summary="Do you want this macro to chain multiple commands? (yes/no)"
            )

    # ----------------------------
    # Stage: ask_chain
    # ----------------------------
    if stage == "ask_chain":
        # Safe universal user text extractor for wizard
        user_text = ""
        if isinstance(args, dict):
            user_text = args.get("raw_text", "") or context.get("raw_text", "") or ""
        user = user_text.lower().strip()
        if user.startswith("y"):
            state["chain_enabled"] = True
            state["stage"] = "ask_chain_items"
            interp.pending_custom_commands[session_id] = state
            return CommandResponse(
                ok=True,
                command="command-wizard",
                summary="Which commands should this macro run? (comma-separated)"
            )
        elif user.startswith("n"):
            state["chain_enabled"] = False
            state["chain_list"] = []
            state["stage"] = "ask_module"
            interp.pending_custom_commands[session_id] = state
            return CommandResponse(
                ok=True,
                command="command-wizard",
                summary="Link this command to a module? If yes, type module name; otherwise type 'no'."
            )
        else:
            return CommandResponse(
                ok=True,
                command="command-wizard",
                summary="Please answer yes or no."
            )

    # ----------------------------
    # Stage: ask_chain_items
    # ----------------------------
    if stage == "ask_chain_items":
        user_text = ""
        if isinstance(args, dict):
            user_text = args.get("raw_text", "") or context.get("raw_text", "") or ""
        items = [c.strip() for c in user_text.split(",") if c.strip()]
        state["chain_list"] = items
        state["stage"] = "ask_module"
        interp.pending_custom_commands[session_id] = state
        return CommandResponse(
            ok=True,
            command="command-wizard",
            summary="Link this command to a module? If yes, type module name; otherwise type 'no'."
        )

    # ----------------------------
    # Stage: ask_module
    # ----------------------------
    if stage == "ask_module":
        # Safe universal user text extractor for wizard
        user_text = ""
        if isinstance(args, dict):
            user_text = args.get("raw_text", "") or context.get("raw_text", "") or ""
        user = user_text.lower().strip()
        if user == "no":
            state["linked_module"] = None
        else:
            state["linked_module"] = user

        state["stage"] = "ask_description"
        interp.pending_custom_commands[session_id] = state
        return CommandResponse(
            ok=True,
            command="command-wizard",
            summary="Write a short description for this command."
        )

    # ----------------------------
    # Stage: ask_description
    # ----------------------------
    if stage == "ask_description":
        user_text = ""
        if isinstance(args, dict):
            user_text = args.get("raw_text", "") or context.get("raw_text", "") or ""
        state["description"] = user_text.strip()
        state["stage"] = "final"
        interp.pending_custom_commands[session_id] = state

        return CommandResponse(
            ok=True,
            command="command-wizard",
            summary="Great. Generating full command spec..."
        )


    # ----------------------------
    # Stage: final — LLM call
    # ----------------------------
    if stage == "final":
        # Build natural-language prompt for the LLM
        prompt = f"""
Please generate a JSON spec for a NovaOS command with the following attributes:

name: {state.get("name")}
kind: {state.get("kind")}
chain_enabled: {state.get("chain_enabled")}
chain_list: {state.get("chain_list")}
linked_module: {state.get("linked_module")}
description: {state.get("description")}

Return ONLY valid JSON.
        """

        llm_output = kernel.llm_client.chat(
            system_prompt="Generate JSON for a NovaOS command.",
            messages=[{"role": "user", "content": prompt}],
            model="gpt-5.1"
        )

        import json
        try:
            spec = json.loads(llm_output)
        except Exception as e:
            return CommandResponse(
                ok=False,
                command="command-wizard",
                summary=f"LLM JSON parse error: {e}\nRaw:\n{llm_output}"
            )

        # Ensure the spec has a usable command name
        import re

        name = spec.get("name") or state.get("name")

        if not name:
            # Derive a simple slug from the description
            desc = (state.get("description") or "").strip()
            if not desc:
                base = "custom macro"
            else:
                base = desc.lower()

            # Turn "this is a test macro" -> "this-is-a-test-macro"
            slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
            if not slug:
                slug = "custom-command"

            name = slug

        # Write the resolved name back into the spec
        spec["name"] = name

        # Save to registry using existing CustomCommandRegistry API
        kernel.custom_registry.add(name, spec)

        # Cleanup
        if session_id in interp.pending_custom_commands:
            del interp.pending_custom_commands[session_id]

        return CommandResponse(
            ok=True,
            command="command-wizard",
            summary=f"Custom command **{spec.get('name')}** created successfully!"
        )

def handle_command_add(cmd_name, args, session_id, context, kernel, meta):
    """
    Add a new custom command.
    Required: name, kind, prompt_template.
    'args' must contain the full metadata (already produced by the interpreter).
    """
    if not isinstance(args, dict):
        return _base_response(cmd_name, "command-add requires JSON metadata.", {"ok": False})

    name = args.get("name")
    if not name:
        return _base_response(cmd_name, "Missing required field: name", {"ok": False})

    kernel.custom_registry.add(name, args)

    summary = F.header("Custom Command Added") + f"'{name}' created."
    return _base_response(cmd_name, summary, args)

def handle_command_remove(cmd_name, args, session_id, context, kernel, meta):
    name = None
    if isinstance(args, dict):
        name = args.get("name") or args.get("_", [None])[0]

    if not name:
        return _base_response(cmd_name, "Usage: command-remove name=<cmd>", {"ok": False})

    ok = kernel.custom_registry.remove(name)
    if not ok:
        return _base_response(cmd_name, f"No such custom command '{name}'.", {"ok": False})

    summary = F.header("Custom Command Removed") + f"'{name}' removed."
    return _base_response(cmd_name, summary, {"ok": True})

def handle_command_toggle(cmd_name, args, session_id, context, kernel, meta):
    name = None
    if isinstance(args, dict):
        name = args.get("name") or args.get("_", [None])[0]

    if not name:
        return _base_response(cmd_name, "Usage: command-toggle name=<cmd>", {"ok": False})

    ok = kernel.custom_registry.toggle(name)
    if not ok:
        return _base_response(cmd_name, f"No such custom command '{name}'.", {"ok": False})

    status = "enabled" if kernel.custom_registry.get(name).get("enabled", True) else "disabled"
    summary = F.header("Custom Command Toggled") + f"'{name}' → {status}"
    return _base_response(cmd_name, summary, {"name": name, "status": status})

# ---------------------------------------------------------------------
# v0.5.2 — Macro Command Executor
# ---------------------------------------------------------------------

def handle_macro(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Execute a macro command that chains multiple syscommands together.

    Expected metadata schema in commands_custom.json:
    {
        "name": "nova morning routine",
        "kind": "macro",
        "steps": [
            {"command": "setenv", "args": {"mode": "deep_work"}},
            {"command": "nova start cyber"},
            {"command": "nova meals"},
            ...
        ]
    }

    Behavior:
    - Iterate through each step
    - Build a synthetic CommandRequest
    - Route through the syscommand router
    - Collect summaries
    - Return one aggregated summary
    """

    steps = meta.get("steps") or args.get("steps")
    if not steps or not isinstance(steps, list):
        return _base_response(
            cmd_name,
            f"Macro '{cmd_name}' has no steps defined.",
            {"ok": False}
        )

    router = kernel.router  # safe: NovaKernel stores router reference
    results = []
    failures = 0

    for idx, step in enumerate(steps, start=1):
        # Normalize step
        if isinstance(step, str):
            step_cmd = step
            step_args = {}
        elif isinstance(step, dict):
            step_cmd = step.get("command")
            step_args = step.get("args") or {}
        else:
            results.append(f"[Step {idx}] Invalid step format.")
            failures += 1
            continue

        if not step_cmd:
            results.append(f"[Step {idx}] Missing command name.")
            failures += 1
            continue

        # Build synthetic CommandRequest
        from .command_types import CommandRequest, CommandResponse
        synthetic = CommandRequest(
            cmd_name=step_cmd,
            args=step_args if isinstance(step_args, dict) else {},
            session_id=session_id,
            raw_text=f"{cmd_name} → {step_cmd}",
            meta=None,
        )

        # Execute via router
        resp = router.route(synthetic, kernel)
        ok = resp.ok
        results.append(
            f"[{idx}] {step_cmd}: "
            + ("OK" if ok else f"ERROR: {resp.summary}")
        )

        if not ok:
            failures += 1

    # Build final summary
    body = "\n".join(results)
    status = "completed" if failures == 0 else f"completed with {failures} error(s)"
    final = F.header(f"Macro '{cmd_name}' {status}") + body

    return _base_response(cmd_name, final, {"steps": len(steps), "failures": failures})

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

    # v0.4 Workflow
    "handle_flow": handle_flow,
    "handle_advance": handle_advance,
    "handle_halt": handle_halt,
    "handle_compose": handle_compose,

    # v0.4 Time Rhythm
    "handle_presence": handle_presence,
    "handle_pulse": handle_pulse,
    "handle_align": handle_align,

    # v0.4.1 Reminders
    "handle_remind_add": handle_remind_add,
    "handle_remind_list": handle_remind_list,
    "handle_remind_update": handle_remind_update,
    "handle_remind_delete": handle_remind_delete,

    # v0.4.4 Workflow delete
    "handle_workflow_delete": handle_workflow_delete,
    "handle_workflow_list": handle_workflow_list,
    # v0.5 Custom Commands
    "handle_prompt_command": handle_prompt_command,
    "handle_command_add": handle_command_add,
    "handle_command_list": handle_command_list,
    "handle_command_inspect": handle_command_inspect,
    "handle_command_remove": handle_command_remove,
    "handle_command_toggle": handle_command_toggle,
        # v0.5 Interpretation
    "handle_interpret": handle_interpret,
    "handle_derive": handle_derive,
    "handle_synthesize": handle_synthesize,
    "handle_frame": handle_frame,
    "handle_forecast": handle_forecast,
    "handle_command_wizard": handle_command_wizard,
    # v0.5.1 Environment / Mode
    "handle_env": handle_env,
    "handle_setenv": handle_setenv,
    "handle_mode": handle_mode,
    "handle_macro": handle_macro,


}
