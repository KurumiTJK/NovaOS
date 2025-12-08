# kernel/syscommand_router.py
"""
v0.8.1 — Syscommand Router (Zero-Latency)

Simple syscommands execute instantly with NO LLM API calls.
Routing decisions are logged locally without network requests.

Architecture:
- Simple commands (#help, #status, etc.): Pure Python, ~0ms latency
- LLM-intensive commands (#compose, etc.): Use LLM, ~1-2s latency

Flow for simple commands:
1. Python handler executes → CommandResponse
2. ModelRouter.route() logs decision (NO API call)
3. Return response instantly

Flow for LLM-intensive commands:
1. Python handler calls _llm_with_policy internally
2. LLM API call made with gpt-5.1
3. Return LLM-generated response
"""

from __future__ import annotations

from typing import Any, Dict, Callable

from .command_types import CommandRequest, CommandResponse
from . import syscommands

HandlerFn = Callable[..., CommandResponse]

# Commands that should skip LLM post-processing (already use LLM internally)
# These commands call _llm_with_policy or llm_client directly
SKIP_LLM_POSTPROCESS = {
    "compose",
    "prompt_command",
    "prompt-command",
    "command-wizard",
}


class SyscommandRouter:
    """
    v0.8.1: Zero-latency syscommand routing.
    
    - Simple commands: Pure Python, routing logged locally, NO API call
    - LLM-intensive commands: Use gpt-5.1 via internal _llm_with_policy
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
        v0.7.15: Log routing decision WITHOUT making an LLM call.
        
        This triggers:
        1. ModelRouter.route() → model selection + logging
        
        NO API call is made. Zero latency. Zero tokens.
        """
        try:
            # Just call the router to get routing decision + logging
            # This does NOT make an API call
            from backend.model_router import RoutingContext
            ctx = RoutingContext(
                command=cmd_name,
                input_length=0,
                think_mode=False,
            )
            kernel.model_router.route(ctx)
            # That's it - routing logged, no API call
        except Exception as e:
            print(f"[SyscommandRouter] routing log failed: {e}", flush=True)

    def route(self, request: CommandRequest, kernel: Any) -> CommandResponse:
        """
        Route a syscommand request to its handler.
        
        v0.7.12: ALL commands now trigger LLM logging via post-processing.
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
            
            # v0.7.15: Log routing decision (NO API call, zero latency)
            # Skip if command already uses LLM internally (they do their own logging)
            if request.cmd_name.lower() not in SKIP_LLM_POSTPROCESS:
                self._log_routing_decision(
                    kernel=kernel,
                    cmd_name=request.cmd_name,
                )
            
            # Return original Python handler response (instant)
            return response
            
        except Exception as e:
            kernel.logger.log_exception(request.session_id, request.cmd_name, e)
            return CommandResponse(
                ok=False,
                command=request.cmd_name,
                summary=f"Exception in '{request.cmd_name}': {e}",
                error_code="EXCEPTION",
                error_message=str(e),
            )
