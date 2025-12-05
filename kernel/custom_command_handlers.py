# kernel/custom_command_handlers.py
"""
v0.7.17 — Enhanced Custom Command Handlers

This module contains updated handlers for the custom command system:
- handle_command_add_with_wizard: Add commands via wizard OR direct mode
- handle_prompt_command_v2: Execute custom commands with enhanced metadata
- handle_command_list_v2: Show enhanced metadata in listings
- handle_command_inspect_v2: Show all v0.7.16 fields

WIZARD MODE:
    #command-add          → starts interactive wizard
    #command-add name=... → direct creation (existing behavior)

INTEGRATION:

    To use these handlers, update SYS_HANDLERS in syscommands.py:
    
        from .custom_command_handlers import get_v2_handlers
        
        SYS_HANDLERS.update(get_v2_handlers())
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .command_types import CommandResponse
from .formatting import OutputFormatter as F
from .custom_command_v2 import (
    normalize_custom_command_v2,
    build_system_prompt,
    render_user_prompt,
    execute_custom_prompt_command,
    format_command_for_list,
    format_command_for_inspect,
    OUTPUT_STYLES,
    PERSONA_MODES,
)

# v0.7.17: Import wizard handler
from .command_add_wizard import (
    handle_command_add_with_wizard,
    is_command_add_wizard_active,
    clear_command_add_wizard,
)


# =============================================================================
# HELPER
# =============================================================================

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


# =============================================================================
# handle_prompt_command_v2
# =============================================================================

def handle_prompt_command_v2(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    v0.7.16 — Execute an enhanced custom prompt command.
    
    This handler:
    1. Normalizes the command config with v0.7.16 fields
    2. Builds system prompt with style/strict/persona/examples
    3. Calls complete_system() with appropriate model tier
    4. Triggers routing + logging automatically
    
    Enhanced fields:
    - intensive: If true, uses gpt-5.1 (think mode)
    - output_style: Controls response format (bullets, short, etc.)
    - examples: Few-shot examples included in system prompt
    - strict: If true, instructs LLM not to improvise
    - persona_mode: Controls tone (nova, neutral, professional)
    """
    # Safety: require prompt_template
    template = meta.get("prompt_template")
    if not template:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary=f"Custom command '{cmd_name}' missing prompt_template.",
            error_code="MISSING_TEMPLATE",
            error_message="No prompt_template defined",
        )
    
    # Normalize config with v0.7.16 fields
    cmd_config = normalize_custom_command_v2(cmd_name, meta)
    
    # Execute via the v2 executor
    response = execute_custom_prompt_command(
        kernel=kernel,
        cmd_name=cmd_name,
        cmd_config=cmd_config,
        args=args if isinstance(args, dict) else {},
        session_id=session_id,
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # Post-Actions (preserve v0.5.1 behavior)
    # ─────────────────────────────────────────────────────────────────────
    post_actions = meta.get("post_actions") or []
    if post_actions and response.ok:
        output_text = response.data.get("result", "") if response.data else ""
        user_input = args.get("full_input", "") if isinstance(args, dict) else ""
        
        post_action_summaries = _execute_post_actions(
            kernel=kernel,
            session_id=session_id,
            post_actions=post_actions,
            user_input=user_input,
            llm_output=output_text,
        )
        
        if post_action_summaries:
            # Append post-action results to response
            response = CommandResponse(
                ok=response.ok,
                command=response.command,
                summary=response.summary + "\n\n" + "\n".join(post_action_summaries),
                data=response.data,
                type=response.type,
            )
    
    return response


def _execute_post_actions(
    kernel: Any,
    session_id: str,
    post_actions: list,
    user_input: str,
    llm_output: str,
) -> list:
    """Execute post-actions after a custom command completes."""
    from .command_types import CommandRequest
    
    summaries = []
    router = kernel.router
    
    for action in post_actions:
        if not isinstance(action, dict):
            continue
        
        action_type = action.get("type")
        if action_type != "syscommand":
            continue
        
        target_cmd = action.get("command")
        if not target_cmd:
            continue
        
        args_mode = action.get("args_mode", "pass_result")
        base_args = dict(action.get("args") or {})
        silent = action.get("silent", False)
        
        # Build payload based on args_mode
        if args_mode == "pass_input":
            base_args["content"] = user_input
        elif args_mode == "pass_result":
            base_args["content"] = llm_output
        elif args_mode == "pass_both":
            base_args["input"] = user_input
            base_args["result"] = llm_output
            base_args["content"] = llm_output
        
        # Execute via router
        try:
            req = CommandRequest(
                cmd_name=target_cmd,
                args=base_args,
                session_id=session_id,
                raw_text=f"#{target_cmd}",
            )
            result = router.route(req, kernel)
            
            if not silent and result.ok:
                summaries.append(f"→ {target_cmd}: {result.summary[:100]}")
        except Exception as e:
            if not silent:
                summaries.append(f"→ {target_cmd}: (error) {e}")
    
    return summaries


# =============================================================================
# handle_command_add_v2
# =============================================================================

def handle_command_add_v2(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    v0.7.16 — Add a new custom command with enhanced options.
    
    Required fields:
    - name: Command name (e.g., "daily-reflect")
    - kind: "prompt" or "macro"
    - prompt_template: The prompt template (for kind=prompt)
    
    Optional enhanced fields:
    - intensive: true/false (default: false) - use gpt-5.1 if true
    - model_tier: "mini" or "thinking" (alternative to intensive)
    - output_style: "natural" | "bullets" | "numbered" | "short" | "verbose" | "json"
    - examples: JSON array of {input, output} pairs
    - strict: true/false (default: false) - no improvisation
    - persona_mode: "nova" | "neutral" | "professional"
    - description: Help text for the command
    
    Example:
        #command-add name=summarize kind=prompt \\
            prompt_template="Summarize: {{full_input}}" \\
            intensive=false \\
            output_style=bullets \\
            strict=true
    """
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
    tier = "gpt-5.1 (thinking)" if normalized.get("intensive") else "gpt-4.1-mini"
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
    return _base_response(cmd_name, summary, normalized)


# =============================================================================
# handle_command_list_v2
# =============================================================================

def handle_command_list_v2(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    v0.7.16 — List commands with enhanced metadata display.
    
    Shows:
    - Command name
    - Kind (prompt/macro)
    - Status (enabled/disabled)
    - Model tier (⚡=mini, 🧠=thinking)
    - Output style (if not natural)
    - Strict flag
    - Example count
    """
    custom = kernel.custom_registry.list()
    core = kernel.commands
    
    formatted_core = []
    formatted_custom = []
    
    # Core commands (unchanged)
    for name, m in core.items():
        desc = m.get("description", "")
        formatted_core.append(f"  {name}: {desc[:50]}" if desc else f"  {name}")
    
    # Custom commands with enhanced display
    for name, m in custom.items():
        # Normalize to get v0.7.16 fields
        normalized = normalize_custom_command_v2(name, m)
        formatted_custom.append(format_command_for_list(name, normalized))
    
    # Legend for symbols
    legend = "Legend: ⚡=mini model, 🧠=thinking model"
    
    summary = (
        F.header("Commands") +
        F.subheader("Core Commands") +
        "\n".join(formatted_core[:20]) +  # Limit core display
        (f"\n  ... and {len(formatted_core) - 20} more" if len(formatted_core) > 20 else "") +
        "\n\n" +
        F.subheader("Custom Commands") +
        ("\n".join(f"  {c}" for c in formatted_custom) if formatted_custom else "  (none)") +
        f"\n\n{legend}"
    )
    
    return _base_response(cmd_name, summary, {"custom": custom, "core": core})


# =============================================================================
# handle_command_inspect_v2
# =============================================================================

def handle_command_inspect_v2(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    v0.7.16 — Inspect a custom command with full enhanced metadata.
    
    Shows all fields including:
    - Basic: name, kind, enabled, handler
    - Model: intensive, model_tier
    - Output: output_style, strict, persona_mode
    - Examples: count and preview
    - Template: prompt_template preview
    """
    name = None
    if isinstance(args, dict):
        name = args.get("name") or (args.get("_", [None])[0] if args.get("_") else None)
    
    if not name:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Usage: #command-inspect name=<command>",
            error_code="MISSING_NAME",
            error_message="Command name required",
        )
    
    entry = kernel.custom_registry.get(name)
    if not entry:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary=f"No custom command '{name}' found.",
            error_code="NOT_FOUND",
            error_message=f"Command '{name}' does not exist",
        )
    
    # Normalize with v0.7.16 fields
    normalized = normalize_custom_command_v2(name, entry)
    
    # Format for display
    display = format_command_for_inspect(normalized)
    
    # Also include raw JSON for debugging
    raw_json = json.dumps(normalized, indent=2, ensure_ascii=False)
    
    summary = (
        F.header(f"Command: #{name}") +
        display +
        "\n\n" +
        F.subheader("Raw Configuration") +
        f"\n```json\n{raw_json}\n```"
    )
    
    return _base_response(cmd_name, summary, {"command": normalized})


# =============================================================================
# INTEGRATION PATCH
# =============================================================================

def get_v2_handlers() -> Dict[str, Any]:
    """
    Get all v0.7.17 enhanced handlers.
    
    Usage in syscommands.py:
        from .custom_command_handlers import get_v2_handlers
        SYS_HANDLERS.update(get_v2_handlers())
    
    Note: handle_command_add now supports wizard mode when called without args.
    """
    return {
        "handle_prompt_command": handle_prompt_command_v2,
        "handle_command_add": handle_command_add_with_wizard,  # v0.7.17: wizard support
        "handle_command_list": handle_command_list_v2,
        "handle_command_inspect": handle_command_inspect_v2,
    }


# =============================================================================
# NORMALIZER PATCH
# =============================================================================

def patch_normalizer():
    """
    Patch nova_registry._normalize_custom_command to use v0.7.16 version.
    
    Call this once at startup:
        from .custom_command_handlers import patch_normalizer
        patch_normalizer()
    """
    import sys
    if 'system.nova_registry' in sys.modules:
        import system.nova_registry as registry
        registry._normalize_custom_command = normalize_custom_command_v2
        print("[CustomCommands] Patched normalizer to v0.7.16", flush=True)
