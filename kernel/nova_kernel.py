# kernel/nova_kernel.py
from typing import Dict, Any

from backend.llm_client import LLMClient
from backend.model_router import ModelRouter, RoutingContext
from system.config import Config
from system import nova_registry
from persona.nova_persona import BASE_SYSTEM_PROMPT
from .command_types import CommandRequest, CommandResponse
from .syscommand_router import SyscommandRouter
from .context_manager import ContextManager
from .memory_manager import MemoryManager
from .policy_engine import PolicyEngine
from .logger import KernelLogger
from .identity_manager import IdentityManager
from .memory_policy import MemoryPolicy
from kernel.interpretation_engine import InterpretationEngine


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
        model_router: ModelRouter | None = None,
    ):
        self.config = config

        # ---------------- Core dependencies ----------------
        # (These MUST be set before handle_input is ever called)
        self.llm_client = llm_client or LLMClient()
        self.context_manager = context_manager or ContextManager(config=config)
        self.memory_manager = memory_manager or MemoryManager(config=config)
        self.policy_engine = policy_engine or PolicyEngine(config=config)
        self.logger = logger or KernelLogger(config=config)

        # ---------------- v0.5.3 Model Router ----------------
        self.model_router = model_router or ModelRouter()

        # ---------------- Environment State (v0.5.1) ----------------
        # Safe even if nothing uses it yet.
        self.env_state: Dict[str, Any] = {
            "mode": "normal",
            "debug": False,
            "verbosity": "normal",
        }

        # ---------------- Command registry + router ----------------
        raw_commands = nova_registry.load_commands(config=self.config)
        self.commands = self._normalize_commands(raw_commands)

        # v0.5 — Custom Commands
        self.custom_registry = nova_registry.CustomCommandRegistry(self.config)
        self.custom_commands = self.custom_registry.list()
        self.module_registry = nova_registry.ModuleRegistry(config=config)
        self.router = router or SyscommandRouter(self.commands)

        # ---------------- TimeRhythm / Workflows / Reminders ----------------
        from kernel.time_rhythm import TimeRhythmEngine
        from kernel.workflow_engine import WorkflowEngine
        from kernel.reminders_manager import RemindersManager

        self.time_rhythm_engine = TimeRhythmEngine()
        self.workflow_engine = WorkflowEngine()
        self.reminders = RemindersManager(self.config.data_dir)

        # ---------------- v0.5.5 Identity Manager ----------------
        self.identity_manager = IdentityManager(self.config.data_dir)

        # ---------------- v0.5.7 Memory Policy ----------------
        self.memory_policy = MemoryPolicy()
        self.memory_policy.set_mode(self.env_state.get("mode", "normal"))
        # Wire up policy hooks to memory manager
        if hasattr(self.memory_manager, "set_pre_store_hook"):
            self.memory_manager.set_pre_store_hook(
                self.memory_policy.create_pre_store_hook()
            )
        if hasattr(self.memory_manager, "set_post_recall_hook"):
            self.memory_manager.set_post_recall_hook(
                self.memory_policy.create_post_recall_hook()
            )

        # ---------------- Persona fallback ----------------
        from persona.nova_persona import NovaPersona
        self.persona = NovaPersona(self.llm_client)

        # ---------------- Interpretation Engine (v0.5) ----------------
        custom_cmds = nova_registry.load_custom_commands(config=self.config)
        self.interpreter = InterpretationEngine(self.commands, custom_cmds)

    # ------------------------------------------------------------------
    # Core input handling
    # ------------------------------------------------------------------

    def handle_input(self, text: str, session_id: str) -> Dict[str, Any]:
        """
        Entry point for all UI input.
        Returns a structured dict suitable for the UI.
        """
        self.logger.log_input(session_id, text)

        if not text.strip():
            return self._error("EMPTY_INPUT", "No input provided.").to_dict()

        stripped = text.strip()
        tokens = stripped.split()
        cmd_name = tokens[0].lower()
        args_str = " ".join(tokens[1:]) if len(tokens) > 1 else ""

        # -------------------------------------------------------------
        # 1) Explicit syscommand: first token matches commands.json
        #    (takes precedence over interpretation)
        # -------------------------------------------------------------
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

        # -------------------------------------------------------------
        # 2) v0.5 — Full NL → Command Interpreter (custom + macros)
        # -------------------------------------------------------------
        interpreted_req = self.interpreter.interpret(stripped, session_id)
        if interpreted_req is not None:
            # v0.5.2 — attach metadata for custom commands (prompt + macro)
            if interpreted_req.meta is None:
                meta = self.custom_registry.get(interpreted_req.cmd_name)
                if meta is None:
                    meta = self.commands.get(interpreted_req.cmd_name)
                interpreted_req.meta = meta

            response = self.router.route(interpreted_req, kernel=self)
            self.logger.log_response(session_id, interpreted_req.cmd_name, response.to_dict())
            return response.to_dict()

        # -------------------------------------------------------------
        # 3) Legacy NL → command interpretation (v0.3 helper)
        # -------------------------------------------------------------
        interpreted = self._interpret_nl_to_command(stripped, session_id)
        if interpreted is not None:
            response = self.router.route(interpreted, kernel=self)
            self.logger.log_response(session_id, interpreted.cmd_name, response.to_dict())
            return response.to_dict()

        # -------------------------------------------------------------
        # 4) v0.4.1 — Reminder checking (no background threads)
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
        # -------------------------------------------------------------
        # v0.4.5 — Persona fallback (RESTORED) + v0.5.1 Policy hooks
        # -------------------------------------------------------------
        self.logger.log_input(session_id, "[ROUTER] No syscommand match. Falling back to persona.")

        policy_meta = {
            "session_id": session_id,
            "source": "persona_fallback",
            "env": getattr(self, "env_state", None),
        }

        # Pre-LLM sanitization before sending user text into persona/LLM
        safe_input = stripped
        if self.policy_engine is not None:
            try:
                safe_input = self.policy_engine.pre_llm(stripped, policy_meta)
            except Exception as e:
                self.logger.log_error(session_id, f"policy.pre_llm error (persona): {e}")

        # Persona LLM call
        reply = self.persona.generate_response(
            safe_input,
            session_id=session_id
        )

        # Post-LLM correction/stabilization
        if self.policy_engine is not None:
            try:
                reply = self.policy_engine.post_llm(reply, policy_meta)
            except Exception as e:
                self.logger.log_error(session_id, f"policy.post_llm error (persona): {e}")

        # Double-guard: never send an empty summary to the UI
        if not reply or not str(reply).strip():
            reply = "(kernel-fallback) I heard you, but couldn’t generate a response. Can you rephrase that?"

        response_dict = {
            "ok": True,
            "command": "persona",
            "summary": reply,
            # Mirror the reminder / other-command shape by also providing `content.summary`
            "content": {
                "command": "persona",
                "summary": reply,
            },
            "meta": {"source": "persona_fallback"},
        }

        self.logger.log_response(session_id, "persona", response_dict)
        return response_dict

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
        v0.5.1 — Expanded NL → Command Interpreter

        Handles natural language patterns and maps them to syscommands.
        Falls through to persona if no match.
        """
        import re
        lowered = text.lower().strip()

        # =================================================================
        # SYSTEM / STATUS PATTERNS
        # =================================================================

        # "what's my status" / "how's my system" / "system status"
        if any(p in lowered for p in [
            "what's my status", "whats my status", "my status",
            "system status", "how's my system", "hows my system",
            "how am i doing", "check system", "nova status"
        ]):
            return CommandRequest(
                cmd_name="status",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("status"),
            )

        # "what can you do" / "help me" / "show commands"
        if any(p in lowered for p in [
            "what can you do", "show commands", "list commands",
            "help me", "what commands", "available commands"
        ]):
            return CommandRequest(
                cmd_name="help",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("help"),
            )

        # "why do you exist" / "what are you" / "what is novaos"
        if any(p in lowered for p in [
            "why do you exist", "what are you", "what is novaos",
            "who are you", "your purpose", "why novaos"
        ]):
            return CommandRequest(
                cmd_name="why",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("why"),
            )

        # =================================================================
        # ENVIRONMENT / MODE PATTERNS
        # =================================================================

        # "show environment" / "what mode" / "current mode"
        if any(p in lowered for p in [
            "show environment", "show env", "what mode",
            "current mode", "what's my mode", "whats my mode"
        ]):
            return CommandRequest(
                cmd_name="env",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("env"),
            )

        # "switch to deep work" / "enter focus mode" / "go into reflection"
        mode_patterns = [
            (r"(?:switch to|enter|go into|set mode to|activate)\s+(deep.?work|focus)", "deep_work"),
            (r"(?:switch to|enter|go into|set mode to|activate)\s+(reflection|reflect)", "reflection"),
            (r"(?:switch to|enter|go into|set mode to|activate)\s+(debug)", "debug"),
            (r"(?:switch to|enter|go into|set mode to|activate)\s+(normal)", "normal"),
            (r"(?:i need to|let's|time to)\s+(focus|concentrate|deep work)", "deep_work"),
            (r"(?:i need to|let's|time to)\s+(reflect|think)", "reflection"),
        ]
        for pattern, mode_name in mode_patterns:
            if re.search(pattern, lowered):
                return CommandRequest(
                    cmd_name="mode",
                    args={"name": mode_name},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("mode"),
                )

        # =================================================================
        # WORKFLOW PATTERNS
        # =================================================================

        # "list workflows" / "show workflows" / "what workflows"
        if lowered.strip() in ("list workflows", "show workflows", "what workflows do i have", "my workflows"):
            return CommandRequest(
                cmd_name="workflow-list",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("workflow-list"),
            )

        # "delete workflow 3" / "remove workflow 10"
        m = re.match(r"^(?:delete|remove)\s+workflow\s+(\d+)\b", lowered)
        if m:
            wid = int(m.group(1))
            return CommandRequest(
                cmd_name="workflow-delete",
                args={"id": wid},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("workflow-delete"),
            )

        # "start workflow X" / "begin workflow X" / "start my X workflow"
        m = re.match(r"^(?:start|begin|launch)\s+(?:my\s+)?(?:workflow\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+workflow)?$", lowered)
        if m:
            workflow_name = m.group(1).strip()
            if workflow_name and workflow_name not in ("a", "the", "my"):
                return CommandRequest(
                    cmd_name="flow",
                    args={"id": workflow_name.replace(" ", "_"), "name": workflow_name},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("flow"),
                )

        # "advance workflow" / "next step" / "move forward"
        if any(p in lowered for p in [
            "advance workflow", "next step", "move forward",
            "continue workflow", "proceed", "next phase"
        ]):
            # Try to extract workflow id if present
            m = re.search(r"workflow\s+(\S+)", lowered)
            wid = m.group(1) if m else None
            return CommandRequest(
                cmd_name="advance",
                args={"id": wid} if wid else {},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("advance"),
            )

        # "pause workflow" / "halt workflow" / "stop workflow"
        if any(p in lowered for p in ["pause workflow", "halt workflow", "stop workflow"]):
            m = re.search(r"workflow\s+(\S+)", lowered)
            wid = m.group(1) if m else None
            return CommandRequest(
                cmd_name="halt",
                args={"id": wid} if wid else {},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("halt"),
            )

        # "create a workflow for X" / "plan out X"
        if re.match(r"^(?:create|make|build|plan)\s+(?:a\s+)?(?:workflow|plan)\s+(?:for\s+)?(.+)$", lowered):
            m = re.match(r"^(?:create|make|build|plan)\s+(?:a\s+)?(?:workflow|plan)\s+(?:for\s+)?(.+)$", lowered)
            goal = m.group(1).strip() if m else text
            return CommandRequest(
                cmd_name="compose",
                args={"goal": goal},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("compose"),
            )

        # =================================================================
        # TIME RHYTHM PATTERNS
        # =================================================================

        # "where am i in time" / "what day is it" / "time presence"
        if any(p in lowered for p in [
            "where am i in time", "time presence", "what cycle",
            "current cycle", "my rhythm", "time rhythm"
        ]):
            return CommandRequest(
                cmd_name="presence",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("presence"),
            )

        # "check pulse" / "workflow health" / "system pulse"
        if any(p in lowered for p in ["check pulse", "workflow health", "system pulse", "pulse check"]):
            return CommandRequest(
                cmd_name="pulse",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("pulse"),
            )

        # "what should i do" / "align me" / "suggest next action"
        if any(p in lowered for p in [
            "what should i do", "align me", "suggest next",
            "what's next", "whats next", "next action", "prioritize"
        ]):
            return CommandRequest(
                cmd_name="align",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("align"),
            )

        # =================================================================
        # MEMORY PATTERNS
        # =================================================================

        # "remember this for <tag>: <payload>"
        if lowered.startswith("remember"):
            mem_type = "semantic"
            tags = ["general"]

            if "for finance" in lowered:
                tags = ["finance"]
            elif "for real estate" in lowered:
                tags = ["real_estate"]
            elif "for health" in lowered:
                tags = ["health"]
            elif "for work" in lowered:
                tags = ["work"]
            elif "for personal" in lowered:
                tags = ["personal"]

            if "as procedural" in lowered:
                mem_type = "procedural"
            elif "as episodic" in lowered or "log this" in lowered:
                mem_type = "episodic"

            if ":" in text:
                payload = text.split(":", 1)[1].strip()
            else:
                payload = text.replace("remember", "", 1).strip()
                # Remove tag phrases from payload
                for phrase in ["for finance", "for real estate", "for health", "for work", "for personal",
                              "as procedural", "as episodic", "log this"]:
                    payload = payload.replace(phrase, "").strip()

            if payload:
                return CommandRequest(
                    cmd_name="store",
                    args={"payload": payload, "type": mem_type, "tags": tags},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("store"),
                )

        # "show my <tag> memories" / "recall my <tag> memories"
        if "memories" in lowered or "memory" in lowered:
            tags = None
            mem_type = None

            if "finance" in lowered:
                tags = ["finance"]
            elif "real estate" in lowered:
                tags = ["real_estate"]
            elif "health" in lowered:
                tags = ["health"]
            elif "work" in lowered:
                tags = ["work"]
            elif "personal" in lowered:
                tags = ["personal"]

            if "semantic" in lowered:
                mem_type = "semantic"
            elif "procedural" in lowered:
                mem_type = "procedural"
            elif "episodic" in lowered:
                mem_type = "episodic"

            args: Dict[str, Any] = {}
            if mem_type:
                args["type"] = mem_type
            if tags:
                args["tags"] = tags

            # Only route if we have some filter, otherwise let persona handle
            if args:
                return CommandRequest(
                    cmd_name="recall",
                    args=args,
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("recall"),
                )

        # "forget memory #5" / "delete memory 5"
        m = re.match(r"^(?:forget|delete|remove)\s+memory\s+#?(\d+)", lowered)
        if m:
            mem_id = int(m.group(1))
            return CommandRequest(
                cmd_name="forget",
                args={"ids": [mem_id]},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("forget"),
            )

        # =================================================================
        # REMINDER PATTERNS
        # =================================================================

        # "remind me to X at TIME"
        if lowered.startswith("remind me"):
            text_no_prefix = lowered.replace("remind me", "", 1).strip()
            # Remove "to" if present
            if text_no_prefix.startswith("to "):
                text_no_prefix = text_no_prefix[3:]

            if " at " in text_no_prefix:
                title_part, when_part = text_no_prefix.split(" at ", 1)
                return CommandRequest(
                    cmd_name="remind-add",
                    args={"title": title_part.strip(), "when": when_part.strip()},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("remind-add"),
                )
            elif " in " in text_no_prefix:
                title_part, when_part = text_no_prefix.split(" in ", 1)
                return CommandRequest(
                    cmd_name="remind-add",
                    args={"title": title_part.strip(), "when": f"in {when_part.strip()}"},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("remind-add"),
                )

        # "show reminders" / "list reminders" / "my reminders"
        if any(p in lowered for p in ["show reminders", "list reminders", "my reminders", "what reminders"]):
            return CommandRequest(
                cmd_name="remind-list",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("remind-list"),
            )

        # =================================================================
        # MODULE PATTERNS
        # =================================================================

        # "list modules" / "show modules" / "what modules"
        if any(p in lowered for p in ["list modules", "show modules", "what modules", "my modules"]):
            return CommandRequest(
                cmd_name="map",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("map"),
            )

        # "create module X" / "forge module X"
        m = re.match(r"^(?:create|forge|make)\s+(?:a\s+)?module\s+(?:called\s+|named\s+)?([a-zA-Z0-9_\-]+)", lowered)
        if m:
            key = m.group(1).strip()
            return CommandRequest(
                cmd_name="forge",
                args={"key": key, "name": key, "mission": f"Module for {key}"},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("forge"),
            )

        # "inspect module X" / "show module X"
        m = re.match(r"^(?:inspect|show|describe)\s+module\s+([a-zA-Z0-9_\-]+)", lowered)
        if m:
            key = m.group(1).strip()
            return CommandRequest(
                cmd_name="inspect",
                args={"key": key},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("inspect"),
            )

        # =================================================================
        # INTERPRETATION PATTERNS
        # =================================================================

        # "analyze X" / "break down X" / "explain X"
        if lowered.startswith(("analyze ", "break down ", "what does this mean")):
            content = re.sub(r"^(analyze|break down|what does this mean)\s*:?\s*", "", lowered)
            if content:
                return CommandRequest(
                    cmd_name="interpret",
                    args={"input": content},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("interpret"),
                )

        # "think from first principles about X"
        if "first principles" in lowered:
            content = re.sub(r".*first principles\s*(about|on)?\s*", "", lowered)
            if content:
                return CommandRequest(
                    cmd_name="derive",
                    args={"input": content},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("derive"),
                )

        # "reframe X" / "look at X differently"
        if lowered.startswith("reframe ") or "look at" in lowered and "differently" in lowered:
            content = re.sub(r"^reframe\s*:?\s*", "", lowered)
            content = re.sub(r"look at\s*(.+)\s*differently.*", r"\1", content)
            if content and content != lowered:
                return CommandRequest(
                    cmd_name="frame",
                    args={"input": content},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("frame"),
                )

        # "predict X" / "forecast X" / "what might happen with X"
        if lowered.startswith(("predict ", "forecast ")) or "what might happen" in lowered:
            content = re.sub(r"^(predict|forecast)\s*:?\s*", "", lowered)
            content = re.sub(r"what might happen\s*(with|to|if)?\s*", "", content)
            if content and content != lowered:
                return CommandRequest(
                    cmd_name="forecast",
                    args={"input": content},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get("forecast"),
                )

        # =================================================================
        # SNAPSHOT PATTERNS
        # =================================================================

        # "save state" / "create snapshot" / "backup"
        if any(p in lowered for p in ["save state", "create snapshot", "backup system", "snapshot"]):
            return CommandRequest(
                cmd_name="snapshot",
                args={},
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get("snapshot"),
            )

        # =================================================================
        # NO MATCH — Return None, falls through to persona
        # =================================================================
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
        """
        Natural language handler routed through the LLM with policy enforcement.
        """
        # Get whatever your ContextManager returns (likely a dict)
        ctx = self.context_manager.get_context(session_id)

        # Build system prompt via persona fallback
        system_prompt = self._build_system_prompt(ctx)

        # Policy metadata (can be extended later with more context/env)
        policy_meta = {
            "session_id": session_id,
            "source": "kernel_nl",
            "env": getattr(self, "env_state", None),
        }

        # ------------------ Policy: pre-LLM ------------------
        safe_user_text = text
        if self.policy_engine is not None:
            try:
                safe_user_text = self.policy_engine.pre_llm(text, policy_meta)
            except Exception as e:
                # Fail-open but log; never crash the kernel on policy failure
                self.logger.log_error(session_id, f"policy.pre_llm error: {e}")

        # Call LLM using persona + context
        llm_result = self.llm_client.complete(
            system=system_prompt,
            user=safe_user_text,
            session_id=session_id,
        )

        raw_output = llm_result.get("text", "")

        # ------------------ Policy: post-LLM ------------------
        final_output = raw_output
        if self.policy_engine is not None:
            try:
                final_output = self.policy_engine.post_llm(raw_output, policy_meta)
            except Exception as e:
                self.logger.log_error(session_id, f"policy.post_llm error: {e}")

        return CommandResponse(
            ok=True,
            command="natural_language",
            summary=final_output,
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
    # v0.5.1 — Environment State Helpers
    # ------------------------------------------------------------------
    def get_env(self, key: str, default=None):
        return self.env_state.get(key, default)

    def set_env(self, key: str, value: Any):
        # type coercion: bool/int if possible
        lowered = str(value).lower()

        if lowered in ("true", "false"):
            value = lowered == "true"
        else:
            # try int
            try:
                value = int(value)
            except ValueError:
                pass

        self.env_state[key] = value
        return value

    # ------------------------------------------------------------------
    # v0.5.3 — Model Routing Helpers
    # ------------------------------------------------------------------
    def get_model(
        self,
        command: str | None = None,
        input_text: str = "",
        think: bool = False,
        explicit_model: str | None = None,
    ) -> str:
        """
        Get the appropriate model for a given context using ModelRouter.
        
        Args:
            command: The syscommand name (e.g., "derive", "interpret")
            input_text: The user input (used for length-based routing)
            think: Whether to force thinking tier
            explicit_model: User-specified model override
            
        Returns:
            Model ID string (e.g., "gpt-4.1-mini")
        """
        return self.model_router.route_for_command(
            command=command or "default",
            input_text=input_text,
            mode=self.env_state.get("mode", "normal"),
            think=think,
            explicit_model=explicit_model,
        )

    def get_model_info(self) -> dict:
        """
        Return information about available model tiers.
        Useful for status/debug commands.
        """
        return {
            "tiers": self.model_router.list_tiers(),
            "current_mode": self.env_state.get("mode", "normal"),
        }

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

