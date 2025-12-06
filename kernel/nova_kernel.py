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
# v0.7: Working Memory Engine (NovaWM)
from .nova_wm import (
    get_wm,
    wm_update,
    wm_record_response,
    wm_get_context,
    wm_get_context_string,
    wm_answer_reference,
    wm_clear,
)
# v0.8.0: InterpretationEngine removed - wizard logic handled by wizard_mode.py
# NL routing handled by nl_router.py

# v0.8.2: Message Logger for fine-tuning data collection
from .message_logger import MessageLogger

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

        # ---------------- TimeRhythm / Reminders ----------------
        from kernel.reminders_manager import RemindersManager
        self.reminders = RemindersManager(self.config.data_dir)
        
        # v0.8.0: Time Rhythm Manager (replaces legacy TimeRhythmEngine)
        try:
            from kernel.time_rhythm import TimeRhythmManager
            self.time_rhythm_manager = TimeRhythmManager(self.config.data_dir)
            self.time_rhythm_engine = self.time_rhythm_manager  # Alias for compatibility
        except ImportError:
            self.time_rhythm_manager = None
            self.time_rhythm_engine = None
        
        # v0.8.0: Quest Engine (the ONLY quest/workflow system)
        try:
            from kernel.quest_engine import QuestEngine
            self.quest_engine = QuestEngine(self.config.data_dir)
        except ImportError:
            self.quest_engine = None
        
        # v0.8.0: Player Profile Manager
        try:
            from kernel.player_profile import PlayerProfileManager
            self.player_profile_manager = PlayerProfileManager(self.config.data_dir)
        except ImportError:
            self.player_profile_manager = None
        
        # v0.8.1: Module Store (regions/world map) - NO DEFAULTS
        try:
            from kernel.module_manager import ModuleStore
            self.module_store = ModuleStore(self.config.data_dir)
        except ImportError:
            self.module_store = None
        
        # v0.8.0: Assistant Mode (story vs utility)
        try:
            from kernel.assistant_mode import AssistantModeManager
            initial_mode = self.env_state.get("assistant_mode", "story")
            self.assistant_mode_manager = AssistantModeManager(initial_mode)
        except ImportError:
            self.assistant_mode_manager = None
        
        # v0.8.0: Inbox Store (quick capture)
        try:
            from kernel.inbox_manager import InboxStore
            self.inbox_store = InboxStore(self.config.data_dir)
        except ImportError:
            self.inbox_store = None

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

        # ---------------- v0.8.2: Message Logger ----------------
        # Logs assistant messages to JSONL for fine-tuning
        self.message_logger = MessageLogger(base_dir="data/logs")

        # v0.8.0: InterpretationEngine removed - dead code
        # Wizard logic is now handled by wizard_mode.py
        # NL routing is handled by nl_router.py


    # ------------------------------------------------------------------
    # Core input handling
    # ------------------------------------------------------------------

    def handle_input(self, text: str, session_id: str, source: str = "ui") -> Dict[str, Any]:
        """
        Entry point for all UI input.
        Returns a structured dict suitable for the UI.
        
        v0.6 Routing Order:
        
        FOR ALL INPUTS:
        1. Active wizard check → feed text to wizard
        2. Active section menu check → treat text as command selection
           (ONLY place where bare command names work)
        
        FOR INPUTS STARTING WITH #:
        3. Explicit syscommand (ALL commands require # prefix)
        4. Wizard mode for no-arg commands
        
        FOR NON-# INPUTS:
        5. v0.6 NL Router → pattern-based intent detection
        6. Reminder check
        7. Persona fallback → normal chat
        
        STRICT RULE: All commands MUST start with # at top level.
        Bare words like "core", "help", "status" are NOT commands.
        Exception: Inside an active section menu, bare command names work.
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
            selection = stripped.lower().strip()
            valid_commands = get_section_command_names(active_section)
            
            if selection in valid_commands:
                # It's a valid command for this section - execute it
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
                # Not a valid command - exit section menu and continue to persona
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
                    # v0.7: Clear Working Memory when wizard starts
                    wm_clear(session_id)
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
        # NON-# INPUT: Goes directly to NL Router → Reminder → Persona
        # v0.6 RULE: All commands MUST start with # at top level
        # Bare words like "core", "help", "status" are NOT commands
        # (except inside an active section menu, handled above)
        # -------------------------------------------------------------

        # -------------------------------------------------------------
        # 5) v0.6 NL Router (pattern-based intent detection)
        # -------------------------------------------------------------
        nl_request = route_natural_language(stripped)
        if nl_request is not None:
            nl_request.session_id = session_id
            
            # Check if NL router wants to trigger a wizard
            use_wizard = nl_request.meta.get("use_wizard", False) if nl_request.meta else False
            
            if use_wizard and is_wizard_command(nl_request.cmd_name):
                # v0.7: Clear Working Memory when wizard starts
                wm_clear(session_id)
                # Start wizard for this command
                result = start_wizard(session_id, nl_request.cmd_name)
                return {
                    "ok": result.get("ok", True),
                    "command": "wizard",
                    "summary": result.get("summary", ""),
                    "content": {"command": "wizard", "summary": result.get("summary", "")},
                    "extra": result.get("extra", {}),
                }
            
            # Otherwise execute command directly
            if nl_request.meta is None or "source" in nl_request.meta:
                # Preserve NL router meta but add command meta
                nl_meta = nl_request.meta or {}
                cmd_meta = self.commands.get(nl_request.cmd_name) or {}
                nl_request.meta = {**cmd_meta, **nl_meta}
            
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
        # 7) Persona Fallback (normal chat) with NovaWM v0.7
        # -------------------------------------------------------------
        self.logger.log_input(session_id, "[ROUTER] No syscommand match. Falling back to persona.")

        # v0.7: Check if Working Memory can answer directly (reference questions)
        direct_answer = wm_answer_reference(session_id, stripped)
        
        # v0.7: Update Working Memory with user message
        wm_result = wm_update(session_id, stripped)
        
        # v0.7: Get formatted context string for persona system prompt
        wm_context_string = wm_get_context_string(session_id)
        
        policy_meta = {
            "session_id": session_id,
            "source": "persona_fallback",
            "env": getattr(self, "env_state", None),
            "wm_turn": wm_result.get("turn", 0),
        }

        # Pre-LLM sanitization
        safe_input = stripped
        if self.policy_engine is not None:
            try:
                safe_input = self.policy_engine.pre_llm(stripped, policy_meta)
            except Exception as e:
                self.logger.log_error(session_id, f"policy.pre_llm error (persona): {e}")

        # Persona LLM call with NovaWM context
        reply = self.persona.generate_response(
            safe_input,
            session_id=session_id,
            wm_context_string=wm_context_string,
            direct_answer=direct_answer,
        )

        # v0.7: Record Nova's response in Working Memory
        if reply:
            wm_record_response(session_id, reply)

        # Post-LLM correction/stabilization
        if self.policy_engine is not None:
            try:
                reply = self.policy_engine.post_llm(reply, policy_meta)
            except Exception as e:
                self.logger.log_error(session_id, f"policy.post_llm error (persona): {e}")

        # Never send an empty summary to the UI
        if not reply or not str(reply).strip():
            reply = "(kernel-fallback) I heard you, but couldn't generate a response. Can you rephrase that?"

        # -------------------------------------------------------------
        # v0.8.2: Log assistant message for fine-tuning
        # -------------------------------------------------------------
        self._log_assistant_message(
            reply_text=reply,
            user_message=stripped,
            session_id=session_id,
            source=source,
        )

        response_dict = {
            "ok": True,
            "command": "persona",
            "summary": reply,
            "content": {
                "command": "persona",
                "summary": reply,
            },
            "meta": {
                "source": "persona_fallback",
                "wm": {
                    "turn": wm_result.get("turn", 0),
                    "entities": wm_result.get("entities_extracted", []),
                    "pronouns_resolved": wm_result.get("pronouns_resolved", {}),
                    "emotional_tone": wm_result.get("emotional_tone"),
                },
            },
        }

        self.logger.log_response(session_id, "persona", response_dict)
        return response_dict

    # ------------------------------------------------------------------
    # v0.8.2: Message Logging Helper
    # ------------------------------------------------------------------
    
    def _log_assistant_message(
        self,
        reply_text: str,
        user_message: str,
        session_id: str,
        source: str = "ui",
    ) -> None:
        """
        Log an assistant message for fine-tuning data collection.
        
        This method NEVER crashes - errors are silently ignored.
        """
        try:
            # Gather context safely
            assistant_mode = None
            if self.assistant_mode_manager:
                try:
                    assistant_mode = self.assistant_mode_manager.current_mode.value
                except AttributeError:
                    assistant_mode = getattr(self.assistant_mode_manager, "mode_name", None)
            
            persona_mode = getattr(self.persona, "current_mode", None)
            
            active_section = None
            if hasattr(self, "context_manager"):
                active_section = getattr(self.context_manager, "active_section", None)
            
            quest_id = None
            if self.quest_engine:
                quest_id = getattr(self.quest_engine, "active_quest_id", None)
            
            module_id = None
            if self.quest_engine and hasattr(self.quest_engine, "get_active_module_id"):
                try:
                    module_id = self.quest_engine.get_active_module_id()
                except Exception:
                    pass
            
            model_name = getattr(self.llm_client, "last_model_used", None)
            
            # Log the message
            self.message_logger.log_assistant_message(
                text=reply_text,
                user_last_message=user_message,
                assistant_mode=assistant_mode,
                persona_mode=persona_mode,
                active_section=active_section,
                quest_id=quest_id,
                module_id=module_id,
                model_name=model_name,
                session_id=session_id,
                extra={
                    "source": source,
                    "kernel_version": self.env_state.get("kernel_version", "0.8.2"),
                },
            )
        except Exception:
            # NEVER crash NovaOS due to logging failure
            pass

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
            "time_rhythm": getattr(self.time_rhythm_manager, "to_dict", lambda: {})() if self.time_rhythm_manager else {},
            "quest_progress": self.quest_engine.get_progress().to_dict() if self.quest_engine else {},
        }
