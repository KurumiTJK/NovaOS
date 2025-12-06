# kernel/assistant_mode.py
"""
v0.8.0 — Assistant Mode for NovaOS Life RPG

Controls the presentation style of NovaOS responses:

- **story** — Full Life RPG experience
  - Narrative flavor text
  - XP celebrations with fanfare
  - Quest completion ceremonies
  - Rich formatting and emojis
  - Boss battle drama
  
- **utility** — Clean, minimal responses
  - Just the facts
  - Minimal formatting
  - No fanfare or celebrations
  - Efficient for getting things done

The mode affects how command responses are formatted,
but does NOT change the underlying functionality.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


# =============================================================================
# MODE ENUM
# =============================================================================

class AssistantMode(Enum):
    """Available assistant modes."""
    STORY = "story"
    UTILITY = "utility"
    
    @classmethod
    def from_string(cls, value: str) -> "AssistantMode":
        """Parse mode from string."""
        value = value.lower().strip()
        if value in ("story", "rpg", "narrative", "full"):
            return cls.STORY
        elif value in ("utility", "minimal", "clean", "simple"):
            return cls.UTILITY
        else:
            raise ValueError(f"Unknown mode: {value}. Use 'story' or 'utility'.")


# =============================================================================
# MODE CONFIGURATION
# =============================================================================

@dataclass
class ModeConfig:
    """Configuration for a specific mode."""
    name: str
    description: str
    show_xp_fanfare: bool = True
    show_level_up_celebration: bool = True
    show_quest_narrative: bool = True
    show_emojis: bool = True
    show_borders: bool = True
    verbose_feedback: bool = True


# Default configurations
MODE_CONFIGS: Dict[AssistantMode, ModeConfig] = {
    AssistantMode.STORY: ModeConfig(
        name="Story Mode",
        description="Full Life RPG experience with narrative and celebrations",
        show_xp_fanfare=True,
        show_level_up_celebration=True,
        show_quest_narrative=True,
        show_emojis=True,
        show_borders=True,
        verbose_feedback=True,
    ),
    AssistantMode.UTILITY: ModeConfig(
        name="Utility Mode", 
        description="Clean, minimal responses focused on efficiency",
        show_xp_fanfare=False,
        show_level_up_celebration=False,
        show_quest_narrative=False,
        show_emojis=False,
        show_borders=False,
        verbose_feedback=False,
    ),
}


# =============================================================================
# ASSISTANT MODE MANAGER
# =============================================================================

class AssistantModeManager:
    """
    Manages the assistant mode and provides formatting helpers.
    
    Usage:
        manager = AssistantModeManager()
        manager.set_mode("story")
        
        if manager.show_xp_fanfare:
            print("🎉 +50 XP!")
        else:
            print("+50 XP")
    """
    
    def __init__(self, initial_mode: str = "story"):
        self._mode = AssistantMode.from_string(initial_mode)
    
    @property
    def mode(self) -> AssistantMode:
        """Get current mode."""
        return self._mode
    
    @property
    def mode_name(self) -> str:
        """Get current mode name as string."""
        return self._mode.value
    
    @property
    def config(self) -> ModeConfig:
        """Get current mode configuration."""
        return MODE_CONFIGS[self._mode]
    
    def set_mode(self, mode: str) -> None:
        """Set the assistant mode."""
        self._mode = AssistantMode.from_string(mode)
    
    def is_story_mode(self) -> bool:
        """Check if in story mode."""
        return self._mode == AssistantMode.STORY
    
    def is_utility_mode(self) -> bool:
        """Check if in utility mode."""
        return self._mode == AssistantMode.UTILITY
    
    # -------------------------------------------------------------------------
    # Formatting Properties (shortcuts to config)
    # -------------------------------------------------------------------------
    
    @property
    def show_xp_fanfare(self) -> bool:
        return self.config.show_xp_fanfare
    
    @property
    def show_level_up_celebration(self) -> bool:
        return self.config.show_level_up_celebration
    
    @property
    def show_quest_narrative(self) -> bool:
        return self.config.show_quest_narrative
    
    @property
    def show_emojis(self) -> bool:
        return self.config.show_emojis
    
    @property
    def show_borders(self) -> bool:
        return self.config.show_borders
    
    @property
    def verbose_feedback(self) -> bool:
        return self.config.verbose_feedback
    
    # -------------------------------------------------------------------------
    # Formatting Helpers
    # -------------------------------------------------------------------------
    
    def format_xp_gain(self, amount: int, source: Optional[str] = None) -> str:
        """Format XP gain message."""
        if self.show_xp_fanfare:
            if source:
                return f"🎉 **+{amount} XP** from {source}!"
            return f"🎉 **+{amount} XP**!"
        else:
            if source:
                return f"+{amount} XP ({source})"
            return f"+{amount} XP"
    
    def format_level_up(self, new_level: int) -> str:
        """Format level up message."""
        if self.show_level_up_celebration:
            return f"🎊 **LEVEL UP!** You are now level {new_level}! 🎊"
        else:
            return f"Level up: {new_level}"
    
    def format_tier_up(self, domain: str, tier_name: str) -> str:
        """Format tier up message."""
        if self.show_level_up_celebration:
            return f"⬆️ **{domain.title()} tier up!** Now: {tier_name}"
        else:
            return f"{domain} tier: {tier_name}"
    
    def format_quest_complete(self, quest_title: str) -> str:
        """Format quest completion message."""
        if self.show_quest_narrative:
            return (
                "═══════════════════════════════\n"
                f"🎉 **Quest Complete: {quest_title}**\n"
                "═══════════════════════════════"
            )
        else:
            return f"Quest complete: {quest_title}"
    
    def format_boss_defeated(self) -> str:
        """Format boss defeated message."""
        if self.show_quest_narrative:
            return "👑 **Boss defeated!**"
        else:
            return "Boss defeated"
    
    def format_title_earned(self, title: str) -> str:
        """Format title earned message."""
        if self.show_xp_fanfare:
            return f"🏆 **New Title:** {title}"
        else:
            return f"Title: {title}"
    
    def format_header(self, text: str) -> str:
        """Format a section header."""
        if self.show_borders:
            return f"╔══ {text} ══╗"
        else:
            return f"## {text}"
    
    def format_emoji(self, emoji: str, fallback: str = "") -> str:
        """Return emoji if in story mode, fallback otherwise."""
        if self.show_emojis:
            return emoji
        return fallback
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "mode": self._mode.value,
            "config": {
                "name": self.config.name,
                "description": self.config.description,
                "show_xp_fanfare": self.config.show_xp_fanfare,
                "show_level_up_celebration": self.config.show_level_up_celebration,
                "show_quest_narrative": self.config.show_quest_narrative,
                "show_emojis": self.config.show_emojis,
                "show_borders": self.config.show_borders,
                "verbose_feedback": self.config.verbose_feedback,
            }
        }


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_assistant_mode(cmd_name, args, session_id, context, kernel, meta) -> "CommandResponse":
    """
    View or set the assistant mode (story vs utility).
    
    Usage:
        #assistant-mode           - Show current mode
        #assistant-mode story     - Set to story mode (full RPG experience)
        #assistant-mode utility   - Set to utility mode (minimal, clean)
    """
    from .command_types import CommandResponse
    
    manager = getattr(kernel, 'assistant_mode_manager', None)
    if not manager:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary="Assistant mode system not available.",
            error_code="NO_MODE_MANAGER",
        )
    
    # Get desired mode from args
    desired_mode = None
    if isinstance(args, dict):
        desired_mode = args.get("mode")
        positional = args.get("_", [])
        if not desired_mode and positional:
            desired_mode = positional[0]
    elif isinstance(args, str):
        desired_mode = args
    
    # If no mode specified, show current
    if not desired_mode:
        config = manager.config
        lines = [
            manager.format_header("Assistant Mode"),
            "",
            f"**Current:** {config.name}",
            f"*{config.description}*",
            "",
            "**Settings:**",
        ]
        
        if manager.show_emojis:
            lines.append(f"  ✓ XP fanfare")
            lines.append(f"  ✓ Level celebrations")
            lines.append(f"  ✓ Quest narrative")
            lines.append(f"  ✓ Emojis")
            lines.append(f"  ✓ Decorative borders")
        else:
            lines.append(f"  • XP fanfare: off")
            lines.append(f"  • Level celebrations: off")
            lines.append(f"  • Quest narrative: off")
            lines.append(f"  • Emojis: off")
            lines.append(f"  • Decorative borders: off")
        
        lines.append("")
        lines.append("**Switch modes:**")
        lines.append("• `#assistant-mode story` — Full RPG experience")
        lines.append("• `#assistant-mode utility` — Minimal, clean output")
        
        return CommandResponse(
            ok=True,
            command=cmd_name,
            summary="\n".join(lines),
            data=manager.to_dict(),
        )
    
    # Set mode
    try:
        manager.set_mode(desired_mode)
    except ValueError as e:
        return CommandResponse(
            ok=False,
            command=cmd_name,
            summary=str(e),
            error_code="INVALID_MODE",
        )
    
    # Also store in env_state for persistence
    if hasattr(kernel, 'set_env'):
        kernel.set_env("assistant_mode", manager.mode_name)
    elif hasattr(kernel, 'env_state'):
        kernel.env_state["assistant_mode"] = manager.mode_name
    
    # Confirm change
    config = manager.config
    if manager.is_story_mode():
        summary = (
            "🎭 **Story Mode activated!**\n\n"
            "The full Life RPG experience awaits. "
            "Expect narrative flavor, XP celebrations, and quest drama!"
        )
    else:
        summary = (
            "⚡ Utility Mode activated.\n\n"
            "Clean, minimal responses. Just the essentials."
        )
    
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=manager.to_dict(),
    )


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

ASSISTANT_MODE_HANDLERS = {
    "handle_assistant_mode": handle_assistant_mode,
}


def get_assistant_mode_handlers():
    """Get all assistant mode handlers for registration."""
    return ASSISTANT_MODE_HANDLERS
