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
from .continuity_helpers import ContinuityHelpers
from .human_state import HumanStateManager
# v0.6 imports
from .nl_router import route_natural_language
from .section_defs import get_section_keys, get_section, SECTION_DEFS
from .syscommands import (
    get_active_section,
    clear_active_section,
    get_section_command_names,
)
from .wizard_mode import (
    is_wizard_active,
    is_wizard_command,
    start_wizard,
    process_wizard_input,
    cancel_wizard,
    build_command_args_from_wizard,
)
# InterpretationEngine is kept for explicit #interpret, #derive, etc. commands
# but is NO LONGER used for automatic NL → command routing
from kernel.interpretation_engine import InterpretationEngine

# v0.6 Config flag - DEPRECATED, kept for reference only
# Legacy NL routing has been fully removed from runtime
USE_LEGACY_NL = False  # No longer affects runtime behavior


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

        # ---------------- v0.5.8 Continuity Helpers ----------------
        self.continuity = ContinuityHelpers(
            memory_manager=self.memory_manager,
            identity_manager=self.identity_manager,
        )

        # ---------------- v0.5.9 Human State ----------------
        self.human_state = HumanStateManager(self.config.data_dir)

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
        
        v0.6 Routing Order:
        
        FOR ALL INPUTS:
        1. Active wizard check → feed text to wizard
        2. Active section menu check → treat text as command selection
        
        FOR INPUTS STARTING WITH #:
        3. Explicit syscommand (includes section menus, help, all registered commands)
        4. Wizard mode for no-arg commands
        
        FOR NON-# INPUTS:
        5. Section command without # (core, memory, workflow, etc.)
        6. v0.6 NL Router → pattern-based intent detection
        7. Reminder check
        8. Persona fallback → normal chat
        
        REMOVED in v0.6:
        - Legacy NL routing (legacy_nl_router.py) - file preserved but not imported
        - InterpretationEngine auto-routing (kept for explicit #interpret, #derive, etc.)
        """
        self.logger.log_input(session_id, text)

        if not text.strip():
            return self._error("EMPTY_INPUT", "No input provided.").to_dict()

        stripped = text.strip()

        # -------------------------------------------------------------
        # 1) Active Wizard Check
        # -------------------------------------------------------------
        if is_wizard_active(session_id):
            result = process_wizard_input(session_id, stripped)
            
            if result.get("extra", {}).get("wizard_complete"):
                # Execute the completed command
                target_cmd = result["extra"]["target_command"]
                collected = result["extra"]["collected_args"]
                args_dict = build_command_args_from_wizard(target_cmd, collected)
                
                request = CommandRequest(
                    cmd_name=target_cmd,
                    args=args_dict,
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get(target_cmd),
                )
                response = self.router.route(request, kernel=self)
                self.logger.log_response(session_id, target_cmd, response.to_dict())
                return response.to_dict()
            
            # Wizard in progress or cancelled
            return {
                "ok": result.get("ok", True),
                "command": result.get("command", "wizard"),
                "summary": result.get("summary", ""),
                "content": {"command": "wizard", "summary": result.get("summary", "")},
                "extra": result.get("extra", {}),
            }

        # -------------------------------------------------------------
        # 2) Active Section Menu Check
        # -------------------------------------------------------------
        active_section = get_active_section(session_id)
        if active_section and not stripped.startswith("#"):
            # User is in a section menu, check their selection
            selection = stripped.lower().strip()
            valid_commands = get_section_command_names(active_section)
            
            # Check if valid command name - EXACT match required
            if selection in valid_commands:
                # Clear the menu state and execute the command
                clear_active_section(session_id)
                request = CommandRequest(
                    cmd_name=selection,
                    args={},
                    session_id=session_id,
                    raw_text=text,
                    meta=self.commands.get(selection),
                )
                response = self.router.route(request, kernel=self)
                self.logger.log_response(session_id, selection, response.to_dict())
                return response.to_dict()
            else:
                # ANY invalid input exits the section menu immediately
                # This includes: numbers, wrong names, "exit", "quit", natural language, etc.
                clear_active_section(session_id)
                self.logger.log_input(session_id, f"[SECTION_MENU] Exiting {active_section} menu - invalid input: {selection}")
                return {
                    "ok": True,
                    "command": "section_menu_exit",
                    "summary": "Exiting section menu.",
                    "content": {"command": "section_menu_exit", "summary": "Exiting section menu."},
                }

        # Clear any stale section menu state if user types a # command
        if stripped.startswith("#"):
            clear_active_section(session_id)

        # -------------------------------------------------------------
        # 3) Explicit Syscommand (# prefix)
        # -------------------------------------------------------------
        if stripped.startswith("#"):
            tokens = stripped.split()
            cmd_token = tokens[0].lower()
            cmd_name = cmd_token[1:]  # Remove #
            args_str = " ".join(tokens[1:]) if len(tokens) > 1 else ""
            
            if cmd_name in self.commands:
                args_dict = self._parse_args(args_str)
                
                # 4) Wizard mode for no-arg commands
                if not args_dict and is_wizard_command(cmd_name):
                    result = start_wizard(session_id, cmd_name)
                    return {
                        "ok": result.get("ok", True),
                        "command": "wizard",
                        "summary": result.get("summary", ""),
                        "content": {"command": "wizard", "summary": result.get("summary", "")},
                        "extra": result.get("extra", {}),
                    }
                
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
            else:
                # Unknown command
                return self._error("UNKNOWN_COMMAND", f"Unknown command: #{cmd_name}").to_dict()

        # -------------------------------------------------------------
        # NON-# INPUT PATH
        # -------------------------------------------------------------
        
        # -------------------------------------------------------------
        # 5) Section Command without # prefix (e.g., "core", "memory")
        # -------------------------------------------------------------
        # Check if input matches a section command name
        first_word = stripped.split()[0].lower() if stripped.split() else ""
        section_commands = ["core", "memory", "continuity", "human_state", "modules", 
                          "identity", "system", "workflow", "timerhythm", "reminders", 
                          "commands", "interpretation"]
        
        if first_word in section_commands and first_word in self.commands:
            # Route to section menu handler (same as #core, #memory, etc.)
            args_str = " ".join(stripped.split()[1:]) if len(stripped.split()) > 1 else ""
            args_dict = self._parse_args(args_str)
            
            request = CommandRequest(
                cmd_name=first_word,
                args=args_dict,
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get(first_word),
            )
            response = self.router.route(request, kernel=self)
            self.logger.log_response(session_id, first_word, response.to_dict())
            return response.to_dict()

        # -------------------------------------------------------------
        # 6) v0.6 NL Router (pattern-based intent detection)
        # -------------------------------------------------------------
        nl_request = route_natural_language(stripped)
        if nl_request is not None:
            nl_request.session_id = session_id
            if nl_request.meta is None:
                nl_request.meta = self.commands.get(nl_request.cmd_name)
            response = self.router.route(nl_request, kernel=self)
            self.logger.log_response(session_id, nl_request.cmd_name, response.to_dict())
            return response.to_dict()

        # -------------------------------------------------------------
        # 6) Reminder Check (no background threads)
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
        # 7) Persona Fallback (normal chat)
        # -------------------------------------------------------------
        self.logger.log_input(session_id, "[ROUTER] No syscommand match. Falling back to persona.")

        policy_meta = {
            "session_id": session_id,
            "source": "persona_fallback",
            "env": getattr(self, "env_state", None),
        }

        # Pre-LLM sanitization
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

        # Never send an empty summary to the UI
        if not reply or not str(reply).strip():
            reply = "(kernel-fallback) I heard you, but couldn't generate a response. Can you rephrase that?"

        response_dict = {
            "ok": True,
            "command": "persona",
            "summary": reply,
            "content": {
                "command": "persona",
                "summary": reply,
            },
            "meta": {"source": "persona_fallback"},
        }

        self.logger.log_response(session_id, "persona", response_dict)
        return response_dict

    def _normalize_commands(self, raw: Any) -> Dict[str, Dict[str, Any]]:
        """
        Ensure the in-memory command registry is always a dict:
        { cmd_name: meta_dict }.
        
        v0.6: Also strips any '#' prefix from command names since
        the # is input syntax only, not part of the command identifier.

        Handles:
        - dict: already in desired shape (with # stripped from keys).
        - list-of-dicts v0.2 formats.
        This mirrors nova_registry._normalize_commands but is defensive
        in case anything upstream returns an unexpected shape.
        """
        if isinstance(raw, dict):
            # v0.6: Strip # prefix from all keys
            normalized = {}
            for key, value in raw.items():
                clean_key = key.lstrip("#")
                normalized[clean_key] = value
            return normalized

        normalized: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw, list):
            for entry in raw:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name") or entry.get("command") or entry.get("cmd")
                if name:
                    # v0.6: Strip # prefix
                    name = name.lstrip("#")
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
                        # v0.6: Strip # prefix
                        normalized[k.lstrip("#")] = v
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
    # v0.5.8 Continuity Helpers
    # ------------------------------------------------------------------

    def get_user_preferences(self, limit: int = 10) -> list:
        """
        Get user preferences from memory and identity.
        Convenience method wrapping ContinuityHelpers.
        """
        return [p.to_dict() for p in self.continuity.get_user_preferences(limit=limit)]

    def get_active_projects(self, limit: int = 5) -> list:
        """
        Get active projects/goals from memory and identity.
        Convenience method wrapping ContinuityHelpers.
        """
        return [p.to_dict() for p in self.continuity.get_active_projects(limit=limit)]

    def get_continuity_context(self) -> dict:
        """
        Get full continuity context for interpretation framing.
        """
        return self.continuity.get_continuity_context().to_dict()

    def get_reconfirmation_prompts(self, limit: int = 3) -> list:
        """
        Get gentle re-confirmation prompts for stale items.
        """
        return self.continuity.generate_reconfirmation_prompts(limit=limit)

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
