# kernel/kernel_response.py
"""
NovaOS v0.9.0 — Kernel Response Object

KernelResponse is the structured output from the kernel layer.
The persona layer uses this to render natural language replies.

This separates concerns:
- Kernel: Logic, routing, data
- Persona: Voice, tone, phrasing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class KernelResponse:
    """
    Structured response from the NovaOS kernel.
    
    Attributes:
        handled: Did the kernel handle this input?
                 True = kernel processed it (syscommand, module, etc.)
                 False = kernel didn't recognize it (fallback to persona)
        
        system_message: Pure system output for direct display.
                        Used for status dumps, debug output, etc.
                        If set, persona may display as-is or lightly format.
        
        persona_prompt: Content for persona to phrase naturally.
                        Kernel provides the "what", persona provides the "how".
                        Example: "User created a new quest called 'Learn Python'"
        
        payload: Structured data for UI, logging, or further processing.
                 Contains raw command results, module outputs, etc.
        
        command: Which command was executed (e.g., "status", "quest").
        
        error: Error message if something went wrong.
        
        suggestions: Optional follow-up suggestions for the user.
    
    Usage:
        # Kernel handled a syscommand
        return KernelResponse(
            handled=True,
            command="status",
            persona_prompt="NovaOS is healthy with 5 modules loaded.",
            payload={"modules": 5, "memory_health": "ok"}
        )
        
        # Kernel didn't recognize input
        return KernelResponse(handled=False)
    """
    
    handled: bool
    system_message: Optional[str] = None
    persona_prompt: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    command: Optional[str] = None
    error: Optional[str] = None
    suggestions: Optional[List[str]] = None
    
    # ─────────────────────────────────────────────────────────────────────
    # Factory Methods
    # ─────────────────────────────────────────────────────────────────────
    
    @classmethod
    def not_handled(cls) -> "KernelResponse":
        """Create a 'not handled' response for persona fallback."""
        return cls(handled=False)
    
    @classmethod
    def success(
        cls,
        command: str,
        persona_prompt: str,
        payload: Optional[Dict[str, Any]] = None,
        suggestions: Optional[List[str]] = None,
    ) -> "KernelResponse":
        """Create a successful handled response."""
        return cls(
            handled=True,
            command=command,
            persona_prompt=persona_prompt,
            payload=payload or {},
            suggestions=suggestions,
        )
    
    @classmethod
    def system(
        cls,
        command: str,
        system_message: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> "KernelResponse":
        """Create a system output response (displayed as-is)."""
        return cls(
            handled=True,
            command=command,
            system_message=system_message,
            payload=payload or {},
        )
    
    @classmethod
    def error_response(
        cls,
        command: str,
        error: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> "KernelResponse":
        """Create an error response."""
        return cls(
            handled=True,
            command=command,
            error=error,
            payload=payload or {},
        )
    
    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────
    
    @property
    def is_error(self) -> bool:
        """Check if this is an error response."""
        return self.error is not None
    
    @property
    def has_system_message(self) -> bool:
        """Check if this has a system message for direct display."""
        return self.system_message is not None
    
    @property
    def has_persona_prompt(self) -> bool:
        """Check if this has content for persona to phrase."""
        return self.persona_prompt is not None
    
    def get_display_content(self) -> str:
        """
        Get the primary content for display.
        
        Priority:
        1. Error message
        2. System message (as-is)
        3. Persona prompt (to be phrased)
        4. Empty string
        """
        if self.error:
            return f"Error: {self.error}"
        if self.system_message:
            return self.system_message
        if self.persona_prompt:
            return self.persona_prompt
        return ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            "handled": self.handled,
            "system_message": self.system_message,
            "persona_prompt": self.persona_prompt,
            "payload": self.payload,
            "command": self.command,
            "error": self.error,
            "suggestions": self.suggestions,
        }
    
    def __repr__(self) -> str:
        if not self.handled:
            return "KernelResponse(handled=False)"
        return f"KernelResponse(handled=True, command='{self.command}')"
