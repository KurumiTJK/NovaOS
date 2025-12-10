# backend/model_router.py
"""
v0.10.0 — Model Routing Engine (DETERMINISTIC, NO FALLBACK)

Model Tiers (TWO tiers only):
- MINI:     gpt-4.1-mini  — lightweight syscommands
- THINKING: gpt-5.1       — heavy LLM-intensive commands, persona

v0.10.0 CHANGES:
- Added #complete and #halt to LIGHT_SYSCOMMANDS

v0.9.0 CHANGES:
- DETERMINISTIC routing: heavy commands → gpt-5.1, light → gpt-4.1-mini
- NO FALLBACK: if model unavailable, raise hard error
- Expanded HEAVY_LLM_COMMANDS set with all intensive syscommands
- Enhanced logging: every route() call logs command + model + reason

Logging:
    Every route() call prints to terminal:
    [ModelRouter] command=<cmd> model=<model_id> reason=<reason>
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set


# -----------------------------------------------------------------------------
# Model Constants
# -----------------------------------------------------------------------------

MODEL_MINI = "gpt-4.1-mini"
MODEL_THINKING = "gpt-5.1"
PERSONA_MODEL = MODEL_THINKING  # Persona ALWAYS uses thinking tier


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
    description="Fast syscommand processing, lightweight commands",
)

TIER_THINKING = ModelTier(
    name="thinking",
    model_id=MODEL_THINKING,
    max_input_chars=128000,
    description="Deep reasoning, LLM-intensive commands",
)


# -----------------------------------------------------------------------------
# HEAVY LLM-INTENSIVE COMMANDS (use gpt-5.1, NO EXCEPTIONS)
# -----------------------------------------------------------------------------

HEAVY_LLM_COMMANDS: Set[str] = {
    # Quest/Workflow commands (multi-step reasoning)
    "quest-compose",
    "quest-delete",
    "flow",
    "compose",
    "advance",
    
    # Custom command execution (may need deep reasoning)
    "prompt_command",
    "prompt-command",
    "command-wizard",
    
    # Any kernel planner or long structured output
    "interpret",
    "derive",
    "analyze",
}


# -----------------------------------------------------------------------------
# LIGHT SYSCOMMANDS (use gpt-4.1-mini)
# These are fast, simple commands that don't need deep reasoning
# -----------------------------------------------------------------------------

LIGHT_SYSCOMMANDS: Set[str] = {
    # Basic utility commands
    "help",
    "status",
    "boot",
    "shutdown",
    "ping",
    
    # Memory commands (simple CRUD)
    "memory",
    "memory-recall",
    "memory-add",
    "memory-list",
    "memory-search",
    "memory-clear",
    "memory-decay",
    "memory-drift",
    "memory-reconfirm",
    "memory-stale",
    "memory-archive-stale",
    "memory-policy",
    "memory-policy-test",
    "memory-mode-filter",
    "memory-high-salience",
    
    # Identity commands
    "identity-show",
    "identity-set",
    "identity-snapshot",
    "identity-history",
    "identity-restore",
    "identity-clear-history",
    
    # Inspection commands
    "inspect",
    "presence",
    "env",
    "env-set",
    "env-reset",
    
    # Quest simple commands (not composition)
    "quest",
    "quest-list",
    "quest-inspect",
    "quest-log",
    "quest-reset",
    "quest-debug",
    "next",
    "pause",
    
    # v0.10.0: New quest commands
    "complete",
    "halt",
    
    # Reminder commands
    "remind-add",
    "remind-list",
    "remind-update",
    "remind-delete",
    
    # Custom command management (not execution)
    "command-add",
    "command-list",
    "command-inspect",
    "command-enable",
    "command-disable",
    "command-delete",
    
    # Module commands
    "bind-module",
    "module-list",
    "module-inspect",
    
    # Snapshot/restore
    "snapshot",
    "restore",
    
    # Section navigation
    "section",
    "back",
    
    # Continuity
    "preferences",
    "projects",
    "continuity-context",
    "reconfirm-prompts",
    
    # Human state
    "evolution-status",
    "log-state",
    "state-history",
    "capacity-check",
    
    # Time rhythm
    "time-rhythm-add",
    "time-rhythm-list",
    "time-rhythm-delete",
    "time-rhythm-trigger",
    
    # Debug
    "debug",
    "decay-preview",
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
# Custom Exceptions
# -----------------------------------------------------------------------------

class ModelRoutingError(Exception):
    """Raised when model routing fails with no fallback."""
    pass


class ModelUnavailableError(Exception):
    """Raised when a required model is unavailable."""
    pass


# -----------------------------------------------------------------------------
# Model Router (DETERMINISTIC, NO FALLBACK)
# -----------------------------------------------------------------------------

class ModelRouter:
    """
    v0.10.0 Model Routing Engine — DETERMINISTIC, NO FALLBACK
    
    Routing Rules:
    1. explicit_model override → use that model exactly (error if invalid)
    2. think_mode=True → gpt-5.1 (NO FALLBACK)
    3. command in HEAVY_LLM_COMMANDS → gpt-5.1 (NO FALLBACK)
    4. command in LIGHT_SYSCOMMANDS → gpt-4.1-mini (NO FALLBACK)
    5. Unknown command → gpt-4.1-mini (default for safety)
    
    Logs EVERY routing decision to terminal via print().
    """

    def __init__(
        self,
        mini: Optional[ModelTier] = None,
        thinking: Optional[ModelTier] = None,
        heavy_commands: Optional[Set[str]] = None,
        light_commands: Optional[Set[str]] = None,
    ):
        self.mini = mini or TIER_MINI
        self.thinking = thinking or TIER_THINKING
        self.heavy_commands = heavy_commands or HEAVY_LLM_COMMANDS
        self.light_commands = light_commands or LIGHT_SYSCOMMANDS

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
        
        DETERMINISTIC PRIORITY (NO FALLBACK):
        1. explicit_model override → use exact model (error if invalid)
        2. think_mode=True → gpt-5.1
        3. command in HEAVY_LLM_COMMANDS → gpt-5.1
        4. command in LIGHT_SYSCOMMANDS → gpt-4.1-mini
        5. Unknown command → gpt-4.1-mini (default)
        
        ALWAYS prints logging to terminal.
        NO fallback behavior — fails hard if model invalid.
        """
        if ctx is None:
            ctx = RoutingContext()

        model_id: str
        reason: str
        cmd_lower = (ctx.command or "").lower().strip()

        # 1. Explicit model override (NO FALLBACK)
        if ctx.explicit_model:
            if ctx.explicit_model in self._model_ids:
                model_id = ctx.explicit_model
                reason = "explicit_model"
            elif ctx.explicit_model in self._tiers:
                model_id = self._tiers[ctx.explicit_model].model_id
                reason = "explicit_tier"
            else:
                # HARD ERROR: Invalid explicit model
                error_msg = f"Invalid explicit_model '{ctx.explicit_model}'. Valid: {list(self._model_ids.keys())}"
                print(f"[ModelRouter] ERROR: {error_msg}", file=sys.stderr, flush=True)
                raise ModelRoutingError(error_msg)

        # 2. Think mode flag → gpt-5.1 (NO FALLBACK)
        elif ctx.think_mode:
            model_id = self.thinking.model_id
            reason = "think_mode"

        # 3. HEAVY commands → gpt-5.1 (NO FALLBACK)
        elif cmd_lower in self.heavy_commands:
            model_id = self.thinking.model_id
            reason = "heavy_command"

        # 4. LIGHT commands → gpt-4.1-mini
        elif cmd_lower in self.light_commands:
            model_id = self.mini.model_id
            reason = "light_command"

        # 5. Unknown command → default to mini (with warning)
        else:
            model_id = self.mini.model_id
            reason = "unknown_default"
            if cmd_lower:
                print(
                    f"[ModelRouter] WARNING: Unknown command '{cmd_lower}' not in heavy or light sets, defaulting to {model_id}",
                    file=sys.stderr,
                    flush=True,
                )

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

    def is_heavy_command(self, command: str) -> bool:
        """Check if command is in heavy (gpt-5.1) set."""
        return command.lower().strip() in self.heavy_commands

    def is_light_command(self, command: str) -> bool:
        """Check if command is in light (gpt-4.1-mini) set."""
        return command.lower().strip() in self.light_commands

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

    def list_heavy_commands(self) -> Set[str]:
        """Return set of heavy commands (gpt-5.1)."""
        return self.heavy_commands.copy()

    def list_light_commands(self) -> Set[str]:
        """Return set of light commands (gpt-4.1-mini)."""
        return self.light_commands.copy()


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


def is_heavy_command(command: str) -> bool:
    """Check if command requires gpt-5.1."""
    return get_router().is_heavy_command(command)


def is_light_command(command: str) -> bool:
    """Check if command uses gpt-4.1-mini."""
    return get_router().is_light_command(command)
