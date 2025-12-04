# persona/nova_persona.py
"""
v0.6.1 — Nova Persona with Working Memory Support

The persona layer that gives Nova its voice, tone, and conversational continuity.
Now integrates with Working Memory for multi-turn conversation awareness.
"""

from typing import Any, Dict, Optional, List

from backend.llm_client import LLMClient

BASE_SYSTEM_PROMPT = """
You are Nova, an AI operating system persona running on top of a stateless LLM backend.

You are NOT a generic chatbot.
You are the cognitive and conversational layer of NovaOS, an AI operating system built from first principles.

NovaOS architecture (high-level):
- Backend: stateless LLM compute (this model).
- Kernel: deterministic orchestrator that handles syscommands, memory, modules, workflows, and policies.
- Persona: identity, tone, values, narrative, and long-term goals.
- Modules: domain-specific systems (finance, health, business, cybersecurity, etc.).
- Memory: semantic, procedural, and episodic memories stored outside the model.
- UI: a Windows desktop client that renders your responses.

Your role:
- Convert the user's intentions into clear structures: plans, workflows, checklists, mappings, explanations.
- Think from first principles: break down problems into atomic truths and rebuild solutions logically.
- Maintain a calm, softly warm, analytical, and emotionally intelligent tone.
- Prefer structure over noise: use lists, steps, and mappings.

You do NOT:
- Assume you are in control of persistent memory or modules.
- Directly read or write local files. Instead, you describe what should be done and the NovaOS kernel performs those actions.

When responding:
- Use concise, structured responses.
- Respect the current active module(s) and workflows passed in the context.
- Align with the user's long-term goals and previously-defined NovaOS architecture.
- If the kernel asks you to generate a new workflow, output a clear JSON-like structure with steps, phases, and dependencies.

You are one persistent persona (Nova) across all modules and sessions,
even though the backend LLM calls are stateless.
The kernel and memory layer provide continuity; you provide coherence and structure.

Tone:
- Calm
- Supportive but not saccharine
- Analytical and precise
- Emotionally aware but grounded

Always think like an operating system copilot, not a casual chat model.
"""


def build_working_memory_context(wm: Optional[Dict[str, Any]]) -> str:
    """
    Build a context string from Working Memory state.
    
    This helps Nova understand the ongoing conversation and respond naturally.
    """
    if not wm:
        return ""
    
    lines = []
    
    # Check if this is a continuation
    if wm.get("is_continuation") and wm.get("previous_topic"):
        lines.append("[CONVERSATION CONTEXT]")
        lines.append(f"We were just discussing: {wm.get('previous_topic')}")
        
        if wm.get("turn_count", 0) > 1:
            lines.append(f"This is turn {wm.get('turn_count')} in this topic.")
        
        if wm.get("previous_entities"):
            entities = ", ".join(wm.get("previous_entities", [])[:5])
            lines.append(f"Key things mentioned: {entities}")
        
        if wm.get("previous_message"):
            prev_msg = wm.get("previous_message", "")[:100]
            if len(wm.get("previous_message", "")) > 100:
                prev_msg += "..."
            lines.append(f"User's last message: \"{prev_msg}\"")
        
        if wm.get("previous_response"):
            prev_resp = wm.get("previous_response", "")[:150]
            if len(wm.get("previous_response", "")) > 150:
                prev_resp += "..."
            lines.append(f"Your last response: \"{prev_resp}\"")
        
        # Intent tracking
        if wm.get("previous_intent"):
            lines.append(f"Their intent seems to be: {wm.get('previous_intent')}")
        
        lines.append("")
        lines.append("The user's current message continues or relates to this context.")
        lines.append("Respond naturally as if in an ongoing conversation, not starting fresh.")
        
    elif wm.get("current_topic"):
        # New topic
        lines.append("[CONVERSATION CONTEXT]")
        lines.append(f"New topic: {wm.get('current_topic')}")
        lines.append(f"Intent: {wm.get('current_intent', 'unknown')}")
        
        # Mention topic history if relevant
        if wm.get("topic_history"):
            recent = wm.get("topic_history", [])[-2:]
            if recent:
                lines.append(f"We previously talked about: {', '.join(recent)}")
    
    if not lines:
        return ""
    
    return "\n".join(lines) + "\n"


def build_entity_resolution_hints(wm: Optional[Dict[str, Any]], text: str) -> str:
    """
    Build hints for resolving pronouns and references.
    
    Helps Nova understand what "that", "it", "those" refer to.
    """
    if not wm:
        return ""
    
    # Check for pronouns that need resolution
    pronouns = ["that", "it", "this", "those", "these", "they", "them", "the one", "earlier"]
    text_lower = text.lower()
    
    has_pronouns = any(p in text_lower for p in pronouns)
    if not has_pronouns:
        return ""
    
    lines = ["[REFERENCE RESOLUTION]"]
    lines.append("The user's message contains references that may need context:")
    
    if wm.get("previous_topic"):
        lines.append(f"- 'it/that/this' likely refers to: {wm.get('previous_topic')}")
    
    if wm.get("previous_entities"):
        entities = wm.get("previous_entities", [])
        if entities:
            lines.append(f"- 'they/those/these' may refer to: {', '.join(entities[:3])}")
    
    if wm.get("previous_message"):
        lines.append(f"- 'the earlier one' may refer to something in: \"{wm.get('previous_message', '')[:50]}...\"")
    
    lines.append("")
    
    return "\n".join(lines)


class NovaPersona:
    """
    Nova's persona and conversational layer.
    
    v0.6.1: Now supports Working Memory for multi-turn conversation continuity.
    """

    def __init__(self, llm_client: LLMClient, system_prompt: Optional[str] = None) -> None:
        self.llm_client = llm_client
        self.system_prompt = system_prompt or BASE_SYSTEM_PROMPT

    def generate_response(
        self,
        text: str,
        session_id: str,
        working_memory: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate a conversational reply using the Nova persona prompt.
        
        v0.6.1: Now accepts working_memory context for conversation continuity.
        
        Args:
            text: The user's current message
            session_id: Session identifier
            working_memory: Working Memory context dict with:
                - is_continuation: bool
                - previous_topic: str
                - previous_intent: str
                - previous_entities: List[str]
                - previous_message: str
                - previous_response: str
                - turn_count: int
                - current_topic: str
                - current_intent: str
                - current_entities: List[str]
        
        Returns:
            Nova's response as a string
        """
        # Build enriched system prompt with Working Memory context
        system = self.system_prompt
        
        if working_memory:
            wm_context = build_working_memory_context(working_memory)
            entity_hints = build_entity_resolution_hints(working_memory, text)
            
            if wm_context or entity_hints:
                system = self.system_prompt + "\n\n" + wm_context + entity_hints
        
        # Call the LLM
        result: Dict[str, Any] = self.llm_client.complete(
            system=system,
            user=text,
            session_id=session_id,
        )

        raw = result.get("text")
        if raw is None:
            return f"(persona-fallback) I heard: {text}"

        reply = str(raw).strip()
        if not reply:
            return f"(persona-empty) I heard: {text}"

        return reply
    
    def generate_with_context(
        self,
        text: str,
        session_id: str,
        additional_context: str = "",
        working_memory: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate response with additional context prepended.
        
        Useful for system-injected context beyond Working Memory.
        """
        system = self.system_prompt
        
        if additional_context:
            system = self.system_prompt + "\n\n" + additional_context
        
        if working_memory:
            wm_context = build_working_memory_context(working_memory)
            entity_hints = build_entity_resolution_hints(working_memory, text)
            system += "\n\n" + wm_context + entity_hints
        
        result: Dict[str, Any] = self.llm_client.complete(
            system=system,
            user=text,
            session_id=session_id,
        )

        raw = result.get("text")
        if raw is None:
            return f"(persona-fallback) I heard: {text}"

        reply = str(raw).strip()
        if not reply:
            return f"(persona-empty) I heard: {text}"

        return reply
