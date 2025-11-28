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
    """

    def __init__(self, commands: Dict[str, Any]):
        self.commands = commands
        # Map handler_name (from commands.json) -> actual function
        self.handlers: Dict[str, HandlerFn] = {
            "handle_why": syscommands.handle_why,
            "handle_boot": syscommands.handle_boot,
            "handle_status": syscommands.handle_status,
            "handle_help": syscommands.handle_help,
            "handle_reset": syscommands.handle_reset,
            # later: add memory/module/workflow handlers from other files
        }

    def route(self, request: CommandRequest, kernel: Any) -> CommandResponse:

        meta = self.commands.get(request.cmd_name)
        if not meta:
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

        # v0.2 behavior: mark session as booted before executing any command
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
