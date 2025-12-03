# backend/model_router.py
"""
v0.5.3 — Model Routing Engine

Selects the appropriate LLM model tier based on task complexity,
command type, input length, and explicit user flags.

Model Tiers:
- MINI:     gpt-4.1-mini  — default, small tasks, fast responses
- STANDARD: gpt-4.1       — long context, medium-depth reasoning
- THINKING: gpt-5.1       — deep reasoning, multi-year planning, explicit "think" tasks

Backward-compatible: all existing code continues to work unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set


# -----------------------------------------------------------------------------
# Model Tier Definitions
# -----------------------------------------------------------------------------

@dataclass
class ModelTier:
    """Defines a model tier with its identifier and characteristics."""
    name: str
    model_id: str
    max_input_chars: int  # soft limit for routing decisions
    description: str


# Default model tiers (can be overridden via config)
TIER_MINI = ModelTier(
    name="mini",
    model_id="gpt-4.1-mini",
    max_input_chars=4000,
    description="Fast, small tasks, default tier",
)

TIER_STANDARD = ModelTier(
    name="standard",
    model_id="gpt-4.1",
    max_input_chars=32000,
    description="Medium-depth reasoning, longer context",
)

TIER_THINKING = ModelTier(
    name="thinking",
    model_id="gpt-5.1",
    max_input_chars=128000,
    description="Deep reasoning, complex planning, explicit think mode",
)


# -----------------------------------------------------------------------------
# Routing Context
# -----------------------------------------------------------------------------

@dataclass
class RoutingContext:
    """
    Context passed to ModelRouter.route() for model selection.
    
    All fields are optional — the router uses sensible defaults.
    """
    command: Optional[str] = None          # syscommand name (e.g., "interpret", "derive")
    input_length: int = 0                  # character count of user input
    explicit_model: Optional[str] = None   # user-specified model override
    mode: str = "normal"                   # from kernel.env_state["mode"]
    think_mode: bool = False               # explicit deep reasoning request
    meta: Dict[str, Any] = field(default_factory=dict)  # additional context


# -----------------------------------------------------------------------------
# Model Router
# -----------------------------------------------------------------------------

class ModelRouter:
    """
    v0.5.3 Model Routing Engine
    
    Determines which model tier to use based on:
    1. Explicit user override (highest priority)
    2. Think mode flag
    3. Command type (some commands always use higher tiers)
    4. Input length
    5. Environment mode
    6. Default fallback (mini)
    
    Usage:
        router = ModelRouter()
        model = router.route(RoutingContext(command="derive", input_length=500))
        # Returns "gpt-4.1" for derive command
    """

    # Commands that should use STANDARD tier by default
    STANDARD_COMMANDS: Set[str] = {
        "derive",       # first-principles breakdown
        "synthesize",   # integrate multiple ideas
        "frame",        # reframing requires nuance
        "compose",      # workflow generation
        "align",        # alignment suggestions
    }

    # Commands that should use THINKING tier by default
    THINKING_COMMANDS: Set[str] = {
        "forecast",     # future predictions need depth
    }

    # Modes that upgrade the default tier
    ELEVATED_MODES: Dict[str, str] = {
        "deep_work": "standard",
        "reflection": "standard",
        "debug": "mini",  # debug stays fast
    }

    def __init__(
        self,
        mini: Optional[ModelTier] = None,
        standard: Optional[ModelTier] = None,
        thinking: Optional[ModelTier] = None,
    ):
        """
        Initialize with optional custom model tiers.
        Defaults to the global TIER_* constants.
        """
        self.mini = mini or TIER_MINI
        self.standard = standard or TIER_STANDARD
        self.thinking = thinking or TIER_THINKING

        # Build lookup by name and model_id for validation
        self._tiers = {
            "mini": self.mini,
            "standard": self.standard,
            "thinking": self.thinking,
        }
        self._model_ids = {
            self.mini.model_id: self.mini,
            self.standard.model_id: self.standard,
            self.thinking.model_id: self.thinking,
        }

    def route(self, ctx: Optional[RoutingContext] = None) -> str:
        """
        Determine the appropriate model ID based on context.
        
        Returns:
            Model ID string (e.g., "gpt-4.1-mini")
        """
        if ctx is None:
            ctx = RoutingContext()

        # 1. Explicit model override (highest priority)
        if ctx.explicit_model:
            # Validate it's a known model or tier name
            if ctx.explicit_model in self._model_ids:
                return ctx.explicit_model
            if ctx.explicit_model in self._tiers:
                return self._tiers[ctx.explicit_model].model_id
            # Unknown model — pass through (user's responsibility)
            return ctx.explicit_model

        # 2. Think mode flag → always use thinking tier
        if ctx.think_mode:
            return self.thinking.model_id

        # 3. Command-based routing
        if ctx.command:
            cmd = ctx.command.lower()
            if cmd in self.THINKING_COMMANDS:
                return self.thinking.model_id
            if cmd in self.STANDARD_COMMANDS:
                return self.standard.model_id

        # 4. Input length routing
        if ctx.input_length > self.standard.max_input_chars:
            return self.thinking.model_id
        if ctx.input_length > self.mini.max_input_chars:
            return self.standard.model_id

        # 5. Mode-based elevation
        if ctx.mode in self.ELEVATED_MODES:
            tier_name = self.ELEVATED_MODES[ctx.mode]
            return self._tiers[tier_name].model_id

        # 6. Default fallback
        return self.mini.model_id

    def route_for_command(
        self,
        command: str,
        input_text: str = "",
        mode: str = "normal",
        think: bool = False,
        explicit_model: Optional[str] = None,
    ) -> str:
        """
        Convenience method for syscommand handlers.
        
        Example:
            model = router.route_for_command("derive", input_text=user_input)
        """
        ctx = RoutingContext(
            command=command,
            input_length=len(input_text),
            explicit_model=explicit_model,
            mode=mode,
            think_mode=think,
        )
        return self.route(ctx)

    def get_tier_info(self, model_id: str) -> Optional[ModelTier]:
        """
        Get tier information for a model ID.
        Returns None if not a known tier.
        """
        return self._model_ids.get(model_id)

    def list_tiers(self) -> Dict[str, Dict[str, Any]]:
        """
        Return all available tiers as a dict for inspection.
        """
        return {
            name: {
                "model_id": tier.model_id,
                "max_input_chars": tier.max_input_chars,
                "description": tier.description,
            }
            for name, tier in self._tiers.items()
        }


# -----------------------------------------------------------------------------
# Module-level convenience
# -----------------------------------------------------------------------------

# Default router instance (can be used directly or replaced)
_default_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    """Get or create the default ModelRouter instance."""
    global _default_router
    if _default_router is None:
        _default_router = ModelRouter()
    return _default_router


def route(ctx: Optional[RoutingContext] = None) -> str:
    """
    Module-level routing function using the default router.
    
    Example:
        from backend.model_router import route, RoutingContext
        model = route(RoutingContext(command="derive"))
    """
    return get_router().route(ctx)
