# kernel/syscommand_router.py
from __future__ import annotations

from typing import Any, Dict, Callable

from .command_types import CommandRequest, CommandResponse
from . import syscommands  # for now, this is your "core_commands" module

HandlerFn = Callable[..., CommandResponse]


class SyscommandRouter:
    """
    Resolves cmd_name -> handler function and executes it.
    Keeps NovaKernel small and focused.

    v0.3: robust to both dict and list-shaped command registries.
    """

    def __init__(self, commands: Any):
        # Normalize any incoming registry into a dict
        self.commands: Dict[str, Dict[str, Any]] = self._normalize_commands(commands)
        # Central handler table from syscommands
        self.handlers: Dict[str, HandlerFn] = dict(syscommands.SYS_HANDLERS)

    # ----------------- internal helpers -----------------

    def _normalize_commands(self, raw: Any) -> Dict[str, Dict[str, Any]]:
        """
        Ensure we always have a dict: { cmd_name: meta_dict }.

        Handles:
        - dict: { "boot": {...}, "status": {...} }
        - list of dicts with 'name' / 'command' / 'cmd'
        - list of single-key dicts: [{ "boot": {...} }, { "status": {...} }]
        """
        if isinstance(raw, dict):
            return raw

        normalized: Dict[str, Dict[str, Any]] = {}

        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue

                # Shape A: explicit name field
                name = entry.get("name") or entry.get("command") or entry.get("cmd")
                if name:
                    meta = {
                        k: v
                        for k, v in entry.items()
                        if k not in ("name", "command", "cmd")
                    }
                    normalized[name] = meta
                    continue

                # Shape B: { "boot": {...} }
                if len(entry) == 1:
                    k, v = next(iter(entry.items()))
                    if isinstance(v, dict):
                        normalized[k] = v
                    continue

        return normalized

    # ----------------- routing -----------------

    def route(self, request: CommandRequest, kernel: Any) -> CommandResponse:
        # Look up meta from normalized dict (or whatever was passed in)
        meta = self.commands.get(request.cmd_name)

        # If meta is accidentally stored as a list, try to unwrap it
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
                # Convert to dict form in-memory so future lookups are clean
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
                error_message=f"No handler for command '{request.cmd_name}'",
            )

        # Context is still sourced from ContextManager
        context = kernel.context_manager.get_context(request.session_id)

        try:
            return handler(
                cmd_name=request.cmd_name,
                args=request.args,
                session_id=request.session_id,
                context=context,
                kernel=kernel,
                meta=meta,
            )
        except Exception as e:
            kernel.logger.log_exception(request.session_id, request.cmd_name, e)
            return CommandResponse(
                ok=False,
                command=request.cmd_name,
                summary=f"Exception in '{request.cmd_name}': {e}",
                error_code="EXCEPTION",
                error_message=str(e),
            )
