# kernel/nova_kernel.py
from typing import Dict, Any
from backend.llm_client import LLMClient
from system.config import Config
from system import nova_registry
from . import syscommands
from .context_manager import ContextManager
from .memory_manager import MemoryManager
from .policy_engine import PolicyEngine
from .logger import KernelLogger

class NovaKernel:
    """
    NovaOS kernel orchestrator.
    - Parses input
    - Routes syscommands
    - Coordinates memory, modules, persona, and backend calls
    """

    def __init__(self, config: Config):
        self.config = config
        self.llm_client = LLMClient()
        self.commands = nova_registry.load_commands()  # Loaded dynamically
        self.context_manager = ContextManager(config=config)  # ContextManager instance
        self.memory_manager = MemoryManager(config=config)
        self.policy_engine = PolicyEngine(config=config)
        self.logger = KernelLogger(config=config)

    def handle_input(self, text: str, session_id: str) -> Dict[str, Any]:
        """
        Entry point for all UI input.
        Returns a structured KernelResponse dict.
        """
        self.logger.log_input(session_id, text)

        if not text.strip():
            return self._error("EMPTY_INPUT", "No input provided.")

        tokens = text.strip().split()
        cmd_name = tokens[0].lower()
        args = " ".join(tokens[1:]) if len(tokens) > 1 else ""

        if cmd_name in self.commands:
            return self._execute_syscommand(cmd_name, args, session_id)
        else:
            # Natural language: interpretation route
            return self._handle_natural_language(text, session_id)

    def _execute_syscommand(self, cmd_name: str, args: str, session_id: str) -> Dict[str, Any]:
        meta = self.commands[cmd_name]
        handler_name = meta.get("handler")

        handler = syscommands.SYS_HANDLERS.get(handler_name)
        if handler is None:
            return self._error("NO_HANDLER", f"No handler for command '{cmd_name}'.")

        # Directly call mark_booted on the ContextManager instance
        self.context_manager.mark_booted(session_id)  # Correctly use the ContextManager instance here
        context = self.context_manager.get_context(session_id)  # Get session context after marking booted
        try:
            response = handler(
                cmd_name=cmd_name,
                args=args,
                session_id=session_id,
                context=context,
                kernel=self,
                meta=meta,
            )
            self.logger.log_response(session_id, cmd_name, response)
            return response
        except Exception as e:
            self.logger.log_exception(session_id, cmd_name, e)
            return self._error("EXCEPTION", f"Exception in '{cmd_name}': {e}")

    def _handle_natural_language(self, text: str, session_id: str) -> Dict[str, Any]:
        """
        Fallback path for non-syscommand text.
        Uses interpretation-style behavior via LLM.
        """
        context = self.context_manager.get_context(session_id)  # Get the session context
        prompt = context.build_system_prompt()  # Build system prompt using session context

        llm_output = self.llm_client.chat(
            system_prompt=prompt,
            messages=[{"role": "user", "content": text}],
        )

        # Policy and memory hooks
        llm_output = self.policy_engine.postprocess_nl_response(llm_output, context)
        self.memory_manager.maybe_store_nl_interaction(text, llm_output, context)

        return {
            "ok": True,
            "type": "natural_language",
            "content": {
                "summary": llm_output,
            },
        }

    def _error(self, code: str, message: str) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
            },
        }

    def handle_boot(self, cmd_name, args, session_id, context, kernel, meta):
        """
        Boot the system, mark the session as booted.
        """
        # Ensure self.context_manager is a ContextManager instance
        if not isinstance(self.context_manager, ContextManager):
            return self._error("INVALID_CONTEXT_MANAGER", "ContextManager is not an instance of ContextManager.")

        # Correctly call mark_booted directly on the ContextManager instance
        self.context_manager.mark_booted(session_id)  # Directly use the ContextManager instance

        # Optionally print session context after booting for debugging purposes
        # context = self.context_manager.get_context(session_id)
        # print(f"Session context after boot: {context}")

        summary = "NovaOS kernel booted. Persona loaded. Modules and memory initialized."
        return _base_response(cmd_name, summary)
