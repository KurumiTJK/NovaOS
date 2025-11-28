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

        # Command registry + router
        self.commands = nova_registry.load_commands()  # dynamic commands.json
        self.router = router or SyscommandRouter(self.commands)

    def handle_input(self, text: str, session_id: str) -> Dict[str, Any]:
        """
        Entry point for all UI input.
        Returns a structured dict suitable for the UI.
        """
        self.logger.log_input(session_id, text)

        if not text.strip():
            return self._error("EMPTY_INPUT", "No input provided.").to_dict()

        tokens = text.strip().split()
        cmd_name = tokens[0].lower()
        args = " ".join(tokens[1:]) if len(tokens) > 1 else ""

        # v0.2: if the first token matches a command, treat it as a syscommand
        if cmd_name in self.commands:
            request = CommandRequest(
                cmd_name=cmd_name,
                args=args,
                session_id=session_id,
                raw_text=text,
                meta=self.commands.get(cmd_name),
            )
            response = self.router.route(request, kernel=self)
            self.logger.log_response(session_id, cmd_name, response.to_dict())
            return response.to_dict()
        else:
            # Natural language: persona / interpretation route
            response = self._handle_natural_language(text, session_id)
            self.logger.log_response(session_id, "natural_language", response.to_dict())
            return response.to_dict()

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