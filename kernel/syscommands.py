# kernel/syscommands.py
"""
v0.8.0 — NovaOS Life RPG Syscommand Handlers

Updated for Quest Engine integration.
Legacy workflow commands (flow, advance, halt, etc.) are REMOVED.
"""
import json
from typing import Dict, Any, Callable

from .command_types import CommandResponse
from .formatting import OutputFormatter as F

# v0.8.0: Quest Engine handlers
try:
    from .quest_handlers import get_quest_handlers
    _HAS_QUEST_ENGINE = True
except ImportError:
    _HAS_QUEST_ENGINE = False
    def get_quest_handlers():
        return {}

# v0.8.0: Inbox handlers
try:
    from .inbox_handlers import get_inbox_handlers
    _HAS_INBOX = True
except ImportError:
    _HAS_INBOX = False
    def get_inbox_handlers():
        return {}

# v0.8.0: Player Profile handlers
try:
    from .player_profile import get_player_profile_handlers
    _HAS_PLAYER_PROFILE = True
except ImportError:
    _HAS_PLAYER_PROFILE = False
    def get_player_profile_handlers():
        return {}

# v0.8.0: Module Manager handlers (regions/world map)
try:
    from .module_manager import get_module_handlers
    _HAS_MODULE_MANAGER = True
except ImportError:
    _HAS_MODULE_MANAGER = False
    def get_module_handlers():
        return {}

# v0.8.0: Assistant Mode handlers (story vs utility)
try:
    from .assistant_mode import get_assistant_mode_handlers
    _HAS_ASSISTANT_MODE = True
except ImportError:
    _HAS_ASSISTANT_MODE = False
    def get_assistant_mode_handlers():
        return {}

# v0.8.0: Strategist handlers (analyze, route, insight)
try:
    from .strategist import get_strategist_handlers
    _HAS_STRATEGIST = True
except ImportError:
    _HAS_STRATEGIST = False
    def get_strategist_handlers():
        return {}

# v0.8.0: Time Rhythm handlers (presence, pulse, align, weekly-review)
try:
    from .time_rhythm import get_time_rhythm_handlers
    _HAS_TIME_RHYTHM = True
except ImportError:
    _HAS_TIME_RHYTHM = False
    def get_time_rhythm_handlers():
        return {}

# v0.7: Working Memory Engine integration
try:
    from .nova_wm import wm_clear
    _HAS_WORKING_MEMORY = True
except ImportError:
    _HAS_WORKING_MEMORY = False
    def wm_clear(session_id: str) -> None:
        pass  # No-op if WM not installed

# v0.7.2: Behavior Layer integration
try:
    from .nova_wm_behavior import behavior_clear, get_behavior_engine
    _HAS_BEHAVIOR_LAYER = True
except ImportError:
    _HAS_BEHAVIOR_LAYER = False
    def behavior_clear(session_id: str) -> None:
        pass  # No-op if Behavior Layer not installed
    def get_behavior_engine(session_id: str):
        return None

KernelResponse = CommandResponse


def _llm_with_policy(
    *,
    kernel,
    session_id: str,
    system: str,
    user: str,
    meta: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    v0.5.3 - Centralized LLM call with PolicyEngine hooks and ModelRouter.

    - Model selection via kernel.get_model() based on command and input
    - Pre-LLM: policy.pre_llm(user_text, meta) → sanitized user text.
    - Post-LLM: policy.post_llm(output_text, meta) → normalized text.
    - Returns a dict with at least {"text": <final_text>, "model": <model_id>}.
    """
    policy = getattr(kernel, "policy_engine", None)
    meta_full: Dict[str, Any] = dict(meta or {})
    meta_full.setdefault("session_id", session_id)
    meta_full.setdefault("source", meta_full.get("command", "syscommand"))

    # ---- v0.5.3: Model routing ----
    command = meta_full.get("command", "default")
    think_mode = meta_full.get("think", False)
    explicit_model = meta_full.get("model")
    
    model = None
    if hasattr(kernel, "get_model"):
        model = kernel.get_model(
            command=command,
            input_text=user,
            think=think_mode,
            explicit_model=explicit_model,
        )
    
    # v0.6.5: DEBUG LOGGING - print directly to see what's happening
    print(f"[_llm_with_policy] command={command} model={model}")

    # ---- Pre-LLM on the user text only ----
    safe_user = user
    if policy and hasattr(policy, "pre_llm"):
        try:
            safe_user = policy.pre_llm(user, meta_full)
        except Exception:
            # Fail-safe: ignore policy errors, continue with original user text
            safe_user = user

    # ---- Core LLM call (with routed model) ----
    llm_kwargs = {}
    if model:
        llm_kwargs["model"] = model
        
    result = kernel.llm_client.complete(
        system=system,
        user=safe_user,
        session_id=session_id,
        **llm_kwargs,
    )

    raw_text = result.get("text", "")

    # ---- Post-LLM normalization on the output text ----
    final_text = raw_text
    if policy and hasattr(policy, "post_llm"):
        try:
            final_text = policy.post_llm(raw_text, meta_full)
        except Exception:
            final_text = raw_text

    return {"text": final_text, "model": model}

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

    # -------------------------------------------------------------------------
    # v0.5.1 — Post-Actions Executor
    # -------------------------------------------------------------------------
    # Schema:
    # {
    #   "type": "syscommand",
    #   "command": "store",
    #   "args_mode": "pass_input" | "pass_result" | "pass_both",
    #   "args": { "type": "episodic", "tags": ["reflection"] },
    #   "silent": false
    # }
    # -------------------------------------------------------------------------
    post_action_summaries: list[str] = []
    post_actions = meta.get("post_actions") or []

    for idx, action in enumerate(post_actions):
        if not isinstance(action, dict):
            continue

        action_type = action.get("type")
        if action_type != "syscommand":
            # Future: support "workflow", "module" types
            continue

        target_cmd = action.get("command")
        if not target_cmd:
            continue

        args_mode = action.get("args_mode", "pass_result")
        base_args = dict(action.get("args") or {})
        silent = action.get("silent", False)

        # Build payload based on args_mode
        user_input = args.get("full_input", "")
        llm_output = output_text.strip()

        if args_mode == "pass_input":
            base_args.setdefault("payload", user_input)
        elif args_mode == "pass_result":
            base_args.setdefault("payload", llm_output)
        elif args_mode == "pass_both":
            base_args.setdefault("input", user_input)
            base_args.setdefault("result", llm_output)
            # For commands like 'store', also set payload to combined
            if "payload" not in base_args:
                base_args["payload"] = f"Input: {user_input}\nResult: {llm_output}"

        # Build synthetic CommandRequest
        from .command_types import CommandRequest as CR
        synthetic_request = CR(
            cmd_name=target_cmd,
            args=base_args,
            session_id=session_id,
            raw_text=f"[post-action:{idx}] {target_cmd}",
            meta=None,
        )

        # Route through kernel's router
        try:
            result = kernel.router.route(synthetic_request, kernel)
            if not silent:
                status = "OK" if result.ok else "FAIL"
                post_action_summaries.append(f"  → [{target_cmd}] {status}: {result.summary[:80]}")
        except Exception as e:
            if not silent:
                post_action_summaries.append(f"  → [{target_cmd}] ERROR: {e}")

    # -------------------------------------------------------------------------
    # Build final summary
    # -------------------------------------------------------------------------
    summary_parts = [
        F.header(f"Custom command: {cmd_name}"),
        output_text.strip(),
    ]

    if post_action_summaries:
        summary_parts.append("\n" + F.subheader("Post-Actions"))
        summary_parts.extend(post_action_summaries)

    summary = "\n".join(summary_parts)

    return _base_response(cmd_name, summary, {"result": output_text, "post_actions_run": len(post_action_summaries)})

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


def handle_wm_debug(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.1: Debug command to show current Working Memory state.
    
    Shows entities with gender hints and pronoun group resolution.
    
    v0.7.9: Added optional module=<n> filter.
    
    Usage: 
        #wm-debug
        #wm-debug module=business
    """
    try:
        from .nova_wm import get_wm
        wm = get_wm(session_id)
        
        # v0.7.9: Get module filter
        module_filter = None
        if isinstance(args, dict):
            module_filter = args.get("module")
        
        state = wm.to_dict()
        
        lines = [
            F.header("Working Memory State"),
            F.key_value("Session", state['session_id']),
            F.key_value("Turn count", state['turn_count']),
            F.key_value("Emotional tone", state['emotional_tone']),
        ]
        
        # v0.7.9: Show module info
        current_mod = getattr(wm, 'current_module', None)
        if current_mod:
            lines.append(F.key_value("Current Module", current_mod))
        if module_filter:
            lines.append(F.key_value("Scope", f"module={module_filter} (includes global)"))
        lines.append("")
        
        # Entities with gender hints (optionally filtered by module)
        if state['entities']:
            lines.append(F.subheader("Entities"))
            for eid, entity in state['entities'].items():
                # v0.7.9: Filter by module if specified
                entity_module = entity.get('module')
                if module_filter:
                    # Include if matches filter OR is global (None)
                    if entity_module != module_filter and entity_module is not None:
                        continue
                
                desc = f" ({entity.get('description')})" if entity.get('description') else ""
                gender = f" [{entity.get('gender_hint', 'neutral')}]" if entity.get('type') == 'person' else ""
                mod_tag = f" @{entity_module}" if entity_module else ""
                lines.append(f"  • {entity['name']} [{entity['type']}]{gender}{mod_tag}{desc}")
            lines.append("")
        
        # v0.7.1: Pronoun Groups (gender-aware)
        pronoun_groups = state.get('pronoun_groups', {})
        if pronoun_groups:
            lines.append(F.subheader("Pronoun Resolution"))
            for group_name, group in pronoun_groups.items():
                best_match = group.get('best_match')
                if best_match:
                    pronouns = "/".join(sorted(group.get('pronouns', [])))
                    lines.append(f"  • {pronouns} → {best_match}")
            lines.append("")
        
        # Active topic
        if state.get('active_topic_id'):
            topic = state['topics'].get(state['active_topic_id'], {})
            topic_mod = topic.get('module', '')
            mod_str = f" @{topic_mod}" if topic_mod else ""
            lines.append(F.key_value("Active Topic", f"{topic.get('name', 'unknown')}{mod_str}"))
            lines.append("")
        
        # Goals (filtered by module if specified)
        if state.get('goals'):
            lines.append(F.subheader("Active Goals"))
            for gid, goal in state['goals'].items():
                if goal.get('status') == 'active':
                    goal_mod = goal.get('module')
                    if module_filter:
                        if goal_mod != module_filter and goal_mod is not None:
                            continue
                    mod_tag = f" @{goal_mod}" if goal_mod else ""
                    lines.append(f"  • {goal.get('description', 'unknown')[:60]}{mod_tag}")
            lines.append("")
        
        lines.append(F.key_value("Turn history", f"{state['turn_history_count']} turns stored"))
        
        return _base_response(cmd_name, "\n".join(lines), {"wm_state": state})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error reading Working Memory: {e}", {"ok": False})


def handle_behavior_debug(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.2: Debug command to show current Behavior Layer state.
    
    Shows open questions, goals, user state, and topic transitions.
    
    Usage: #behavior-debug
    """
    if not _HAS_BEHAVIOR_LAYER:
        return _base_response(cmd_name, "Behavior Layer not installed.", {"ok": False})
    
    try:
        engine = get_behavior_engine(session_id)
        if engine is None:
            return _base_response(cmd_name, "Behavior Engine not initialized.", {"ok": False})
        
        state = engine.to_dict()
        
        lines = [
            F.header("Behavior Layer State"),
            F.key_value("Session", state['session_id']),
            F.key_value("Turn count", state['turn_count']),
            "",
        ]
        
        # Open Questions
        open_qs = [q for q in state['open_questions'] if not q.get('answered')]
        if open_qs:
            lines.append(F.subheader("Open Questions (Awaiting Response)"))
            for q in open_qs:
                text = q.get('text', '')[:60]
                lines.append(f"  • \"{text}...\"" if len(q.get('text', '')) > 60 else f"  • \"{text}\"")
            lines.append("")
        
        # Active Goal
        if state.get('active_goal_id') and state.get('goals'):
            goal = state['goals'].get(state['active_goal_id'], {})
            lines.append(F.subheader("Active Goal"))
            lines.append(f"  Type: {goal.get('type', 'unknown')}")
            lines.append(f"  Description: {goal.get('description', 'none')[:70]}")
            lines.append("")
        
        # Goal Stack
        if state.get('goal_stack'):
            lines.append(F.key_value("Goal Stack Depth", len(state['goal_stack'])))
            lines.append("")
        
        # User State
        user_state = state.get('user_state', {})
        if user_state:
            lines.append(F.subheader("User State"))
            lines.append(f"  Clarity: {user_state.get('clarity_level', 0.5):.1%}")
            lines.append(f"  Decisiveness: {user_state.get('decisiveness', 0.5):.1%}")
            lines.append(f"  Stress: {user_state.get('stress_level', 0):.1%}")
            lines.append(f"  Engagement: {user_state.get('engagement', 0.5):.1%}")
            lines.append(f"  Urgency: {user_state.get('urgency', 0):.1%}")
            if user_state.get('signals'):
                lines.append(f"  Signals: {', '.join(user_state['signals'])}")
            lines.append("")
        
        # Topic Transitions
        if state.get('topic_transitions'):
            lines.append(F.subheader("Recent Topic Transitions"))
            for t in state['topic_transitions'][-3:]:
                lines.append(f"  • [{t.get('trigger', '?')}] '{t.get('from', '?')}' → '{t.get('to', '?')}'")
            lines.append("")
        
        # Thread Summary
        summary = state.get('thread_summary', {})
        if summary.get('topic') or summary.get('participants'):
            lines.append(F.subheader("Thread Summary"))
            if summary.get('topic'):
                lines.append(f"  Topic: {summary['topic']}")
            if summary.get('participants'):
                lines.append(f"  Participants: {', '.join(summary['participants'])}")
            if summary.get('unresolved_questions'):
                lines.append(f"  Unresolved: {len(summary['unresolved_questions'])} questions")
            lines.append("")
        
        return _base_response(cmd_name, "\n".join(lines), {"behavior_state": state})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error reading Behavior Layer: {e}", {"ok": False})


# ---------------------------------------------------------------------
# v0.7.3 — New WM/Behavior Commands
# ---------------------------------------------------------------------

def handle_wm_clear_cmd(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.3: Clear all working memory for this session.
    
    Usage: #wm-clear
    """
    try:
        wm_clear(session_id)
        behavior_clear(session_id)
        return _base_response(cmd_name, "Working memory and behavior state cleared for this session.")
    except Exception as e:
        return _base_response(cmd_name, f"Error clearing working memory: {e}", {"ok": False})


def handle_wm_clear_topic(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.3: Clear only the current topic, keep entities and pronouns.
    
    Usage: #wm-clear-topic
    """
    try:
        from .nova_wm import wm_clear_topic
        message = wm_clear_topic(session_id)
        return _base_response(cmd_name, message)
    except ImportError:
        return _base_response(cmd_name, "WM topic clearing not available.", {"ok": False})
    except Exception as e:
        return _base_response(cmd_name, f"Error clearing topic: {e}", {"ok": False})


def handle_behavior_mode(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.3: Get or set behavior mode.
    
    Usage:
        #behavior-mode           → show current mode
        #behavior-mode mode=minimal
        #behavior-mode mode=debug
        #behavior-mode mode=normal
    """
    try:
        from .nova_wm_behavior import behavior_get_mode, behavior_set_mode
        
        # Check if setting a mode
        target_mode = None
        if isinstance(args, dict):
            target_mode = args.get("mode")
            if not target_mode and "_" in args and args["_"]:
                target_mode = args["_"][0]
        
        if target_mode:
            # Set mode
            success = behavior_set_mode(session_id, target_mode)
            if success:
                return _base_response(cmd_name, f"Behavior mode set to: {target_mode.lower()}")
            else:
                return _base_response(
                    cmd_name, 
                    f"Invalid mode '{target_mode}'. Valid modes: normal, minimal, debug",
                    {"ok": False}
                )
        else:
            # Show current mode
            current_mode = behavior_get_mode(session_id)
            lines = [
                F.header("Behavior Mode"),
                F.key_value("Current mode", current_mode),
                "",
                "Available modes:",
                "  • normal — Full conversational continuity (default)",
                "  • minimal — Fewer follow-up questions, less hand-holding",
                "  • debug — More explicit about goals/state in responses",
                "",
                "Set with: #behavior-mode mode=<mode>",
            ]
            return _base_response(cmd_name, "\n".join(lines))
    
    except ImportError:
        return _base_response(cmd_name, "Behavior Layer not available.", {"ok": False})
    except Exception as e:
        return _base_response(cmd_name, f"Error with behavior mode: {e}", {"ok": False})


def handle_wm_snapshot(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.6: Save current topic + participants as an episodic memory.
    
    Usage:
        #wm-snapshot
        #wm-snapshot topic="project with Steven"
        #wm-snapshot label="important decision"
        #wm-snapshot module=cyber
    """
    try:
        from .nova_wm import get_wm, wm_create_snapshot, EntityType
        
        # Get args
        label = None
        module = None
        if isinstance(args, dict):
            label = args.get("topic") or args.get("label")
            module = args.get("module")
            if not label and "_" in args and args["_"]:
                label = " ".join(args["_"])
        
        wm = get_wm(session_id)
        
        # Check if MemoryManager available
        if not hasattr(kernel, 'memory_manager') or not kernel.memory_manager:
            # Return preview without persisting
            snapshot = wm_create_snapshot(session_id, label, module)
            lines = [
                F.header("WM Snapshot (Preview)"),
                "",
                f"Topic: {snapshot['payload'].get('topic', 'unknown')}",
            ]
            participants = snapshot['payload'].get('participants', [])
            if participants:
                lines.append(f"Participants: {', '.join(p['name'] for p in participants[:5])}")
            lines.append(f"Tags: {', '.join(snapshot['tags'])}")
            lines.append("")
            lines.append("Note: MemoryManager not available, snapshot not persisted.")
            return _base_response(cmd_name, "\n".join(lines), {"snapshot": snapshot})
        
        # Create snapshot payload
        snapshot = wm_create_snapshot(session_id, label, module)
        
        # Store in memory
        memory_id = kernel.memory_manager.store(
            type=snapshot["type"],
            payload=snapshot["payload"],
            tags=snapshot["tags"],
        )
        
        # Build response
        lines = [
            F.header("WM Snapshot Saved"),
            "",
            f"Memory ID: #{memory_id}",
            f"Topic: {snapshot['payload'].get('topic', 'unknown')}",
        ]
        
        participants = snapshot['payload'].get('participants', [])
        if participants:
            lines.append(f"Participants: {', '.join(p['name'] for p in participants[:5])}")
        
        groups = snapshot['payload'].get('groups', [])
        if groups:
            lines.append(f"Groups: {', '.join(g['name'] for g in groups[:3])}")
        
        lines.append(f"Turns captured: {wm.turn_count}")
        lines.append(f"Tags: {', '.join(snapshot['tags'][:5])}")
        lines.append("")
        lines.append("Snapshot stored to episodic memory.")
        
        return _base_response(cmd_name, "\n".join(lines), {"memory_id": memory_id})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error creating snapshot: {e}", {"ok": False})


def handle_wm_topics(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.3: List active/recent conversation topics.
    
    Usage: #wm-topics
    """
    try:
        from .nova_wm import wm_list_topics
        
        topics = wm_list_topics(session_id)
        
        if not topics:
            return _base_response(cmd_name, "No topics in working memory yet.")
        
        lines = [
            F.header("Conversation Topics"),
            "",
        ]
        
        for i, topic in enumerate(topics, 1):
            active_marker = " ← ACTIVE" if topic.get("is_active") else ""
            status = topic.get("status", "unknown")
            lines.append(f"{i}) {topic['id']}: {topic['name']} [{status}]{active_marker}")
        
        lines.append("")
        lines.append("Switch with: #wm-switch topic=<id or name>")
        
        return _base_response(cmd_name, "\n".join(lines), {"topics": topics})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error listing topics: {e}", {"ok": False})


def handle_wm_switch(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.3: Switch active topic by ID or name.
    
    Usage:
        #wm-switch topic=project
        #wm-switch topic=t1
    """
    try:
        from .nova_wm import wm_switch_topic, get_wm
        
        # Get topic identifier from args
        topic_id = None
        if isinstance(args, dict):
            topic_id = args.get("topic") or args.get("id") or args.get("name")
            if not topic_id and "_" in args and args["_"]:
                topic_id = args["_"][0]
        
        if not topic_id:
            return _base_response(
                cmd_name, 
                "Usage: #wm-switch topic=<id or name>\n\nUse #wm-topics to see available topics.",
                {"ok": False}
            )
        
        result = wm_switch_topic(session_id, topic_id)
        
        if result:
            wm = get_wm(session_id)
            topic = wm.topics.get(result, {})
            topic_name = topic.name if hasattr(topic, 'name') else result
            return _base_response(cmd_name, f"Switched to topic: {topic_name}")
        else:
            return _base_response(
                cmd_name, 
                f"Topic '{topic_id}' not found. Use #wm-topics to see available topics.",
                {"ok": False}
            )
    
    except Exception as e:
        return _base_response(cmd_name, f"Error switching topic: {e}", {"ok": False})


# ---------------------------------------------------------------------
# v0.7.3 — Episodic Memory Bridge (Option B)
# ---------------------------------------------------------------------

def handle_wm_restore(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.3: Restore WM from a saved episodic memory.
    
    Usage:
        #wm-restore id=5
        #wm-restore id=5 force=yes
        #wm-restore id=5 mode=merge
    """
    try:
        from .nova_wm import get_wm
        from .nova_wm_behavior import get_behavior_engine
        from .nova_wm_episodic import episodic_restore, RehydrationMode, is_episodic_enabled
        
        if not is_episodic_enabled():
            return _base_response(cmd_name, "Episodic memory is disabled.", {"ok": False})
        
        # Get args
        memory_id = None
        force = False
        mode = RehydrationMode.MERGE
        
        if isinstance(args, dict):
            memory_id = args.get("id")
            if not memory_id and "_" in args and args["_"]:
                try:
                    memory_id = int(args["_"][0])
                except:
                    memory_id = args["_"][0]
            
            force = args.get("force", "").lower() in ("yes", "true", "1")
            
            mode_str = args.get("mode", "merge").lower()
            if mode_str == "full":
                mode = RehydrationMode.FULL
            elif mode_str == "context":
                mode = RehydrationMode.CONTEXT_ONLY
        
        if not memory_id:
            return _base_response(
                cmd_name,
                "Usage: #wm-restore id=<memory_id>\n\nUse #episodic-list to see available snapshots.",
                {"ok": False}
            )
        
        try:
            memory_id = int(memory_id)
        except:
            return _base_response(cmd_name, f"Invalid memory ID: {memory_id}", {"ok": False})
        
        # Check MemoryManager
        if not hasattr(kernel, 'memory_manager') or not kernel.memory_manager:
            return _base_response(cmd_name, "MemoryManager not available.", {"ok": False})
        
        # Get WM and Behavior
        wm = get_wm(session_id)
        try:
            behavior = get_behavior_engine(session_id)
        except:
            behavior = None
        
        # Perform restore
        success, message = episodic_restore(
            session_id=session_id,
            memory_id=memory_id,
            memory_manager=kernel.memory_manager,
            wm=wm,
            behavior_engine=behavior,
            mode=mode,
            force=force,
        )
        
        if success:
            lines = [
                F.header("WM Restored"),
                "",
                message,
                "",
                f"Mode: {mode.value}",
                f"Entities now: {len(wm.entities)}",
            ]
            return _base_response(cmd_name, "\n".join(lines))
        else:
            return _base_response(cmd_name, message, {"ok": False})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error restoring: {e}", {"ok": False})


def handle_wm_mode(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.3: Enable or disable Working Memory.
    
    Usage:
        #wm-mode           → show current status
        #wm-mode on
        #wm-mode off
    """
    try:
        from system.wm_behavior_config import (
            is_wm_enabled, 
            is_behavior_enabled,
            _config_manager,
        )
        
        # Get mode from args
        mode = None
        if isinstance(args, dict):
            mode = args.get("mode") or args.get("state")
            if not mode and "_" in args and args["_"]:
                mode = args["_"][0]
        
        if mode:
            mode_lower = mode.lower()
            if mode_lower in ("on", "true", "1", "enable", "enabled"):
                _config_manager.set_wm_enabled(session_id, True)
                return _base_response(cmd_name, "Working Memory enabled.")
            elif mode_lower in ("off", "false", "0", "disable", "disabled"):
                _config_manager.set_wm_enabled(session_id, False)
                return _base_response(cmd_name, "Working Memory disabled.")
            else:
                return _base_response(
                    cmd_name,
                    f"Invalid mode '{mode}'. Use: on, off",
                    {"ok": False}
                )
        else:
            # Show status
            wm_on = is_wm_enabled(session_id)
            bh_on = is_behavior_enabled(session_id)
            
            lines = [
                F.header("WM/Behavior Status"),
                "",
                F.key_value("Working Memory", "enabled" if wm_on else "disabled"),
                F.key_value("Behavior Layer", "enabled" if bh_on else "disabled"),
                "",
                "Set with: #wm-mode on/off",
            ]
            return _base_response(cmd_name, "\n".join(lines))
    
    except ImportError:
        return _base_response(cmd_name, "WM config not available.", {"ok": False})
    except Exception as e:
        return _base_response(cmd_name, f"Error: {e}", {"ok": False})


def handle_episodic_list(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.3: List saved episodic snapshots.
    
    Usage:
        #episodic-list
        #episodic-list module=cyber
        #episodic-list limit=20
    """
    try:
        from .nova_wm_episodic import episodic_list, is_episodic_enabled
        
        if not is_episodic_enabled():
            return _base_response(cmd_name, "Episodic memory is disabled.", {"ok": False})
        
        if not hasattr(kernel, 'memory_manager') or not kernel.memory_manager:
            return _base_response(cmd_name, "MemoryManager not available.", {"ok": False})
        
        # Get args
        module = None
        limit = 10
        if isinstance(args, dict):
            module = args.get("module")
            try:
                limit = int(args.get("limit", 10))
            except:
                pass
        
        # List snapshots
        snapshots = episodic_list(kernel.memory_manager, module, limit)
        
        if not snapshots:
            return _base_response(cmd_name, "No episodic snapshots found.")
        
        lines = [
            F.header("Episodic Snapshots"),
            "",
        ]
        
        for snap in snapshots:
            participants = snap.get("participants", [])
            participant_str = ", ".join(p.split(" (")[0] for p in participants[:3])
            module_str = f" [{snap.get('module')}]" if snap.get('module') else ""
            
            lines.append(f"#{snap['id']}: {snap['topic']}{module_str}")
            if participant_str:
                lines.append(f"    Participants: {participant_str}")
            if snap.get('timestamp'):
                lines.append(f"    Saved: {snap['timestamp'][:19]}")
            lines.append("")
        
        lines.append("Restore with: #wm-restore id=<id>")
        
        return _base_response(cmd_name, "\n".join(lines), {"snapshots": snapshots})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error: {e}", {"ok": False})


def handle_episodic_debug(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.3: Show episodic memory debug info.
    
    Usage: #episodic-debug
    """
    try:
        from .nova_wm_episodic import episodic_debug, is_episodic_enabled
        
        debug_info = episodic_debug(session_id)
        
        lines = [
            F.header("Episodic Memory Debug"),
            "",
            F.key_value("Enabled", "yes" if debug_info['enabled'] else "no"),
            F.key_value("Auto-rehydrate", "yes" if debug_info['auto_rehydrate'] else "no"),
            F.key_value("Max age (days)", debug_info['max_age_days']),
            "",
        ]
        
        if debug_info.get('saved_snapshots'):
            lines.append(F.subheader("Saved This Session"))
            for topic, mem_id in debug_info['saved_snapshots'].items():
                lines.append(f"  • '{topic}' → #{mem_id}")
            lines.append("")
        
        if debug_info.get('restored_from'):
            lines.append(F.key_value("Restored from", f"#{debug_info['restored_from']}"))
        
        if debug_info.get('rehydrated_modules'):
            lines.append(F.key_value("Rehydrated modules", ", ".join(debug_info['rehydrated_modules'])))
        
        lines.append(F.key_value("Context rehydrated", "yes" if debug_info['context_rehydrated'] else "no"))
        
        return _base_response(cmd_name, "\n".join(lines), {"debug": debug_info})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error: {e}", {"ok": False})


# ---------------------------------------------------------------------
# v0.7.6 — WM Persistence Layer (Option B)
# ---------------------------------------------------------------------

def handle_wm_load(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.6: Load WM snapshots from episodic memory.
    
    Usage:
        #wm-load
        #wm-load module=cyber
        #wm-load topic=project
    """
    try:
        from .nova_wm import wm_bridge_load_relevant, wm_get_snapshots_info
        
        # Get args
        module = None
        topic_filter = None
        if isinstance(args, dict):
            module = args.get("module")
            topic_filter = args.get("topic")
            if not module and not topic_filter and "_" in args and args["_"]:
                topic_filter = args["_"][0]
        
        # Check MemoryManager
        if not hasattr(kernel, 'memory_manager') or not kernel.memory_manager:
            return _base_response(cmd_name, "MemoryManager not available.", {"ok": False})
        
        # Load relevant snapshots
        results = wm_bridge_load_relevant(
            session_id=session_id,
            memory_manager=kernel.memory_manager,
            module=module,
            max_snapshots=3,
        )
        
        if not results:
            return _base_response(cmd_name, "No matching WM snapshots found in episodic memory.")
        
        lines = [
            F.header("WM Snapshots Loaded"),
            "",
        ]
        
        total_entities = 0
        total_groups = 0
        
        for result in results:
            if "error" in result:
                lines.append(f"Error: {result['error']}")
                continue
            
            topic = result.get("topic", "unknown")
            mem_id = result.get("memory_id", "?")
            entities = result.get("entities_added", [])
            groups = result.get("groups_added", [])
            conflicts = result.get("conflicts", [])
            
            lines.append(f"#{mem_id}: {topic}")
            if entities:
                lines.append(f"  Entities: {', '.join(entities[:5])}")
                total_entities += len(entities)
            if groups:
                lines.append(f"  Groups: {', '.join(groups[:3])}")
                total_groups += len(groups)
            if conflicts:
                lines.append(f"  Conflicts: {', '.join(conflicts[:3])}")
            lines.append("")
        
        lines.append(f"Total: {total_entities} entities, {total_groups} groups rehydrated.")
        
        return _base_response(cmd_name, "\n".join(lines), {"results": results})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error loading snapshots: {e}", {"ok": False})


def handle_wm_bridge(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.6: Show WM bridge/persistence status.
    
    Usage: #wm-bridge
    """
    try:
        from .nova_wm import wm_get_snapshots_info
        
        info = wm_get_snapshots_info(session_id)
        
        lines = [
            F.header("WM Persistence Bridge"),
            "",
        ]
        
        # Saved snapshots
        saved = info.get("saved", [])
        if saved:
            lines.append(F.subheader(f"Snapshots Saved This Session ({len(saved)})"))
            for label in saved[-5:]:
                lines.append(f"  • {label}")
            lines.append("")
        else:
            lines.append("No snapshots saved this session.")
            lines.append("")
        
        # Loaded snapshots
        loaded = info.get("loaded", [])
        if loaded:
            lines.append(F.subheader(f"Snapshots Loaded ({len(loaded)})"))
            for mem_id in loaded[-5:]:
                lines.append(f"  • Memory #{mem_id}")
            lines.append("")
        
        # Rehydration source
        rehydrated = info.get("rehydrated_from")
        if rehydrated:
            lines.append(F.key_value("Rehydrated from", f"#{rehydrated}"))
        
        lines.append("")
        lines.append("Commands: #wm-snapshot, #wm-load, #episodic-list")
        
        return _base_response(cmd_name, "\n".join(lines), {"info": info})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error: {e}", {"ok": False})


# ---------------------------------------------------------------------
# v0.7.7 — Group Entity Layer
# ---------------------------------------------------------------------

def handle_wm_groups(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.7: Show all group entities in working memory.
    
    Usage: #wm-groups
    """
    try:
        from .nova_wm import wm_get_all_groups
        
        groups = wm_get_all_groups(session_id)
        
        if not groups:
            return _base_response(cmd_name, "No groups in working memory.\n\nGroups are created automatically when you mention multiple people together, e.g., 'Steven and Sarah both...'")
        
        lines = [
            F.header("Group Entities"),
            "",
        ]
        
        for g in groups:
            lines.append(f"• {g['name']}")
            lines.append(f"  Members: {', '.join(g['members'])}")
            lines.append(f"  ID: {g['id']}")
            lines.append("")
        
        lines.append("Pronouns like 'they/them/their' will resolve to the most recent group.")
        
        return _base_response(cmd_name, "\n".join(lines), {"groups": groups})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error: {e}", {"ok": False})


# ---------------------------------------------------------------------
# v0.7.9 — Module-Aware Working Memory
# ---------------------------------------------------------------------

def handle_wm_status(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.9: Show comprehensive WM status including module breakdown.
    
    Usage: #wm-status
    """
    try:
        from .nova_wm import wm_get_status
        
        status = wm_get_status(session_id)
        
        lines = [
            F.header("Working Memory Status"),
            "",
            F.key_value("Session", status['session_id']),
            F.key_value("Turn count", status['turn_count']),
            "",
        ]
        
        # Current module
        current = status.get('current_module')
        if current:
            lines.append(F.key_value("Current Module", current))
        else:
            lines.append(F.key_value("Current Module", "(global)"))
        
        # Module history
        history = status.get('module_history', [])
        if history:
            lines.append(F.key_value("Module History", " → ".join(history)))
        lines.append("")
        
        # Totals
        lines.append(F.subheader("Totals"))
        lines.append(f"  Entities: {status['total_entities']}")
        lines.append(f"  Topics: {status['total_topics']}")
        lines.append(f"  Goals: {status['total_goals']}")
        lines.append(f"  Questions: {status['total_questions']}")
        lines.append(f"  Groups: {status['groups']}")
        lines.append("")
        
        # Per-module breakdown
        module_stats = status.get('module_stats', {})
        if module_stats:
            lines.append(F.subheader("Per-Module Breakdown"))
            for mod, stats in module_stats.items():
                total = stats['entities'] + stats['topics'] + stats['goals'] + stats['questions']
                if total > 0:
                    lines.append(f"  {mod}:")
                    lines.append(f"    entities={stats['entities']} topics={stats['topics']} goals={stats['goals']} questions={stats['questions']}")
            lines.append("")
        
        # Snapshots
        if status['snapshots_saved'] > 0 or status['snapshots_loaded'] > 0:
            lines.append(F.subheader("Persistence"))
            lines.append(f"  Snapshots saved: {status['snapshots_saved']}")
            lines.append(f"  Snapshots loaded: {status['snapshots_loaded']}")
        
        return _base_response(cmd_name, "\n".join(lines), {"status": status})
    
    except Exception as e:
        return _base_response(cmd_name, f"Error: {e}", {"ok": False})


# ---------------------------------------------------------------------
# v0.7.8 — Self-Test + Stability
# ---------------------------------------------------------------------

def handle_self_test(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.7.8: Run internal diagnostics suite for WM/Behavior/Topic/Pronouns.
    
    Usage:
        #self-test
        #diagnostics
    
    Runs a series of sanity checks and reports PASS/WARN/FAIL for each.
    """
    from datetime import datetime
    
    # Import WM/Behavior config
    try:
        from .wm_behavior_config import WM_ENABLED, BEHAVIOR_ENABLED
    except ImportError:
        WM_ENABLED = True
        BEHAVIOR_ENABLED = True
    
    results = []
    all_passed = True
    
    def add_result(name: str, status: str, note: str):
        nonlocal all_passed
        if status == "FAIL":
            all_passed = False
        results.append({"name": name, "status": status, "note": note})
    
    # =========================================================================
    # TEST 1: WM/Behavior Config Sanity
    # =========================================================================
    try:
        config_note = f"WM_ENABLED={WM_ENABLED}, BEHAVIOR_ENABLED={BEHAVIOR_ENABLED}"
        if not WM_ENABLED and not BEHAVIOR_ENABLED:
            add_result("Config Flags", "WARN", f"{config_note} — both disabled")
        else:
            add_result("Config Flags", "PASS", config_note)
    except Exception as e:
        add_result("Config Flags", "FAIL", f"Error reading config: {e}")
    
    # =========================================================================
    # TEST 2: Pronoun Resolution (using isolated test WM)
    # =========================================================================
    try:
        from .nova_wm import NovaWorkingMemory, EntityType, GenderHint, WMEntity, ReferentCandidate
        
        # Create isolated test WM (not tied to session)
        test_wm = NovaWorkingMemory("__self_test__")
        
        # Manually inject test entities for reliable testing
        # This bypasses extraction patterns which may vary
        steven = WMEntity(
            id="test_e1",
            name="Steven",
            entity_type=EntityType.PERSON,
            gender_hint=GenderHint.MASCULINE,
            first_mentioned=1,
            last_mentioned=1,
        )
        sarah = WMEntity(
            id="test_e2",
            name="Sarah",
            entity_type=EntityType.PERSON,
            gender_hint=GenderHint.FEMININE,
            first_mentioned=2,
            last_mentioned=2,
        )
        
        test_wm.entities["test_e1"] = steven
        test_wm.entities["test_e2"] = sarah
        
        # Add to pronoun groups
        test_wm.pronoun_groups["masculine"].add_candidate(
            ReferentCandidate(
                entity_id="test_e1",
                entity_name="Steven",
                score=1.0,
                last_mentioned=1,
                gender_match=True,
            )
        )
        test_wm.pronoun_groups["feminine"].add_candidate(
            ReferentCandidate(
                entity_id="test_e2",
                entity_name="Sarah",
                score=1.0,
                last_mentioned=2,
                gender_match=True,
            )
        )
        
        # Test pronoun resolution
        he_result = test_wm.resolve_pronoun("he")
        she_result = test_wm.resolve_pronoun("she")
        
        he_ok = he_result and "steven" in he_result.name.lower()
        she_ok = she_result and "sarah" in she_result.name.lower()
        
        if he_ok and she_ok:
            add_result(
                "Pronoun Resolution", 
                "PASS", 
                f"he→{he_result.name}, she→{she_result.name}"
            )
        else:
            details = []
            if not he_ok:
                details.append(f"he→{he_result.name if he_result else 'None'} (expected Steven)")
            if not she_ok:
                details.append(f"she→{she_result.name if she_result else 'None'} (expected Sarah)")
            add_result("Pronoun Resolution", "FAIL", "; ".join(details))
        
        # Clean up test WM
        del test_wm
        
    except Exception as e:
        add_result("Pronoun Resolution", "FAIL", f"Exception: {e}")
    
    # =========================================================================
    # TEST 3: Topic Stack Operations
    # =========================================================================
    try:
        from .nova_wm import NovaWorkingMemory
        
        test_wm = NovaWorkingMemory("__self_test_topics__")
        
        # Push topic 1
        t1 = test_wm.push_topic("project with Steven")
        
        # Push topic 2 (simulate tangent)
        t2 = test_wm.push_topic("side note about Sarah")
        
        # Verify stack has t1
        stack_ok = t1 in test_wm.topic_stack
        active_is_t2 = test_wm.active_topic_id == t2
        
        # Pop back
        popped = test_wm.pop_topic()
        active_is_t1 = test_wm.active_topic_id == t1
        
        if stack_ok and active_is_t2 and active_is_t1:
            add_result(
                "Topic Stack", 
                "PASS", 
                f"push({t1})→push({t2})→pop→active={t1}"
            )
        else:
            details = []
            if not stack_ok:
                details.append(f"stack missing {t1}")
            if not active_is_t2:
                details.append(f"after push, active was {test_wm.active_topic_id}, expected {t2}")
            if not active_is_t1:
                details.append(f"after pop, active was {test_wm.active_topic_id}, expected {t1}")
            add_result("Topic Stack", "FAIL", "; ".join(details))
        
        del test_wm
        
    except Exception as e:
        add_result("Topic Stack", "FAIL", f"Exception: {e}")
    
    # =========================================================================
    # TEST 4: Group Entity Detection
    # =========================================================================
    try:
        from .nova_wm import NovaWorkingMemory
        
        test_wm = NovaWorkingMemory("__self_test_groups__")
        result = test_wm.update("Steven and Sarah both agreed on the proposal")
        
        groups = test_wm.get_all_groups()
        they_result = test_wm.resolve_pronoun("they")
        
        if groups and they_result:
            add_result(
                "Group Entities", 
                "PASS", 
                f"Detected group '{groups[0]['name']}', they→{they_result.name}"
            )
        elif groups:
            add_result(
                "Group Entities", 
                "WARN", 
                f"Group detected but 'they' didn't resolve (may be expected)"
            )
        else:
            add_result("Group Entities", "FAIL", "No group created from 'X and Y' pattern")
        
        del test_wm
        
    except Exception as e:
        add_result("Group Entities", "FAIL", f"Exception: {e}")
    
    # =========================================================================
    # TEST 5: Episodic Snapshot (dry run)
    # =========================================================================
    try:
        from .nova_wm import NovaWorkingMemory, wm_create_snapshot
        
        test_wm = NovaWorkingMemory("__self_test_snapshot__")
        test_wm.update("Testing snapshot functionality")
        
        # Create snapshot payload (does NOT persist to memory)
        snapshot = test_wm.create_snapshot_payload(label="self-test-snapshot")
        
        if snapshot and "payload" in snapshot and "type" in snapshot:
            add_result(
                "Episodic Snapshot", 
                "PASS", 
                f"Payload created with {len(snapshot.get('tags', []))} tags"
            )
        else:
            add_result("Episodic Snapshot", "FAIL", "Snapshot payload malformed")
        
        del test_wm
        
    except Exception as e:
        add_result("Episodic Snapshot", "FAIL", f"Exception: {e}")
    
    # =========================================================================
    # TEST 6: Behavior Layer Meta-Query
    # =========================================================================
    try:
        from .nova_wm_behavior import WMBehaviorEngine
        
        test_be = WMBehaviorEngine("__self_test_behavior__")
        test_be.thread_summary.topic = "test project"
        test_be.thread_summary.participants = ["Steven", "Sarah"]
        
        # Check meta-question detection
        meta = test_be.check_meta_question("what were we talking about?")
        
        if meta and meta.get("type") == "topic_recall":
            # Try to get summary
            summary = test_be.summarize_thread()
            if summary:
                add_result(
                    "Behavior Meta-Query", 
                    "PASS", 
                    f"Detected 'topic_recall', summary length={len(summary)}"
                )
            else:
                add_result("Behavior Meta-Query", "WARN", "Meta detected but no summary returned")
        else:
            add_result("Behavior Meta-Query", "FAIL", f"Meta-question not detected: {meta}")
        
        del test_be
        
    except Exception as e:
        add_result("Behavior Meta-Query", "FAIL", f"Exception: {e}")
    
    # =========================================================================
    # TEST 7: Event Recording (v0.7.7)
    # =========================================================================
    try:
        from .nova_wm import NovaWorkingMemory
        
        test_wm = NovaWorkingMemory("__self_test_events__")
        test_wm.update("I spoke with Sarah today")
        
        # Find Sarah and record event
        sarah = test_wm._find_entity_by_name("Sarah")
        if sarah:
            test_wm.record_entity_event(sarah.id, "said", "The project is on track")
            events = test_wm.get_entity_events("Sarah")
            
            if events and len(events) > 0:
                add_result(
                    "Event Recording", 
                    "PASS", 
                    f"Recorded {len(events)} event(s) for Sarah"
                )
            else:
                add_result("Event Recording", "FAIL", "Event not retrieved after recording")
        else:
            add_result("Event Recording", "WARN", "Sarah entity not found (extraction may differ)")
        
        del test_wm
        
    except Exception as e:
        add_result("Event Recording", "FAIL", f"Exception: {e}")
    
    # =========================================================================
    # BUILD REPORT
    # =========================================================================
    lines = [
        F.header("NovaOS v0.7.8 Self-Test Report"),
        "",
        f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Session: {session_id}",
        "",
    ]
    
    # Summary counts
    pass_count = sum(1 for r in results if r["status"] == "PASS")
    warn_count = sum(1 for r in results if r["status"] == "WARN")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    
    lines.append(F.subheader("Summary"))
    lines.append(f"  PASS: {pass_count}  |  WARN: {warn_count}  |  FAIL: {fail_count}")
    lines.append("")
    
    # Detailed results
    lines.append(F.subheader("Test Results"))
    for r in results:
        status_icon = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}.get(r["status"], "?")
        lines.append(f"  {status_icon} [{r['status']}] {r['name']}")
        lines.append(f"      {r['note']}")
    
    lines.append("")
    
    # Final verdict
    if all_passed and warn_count == 0:
        lines.append("✅ All tests passed.")
    elif all_passed:
        lines.append(f"✅ All tests passed with {warn_count} warning(s).")
    else:
        lines.append(f"⚠️ {fail_count} test(s) failed. Review details above.")
    
    return _base_response(
        cmd_name, 
        "\n".join(lines), 
        {
            "results": results,
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
            "all_passed": all_passed,
        }
    )


# Alias handler
def handle_diagnostics(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """Alias for #self-test."""
    return handle_self_test("self-test", args, session_id, context, kernel, meta)


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


# ---------------------------------------------------------------------
# v0.6 — Sectioned Help and Section Menu Handlers
# ---------------------------------------------------------------------

# Import section definitions
from .section_defs import SECTION_DEFS, get_section, get_section_keys

# Session state for section menus
_section_menu_state: Dict[str, str] = {}  # session_id -> active_section


def handle_help_v06(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    v0.6 — Help command showing only the 13 section summaries.
    
    Usage:
        #help              (show section list)
        #help section=memory  (show specific section's commands)
    
    TODO: Refactor to pull section list from section_defs.py as single source of truth.
    """
    # Section summaries - one line each (v0.8.0 Life RPG)
    SECTION_SUMMARIES = {
        "core": "Nova's heart & OS control center",
        "memory": "Lore & knowledge store (semantic/procedural/episodic)",
        "continuity": "Long-term arcs, projects, and session state",
        "human_state": "HP / stamina / stress / mood tracking",
        "modules": "Regions/domains on the world map",
        "identity": "Player Profile: level, XP, domains, titles, unlocks",
        "system": "Environment, modes, snapshots, and runtime config",
        "workflow": "Quest Engine: quests, XP, skills, streaks, boss battles",
        "timerhythm": "Time model, daily/weekly rhythm, and seasons",
        "reminders": "Time-based reminders and quest pins",
        "commands": "Abilities/macros you can unlock and reuse",
        "interpretation": "Strategy & oracle (READ-ONLY, suggests but never executes)",
        "debug": "Diagnostics and dev tools",
        "inbox": "Capture layer for raw thoughts, ideas, and tasks",
    }
    
    SECTION_ORDER = [
        "core",
        "memory",
        "continuity",
        "human_state",
        "modules",
        "identity",
        "system",
        "workflow",
        "timerhythm",
        "reminders",
        "commands",
        "interpretation",
        "debug",
        "inbox",  # v0.8.0
    ]
    
    # Check if specific section requested
    target_section = None
    if isinstance(args, dict):
        target_section = args.get("section")
        if not target_section and "_" in args and args["_"]:
            target_section = args["_"][0]
    
    lines = []
    
    if target_section:
        # Show specific section's commands
        section = get_section(target_section)
        if not section:
            return _base_response(
                cmd_name,
                f"Unknown section '{target_section}'. Use #help to see all sections.",
                {"ok": False}
            )
        
        lines.append(f"[{section.title}]")
        lines.append(f"{section.description}")
        lines.append("")
        
        for i, cmd in enumerate(section.commands, 1):
            lines.append(f"{i}) {cmd.name}")
            lines.append(f"   {cmd.description}")
            lines.append("")
        
        lines.append(f"Type #{target_section} to enter this section's menu.")
    else:
        # Show section list only (no individual commands)
        lines.append("NovaOS Sections")
        lines.append("Choose a section to explore its commands (e.g., #core, #memory).")
        lines.append("")
        
        for name in SECTION_ORDER:
            desc = SECTION_SUMMARIES.get(name, "")
            lines.append(f"{name} — {desc}")
    
    summary = "\n".join(lines)
    return _base_response(cmd_name, summary, {"sections": SECTION_ORDER})


def _handle_section_menu(section_key: str, cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Generic section menu handler.
    Shows commands in the section and waits for selection.
    """
    section = get_section(section_key)
    if not section:
        return _base_response(cmd_name, f"Unknown section '{section_key}'.", {"ok": False})
    
    # v0.7: Clear Working Memory when entering section menu
    wm_clear(session_id)
    
    # Set active section for this session
    _section_menu_state[session_id] = section_key
    
    lines = [
        f"You're in the {section.title} section. Which command would you like to run?",
        "",
    ]
    
    for i, cmd in enumerate(section.commands, 1):
        lines.append(f"{i}) {cmd.name}")
        lines.append(f"   Description: {cmd.description}")
        lines.append(f"   Example: {cmd.example}")
        lines.append("")
    
    example_cmd = section.commands[0].name if section.commands else "command"
    lines.append(f'Please type the command name exactly (e.g., "{example_cmd}"). Numbers will not work.')
    
    summary = "\n".join(lines)
    return _base_response(cmd_name, summary, {
        "section": section_key,
        "commands": [cmd.name for cmd in section.commands],
        "menu_active": True,
    })


# Individual section menu handlers
def handle_section_core(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("core", cmd_name, args, session_id, context, kernel, meta)

def handle_section_memory(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("memory", cmd_name, args, session_id, context, kernel, meta)

def handle_section_continuity(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("continuity", cmd_name, args, session_id, context, kernel, meta)

def handle_section_human_state(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("human_state", cmd_name, args, session_id, context, kernel, meta)

def handle_section_modules(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("modules", cmd_name, args, session_id, context, kernel, meta)

def handle_section_identity(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("identity", cmd_name, args, session_id, context, kernel, meta)

def handle_section_system(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("system", cmd_name, args, session_id, context, kernel, meta)

def handle_section_workflow(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("workflow", cmd_name, args, session_id, context, kernel, meta)

def handle_section_timerhythm(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("timerhythm", cmd_name, args, session_id, context, kernel, meta)

def handle_section_reminders(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("reminders", cmd_name, args, session_id, context, kernel, meta)

def handle_section_commands(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("commands", cmd_name, args, session_id, context, kernel, meta)

def handle_section_interpretation(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("interpretation", cmd_name, args, session_id, context, kernel, meta)

# v0.7.2: Debug section
def handle_section_debug(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("debug", cmd_name, args, session_id, context, kernel, meta)

# v0.8.0: Inbox section
def handle_section_inbox(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    return _handle_section_menu("inbox", cmd_name, args, session_id, context, kernel, meta)


def get_active_section(session_id: str) -> str:
    """Get the active section menu for a session."""
    return _section_menu_state.get(session_id)

def clear_active_section(session_id: str) -> None:
    """Clear the active section menu for a session."""
    _section_menu_state.pop(session_id, None)

def get_section_command_names(section_key: str) -> list:
    """Get command names for a section."""
    section = get_section(section_key)
    if section:
        return [cmd.name for cmd in section.commands]
    return []


def handle_reset(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    # v0.7: Clear Working Memory on reset
    wm_clear(session_id)
    # v0.7.2: Clear Behavior Layer on reset
    behavior_clear(session_id)
    kernel.context_manager.reset_session(session_id)
    summary = "Session context reset. Working memory and behavior layer cleared. Modules and workflows reloaded from disk."
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

    # v0.5.7: Sync memory policy mode
    if hasattr(kernel, "memory_policy"):
        kernel.memory_policy.set_mode(desired)

    current_env = getattr(kernel, "env_state", {})
    lines = [F.key_value("mode", desired)]
    summary = F.header("Mode updated") + "\n".join(lines)
    extra = {"mode": desired, "env": current_env}
    return _base_response(cmd_name, summary, extra)


# ---------------------------------------------------------------------
# v0.5.3 — Model Routing Commands
# ---------------------------------------------------------------------

def handle_model_info(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show information about available model tiers and current routing behavior.
    
    Usage:
        model-info
        model-info command=derive  (show what model would be used for a command)
    """
    # Get model info from kernel
    if not hasattr(kernel, "get_model_info"):
        return _base_response(
            cmd_name,
            "Model routing not available.",
            {"ok": False},
        )

    info = kernel.get_model_info()
    tiers = info.get("tiers", {})
    current_mode = info.get("current_mode", "normal")

    # Check if user wants to test routing for a specific command
    test_command = None
    test_input = ""
    if isinstance(args, dict):
        test_command = args.get("command") or args.get("cmd")
        test_input = args.get("input", "")

    lines = []
    lines.append(F.key_value("Current mode", current_mode))
    lines.append("")

    # Show tiers
    for tier_name, tier_info in tiers.items():
        model_id = tier_info.get("model_id", "?")
        desc = tier_info.get("description", "")
        max_chars = tier_info.get("max_input_chars", 0)
        lines.append(f"  {tier_name.upper()}: {model_id}")
        lines.append(f"      {desc}")
        lines.append(f"      Max input: {max_chars:,} chars")
        lines.append("")

    # If testing a specific command
    if test_command and hasattr(kernel, "get_model"):
        routed_model = kernel.get_model(
            command=test_command,
            input_text=test_input,
        )
        lines.append(F.key_value(f"Model for '{test_command}'", routed_model))

    summary = F.header("Model Routing Info") + "\n".join(lines)
    extra = {
        "tiers": tiers,
        "current_mode": current_mode,
    }
    if test_command:
        extra["test_command"] = test_command
        extra["routed_model"] = routed_model

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
        # Accept both "id" (singular) and "ids" (plural)
        raw_ids = args.get("ids") or args.get("id")
        
        # Also check for bare arguments (e.g., #forget 13)
        if raw_ids is None and "_" in args and args["_"]:
            raw_ids = args["_"][0]
        
        if raw_ids is not None:
            if isinstance(raw_ids, int):
                ids = [raw_ids]
            elif isinstance(raw_ids, str):
                # Handle comma-separated or single value
                ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
            else:
                # assume iterable
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
        # Accept both "id" (singular) and "ids" (plural)
        raw_ids = args.get("ids") or args.get("id") or []
        if isinstance(raw_ids, int):
            ids = [raw_ids]
        elif isinstance(raw_ids, str):
            ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip().isdigit()]
        else:
            try:
                ids = [int(x) for x in raw_ids]
            except (ValueError, TypeError):
                ids = []
    if not ids:
        return _base_response(cmd_name, "No memory IDs provided for binding.", {"ok": False})

    cluster_id = mm.bind_cluster(ids)
    summary = f"Bound memories {ids} into cluster {cluster_id}."
    extra = {"cluster_id": cluster_id, "ids": ids}
    return _base_response(cmd_name, summary, extra)


# ---------------------------------------------------------------------
# v0.5.4 — Enhanced Memory Commands
# ---------------------------------------------------------------------

def handle_memory_stats(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show detailed memory statistics.
    
    Usage:
        memory-stats
    """
    mm = kernel.memory_manager
    
    # Get health/stats
    if hasattr(mm, "get_stats"):
        stats = mm.get_stats()
    else:
        stats = {"health": mm.get_health()}
    
    health = stats.get("health", {})
    
    lines = [
        F.key_value("Total memories", health.get("total", 0)),
        "",
        "By Type:",
        F.key_value("  Semantic", health.get("semantic_entries", 0)),
        F.key_value("  Procedural", health.get("procedural_entries", 0)),
        F.key_value("  Episodic", health.get("episodic_entries", 0)),
        "",
        "By Status:",
        F.key_value("  Active", health.get("active", "N/A")),
        F.key_value("  Stale", health.get("stale", "N/A")),
        F.key_value("  Archived", health.get("archived", "N/A")),
        "",
        F.key_value("Unique tags", health.get("unique_tags", "N/A")),
        F.key_value("Unique modules", health.get("unique_modules", "N/A")),
    ]
    
    summary = F.header("Memory Statistics") + "\n".join(lines)
    return _base_response(cmd_name, summary, stats)


def handle_memory_salience(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Update the salience (importance) of a memory item.
    
    Usage:
        memory-salience id=5 salience=0.9
    """
    mm = kernel.memory_manager
    
    if not isinstance(args, dict):
        return _base_response(cmd_name, "Usage: memory-salience id=<id> salience=<0.0-1.0>", {"ok": False})
    
    mem_id = args.get("id")
    salience = args.get("salience")
    
    if mem_id is None:
        return _base_response(cmd_name, "Missing required argument: id", {"ok": False})
    if salience is None:
        return _base_response(cmd_name, "Missing required argument: salience", {"ok": False})
    
    try:
        mem_id = int(mem_id)
        salience = float(salience)
    except (ValueError, TypeError):
        return _base_response(cmd_name, "id must be integer, salience must be float", {"ok": False})
    
    if not (0.0 <= salience <= 1.0):
        return _base_response(cmd_name, "salience must be between 0.0 and 1.0", {"ok": False})
    
    if hasattr(mm, "update_salience"):
        ok = mm.update_salience(mem_id, salience)
        if ok:
            summary = f"Updated memory #{mem_id} salience to {salience:.2f}"
            return _base_response(cmd_name, summary, {"id": mem_id, "salience": salience})
        else:
            return _base_response(cmd_name, f"Memory #{mem_id} not found", {"ok": False})
    else:
        return _base_response(cmd_name, "Salience updates not supported in this version", {"ok": False})


def handle_memory_status(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Update the status of a memory item.
    
    Usage:
        memory-status id=5 status=stale
        memory-status id=5 status=archived
    
    Valid statuses: active, stale, archived, pending_confirmation
    """
    mm = kernel.memory_manager
    
    if not isinstance(args, dict):
        return _base_response(cmd_name, "Usage: memory-status id=<id> status=<status>", {"ok": False})
    
    mem_id = args.get("id")
    status = args.get("status")
    
    if mem_id is None:
        return _base_response(cmd_name, "Missing required argument: id", {"ok": False})
    if status is None:
        return _base_response(cmd_name, "Missing required argument: status", {"ok": False})
    
    try:
        mem_id = int(mem_id)
    except (ValueError, TypeError):
        return _base_response(cmd_name, "id must be integer", {"ok": False})
    
    valid_statuses = {"active", "stale", "archived", "pending_confirmation"}
    if status not in valid_statuses:
        return _base_response(
            cmd_name,
            f"Invalid status. Valid: {', '.join(sorted(valid_statuses))}",
            {"ok": False}
        )
    
    if hasattr(mm, "update_status"):
        ok = mm.update_status(mem_id, status)
        if ok:
            summary = f"Updated memory #{mem_id} status to '{status}'"
            return _base_response(cmd_name, summary, {"id": mem_id, "status": status})
        else:
            return _base_response(cmd_name, f"Memory #{mem_id} not found", {"ok": False})
    else:
        return _base_response(cmd_name, "Status updates not supported in this version", {"ok": False})


def handle_memory_high_salience(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    List high-importance memories.
    
    Usage:
        memory-important
        memory-important min=0.8 limit=10
    """
    mm = kernel.memory_manager
    
    min_salience = 0.7
    limit = 20
    
    if isinstance(args, dict):
        if "min" in args:
            try:
                min_salience = float(args["min"])
            except (ValueError, TypeError):
                pass
        if "limit" in args:
            try:
                limit = int(args["limit"])
            except (ValueError, TypeError):
                pass
    
    if hasattr(mm, "get_high_salience"):
        items = mm.get_high_salience(min_salience=min_salience, limit=limit)
    else:
        # Fallback: regular recall
        items = mm.recall(limit=limit)
    
    if not items:
        summary = f"No memories with salience >= {min_salience:.1f}"
        return _base_response(cmd_name, summary, {"items": []})
    
    formatted = []
    for item in items[:10]:
        trace = getattr(item, "trace", {}) or {}
        salience = trace.get("salience", "?")
        formatted.append(f"#{item.id} [{item.type}] (salience={salience}) {item.payload[:50]}...")
    
    summary = F.header(f"High-Salience Memories ({len(items)})") + "\n".join(formatted)
    return _base_response(cmd_name, summary, {"count": len(items)})


# ---------------------------------------------------------------------
# v0.5.5 — Identity Profile Commands
# ---------------------------------------------------------------------

def handle_identity_show(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show current identity profile.
    
    Usage:
        identity-show
    """
    im = kernel.identity_manager
    profile = im.get_current()
    
    if not profile:
        return _base_response(cmd_name, "No identity profile set.", {"profile": None})
    
    traits = profile.traits
    lines = [
        F.key_value("Profile ID", profile.id),
        F.key_value("Version", profile.version),
        F.key_value("Updated", profile.updated_at[:19]),
        "",
    ]
    
    if traits.name:
        lines.append(F.key_value("Name", traits.name))
    
    if traits.context:
        lines.append(F.key_value("Context", traits.context))
    
    if traits.roles:
        lines.append(F.key_value("Roles", ", ".join(traits.roles)))
    
    if traits.goals:
        lines.append("")
        lines.append("Goals:")
        for goal in traits.goals[:5]:
            lines.append(f"  • {goal}")
    
    if traits.values:
        lines.append("")
        lines.append("Values:")
        for value in traits.values[:5]:
            lines.append(f"  • {value}")
    
    if traits.strengths:
        lines.append("")
        lines.append("Strengths:")
        for s in traits.strengths[:5]:
            lines.append(f"  • {s}")
    
    if traits.growth_areas:
        lines.append("")
        lines.append("Growth Areas:")
        for g in traits.growth_areas[:5]:
            lines.append(f"  • {g}")
    
    if traits.custom:
        lines.append("")
        lines.append("Custom:")
        for k, v in list(traits.custom.items())[:5]:
            lines.append(f"  • {k}: {v}")
    
    summary = F.header("Identity Profile") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"profile": profile.to_dict()})


def handle_identity_set(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Set an identity trait.
    
    Usage:
        identity-set name="Vant"
        identity-set context="Building NovaOS"
        identity-set goals="Learn ML,Build products"  (comma-separated)
        identity-set roles="Developer,Founder"
    """
    im = kernel.identity_manager
    
    if not isinstance(args, dict) or not args:
        return _base_response(
            cmd_name,
            "Usage: identity-set <trait>=<value>\nTraits: name, context, goals, values, roles, strengths, growth_areas, or custom keys",
            {"ok": False}
        )
    
    # Process args
    updates = {}
    for key, value in args.items():
        if key == "_":
            continue
        
        # Handle comma-separated list fields
        list_fields = {"goals", "values", "roles", "strengths", "growth_areas"}
        if key in list_fields and isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        
        updates[key] = value
    
    if not updates:
        return _base_response(cmd_name, "No valid traits provided.", {"ok": False})
    
    # Update each trait
    for key, value in updates.items():
        im.set_trait(key, value, notes=f"Set {key} via identity-set")
    
    profile = im.get_current()
    
    lines = [f"Updated: {', '.join(updates.keys())}"]
    summary = F.header("Identity Updated") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"updated": list(updates.keys()), "profile": profile.to_dict() if profile else None})


def handle_identity_snapshot(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Create a snapshot of current identity.
    
    Usage:
        identity-snapshot
        identity-snapshot notes="Before career change"
    """
    im = kernel.identity_manager
    
    notes = ""
    if isinstance(args, dict):
        notes = args.get("notes", "") or args.get("_", [""])[0] if "_" in args else ""
    
    try:
        entry = im.snapshot(notes=notes)
        summary = (
            F.header("Identity Snapshot Created") +
            f"Snapshot saved at {entry.snapshot_at[:19]}\n" +
            f"Version: {entry.version}"
        )
        return _base_response(cmd_name, summary, {"snapshot": entry.to_dict()})
    except ValueError as e:
        return _base_response(cmd_name, str(e), {"ok": False})


def handle_identity_history(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show identity history.
    
    Usage:
        identity-history
        identity-history limit=5
    """
    im = kernel.identity_manager
    
    limit = 10
    if isinstance(args, dict) and "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            pass
    
    history = im.get_history(limit=limit)
    
    if not history:
        return _base_response(cmd_name, "No identity history.", {"history": []})
    
    lines = []
    for entry in history:
        name = entry.traits.name or "(unnamed)"
        goals_count = len(entry.traits.goals)
        lines.append(
            f"• {entry.snapshot_at[:19]} — v{entry.version} — {name} — {goals_count} goals"
        )
        if entry.notes:
            lines.append(f"    Notes: {entry.notes[:50]}...")
    
    summary = F.header(f"Identity History ({len(history)} snapshots)") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"history": [e.to_dict() for e in history]})


def handle_identity_restore(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Restore identity from a historical snapshot.
    
    Usage:
        identity-restore id=profile-20250101-abc123
        identity-restore timestamp=2025-01-01T12:00:00
    """
    im = kernel.identity_manager
    
    snapshot_id = None
    if isinstance(args, dict):
        snapshot_id = args.get("id") or args.get("timestamp") or args.get("_", [None])[0] if "_" in args else None
    
    if not snapshot_id:
        return _base_response(
            cmd_name,
            "Usage: identity-restore id=<profile-id> or timestamp=<iso-timestamp>",
            {"ok": False}
        )
    
    profile = im.restore_from_history(str(snapshot_id))
    
    if not profile:
        return _base_response(cmd_name, f"Snapshot '{snapshot_id}' not found.", {"ok": False})
    
    summary = (
        F.header("Identity Restored") +
        f"Restored from snapshot. New profile ID: {profile.id}"
    )
    return _base_response(cmd_name, summary, {"profile": profile.to_dict()})


def handle_identity_clear_history(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Clear identity history.
    
    Usage:
        identity-clear-history
    """
    im = kernel.identity_manager
    count = im.clear_history()
    
    summary = F.header("Identity History Cleared") + f"Removed {count} historical snapshots."
    return _base_response(cmd_name, summary, {"cleared": count})


# ---------------------------------------------------------------------
# v0.5.6 — Memory Lifecycle Commands
# ---------------------------------------------------------------------

def handle_memory_decay(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Run decay analysis on memories and optionally apply updates.
    
    Usage:
        memory-decay              (analyze only)
        memory-decay apply=true   (analyze and apply changes)
    """
    from kernel.memory_lifecycle import MemoryLifecycle
    
    # Get memory engine
    mm = kernel.memory_manager
    if not hasattr(mm, "_engine"):
        return _base_response(cmd_name, "Memory engine not available.", {"ok": False})
    
    engine = mm._engine
    
    # Parse args
    apply_changes = False
    if isinstance(args, dict):
        apply_val = args.get("apply", "false")
        apply_changes = str(apply_val).lower() in ("true", "yes", "1")
    
    # Initialize lifecycle manager
    lifecycle = MemoryLifecycle()
    
    # Get all memories for processing
    memories = engine.get_all_for_lifecycle()
    
    if not memories:
        return _base_response(cmd_name, "No memories to process.", {"processed": 0})
    
    # Process
    result = lifecycle.process_memories(
        memories=memories,
        apply_decay=True,
        detect_drift=True,
    )
    
    summary_data = result["summary"]
    
    # Apply changes if requested
    applied = 0
    if apply_changes and result["decay_updates"]:
        applied = engine.apply_decay_updates(result["decay_updates"])
    
    # Build summary
    lines = [
        F.key_value("Memories processed", summary_data["processed"]),
        F.key_value("Decay changes detected", summary_data["decay_changes"]),
        F.key_value("Drift issues found", summary_data["drift_detected"]),
        F.key_value("Need re-confirmation", summary_data["needs_reconfirm"]),
    ]
    
    if apply_changes:
        lines.append("")
        lines.append(F.key_value("Changes applied", applied))
    else:
        lines.append("")
        lines.append("Run with apply=true to apply changes.")
    
    # Show top drift issues
    if result["drift_reports"]:
        lines.append("")
        lines.append("Top drift issues:")
        for drift in result["drift_reports"][:5]:
            lines.append(f"  • #{drift['memory_id']} ({drift['memory_type']}): {drift['drift_reason'][:50]}")
    
    summary = F.header("Memory Decay Analysis") + "\n".join(lines)
    return _base_response(cmd_name, summary, result)


def handle_memory_drift(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Detect drifted/stale memories.
    
    Usage:
        memory-drift
        memory-drift limit=20
    """
    from kernel.memory_lifecycle import MemoryLifecycle
    
    mm = kernel.memory_manager
    if not hasattr(mm, "_engine"):
        return _base_response(cmd_name, "Memory engine not available.", {"ok": False})
    
    engine = mm._engine
    
    # Parse args
    limit = 20
    if isinstance(args, dict) and "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            pass
    
    # Initialize lifecycle manager
    lifecycle = MemoryLifecycle()
    
    # Get all memories
    memories = engine.get_all_for_lifecycle()
    
    # Process for drift only (no decay application)
    result = lifecycle.process_memories(
        memories=memories,
        apply_decay=False,
        detect_drift=True,
    )
    
    drift_reports = result["drift_reports"][:limit]
    
    if not drift_reports:
        return _base_response(cmd_name, "No drifted memories detected.", {"drift_reports": []})
    
    lines = []
    for drift in drift_reports:
        action_label = drift["recommended_action"].upper()
        lines.append(
            f"• #{drift['memory_id']} [{drift['memory_type']}] ({action_label})\n"
            f"    Salience: {drift['current_salience']:.3f} | "
            f"Days since use: {drift['days_since_use']}\n"
            f"    {drift['drift_reason'][:60]}"
        )
    
    summary = F.header(f"Drifted Memories ({len(drift_reports)})") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"drift_reports": drift_reports})


def handle_memory_reconfirm(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Re-confirm a memory (restore to active status).
    
    Usage:
        memory-reconfirm id=5
        memory-reconfirm id=5 salience=0.8
    """
    mm = kernel.memory_manager
    if not hasattr(mm, "_engine"):
        return _base_response(cmd_name, "Memory engine not available.", {"ok": False})
    
    engine = mm._engine
    
    if not isinstance(args, dict) or "id" not in args:
        return _base_response(
            cmd_name,
            "Usage: memory-reconfirm id=<memory_id> [salience=<0.0-1.0>]",
            {"ok": False}
        )
    
    try:
        mem_id = int(args["id"])
    except (ValueError, TypeError):
        return _base_response(cmd_name, "Invalid memory ID.", {"ok": False})
    
    new_salience = None
    if "salience" in args:
        try:
            new_salience = float(args["salience"])
        except (ValueError, TypeError):
            pass
    
    success = engine.reconfirm_memory(mem_id, new_salience)
    
    if success:
        summary = f"Memory #{mem_id} re-confirmed and restored to active status."
        if new_salience is not None:
            summary += f" Salience set to {new_salience:.2f}."
        return _base_response(cmd_name, summary, {"id": mem_id, "reconfirmed": True})
    else:
        return _base_response(cmd_name, f"Memory #{mem_id} not found.", {"ok": False})


def handle_memory_stale(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    List stale memories.
    
    Usage:
        memory-stale
        memory-stale limit=10
    """
    mm = kernel.memory_manager
    if not hasattr(mm, "_engine"):
        return _base_response(cmd_name, "Memory engine not available.", {"ok": False})
    
    engine = mm._engine
    
    limit = 20
    if isinstance(args, dict) and "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            pass
    
    stale = engine.get_stale_memories(limit=limit)
    
    if not stale:
        return _base_response(cmd_name, "No stale memories.", {"items": []})
    
    lines = []
    for item in stale[:10]:
        lines.append(
            f"• #{item.id} [{item.type}] salience={item.salience:.3f}\n"
            f"    {item.payload[:50]}..."
        )
    
    if len(stale) > 10:
        lines.append(f"  ...and {len(stale) - 10} more")
    
    summary = F.header(f"Stale Memories ({len(stale)})") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"count": len(stale)})


def handle_memory_archive_stale(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Archive all stale memories.
    
    Usage:
        memory-archive-stale
    """
    mm = kernel.memory_manager
    if not hasattr(mm, "_engine"):
        return _base_response(cmd_name, "Memory engine not available.", {"ok": False})
    
    engine = mm._engine
    
    stale = engine.get_stale_memories(limit=1000)
    
    if not stale:
        return _base_response(cmd_name, "No stale memories to archive.", {"archived": 0})
    
    ids = [item.id for item in stale]
    count = engine.bulk_update_status(ids, "archived")
    
    summary = F.header("Stale Memories Archived") + f"Archived {count} memories."
    return _base_response(cmd_name, summary, {"archived": count})


def handle_decay_preview(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Preview decay trajectory for a memory type.
    
    Usage:
        decay-preview type=episodic salience=0.8
        decay-preview type=semantic salience=0.6
    """
    from kernel.memory_lifecycle import MemoryLifecycle
    
    mem_type = "semantic"
    salience = 0.5
    
    if isinstance(args, dict):
        mem_type = args.get("type", "semantic")
        try:
            salience = float(args.get("salience", 0.5))
        except (ValueError, TypeError):
            pass
    
    lifecycle = MemoryLifecycle()
    predictions = lifecycle.estimate_decay_preview(
        memory_type=mem_type,
        current_salience=salience,
        days_ahead=180,
    )
    
    lines = [
        f"Type: {mem_type} | Starting salience: {salience:.2f}",
        "",
        "Day  | Salience | Status",
        "-" * 30,
    ]
    
    for p in predictions:
        lines.append(f"{p['day']:4d} | {p['salience']:.4f}  | {p['status']}")
    
    summary = F.header("Decay Preview") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"predictions": predictions})


# ---------------------------------------------------------------------
# v0.5.7 — Memory Policy Commands
# ---------------------------------------------------------------------

def handle_memory_policy(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show memory policy configuration.
    
    Usage:
        memory-policy
    """
    if not hasattr(kernel, "memory_policy"):
        return _base_response(cmd_name, "Memory policy not initialized.", {"ok": False})
    
    policy = kernel.memory_policy
    config = policy.get_config_summary()
    active = policy.get_active_policies()
    
    lines = [
        F.key_value("Current mode", config["current_mode"]),
        "",
        "Active Policies:",
    ]
    
    for p in active:
        lines.append(f"  • {p}")
    
    lines.append("")
    lines.append("Identity Tags:")
    lines.append(f"  {', '.join(config['identity_tags'])}")
    
    lines.append("")
    lines.append("Mode Filters:")
    for mode, filters in config["mode_filters"].items():
        if filters:
            filter_str = ", ".join(f"{k}={v}" for k, v in filters.items())
            lines.append(f"  • {mode}: {filter_str}")
    
    summary = F.header("Memory Policy") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"config": config, "active_policies": active})


def handle_memory_policy_test(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Test memory policy pre-store validation.
    
    Usage:
        memory-policy-test payload="Test memory" type=semantic tags=test,example
    """
    if not hasattr(kernel, "memory_policy"):
        return _base_response(cmd_name, "Memory policy not initialized.", {"ok": False})
    
    policy = kernel.memory_policy
    
    # Parse args
    payload = "Test memory payload"
    mem_type = "semantic"
    tags = ["test"]
    source = "user"
    
    if isinstance(args, dict):
        payload = args.get("payload", payload)
        mem_type = args.get("type", mem_type)
        raw_tags = args.get("tags", "test")
        if isinstance(raw_tags, str):
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        else:
            tags = list(raw_tags)
        source = args.get("source", source)
    
    # Run pre-store check
    result = policy.pre_store(
        payload=payload,
        mem_type=mem_type,
        tags=tags,
        source=source,
    )
    
    lines = [
        F.key_value("Allowed", "Yes" if result.allowed else "No"),
    ]
    
    if not result.allowed:
        lines.append(F.key_value("Reason", result.reason or "Unknown"))
    
    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in result.warnings:
            lines.append(f"  • {w}")
    
    if result.modified_item:
        lines.append("")
        lines.append("Modifications:")
        for k, v in result.modified_item.items():
            if k == "trace":
                lines.append(f"  • trace: (enhanced)")
            else:
                lines.append(f"  • {k}: {v}")
    
    summary = F.header("Policy Test Result") + "\n".join(lines)
    return _base_response(cmd_name, summary, {
        "allowed": result.allowed,
        "reason": result.reason,
        "warnings": result.warnings,
        "modifications": result.modified_item,
    })


def handle_memory_mode_filter(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show memory recall filters for current or specified mode.
    
    Usage:
        memory-mode-filter
        memory-mode-filter mode=deep_work
    """
    if not hasattr(kernel, "memory_policy"):
        return _base_response(cmd_name, "Memory policy not initialized.", {"ok": False})
    
    policy = kernel.memory_policy
    
    # Parse mode
    mode = policy._current_mode
    if isinstance(args, dict) and "mode" in args:
        mode = args["mode"]
    
    # Temporarily set mode to get filter
    original_mode = policy._current_mode
    policy.set_mode(mode)
    mode_filter = policy.get_mode_filter()
    policy.set_mode(original_mode)
    
    lines = [
        F.key_value("Mode", mode),
        "",
    ]
    
    if not mode_filter:
        lines.append("No special filters (default behavior)")
    else:
        lines.append("Active Filters:")
        for k, v in mode_filter.items():
            if isinstance(v, list):
                lines.append(f"  • {k}: {', '.join(v)}")
            else:
                lines.append(f"  • {k}: {v}")
    
    summary = F.header("Memory Mode Filter") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"mode": mode, "filter": mode_filter})


# ---------------------------------------------------------------------
# v0.5.8 — Continuity Commands
# ---------------------------------------------------------------------

def handle_preferences(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show user preferences extracted from memory and identity.
    
    Usage:
        preferences
        preferences limit=20
    """
    if not hasattr(kernel, "continuity"):
        return _base_response(cmd_name, "Continuity helpers not initialized.", {"ok": False})
    
    limit = 10
    if isinstance(args, dict) and "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            pass
    
    prefs = kernel.continuity.get_user_preferences(limit=limit)
    
    if not prefs:
        return _base_response(cmd_name, "No preferences found.", {"preferences": []})
    
    lines = []
    for pref in prefs:
        conf_str = f"({pref.confidence:.0%})"
        source_str = f"[mem #{pref.source_memory_id}]" if pref.source_memory_id > 0 else "[identity]"
        value_str = str(pref.value)[:50]
        lines.append(f"• {pref.key}: {value_str} {conf_str} {source_str}")
    
    summary = F.header(f"User Preferences ({len(prefs)})") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"preferences": [p.to_dict() for p in prefs]})


def handle_projects(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show active projects and goals.
    
    Usage:
        projects
        projects limit=10 include_stale=true
    """
    if not hasattr(kernel, "continuity"):
        return _base_response(cmd_name, "Continuity helpers not initialized.", {"ok": False})
    
    limit = 5
    include_stale = False
    
    if isinstance(args, dict):
        if "limit" in args:
            try:
                limit = int(args["limit"])
            except (ValueError, TypeError):
                pass
        if "include_stale" in args:
            include_stale = str(args["include_stale"]).lower() in ("true", "yes", "1")
    
    projects = kernel.continuity.get_active_projects(limit=limit, include_stale=include_stale)
    
    if not projects:
        return _base_response(cmd_name, "No active projects found.", {"projects": []})
    
    lines = []
    for proj in projects:
        status_icon = "✓" if proj.status == "active" else "○" if proj.status == "stale" else "—"
        priority_str = f"P{proj.priority}"
        source_str = f"[#{proj.source_memory_id}]" if proj.source_memory_id > 0 else "[identity]"
        lines.append(f"{status_icon} {priority_str} {proj.name} {source_str}")
        if proj.description and proj.description != proj.name:
            desc = proj.description[:60]
            lines.append(f"    {desc}...")
    
    summary = F.header(f"Active Projects ({len(projects)})") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"projects": [p.to_dict() for p in projects]})


def handle_continuity_context(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show full continuity context (preferences + projects + identity + stale items).
    
    Usage:
        continuity-context
    """
    if not hasattr(kernel, "continuity"):
        return _base_response(cmd_name, "Continuity helpers not initialized.", {"ok": False})
    
    ctx = kernel.continuity.get_continuity_context()
    
    lines = []
    
    # Identity summary
    if ctx.identity_summary:
        lines.append("Identity:")
        if ctx.identity_summary.get("name"):
            lines.append(f"  Name: {ctx.identity_summary['name']}")
        if ctx.identity_summary.get("context"):
            lines.append(f"  Context: {ctx.identity_summary['context'][:50]}...")
        if ctx.identity_summary.get("goals"):
            lines.append(f"  Goals: {', '.join(ctx.identity_summary['goals'][:3])}")
        lines.append("")
    
    # Active projects
    active_projects = [p for p in ctx.projects if p.status == "active"]
    if active_projects:
        lines.append(f"Active Projects ({len(active_projects)}):")
        for proj in active_projects[:3]:
            lines.append(f"  • {proj.name}")
        lines.append("")
    
    # Top preferences
    if ctx.preferences:
        lines.append(f"Preferences ({len(ctx.preferences)}):")
        for pref in ctx.preferences[:3]:
            lines.append(f"  • {pref.key}: {str(pref.value)[:30]}")
        lines.append("")
    
    # Stale items
    if ctx.stale_items:
        lines.append(f"Items Needing Re-confirmation ({len(ctx.stale_items)}):")
        for item in ctx.stale_items[:3]:
            lines.append(f"  ? {item['suggestion']}")
    
    summary = F.header("Continuity Context") + "\n".join(lines)
    return _base_response(cmd_name, summary, ctx.to_dict())


def handle_reconfirm_prompts(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show gentle re-confirmation prompts for stale items.
    
    Usage:
        reconfirm-prompts
        reconfirm-prompts limit=5
    """
    if not hasattr(kernel, "continuity"):
        return _base_response(cmd_name, "Continuity helpers not initialized.", {"ok": False})
    
    limit = 3
    if isinstance(args, dict) and "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            pass
    
    prompts = kernel.continuity.generate_reconfirmation_prompts(limit=limit)
    
    if not prompts:
        return _base_response(cmd_name, "No re-confirmation prompts needed.", {"prompts": []})
    
    lines = []
    for p in prompts:
        tone_icon = "💭" if p["tone"] == "gentle" else "🤔" if p["tone"] == "curious" else "❓"
        lines.append(f"{tone_icon} {p['prompt']}")
    
    summary = F.header("Re-confirmation Suggestions") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"prompts": prompts})


def handle_suggest_workflow(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Suggest a workflow for a goal.
    
    Usage:
        suggest-workflow goal="Learn ML"
    """
    if not hasattr(kernel, "continuity"):
        return _base_response(cmd_name, "Continuity helpers not initialized.", {"ok": False})
    
    goal_name = None
    if isinstance(args, dict):
        goal_name = args.get("goal") or args.get("name")
        if not goal_name:
            positional = args.get("_", [])
            if positional:
                goal_name = " ".join(str(p) for p in positional)
    
    if not goal_name:
        # Show available goals
        projects = kernel.continuity.get_active_projects(limit=5)
        if projects:
            goal_list = ", ".join(p.name for p in projects)
            return _base_response(
                cmd_name,
                f"Usage: suggest-workflow goal=\"<goal_name>\"\nAvailable goals: {goal_list}",
                {"ok": False, "available_goals": [p.name for p in projects]}
            )
        return _base_response(cmd_name, "No goals found. Set some with identity-set or store memories.", {"ok": False})
    
    suggestion = kernel.continuity.suggest_workflow_for_goal(goal_name)
    
    if not suggestion:
        return _base_response(cmd_name, f"Goal '{goal_name}' not found.", {"ok": False})
    
    lines = [
        F.key_value("Workflow Name", suggestion["name"]),
        "",
        "Suggested Steps:",
    ]
    for i, step in enumerate(suggestion["suggested_steps"], 1):
        lines.append(f"  {i}. {step}")
    
    lines.append("")
    lines.append("To create: compose name=\"" + suggestion["name"] + "\"")
    
    summary = F.header("Workflow Suggestion") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"suggestion": suggestion})


# ---------------------------------------------------------------------
# v0.5.9 — Human State Commands
# ---------------------------------------------------------------------

def handle_evolution_status(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show evolution status (human state summary).
    Non-LLM, formatted via OutputFormatter.
    
    Usage:
        evolution-status
    """
    if not hasattr(kernel, "human_state"):
        return _base_response(cmd_name, "Human state manager not initialized.", {"ok": False})
    
    hsm = kernel.human_state
    summary_data = hsm.get_evolution_summary()
    
    current = summary_data["current"]
    trends = summary_data["trends"]
    meta_info = summary_data["meta"]
    recs = summary_data["recommendations"]
    
    # Build formatted output
    lines = []
    
    # Current state section
    lines.append("Current State:")
    
    # Energy with trend indicator
    energy_icon = "⚡" if current["energy"] in ("good", "high") else "🔋" if current["energy"] == "moderate" else "🪫"
    trend_arrow = "↑" if trends["energy"] == "improving" else "↓" if trends["energy"] == "declining" else "→"
    lines.append(f"  {energy_icon} Energy: {current['energy']} {trend_arrow}")
    
    # Stress with trend
    stress_icon = "😌" if current["stress"] in ("calm", "low") else "😐" if current["stress"] == "moderate" else "😰"
    stress_arrow = "↓" if trends["stress"] == "improving" else "↑" if trends["stress"] == "increasing" else "→"
    lines.append(f"  {stress_icon} Stress: {current['stress']} {stress_arrow}")
    
    # Cognitive load
    load_icon = "🧠" if current["cognitive_load"] in ("clear", "light") else "💭" if current["cognitive_load"] == "moderate" else "🤯"
    lines.append(f"  {load_icon} Cognitive load: {current['cognitive_load']}")
    
    # Momentum with trend
    momentum_icon = "🚀" if current["momentum"] in ("building", "flowing") else "🚶" if current["momentum"] == "steady" else "🐢"
    momentum_arrow = "↑" if trends["momentum"] == "building" else "↓" if trends["momentum"] == "slowing" else "→"
    lines.append(f"  {momentum_icon} Momentum: {current['momentum']} {momentum_arrow}")
    
    lines.append("")
    
    # Capacity summary
    capacity_icons = {
        "excellent": "🟢",
        "good": "🟢",
        "moderate": "🟡",
        "limited": "🟠",
        "very_limited": "🔴",
    }
    cap_icon = capacity_icons.get(current["capacity"], "⚪")
    lines.append(f"Overall Capacity: {cap_icon} {current['capacity'].replace('_', ' ').title()}")
    lines.append(f"Strain Level: {current['strain']:.0%}")
    
    # Streak
    if meta_info["checkin_streak"] > 0:
        lines.append("")
        lines.append(f"🔥 Check-in streak: {meta_info['checkin_streak']} days")
    
    # Recommendations
    if recs:
        lines.append("")
        lines.append("Recommendations:")
        for rec in recs[:4]:
            lines.append(f"  • {rec}")
    
    summary = F.header("Evolution Status") + "\n".join(lines)
    return _base_response(cmd_name, summary, summary_data)


def handle_log_state(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Guided check-in for updating human state.
    
    Usage:
        log-state                          (show current + prompts)
        log-state energy=good stress=low   (update specific fields)
        log-state checkin                  (record check-in)
    """
    if not hasattr(kernel, "human_state"):
        return _base_response(cmd_name, "Human state manager not initialized.", {"ok": False})
    
    hsm = kernel.human_state
    
    if not isinstance(args, dict) or not args:
        # Show guided prompts
        state = hsm.get_state()
        
        lines = [
            "Current State:",
            f"  Energy: {state.bio.energy}",
            f"  Stress: {state.bio.stress}",
            f"  Cognitive Load: {state.load.cognitive_load}",
            f"  Momentum: {state.aspiration.momentum}",
            "",
            "Update with:",
            "  log-state energy=<level>",
            "    Levels: depleted, low, moderate, good, high",
            "",
            "  log-state stress=<level>",
            "    Levels: overwhelmed, high, moderate, low, calm",
            "",
            "  log-state load=<level>",
            "    Levels: overloaded, heavy, moderate, light, clear",
            "",
            "  log-state momentum=<level>",
            "    Levels: stalled, slow, steady, building, flowing",
            "",
            "  log-state checkin notes=\"How I'm feeling\"",
            "    Record a check-in snapshot",
        ]
        
        summary = F.header("Log State — Guided Check-in") + "\n".join(lines)
        return _base_response(cmd_name, summary, {"current": state.to_dict()})
    
    # Process updates
    updates_made = []
    
    # Energy
    if "energy" in args:
        energy = args["energy"]
        valid_energy = {"depleted", "low", "moderate", "good", "high"}
        if energy in valid_energy:
            hsm.update_bio(energy=energy)
            updates_made.append(f"energy → {energy}")
    
    # Stress
    if "stress" in args:
        stress = args["stress"]
        valid_stress = {"overwhelmed", "high", "moderate", "low", "calm"}
        if stress in valid_stress:
            hsm.update_bio(stress=stress)
            updates_made.append(f"stress → {stress}")
    
    # Sleep
    if "sleep_hours" in args:
        try:
            hours = float(args["sleep_hours"])
            hsm.update_bio(sleep_hours=hours)
            updates_made.append(f"sleep_hours → {hours}")
        except (ValueError, TypeError):
            pass
    
    if "sleep_quality" in args:
        quality = args["sleep_quality"]
        valid_quality = {"poor", "fair", "good", "great"}
        if quality in valid_quality:
            hsm.update_bio(sleep_quality=quality)
            updates_made.append(f"sleep_quality → {quality}")
    
    # Cognitive load
    if "load" in args:
        load = args["load"]
        valid_load = {"overloaded", "heavy", "moderate", "light", "clear"}
        if load in valid_load:
            hsm.update_load(cognitive_load=load)
            updates_made.append(f"cognitive_load → {load}")
    
    # Tasks
    if "tasks" in args:
        try:
            tasks = int(args["tasks"])
            hsm.update_load(active_tasks=tasks)
            updates_made.append(f"active_tasks → {tasks}")
        except (ValueError, TypeError):
            pass
    
    # Focus
    if "focus" in args:
        focus = args["focus"]
        valid_focus = {"scattered", "okay", "focused", "deep"}
        if focus in valid_focus:
            hsm.update_load(focus_quality=focus)
            updates_made.append(f"focus_quality → {focus}")
    
    # Momentum
    if "momentum" in args:
        momentum = args["momentum"]
        valid_momentum = {"stalled", "slow", "steady", "building", "flowing"}
        if momentum in valid_momentum:
            hsm.update_aspiration(momentum=momentum)
            updates_made.append(f"momentum → {momentum}")
    
    # Win
    if "win" in args:
        win = args["win"]
        hsm.update_aspiration(add_win=win)
        updates_made.append(f"added win: {win[:30]}")
    
    # Blocker
    if "blocker" in args:
        blocker = args["blocker"]
        hsm.update_aspiration(add_blocker=blocker)
        updates_made.append(f"added blocker: {blocker[:30]}")
    
    if "clear_blocker" in args:
        blocker = args["clear_blocker"]
        hsm.update_aspiration(remove_blocker=blocker)
        updates_made.append(f"cleared blocker: {blocker[:30]}")
    
    # Current focus
    if "current_focus" in args:
        focus = args["current_focus"]
        hsm.update_aspiration(current_focus=focus)
        updates_made.append(f"current_focus → {focus[:30]}")
    
    # Check-in
    if "checkin" in args or args.get("_") == ["checkin"]:
        notes = args.get("notes", "")
        entry = hsm.do_checkin(notes=notes if notes else None)
        updates_made.append(f"check-in recorded (strain: {entry.overall_strain:.0%})")
    
    if not updates_made:
        return _base_response(cmd_name, "No valid updates provided. Run 'log-state' for help.", {"ok": False})
    
    lines = ["Updates applied:"] + [f"  ✓ {u}" for u in updates_made]
    
    # Show new capacity
    state = hsm.get_state()
    lines.append("")
    lines.append(f"Current capacity: {state.get_capacity_level().replace('_', ' ')}")
    
    if state.needs_small_version():
        lines.append("⚡ Recommendation: Consider 'small version' tasks")
    
    summary = F.header("State Updated") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"updates": updates_made, "current": state.to_dict()})


def handle_state_history(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Show human state history.
    
    Usage:
        state-history
        state-history limit=20
    """
    if not hasattr(kernel, "human_state"):
        return _base_response(cmd_name, "Human state manager not initialized.", {"ok": False})
    
    hsm = kernel.human_state
    
    limit = 10
    if isinstance(args, dict) and "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            pass
    
    history = hsm.get_history(limit=limit)
    
    if not history:
        return _base_response(cmd_name, "No state history yet. Use 'log-state checkin' to record.", {"history": []})
    
    lines = []
    for entry in history:
        ts = entry.timestamp[:16].replace("T", " ")
        strain_pct = f"{entry.overall_strain:.0%}"
        lines.append(
            f"• {ts} — Energy: {entry.bio_energy}, Stress: {entry.bio_stress}, "
            f"Momentum: {entry.aspiration_momentum} ({strain_pct} strain)"
        )
        if entry.notes:
            lines.append(f"    \"{entry.notes[:50]}...\"")
    
    summary = F.header(f"State History ({len(history)} entries)") + "\n".join(lines)
    return _base_response(cmd_name, summary, {"history": [e.to_dict() for e in history]})


def handle_capacity_check(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Quick capacity check with recommendations.
    
    Usage:
        capacity
    """
    if not hasattr(kernel, "human_state"):
        return _base_response(cmd_name, "Human state manager not initialized.", {"ok": False})
    
    hsm = kernel.human_state
    state = hsm.get_state()
    
    capacity = state.get_capacity_level()
    strain = state.get_overall_strain()
    needs_small = state.needs_small_version()
    
    # Capacity emoji
    cap_emoji = {
        "excellent": "🟢 Excellent",
        "good": "🟢 Good",
        "moderate": "🟡 Moderate",
        "limited": "🟠 Limited",
        "very_limited": "🔴 Very Limited",
    }
    
    lines = [
        f"Capacity: {cap_emoji.get(capacity, capacity)}",
        f"Strain: {strain:.0%}",
        "",
    ]
    
    if needs_small:
        lines.append("⚡ Consider 'small version' tasks today:")
        lines.append("  • Break tasks into 15-minute chunks")
        lines.append("  • Focus on one thing at a time")
        lines.append("  • Defer non-essential decisions")
    else:
        lines.append("✓ You have good capacity for normal tasks")
        if state.aspiration.momentum in ("building", "flowing"):
            lines.append("🚀 Momentum is strong — good time for deep work")
    
    summary = F.header("Capacity Check") + "\n".join(lines)
    return _base_response(cmd_name, summary, {
        "capacity": capacity,
        "strain": strain,
        "needs_small_version": needs_small,
    })


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
    Start or resume a workflow.
    
    v0.7.11: 
    - Enhanced presentation showing goal, step count, and current step details.
    - Number-based selection wizard when no ID provided.
    
    Usage:
        flow                                     # Trigger selection wizard
        flow id=<workflow_id>                    # Resume existing workflow
        flow id=<id> steps='[{"title": "..."}]'  # Create new workflow with steps
    
    If workflow exists and no new steps provided, resumes it.
    If workflow doesn't exist or new steps provided, creates/recreates it.
    """
    from .workflow_selection import set_workflow_selection
    
    wf_engine = kernel.workflow_engine

    wf_id = None
    name = None
    steps_raw = None
    from_wizard = False

    if isinstance(args, dict):
        wf_id = args.get("id") or args.get("workflow") or args.get("_", [None])[0]
        name = args.get("name")
        steps_raw = args.get("steps")
        from_wizard = args.get("_from_wizard", False)

    # =================================================================
    # v0.7.11: Show wizard with number selection if no ID provided
    # =================================================================
    if not wf_id:
        workflows = wf_engine.summarize_all()
        
        if not workflows:
            return _base_response(
                cmd_name, 
                "No workflows available. Create one first with #compose.",
                {"ok": True, "no_workflows": True}
            )
        
        # Store selection state for numeric input handling
        set_workflow_selection(session_id, "flow", workflows)
        
        # Build wizard display
        lines = [
            "╔══ Workflow Start Wizard ══╗",
            "",
            "Select a workflow to start or resume:",
            "",
            "Available workflows:",
            "",
        ]
        
        for idx, wf in enumerate(workflows, start=1):
            wf_id_str = wf.get("id", "?")
            wf_name = wf.get("name", "Untitled")
            wf_status = wf.get("status", "unknown")
            total_steps = wf.get("total_steps", 0)
            current_step_idx = wf.get("current_step_index", 0)
            active_step_title = wf.get("active_step_title", "")
            
            lines.append(f"  {idx}) {wf_name}")
            lines.append(f"     ID: {wf_id_str}")
            
            if wf_status == "completed":
                lines.append(f"     Status: completed ({total_steps} steps)")
            elif wf_status == "active" and active_step_title:
                lines.append(f"     Status: active at step {current_step_idx + 1}/{total_steps}")
                lines.append(f"     Current: {active_step_title}")
            elif wf_status == "paused" and active_step_title:
                lines.append(f"     Status: paused at step {current_step_idx + 1}/{total_steps}")
                lines.append(f"     Current: {active_step_title}")
            elif wf_status == "pending":
                lines.append(f"     Status: not started ({total_steps} steps)")
            else:
                lines.append(f"     Status: {wf_status} ({total_steps} steps)")
            
            lines.append("")
        
        lines.append("Step 1/1:")
        lines.append("Type a number to select a workflow, or 'cancel' to exit.")
        
        return _base_response(cmd_name, "\n".join(lines), {
            "ok": True,
            "workflows": workflows,
            "workflow_count": len(workflows),
            "awaiting_selection": True,
            "selection_command": "flow",
        })

    # Parse steps if provided
    steps = None
    if isinstance(steps_raw, str):
        try:
            steps = json.loads(steps_raw)
        except Exception:
            return _base_response(cmd_name, "Invalid steps JSON.", {"ok": False})
    elif isinstance(steps_raw, list):
        steps = steps_raw

    # Check if workflow already exists
    existing_wf = wf_engine.get(wf_id)
    
    if existing_wf and steps is None:
        # =================================================================
        # v0.7.10: Enhanced resume presentation
        # =================================================================
        wf = existing_wf
        goal = wf.meta.get("goal", "") if wf.meta else ""
        total = len(wf.steps)
        current_idx = wf.current_step + 1
        
        lines = [
            f"Resumed workflow \"{wf.name}\"" + (f" (Goal: {goal})" if goal else ""),
            f"Total steps: {total}",
            "",
        ]
        
        if wf.steps and wf.current_step < len(wf.steps):
            current = wf.active_step()
            if current:
                lines.append(f"Current step [{current_idx}/{total}]:")
                lines.append(f"  {current_idx}. {current.title}")
                if current.description:
                    # v0.7.12: Show full description (no truncation)
                    lines.append(f"   {current.description}")
                lines.append("")
                # v0.7.10: Updated hint text (no ID needed)
                lines.append("(Type '#halt' to pause, '#advance' to go to the next step.)")
        elif wf.status == "completed":
            lines.append("✓ This workflow is completed.")
        else:
            lines.append("(No steps remaining)")
        
        extra = wf.to_dict()
        return _base_response(cmd_name, "\n".join(lines), extra)
    
    # Create new workflow (or recreate with new steps)
    wf = wf_engine.start(workflow_id=wf_id, name=name, steps=steps or [])
    
    # v0.7.10: Enhanced start presentation
    goal = wf.meta.get("goal", "") if wf.meta else ""
    total = len(wf.steps)
    
    lines = [
        f"Started workflow \"{wf.name}\"" + (f" (Goal: {goal})" if goal else ""),
        f"Total steps: {total}",
        "",
    ]
    
    if wf.steps:
        current = wf.active_step()
        if current:
            lines.append(f"Current step [1/{total}]:")
            lines.append(f"  1. {current.title}")
            if current.description:
                # v0.7.12: Show full description (no truncation)
                lines.append(f"   {current.description}")
            lines.append("")
            # v0.7.10: Updated hint text (no ID needed)
            lines.append("(Type '#halt' to pause, '#advance' to go to the next step.)")
    
    extra = wf.to_dict()
    return _base_response(cmd_name, "\n".join(lines), extra)


def handle_advance(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Advance a workflow by one step.
    
    v0.7.11: 
    - Enhanced to show next step details.
    - Number-based selection wizard when no ID provided.
    - Auto-advances single active workflow without prompting.
    
    Usage:
        advance                  # Show workflow list or auto-advance
        advance id=<workflow_id> # Advance specific workflow
    """
    from .workflow_selection import set_workflow_selection
    
    wf_engine = kernel.workflow_engine
    wf_id = None
    from_wizard = False

    if isinstance(args, dict):
        wf_id = args.get("id") or args.get("_", [None])[0]
        from_wizard = args.get("_from_wizard", False)

    # =================================================================
    # v0.7.11: Show workflow list if no ID provided
    # =================================================================
    if not wf_id:
        all_workflows = wf_engine.summarize_all()
        active_workflows = [w for w in all_workflows if w.get("status") in ("active", "paused", "pending")]
        
        if not active_workflows:
            return _base_response(
                cmd_name,
                "No active workflows to advance. Use #flow to start one first.",
                {"ok": True, "no_workflows": True}
            )
        
        # v0.7.11: Auto-advance if only one active workflow
        if len(active_workflows) == 1:
            wf_id = active_workflows[0].get("id")
            # Fall through to advance logic below
        else:
            # Store selection state for numeric input handling
            set_workflow_selection(session_id, "advance", active_workflows)
            
            lines = [
                "╔══ Advance Workflow Wizard ══╗",
                "",
                "Select a workflow to advance:",
                "",
                "Active workflows:",
                "",
            ]
            
            for idx, wf in enumerate(active_workflows, start=1):
                wf_id_str = wf.get("id", "?")
                wf_name = wf.get("name", "Untitled")
                wf_status = wf.get("status", "unknown")
                total_steps = wf.get("total_steps", 0)
                current_step_idx = wf.get("current_step_index", 0)
                active_step_title = wf.get("active_step_title", "")
                
                lines.append(f"  {idx}) {wf_name}")
                lines.append(f"     ID: {wf_id_str}")
                if active_step_title:
                    lines.append(f"     Current: Step {current_step_idx + 1}/{total_steps} — {active_step_title}")
                else:
                    lines.append(f"     Status: {wf_status} ({total_steps} steps)")
                lines.append("")
            
            lines.append("Step 1/1:")
            lines.append("Type a number to select a workflow, or 'cancel' to exit.")
            
            return _base_response(cmd_name, "\n".join(lines), {
                "ok": True,
                "workflows": active_workflows,
                "workflow_count": len(active_workflows),
                "awaiting_selection": True,
                "selection_command": "advance",
            })

    wf = wf_engine.advance(wf_id)
    if not wf:
        return _base_response(cmd_name, f"No such workflow '{wf_id}'.", {"ok": False})

    total = len(wf.steps)
    current_idx = wf.current_step + 1
    
    # Check if workflow is completed
    if wf.status == "completed":
        lines = [
            f"✓ Workflow \"{wf.name}\" completed!",
            f"All {total} steps done.",
        ]
        return _base_response(cmd_name, "\n".join(lines), wf.to_dict())
    
    # Show current step
    current = wf.active_step()
    lines = [
        f"Advanced workflow \"{wf.name}\"",
        "",
        f"Current step [{current_idx}/{total}]:",
    ]
    
    if current:
        lines.append(f"  {current_idx}. {current.title}")
        if current.description:
            # v0.7.12: Show full description (no truncation)
            lines.append(f"   {current.description}")
    
    # v0.7.10: Add hint text
    lines.append("")
    lines.append("(Type '#halt' to pause, '#advance' to go to the next step.)")
    
    extra = wf.to_dict()
    return _base_response(cmd_name, "\n".join(lines), extra)


def handle_halt(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Pause or halt a workflow.
    
    v0.7.11: Number-based selection wizard when no ID provided.
    
    Usage:
        halt                             # Show workflow list
        halt id=<workflow_id>            # Halt specific workflow
        halt id=<workflow_id> status=paused
    """
    from .workflow_selection import set_workflow_selection
    
    wf_engine = kernel.workflow_engine
    wf_id = None
    new_status = "paused"
    from_wizard = False

    if isinstance(args, dict):
        wf_id = args.get("id") or args.get("_", [None])[0]
        new_status = args.get("status", "paused")
        from_wizard = args.get("_from_wizard", False)

    # =================================================================
    # v0.7.11: Show workflow list if no ID provided
    # =================================================================
    if not wf_id:
        all_workflows = wf_engine.summarize_all()
        active_workflows = [w for w in all_workflows if w.get("status") == "active"]
        
        if not active_workflows:
            return _base_response(
                cmd_name,
                "No active workflows to halt. All workflows are already paused or completed.",
                {"ok": True, "no_workflows": True}
            )
        
        # v0.7.11: Auto-halt if only one active workflow
        if len(active_workflows) == 1:
            wf_id = active_workflows[0].get("id")
            # Fall through to halt logic below
        else:
            # Store selection state for numeric input handling
            set_workflow_selection(session_id, "halt", active_workflows)
            
            lines = [
                "╔══ Halt Workflow Wizard ══╗",
                "",
                "Select a workflow to pause:",
                "",
                "Running workflows:",
                "",
            ]
            
            for idx, wf in enumerate(active_workflows, start=1):
                wf_id_str = wf.get("id", "?")
                wf_name = wf.get("name", "Untitled")
                total_steps = wf.get("total_steps", 0)
                current_step_idx = wf.get("current_step_index", 0)
                active_step_title = wf.get("active_step_title", "")
                
                lines.append(f"  {idx}) {wf_name}")
                lines.append(f"     ID: {wf_id_str}")
                if active_step_title:
                    lines.append(f"     Current: Step {current_step_idx + 1}/{total_steps} — {active_step_title}")
                else:
                    lines.append(f"     Progress: Step {current_step_idx + 1}/{total_steps}")
                lines.append("")
            
            lines.append("Step 1/1:")
            lines.append("Type a number to select a workflow, or 'cancel' to exit.")
            
            return _base_response(cmd_name, "\n".join(lines), {
                "ok": True,
                "workflows": active_workflows,
                "workflow_count": len(active_workflows),
                "awaiting_selection": True,
                "selection_command": "halt",
            })

    wf = wf_engine.halt(wf_id, status=new_status)
    if not wf:
        return _base_response(cmd_name, f"No such workflow '{wf_id}'.", {"ok": False})

    lines = [
        f"Workflow \"{wf.name}\" has been {new_status}.",
        f"ID: {wf_id}",
        "",
        f"(Type '#flow' to resume this workflow.)",
    ]
    return _base_response(cmd_name, "\n".join(lines), wf.to_dict())


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
    
    v0.7.10: Enhanced to show goal/purpose for each workflow.

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

    lines = [F.header(f"Known Workflows ({len(summaries)})"), ""]
    
    for wf in summaries:
        wid = wf.get("id")
        name = wf.get("name") or f"Workflow {wid}"
        status = wf.get("status", "unknown")
        step_count = wf.get("total_steps", 0)
        meta_data = wf.get("meta", {}) or {}
        goal = meta_data.get("goal", "")
        
        # Truncate goal if too long
        if goal and len(goal) > 60:
            goal = goal[:57] + "..."
        
        lines.append(f"• {wid} — {name}")
        if goal:
            lines.append(f"  Goal: {goal}")
        lines.append(f"  Status: {status} | Steps: {step_count}")
        lines.append("")

    extra = {
        "ok": True,
        "count": len(summaries),
        "workflows": summaries,
    }
    return _base_response(cmd_name, "\n".join(lines), extra)


def handle_workflow_inspect(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Inspect a workflow and show all its steps.
    
    v0.7.10: Enhanced presentation with goal and full step list.
    
    Usage:
        workflow-inspect id=<workflow_id>
    """
    wf_engine = kernel.workflow_engine
    
    wf_id = None
    if isinstance(args, dict):
        wf_id = args.get("id") or args.get("_", [None])[0]
    
    if not wf_id:
        return _base_response(cmd_name, "Missing workflow id (id=<id>).", {"ok": False})
    
    wf = wf_engine.get(wf_id)
    if not wf:
        return _base_response(cmd_name, f"No workflow found with id '{wf_id}'.", {"ok": False})
    
    goal = wf.meta.get("goal", "") if wf.meta else ""
    total = len(wf.steps)
    current_idx = wf.current_step + 1
    
    lines = [
        f"Workflow: {wf.name} ({wf.id})",
    ]
    
    if goal:
        lines.append(f"Goal: {goal}")
    
    lines.append(f"Status: {wf.status} | Current: step {current_idx}/{total}")
    lines.append("")
    
    if wf.steps:
        lines.append(f"Steps ({total}):")
        for idx, step in enumerate(wf.steps, start=1):
            # Mark current step with arrow
            if idx == current_idx:
                marker = "→"
            elif idx < current_idx:
                marker = "✓"  # Completed
            else:
                marker = " "
            
            lines.append(f"  {marker} {idx}. {step.title}")
            
            # Show description for current step only (to keep output manageable)
            if idx == current_idx and step.description:
                desc = step.description[:80]
                if len(step.description) > 80:
                    desc += "..."
                lines.append(f"       {desc}")
    else:
        lines.append("(No steps defined)")
    
    return _base_response(cmd_name, "\n".join(lines), {"ok": True, "workflow": wf.to_dict()})


def handle_compose(cmd_name, args, session_id, context, kernel, meta) -> KernelResponse:
    """
    Create a workflow with optional LLM-generated steps.
    
    v0.7.10: Full wizard support with confirmation step.

    Usage (Direct - power user):
        #compose name="Morning Routine" goal="Standardize my mornings"
        #compose name="Morning Routine" goal="Standardize my mornings" module="health"
    
    Wizard Mode (no args or NL-triggered):
        #compose
        → Step-by-step wizard: name → goal → manual/auto steps → confirm
    """
    import uuid
    
    # Parse arguments
    args = args if isinstance(args, dict) else {}
    
    # Check if from wizard
    from_wizard = args.get("_from_wizard", False)
    
    if from_wizard:
        # =====================================================================
        # WIZARD FLOW
        # =====================================================================
        name = args.get("name", "").strip()
        goal = args.get("goal", "").strip()
        step_mode = args.get("step_mode", "1")  # Default to auto (1=auto, 2=manual)
        manual_steps = args.get("manual_steps", "").strip()
        confirm = args.get("confirm", "").lower().strip()
        
        # Handle cancel
        if confirm in ["no", "n"]:
            return _base_response(cmd_name, "Okay, not creating anything.", {"ok": True, "cancelled": True})
        
        # Handle edit request
        if confirm == "edit":
            return _base_response(
                cmd_name, 
                "To edit, please run #compose again and provide updated values.",
                {"ok": True, "edit_requested": True}
            )
        
        # Must have confirmed
        if confirm not in ["yes", "y"]:
            return _base_response(cmd_name, "Please confirm with 'yes' or 'no'.", {"ok": False})
        
        # Build steps
        steps = []
        
        # step_mode=2 means manual steps
        if step_mode == "2" and manual_steps:
            # Manual steps: parse bullet lines
            for line in manual_steps.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Remove bullet markers
                for prefix in ["-", "*", "•", "→"]:
                    if line.startswith(prefix):
                        line = line[len(prefix):].strip()
                        break
                # Remove numbered markers like "1." or "1)"
                import re
                line = re.sub(r"^\d+[\.\)]\s*", "", line)
                
                if line:
                    steps.append({
                        "title": line,
                        "description": "",
                    })
        else:
            # Auto-generate steps using LLM (step_mode=1)
            prompt = (
                f"Generate a workflow plan as a JSON array of steps. "
                f"Each step must have: title, description. "
                f"Workflow name: {name}\n"
                f"Goal: {goal}\n"
                f"Return ONLY valid JSON array, no markdown, no explanation."
            )
            
            try:
                llm_result = kernel.llm_client.complete(
                    system="You generate structured workflow plans in JSON. Return only a JSON array.",
                    user=prompt,
                    session_id=session_id,
                )
                
                text = llm_result.get("text", "").strip()
                # Try to extract JSON from response
                if "```" in text:
                    # Extract from code block
                    import re
                    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
                    if match:
                        text = match.group(1).strip()
                
                steps = json.loads(text)
                if not isinstance(steps, list):
                    steps = [steps]
            except Exception as e:
                return _base_response(
                    cmd_name, 
                    f"Failed to generate steps: {e}\nPlease try again or provide manual steps.",
                    {"ok": False, "error": str(e)}
                )
        
        if not steps:
            return _base_response(cmd_name, "No steps provided. Workflow not created.", {"ok": False})
        
        # Generate workflow ID
        wf_id = f"wf-{uuid.uuid4().hex[:8]}"
        
        # Create workflow
        wf_engine = kernel.workflow_engine
        wf = wf_engine.start(
            workflow_id=wf_id,
            name=name,
            steps=steps,
            meta={
                "source": "compose",
                "goal": goal,
                "session_id": session_id,
            },
        )
        
        # Format output
        formatted_steps = []
        for idx, step in enumerate(steps, start=1):
            title = step.get("title", f"Step {idx}")
            desc = step.get("description", "")
            if desc:
                formatted_steps.append(f"  {idx}. {title}\n     {desc}")
            else:
                formatted_steps.append(f"  {idx}. {title}")
        
        lines = [
            F.header(f"Created workflow \"{name}\""),
            "",
            f"ID: {wf_id}",
            f"Goal: {goal}",
            f"Steps: {len(steps)}",
            "",
        ]
        lines.extend(formatted_steps)
        lines.append("")
        lines.append("Use #flow to start it.")
        
        return _base_response(cmd_name, "\n".join(lines), {
            "ok": True,
            "workflow_id": wf_id,
            "workflow": wf.to_dict(),
        })
    
    else:
        # =====================================================================
        # DIRECT CALL (power user mode)
        # =====================================================================
        name = args.get("name", "").strip()
        goal = args.get("goal", "").strip()
        
        # Backward compat: support old 'id' + 'goal' syntax
        wf_id = args.get("id") or args.get("workflow")
        
        # If only goal provided (old syntax), use goal as both name and goal
        if goal and not name:
            name = goal
        
        if not name or not goal:
            return _base_response(
                cmd_name, 
                "compose requires name=<text> goal=<text>\n\n"
                "Example: #compose name=\"Morning Routine\" goal=\"Standardize my mornings\"\n\n"
                "Or run #compose without arguments to start the wizard.",
                {"ok": False}
            )
        
        # Auto-generate steps
        prompt = (
            f"Generate a workflow plan as a JSON array of steps. "
            f"Each step must have: title, description. "
            f"Workflow name: {name}\n"
            f"Goal: {goal}\n"
            f"Return ONLY valid JSON array, no markdown."
        )
        
        try:
            llm_result = kernel.llm_client.complete(
                system="You generate structured workflow plans in JSON. Return only a JSON array.",
                user=prompt,
                session_id=session_id,
            )
            
            text = llm_result.get("text", "").strip()
            # Extract JSON
            if "```" in text:
                import re
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
                if match:
                    text = match.group(1).strip()
            
            steps = json.loads(text)
            if not isinstance(steps, list):
                steps = [steps]
        except Exception as e:
            return _base_response(
                cmd_name,
                f"Failed to generate steps: {e}",
                {"ok": False, "error": str(e)}
            )
        
        # Generate ID if not provided
        if not wf_id:
            wf_id = f"wf-{uuid.uuid4().hex[:8]}"
        
        # Create workflow
        wf_engine = kernel.workflow_engine
        wf = wf_engine.start(
            workflow_id=str(wf_id),
            name=name,
            steps=steps,
            meta={
                "source": "compose",
                "goal": goal,
                "session_id": session_id,
            },
        )
        
        # Format output
        formatted_steps = []
        for idx, step in enumerate(steps, start=1):
            title = step.get("title", f"Step {idx}")
            formatted_steps.append(f"  {idx}. {title}")
        
        lines = [
            f"Created workflow \"{name}\" with id={wf_id}",
            f"Goal: {goal}",
            "",
        ]
        lines.extend(formatted_steps)
        lines.append("")
        lines.append("Use #flow to start it.")
        
        return _base_response(cmd_name, "\n".join(lines), {
            "ok": True,
            "workflow_id": wf_id,
            "workflow": wf.to_dict(),
        })


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

    # Prefer explicit steps from metadata or args
    steps = meta.get("steps") if isinstance(meta, dict) else None
    if not steps and isinstance(args, dict):
        steps = args.get("steps")

    # Fallback: derive steps from chain_list (wizard v0.5.2)
    if (not steps or not isinstance(steps, list)) and isinstance(meta, dict):
        chain_list = meta.get("chain_list")
        if isinstance(chain_list, list) and chain_list:
            # Normalize: "help" -> {"command": "help"}
            steps = []
            for c in chain_list:
                if isinstance(c, str):
                    steps.append({"command": c})
                elif isinstance(c, dict) and "command" in c:
                    steps.append(c)
                else:
                    # Skip unusable entries
                    continue

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
    "handle_wm_debug": handle_wm_debug,  # v0.7: Working Memory debug
    "handle_behavior_debug": handle_behavior_debug,  # v0.7.2: Behavior Layer debug
    # v0.7.3: New WM/Behavior commands
    "handle_wm_clear_cmd": handle_wm_clear_cmd,
    "handle_wm_clear_topic": handle_wm_clear_topic,
    "handle_behavior_mode": handle_behavior_mode,
    "handle_wm_snapshot": handle_wm_snapshot,
    "handle_wm_topics": handle_wm_topics,
    "handle_wm_switch": handle_wm_switch,
    # v0.7.3: Episodic Memory Bridge (Option B)
    "handle_wm_restore": handle_wm_restore,
    "handle_wm_mode": handle_wm_mode,
    "handle_episodic_list": handle_episodic_list,
    "handle_episodic_debug": handle_episodic_debug,
    # v0.7.6: WM Persistence Layer
    "handle_wm_load": handle_wm_load,
    "handle_wm_bridge": handle_wm_bridge,
    # v0.7.7: Group Entity Layer
    "handle_wm_groups": handle_wm_groups,
    # v0.7.8: Self-Test + Stability
    "handle_self_test": handle_self_test,
    "handle_diagnostics": handle_diagnostics,
    # v0.7.9: Module-Aware Working Memory
    "handle_wm_status": handle_wm_status,
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

    # v0.8.0: Legacy workflow handlers REMOVED — Quest Engine replaces them
    # "handle_flow": handle_flow,           # REMOVED
    # "handle_advance": handle_advance,     # REMOVED
    # "handle_halt": handle_halt,           # REMOVED
    # "handle_compose": handle_compose,     # REMOVED (workflow version)

    # v0.4 Time Rhythm
    "handle_presence": handle_presence,
    "handle_pulse": handle_pulse,
    "handle_align": handle_align,

    # v0.4.1 Reminders
    "handle_remind_add": handle_remind_add,
    "handle_remind_list": handle_remind_list,
    "handle_remind_update": handle_remind_update,
    "handle_remind_delete": handle_remind_delete,

    # v0.8.0: Legacy workflow handlers REMOVED — Quest Engine replaces them
    # "handle_workflow_delete": handle_workflow_delete,   # REMOVED
    # "handle_workflow_list": handle_workflow_list,       # REMOVED  
    # "handle_workflow_inspect": handle_workflow_inspect, # REMOVED
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

    # v0.5.3 Model Routing
    "handle_model_info": handle_model_info,

    # v0.5.4 Memory Engine
    "handle_memory_stats": handle_memory_stats,
    "handle_memory_salience": handle_memory_salience,
    "handle_memory_status": handle_memory_status,
    "handle_memory_high_salience": handle_memory_high_salience,

    # v0.5.5 Identity Profile
    "handle_identity_show": handle_identity_show,
    "handle_identity_set": handle_identity_set,
    "handle_identity_snapshot": handle_identity_snapshot,
    "handle_identity_history": handle_identity_history,
    "handle_identity_restore": handle_identity_restore,
    "handle_identity_clear_history": handle_identity_clear_history,

    # v0.5.6 Memory Lifecycle
    "handle_memory_decay": handle_memory_decay,
    "handle_memory_drift": handle_memory_drift,
    "handle_memory_reconfirm": handle_memory_reconfirm,
    "handle_memory_stale": handle_memory_stale,
    "handle_memory_archive_stale": handle_memory_archive_stale,
    "handle_decay_preview": handle_decay_preview,

    # v0.5.7 Memory Policy
    "handle_memory_policy": handle_memory_policy,
    "handle_memory_policy_test": handle_memory_policy_test,
    "handle_memory_mode_filter": handle_memory_mode_filter,

    # v0.5.8 Continuity
    "handle_preferences": handle_preferences,
    "handle_projects": handle_projects,
    "handle_continuity_context": handle_continuity_context,
    "handle_reconfirm_prompts": handle_reconfirm_prompts,
    "handle_suggest_workflow": handle_suggest_workflow,

    # v0.5.9 Human State
    "handle_evolution_status": handle_evolution_status,
    "handle_log_state": handle_log_state,
    "handle_state_history": handle_state_history,
    "handle_capacity_check": handle_capacity_check,

    # v0.6 Sectioned Help and Section Menus
    "handle_help_v06": handle_help_v06,
    "handle_section_core": handle_section_core,
    "handle_section_memory": handle_section_memory,
    "handle_section_continuity": handle_section_continuity,
    "handle_section_human_state": handle_section_human_state,
    "handle_section_modules": handle_section_modules,
    "handle_section_identity": handle_section_identity,
    "handle_section_system": handle_section_system,
    "handle_section_workflow": handle_section_workflow,
    "handle_section_timerhythm": handle_section_timerhythm,
    "handle_section_reminders": handle_section_reminders,
    "handle_section_commands": handle_section_commands,
    "handle_section_interpretation": handle_section_interpretation,
    "handle_section_debug": handle_section_debug,
    "handle_section_inbox": handle_section_inbox,  # v0.8.0


}

# =============================================================================
# v0.8.0: Quest Engine Integration
# =============================================================================
# Add quest handlers to SYS_HANDLERS (replaces legacy workflow commands)
if _HAS_QUEST_ENGINE:
    SYS_HANDLERS.update(get_quest_handlers())

# v0.8.0: Inbox handlers
if _HAS_INBOX:
    SYS_HANDLERS.update(get_inbox_handlers())

# v0.8.0: Player Profile handlers
if _HAS_PLAYER_PROFILE:
    SYS_HANDLERS.update(get_player_profile_handlers())

# v0.8.0: Module Manager handlers (regions/world map)
if _HAS_MODULE_MANAGER:
    SYS_HANDLERS.update(get_module_handlers())

# v0.8.0: Assistant Mode handlers (story vs utility)
if _HAS_ASSISTANT_MODE:
    SYS_HANDLERS.update(get_assistant_mode_handlers())

# v0.8.0: Strategist handlers (analyze, route, insight)
if _HAS_STRATEGIST:
    SYS_HANDLERS.update(get_strategist_handlers())

# v0.8.0: Time Rhythm handlers (presence, pulse, align, weekly-review)
if _HAS_TIME_RHYTHM:
    SYS_HANDLERS.update(get_time_rhythm_handlers())
