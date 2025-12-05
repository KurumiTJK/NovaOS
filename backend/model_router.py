# backend/model_router.py
"""
v0.6.6 — Model Routing Engine

Model Tiers (TWO tiers only):
- MINI:     gpt-4.1-mini  — default for non-intensive syscommands
- THINKING: gpt-5.1       — deep reasoning, LLM-intensive commands, persona

Logging:
    Every route() call prints to terminal:
    [ModelRouter] command=<cmd> model=<model_id> reason=<reason>
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set


# -----------------------------------------------------------------------------
# Model Constants
# -----------------------------------------------------------------------------

MODEL_MINI = "gpt-4.1-mini"
MODEL_THINKING = "gpt-5.1"
PERSONA_MODEL = MODEL_THINKING  # Persona always uses thinking tier


# -----------------------------------------------------------------------------
# Model Tier Definitions
# -----------------------------------------------------------------------------

@dataclass
class ModelTier:
    """Defines a model tier with its identifier and characteristics."""
    name: str
    model_id: str
    max_input_chars: int
    description: str


TIER_MINI = ModelTier(
    name="mini",
    model_id=MODEL_MINI,
    max_input_chars=8000,
    description="Fast syscommand processing, default tier",
)

TIER_THINKING = ModelTier(
    name="thinking",
    model_id=MODEL_THINKING,
    max_input_chars=128000,
    description="Deep reasoning, LLM-intensive commands",
)


# -----------------------------------------------------------------------------
# LLM-Intensive Commands (use thinking tier)
# -----------------------------------------------------------------------------

LLM_INTENSIVE_COMMANDS: Set[str] = {
    "interpret",
    "derive",
    "synthesize",
    "frame",
    "forecast",
    "compose",
    "prompt_command",
    "prompt-command",
    "command-wizard",
}


# -----------------------------------------------------------------------------
# Routing Context
# -----------------------------------------------------------------------------

@dataclass
class RoutingContext:
    """Context passed to ModelRouter.route() for model selection."""
    command: Optional[str] = None
    input_length: int = 0
    explicit_model: Optional[str] = None
    think_mode: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)


# -----------------------------------------------------------------------------
# Model Router
# -----------------------------------------------------------------------------

class ModelRouter:
    """
    v0.6.6 Model Routing Engine
    
    Logs EVERY routing decision to terminal via print().
    """

    def __init__(
        self,
        mini: Optional[ModelTier] = None,
        thinking: Optional[ModelTier] = None,
        llm_intensive_commands: Optional[Set[str]] = None,
    ):
        self.mini = mini or TIER_MINI
        self.thinking = thinking or TIER_THINKING
        self.llm_intensive_commands = llm_intensive_commands or LLM_INTENSIVE_COMMANDS

        self._tiers = {
            "mini": self.mini,
            "thinking": self.thinking,
        }
        self._model_ids = {
            self.mini.model_id: self.mini,
            self.thinking.model_id: self.thinking,
        }

    def route(self, ctx: Optional[RoutingContext] = None) -> str:
        """
        Determine the appropriate model ID based on context.
        
        Priority:
        1. explicit_model override
        2. think_mode flag → thinking
        3. LLM_INTENSIVE_COMMANDS → thinking
        4. Input length > threshold → thinking
        5. Default → mini
        
        ALWAYS prints logging to terminal.
        """
        if ctx is None:
            ctx = RoutingContext()

        model_id: str
        reason: str

        # 1. Explicit model override
        if ctx.explicit_model:
            if ctx.explicit_model in self._model_ids:
                model_id = ctx.explicit_model
                reason = "explicit_model"
            elif ctx.explicit_model in self._tiers:
                model_id = self._tiers[ctx.explicit_model].model_id
                reason = "explicit_tier"
            else:
                model_id = ctx.explicit_model
                reason = "explicit_unknown"

        # 2. Think mode flag
        elif ctx.think_mode:
            model_id = self.thinking.model_id
            reason = "think_mode"

        # 3. LLM-intensive commands
        elif ctx.command and ctx.command.lower() in self.llm_intensive_commands:
            model_id = self.thinking.model_id
            reason = "llm_intensive"

        # 4. Input length
        elif ctx.input_length > self.mini.max_input_chars:
            model_id = self.thinking.model_id
            reason = "input_length"

        # 5. Default → mini
        else:
            model_id = self.mini.model_id
            reason = "default"

        # ALWAYS LOG
        cmd_str = ctx.command or "unknown"
        print(f"[ModelRouter] command={cmd_str} model={model_id} reason={reason}", flush=True)

        return model_id

    def route_for_command(
        self,
        command: str,
        input_text: str = "",
        think: bool = False,
        explicit_model: Optional[str] = None,
        mode: str = "normal",  # Kept for backward compatibility (ignored)
    ) -> str:
        """Convenience method for syscommand handlers."""
        ctx = RoutingContext(
            command=command,
            input_length=len(input_text),
            explicit_model=explicit_model,
            think_mode=think,
        )
        return self.route(ctx)

    def get_tier_for_model(self, model_id: str) -> str:
        tier = self._model_ids.get(model_id)
        return tier.name if tier else "unknown"

    def get_tier_info(self, model_id: str) -> Optional[ModelTier]:
        return self._model_ids.get(model_id)

    def list_tiers(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: {
                "model_id": tier.model_id,
                "max_input_chars": tier.max_input_chars,
                "description": tier.description,
            }
            for name, tier in self._tiers.items()
        }

    def is_llm_intensive(self, command: str) -> bool:
        return command.lower() in self.llm_intensive_commands


# -----------------------------------------------------------------------------
# Module-level singleton and convenience functions
# -----------------------------------------------------------------------------

_default_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    """Get or create the default ModelRouter singleton."""
    global _default_router
    if _default_router is None:
        _default_router = ModelRouter()
    return _default_router


def route(ctx: Optional[RoutingContext] = None) -> str:
    """Route using the default router."""
    return get_router().route(ctx)


def route_for_command(
    command: str,
    input_text: str = "",
    think: bool = False,
    explicit_model: Optional[str] = None,
    mode: str = "normal",
) -> str:
    """Route for a specific command using the default router."""
    return get_router().route_for_command(
        command=command,
        input_text=input_text,
        think=think,
        explicit_model=explicit_model,
        mode=mode,
    )
