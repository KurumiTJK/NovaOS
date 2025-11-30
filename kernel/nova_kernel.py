# kernel/nova_kernel.py
from typing import Dict, Any

from backend.llm_client import LLMClient
from system.config import Config
from system import nova_registry
from persona.nova_persona import BASE_SYSTEM_PROMPT
from .command_types import CommandRequest, CommandResponse
from .syscommand_router import SyscommandRouter
from .context_manager import ContextManager
from .memory_manager import MemoryManager
from .policy_engine import PolicyEngine
from .logger import KernelLogger


class NovaKernel:
    """
    NovaOS kernel orchestrator.
    - Parses input
    - Builds CommandRequest objects
    - Routes syscommands via SyscommandRouter
    - Coordinates memory, modules, persona, and backend calls
    """

    def __init__(
        self,
        config: Config,
        llm_client: LLMClient | None = None,
        context_manager: ContextManager | None = None,
        memory_manager: MemoryManager | None = None,
        policy_engine: PolicyEngine | None = None,
        logger: KernelLogger | None = None,
        router: SyscommandRouter | None = None,
    ):
        self.config = config

        # Dependencies (decoupled but with sensible defaults)
        self.llm_client = llm_client or LLMClient()
        self.context_manager = context_manager or ContextManager(config=config)
        self.memory_manager = memory_manager or MemoryManager(config=config)
        self.policy_engine = policy_engine or PolicyEngine(config=config)
        self.logger = logger or KernelLogger(config=config)

        # Command registry + router + modules
        raw_commands = nova_registry.load_commands(config=self.config)
        self.commands = self._normalize_commands(raw_commands)
        self.module_registry = nova_registry.ModuleRegistry(config=config)
        self.router = router or SyscommandRouter(self.commands)

        # -------------------------------------------------------------
        # v0.4: Add TimeRhythmEngine + WorkflowEngine
        # -------------------------------------------------------------
        from kernel.time_rhythm import TimeRhythmEngine
        from kernel.workflow_engine import WorkflowEngine
        from kernel.reminders_manager import RemindersManager

        # For v0.4, initialize fresh engines each run.
        # We can wire real persistence later without touching MemoryManager.
        self.time_rhythm_engine = TimeRhythmEngine()
        self.workflow_engine = WorkflowEngine()

        # v0.4.1: Reminders subsystem
        self.reminders = RemindersManager(self.config.data_dir)


    # ------------------------------------------------------------------
    # Core input handling
    # ------------------------------------------------------------------

    def handle_input(self, text: str, session_id: str) -> Dict[str, Any]:
        """
        Entry point for all UI input.
        Returns a structured dict suitable for the UI.

        v0.3:
        1) If first token matches a syscommand -> route directly.
        2) Else attempt minimal NL → command interpretation (memory only).
        3) Else fall back to Nova persona (_handle_natural_language).
        """
        self.logger.log_input(session_id, text)

        if not text.strip():
            return self._error("EMPTY_INPUT", "No input provided.").to_dict()

        stripped = text.strip()
        tokens = stripped.split()
        cmd_name = tokens[0].lower()
        args_str = " ".join(tokens[1:]) if len(tokens) > 1 else ""

        # 1) Explicit syscommand: first token matches commands.json
        if cmd_name in self.commands:
            args_dict = self._parse_args(args_str)
            request = CommandRequest(
                cmd_name=cmd_name,
                args=args_dict,
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get(cmd_name),
            )
            response = self.router.route(request, kernel=self)
            self.logger.log_response(session_id, cmd_name, response.to_dict())
            return response.to_dict()

        # 2) NL → command interpretation (memory-only for v0.3)
        interpreted = self._interpret_nl_to_command(stripped, session_id)
        if interpreted is not None:
            response = self.router.route(interpreted, kernel=self)
            self.logger.log_response(session_id, interpreted.cmd_name, response.to_dict())
            return response.to_dict()
        
        # -------------------------------------------------------------
        # v0.4.1 — Reminder checking (no background threads)
        # -------------------------------------------------------------
        due = self.reminders.check_due()
        if due:
            lines = []
            items = []
            for r in due:
                line = f"🔔 Reminder: {r.title}  (when={r.when}, id={r.id})"
                lines.append(line)
                items.append(r.to_dict())

            return {
                "ok": True,
                "type": "reminder",
                "content": {
                    "command": "reminder-triggered",
                    "summary": "\n".join(lines),
                    "items": items,
                },
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_commands(self, raw: Any) -> Dict[str, Dict[str, Any]]:
        """
        Ensure the in-memory command registry is always a dict:
        { cmd_name: meta_dict }.

        Handles:
        - dict: already in desired shape.
        - list-of-dicts v0.2 formats.
        This mirrors nova_registry._normalize_commands but is defensive
        in case anything upstream returns an unexpected shape.
        """
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

    def _parse_args(self, args_str: str) -> Dict[str, Any]:
        """
        Minimal v0.3 argument parser.

        - Supports key=value pairs (quoted via shell-style rules).
        - Bare tokens are collected under "_" as a list.
        """
        import shlex

        result: Dict[str, Any] = {}
        if not args_str:
            return result

        try:
            parts = shlex.split(args_str)
        except ValueError:
            parts = args_str.split()

        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if value.isdigit():
                    result[key] = int(value)
                else:
                    result[key] = value
            else:
                result.setdefault("_", []).append(part)
        return result

    def _interpret_nl_to_command(self, text: str, session_id: str) -> CommandRequest | None:
        """
        Minimal NL → command interpreter for v0.3.

        Only handles memory-related patterns for now.
        Everything else falls through to persona.
        """
        lowered = text.lower()
        
        # -------------------------------------------------------------
        # v0.4.4 — NL → workflow-list
        # Patterns like:
        #   "list workflows"
        #   "show workflows"
        # -------------------------------------------------------------
        if lowered.strip() in ("list workflows", "show workflows", "what workflows do i have"):
            return CommandRequest(
                cmd_name="workflow-list",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("workflow-list"),
            )
               
       # -------------------------------------------------------------
        # v0.4.4 — NL → workflow-delete
        # Patterns like:
        #   "delete workflow 3"
        #   "remove workflow 10"
        # -------------------------------------------------------------
        import re

        m = re.match(r"^(delete|remove)\s+workflow\s+(\d+)\b", lowered)
        if m:
            wid = int(m.group(2))
            args = {"id": wid}
            return CommandRequest(
                cmd_name="workflow-delete",
                args=args,
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("workflow-delete"),
            )

        # Pattern 1: "remember this for <tag>: <payload>"
        if lowered.startswith("remember"):
            mem_type = "semantic"
            tags = ["general"]

            if "for finance" in lowered:
                tags = ["finance"]
            elif "for real estate" in lowered:
                tags = ["real_estate"]
            elif "for health" in lowered:
                tags = ["health"]

            if "as procedural" in lowered:
                mem_type = "procedural"
            elif "as episodic" in lowered or "log this" in lowered:
                mem_type = "episodic"

            if ":" in text:
                payload = text.split(":", 1)[1].strip()
            else:
                payload = text.strip()

            args = {
                "payload": payload,
                "type": mem_type,
                "tags": tags,
            }
            return CommandRequest(
                cmd_name="store",
                args=args,
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("store"),
            )

        # Pattern 2: "show my <tag> memories" / "recall my <tag> memories"
        if "memories" in lowered or "memory" in lowered:
            mem_type = None
            tags = None

            if "finance" in lowered:
                tags = ["finance"]
            elif "real estate" in lowered:
                tags = ["real_estate"]
            elif "health" in lowered:
                tags = ["health"]

            args: Dict[str, Any] = {}
            if mem_type:
                args["type"] = mem_type
            if tags:
                args["tags"] = tags

            if not args:
                return None

            return CommandRequest(
                cmd_name="recall",
                args=args,
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("recall"),
            )
        # -------------------------------------------------------------
        # v0.4.1 — Minimal NL → Reminder interpretation
        # -------------------------------------------------------------
        if lowered.startswith("remind me"):
            # naive parse: "remind me to X at TIME"
            # We accept two simple shapes:
            #   remind me to <title> at <time>
            #   remind me <title> at <time>
            text_no_prefix = text.lower().replace("remind me", "", 1).strip()

            # Best-effort split on common " at "
            if " at " in text_no_prefix:
                title_part, when_part = text_no_prefix.split(" at ", 1)
                title = title_part.strip()
                when = when_part.strip()

                args = {
                    "title": title,
                    "when": when,
                }
                return CommandRequest(
                    cmd_name="remind-add",
                    args=args,
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("remind-add"),
                )

        return None

    def _build_system_prompt(self, context: dict | None = None) -> str:
        """
        Merge the static Nova persona prompt with dynamic OS context.
        Hard fallback: even if context is None or malformed, we still return a valid system prompt.
        """
        parts = [BASE_SYSTEM_PROMPT.strip()]

        # context is allowed to just be a dict
        if isinstance(context, dict):
            memory_summary = context.get("memory_summary")
            active_modules = context.get("active_modules")
            time_rhythm = context.get("time_rhythm")

            if memory_summary:
                parts.append(f"\n\n[Memory Summary]\n{memory_summary}")
            if active_modules:
                parts.append(f"\n\n[Active Modules]\n{active_modules}")
            if time_rhythm:
                parts.append(f"\n\n[Time Rhythm]\n{time_rhythm}")

        return "\n".join(parts)

    def _handle_natural_language(self, text: str, session_id: str) -> CommandResponse:
        # Get whatever your ContextManager returns (likely a dict)
        ctx = self.context_manager.get_context(session_id)

        # Build system prompt via persona fallback
        system_prompt = self._build_system_prompt(ctx)

        # Call LLM using persona + context
        llm_result = self.llm_client.complete(
            system=system_prompt,
            user=text,
            session_id=session_id,
        )

        return CommandResponse(
            ok=True,
            command="natural_language",
            summary=llm_result["text"],
        )

    def _error(self, code: str, message: str) -> CommandResponse:
        return CommandResponse(
            ok=False,
            command=code,
            summary=message,
            error_code=code,
            error_message=message,
        )
    # ------------------------------------------------------------------
    # v0.4 kernel state export (for snapshots)
    # ------------------------------------------------------------------
    def export_kernel_state(self) -> Dict[str, Any]:
        """
        Optional: kernel-level state export.
        Not yet wired into MemoryManager, but safe to call from snapshot logic.
        """
        return {
            "time_rhythm": getattr(self.time_rhythm_engine, "to_dict", lambda: {})(),
            "workflows": getattr(self.workflow_engine, "to_dict", lambda: {})(),
        }

