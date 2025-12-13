# kernel/syscommand_router.py
"""
v0.9.1 — Syscommand Router (DETERMINISTIC, NO FALLBACK)

v0.9.1 CHANGES:
- Removed "command-wizard" from SKIP_LLM_POSTPROCESS (Commands feature removed)

🔥 v0.9.0 CHANGES:
- Enhanced logging: logs command + model for every syscommand
- Deterministic routing via ModelRouter
- NO FALLBACK behavior
- Explicit model logging in route() method

Architecture:
- Simple commands (#help, #status, etc.): Pure Python, ~0ms latency
- LLM-intensive commands (#compose, etc.): Use LLM, ~1-2s latency

Flow for simple commands:
1. Python handler executes → CommandResponse
2. ModelRouter.route() logs decision (NO API call)
3. Return response instantly

Flow for LLM-intensive commands:
1. Python handler calls _llm_with_policy internally
2. LLM API call made with appropriate model
3. Return LLM-generated response
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Callable

from .command_types import CommandRequest, CommandResponse
from . import syscommands

HandlerFn = Callable[..., CommandResponse]


# Commands that should skip LLM post-processing (already use LLM internally)
# These commands call _llm_with_policy or llm_client directly
SKIP_LLM_POSTPROCESS = {
    # Heavy LLM commands
    "compose",
    "prompt_command",
    "prompt-command",
    "quest-compose",
    "quest-delete",
    "flow",
    "advance",
    "interpret",
    "derive",
    "analyze",
}


class SyscommandRouter:
    """
    v0.9.0: Deterministic syscommand routing with enhanced logging.
    
    - Simple commands: Pure Python, routing logged locally, NO API call
    - LLM-intensive commands: Use appropriate model via internal _llm_with_policy
    """

    def __init__(self, commands: Any):
        self.commands: Dict[str, Dict[str, Any]] = self._normalize_commands(commands)
        self.handlers: Dict[str, HandlerFn] = dict(syscommands.SYS_HANDLERS)

    def _normalize_commands(self, raw: Any) -> Dict[str, Dict[str, Any]]:
        """Normalize command registry into dict format."""
        if isinstance(raw, dict):
            return raw

        normalized: Dict[str, Dict[str, Any]] = {}

        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue

                name = entry.get("name") or entry.get("command") or entry.get("cmd")
                if name:
                    meta = {
                        k: v
                        for k, v in entry.items()
                        if k not in ("name", "command", "cmd")
                    }
                    normalized[name] = meta
                    continue

                if len(entry) == 1:
                    k, v = next(iter(entry.items()))
                    if isinstance(v, dict):
                        normalized[k] = v
                    continue

        return normalized

    def _log_routing_decision(
        self,
        kernel: Any,
        cmd_name: str,
    ) -> None:
        """
        v0.9.0: Log routing decision WITHOUT making an LLM call.
        
        This triggers:
        1. ModelRouter.route() → model selection + logging
        
        NO API call is made. Zero latency. Zero tokens.
        """
        try:
            from backend.model_router import RoutingContext, is_heavy_command, is_light_command
            
            ctx = RoutingContext(
                command=cmd_name,
                input_length=0,
                think_mode=False,
            )
            
            # This logs the routing decision via ModelRouter
            model = kernel.model_router.route(ctx)
            
            # Additional logging for clarity
            cmd_type = "heavy" if is_heavy_command(cmd_name) else "light"
            print(f"[SyscommandRouter] routed command={cmd_name} type={cmd_type} model={model}", flush=True)
            
        except Exception as e:
            print(f"[SyscommandRouter] routing log failed: {e}", file=sys.stderr, flush=True)

    def route(self, request: CommandRequest, kernel: Any) -> CommandResponse:
        """
        Route a syscommand request to its handler.
        
        v0.9.0: Enhanced logging, deterministic routing.
        """
        # Look up meta from normalized dict
        meta = self.commands.get(request.cmd_name)

        # Handle list-shaped meta (legacy)
        if isinstance(meta, list):
            if not meta:
                return CommandResponse(
                    ok=False,
                    command=request.cmd_name,
                    summary=f"Invalid command metadata for '{request.cmd_name}' (empty list).",
                    error_code="BAD_COMMAND_META",
                    error_message=f"Invalid command metadata for '{request.cmd_name}'.",
                )
            first = meta[0]
            if isinstance(first, dict):
                meta = first
                self.commands[request.cmd_name] = meta
            else:
                return CommandResponse(
                    ok=False,
                    command=request.cmd_name,
                    summary=f"Invalid command metadata for '{request.cmd_name}' (list of non-dicts).",
                    error_code="BAD_COMMAND_META",
                    error_message=f"Invalid command metadata for '{request.cmd_name}'.",
                )

        # Fallback to request.meta for custom commands
        if (not meta or not isinstance(meta, dict)) and getattr(request, "meta", None):
            meta = request.meta
            if isinstance(meta, dict):
                self.commands[request.cmd_name] = meta

        if not meta or not isinstance(meta, dict):
            return CommandResponse(
                ok=False,
                command=request.cmd_name,
                summary=f"Unknown command '{request.cmd_name}'",
                error_code="UNKNOWN_COMMAND",
                error_message=f"Unknown command '{request.cmd_name}'",
            )

        handler_name = meta.get("handler")
        handler = self.handlers.get(handler_name)
        if handler is None:
            return CommandResponse(
                ok=False,
                command=request.cmd_name,
                summary=f"No handler for command '{request.cmd_name}'",
                error_code="NO_HANDLER",
                error_message=f"No handler for '{request.cmd_name}'",
            )

        context = kernel.context_manager.get_context(request.session_id)

        # v0.9.0: Log which command is being executed BEFORE execution
        print(f"[SyscommandRouter] executing command={request.cmd_name} handler={handler_name}", flush=True)

        try:
            # Execute the handler
            response = handler(
                cmd_name=request.cmd_name,
                args=request.args,
                session_id=request.session_id,
                context=context,
                kernel=kernel,
                meta=meta,
            )
            
            # v0.9.0: Log routing decision (NO API call, zero latency)
            # Skip if command already uses LLM internally (they do their own logging)
            if request.cmd_name.lower() not in SKIP_LLM_POSTPROCESS:
                self._log_routing_decision(
                    kernel=kernel,
                    cmd_name=request.cmd_name,
                )
            
            # v0.9.0: Log completion
            print(f"[SyscommandRouter] completed command={request.cmd_name} ok={response.ok}", flush=True)
            
            # Return original Python handler response (instant)
            return response
            
        except Exception as e:
            print(f"[SyscommandRouter] EXCEPTION command={request.cmd_name} error={e}", file=sys.stderr, flush=True)
            kernel.logger.log_exception(request.session_id, request.cmd_name, e)
            return CommandResponse(
                ok=False,
                command=request.cmd_name,
                summary=f"Exception in '{request.cmd_name}': {e}",
                error_code="EXCEPTION",
                error_message=str(e),
            )
