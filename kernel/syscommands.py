# kernel/syscommands.py
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


SYS_HANDLERS: Dict[str, Callable[..., KernelResponse]] = {
    "handle_why": handle_why,
    "handle_boot": handle_boot,
    "handle_status": handle_status,
    "handle_help": handle_help,
    "handle_reset": handle_reset,
}