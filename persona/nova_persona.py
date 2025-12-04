# persona/nova_persona.py
"""
NovaOS v0.7 — Nova Persona with Working Memory Engine

The persona layer that gives Nova its voice, tone, and conversational continuity.
Integrates with NovaWM for true multi-turn conversation awareness.

Key capabilities:
- Uses NovaWM context for coherent responses
- Answers reference questions directly when possible
- Maintains natural conversation flow
- Resolves pronouns automatically
"""

from typing import Any, Dict, Optional

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


class NovaPersona:
    """
    Nova's persona and conversational layer.
    
    v0.7: Uses NovaWM for comprehensive working memory.
    """

    def __init__(self, llm_client: LLMClient, system_prompt: Optional[str] = None) -> None:
        self.llm_client = llm_client
        self.system_prompt = system_prompt or BASE_SYSTEM_PROMPT

    def generate_response(
        self,
        text: str,
        session_id: str,
        wm_context: Optional[Dict[str, Any]] = None,
        wm_context_string: Optional[str] = None,
        direct_answer: Optional[str] = None,
    ) -> str:
        """
        Generate a conversational reply using the Nova persona prompt.
        
        Args:
            text: The user's current message
            session_id: Session identifier
            wm_context: Working memory context bundle (dict)
            wm_context_string: Pre-formatted context string for system prompt
            direct_answer: If WM can answer directly, this is the answer
        
        Returns:
            Nova's response as a string
        """
        # If working memory can provide a direct answer to a reference question
        if direct_answer:
            # Return it directly for simple recalls
            # For more complex questions, we might still want LLM to phrase it nicely
            return direct_answer
        
        # Build system prompt with working memory context
        system = self.system_prompt
        
        if wm_context_string:
            system = self.system_prompt + "\n\n" + wm_context_string
        elif wm_context:
            # Build context string from bundle
            context_str = self._build_context_from_bundle(wm_context)
            if context_str:
                system = self.system_prompt + "\n\n" + context_str
        
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
    
    def _build_context_from_bundle(self, bundle: Dict[str, Any]) -> str:
        """Build context string from WM bundle if no pre-formatted string provided."""
        if not bundle:
            return ""
        
        lines = ["[WORKING MEMORY CONTEXT]"]
        
        # Turn count
        if bundle.get("turn_count"):
            lines.append(f"Turn {bundle['turn_count']} in this conversation.")
        
        # Active topic
        if bundle.get("active_topic"):
            topic = bundle["active_topic"]
            lines.append(f"Current topic: {topic.get('name', 'unknown')}")
        
        # People
        people = bundle.get("entities", {}).get("people", [])
        if people:
            lines.append("People mentioned:")
            for p in people[:3]:
                desc = f" ({p.get('description')})" if p.get('description') else ""
                lines.append(f"  - {p.get('name')}{desc}")
        
        # Projects
        projects = bundle.get("entities", {}).get("projects", [])
        if projects:
            lines.append("Projects/topics:")
            for p in projects[:3]:
                lines.append(f"  - {p.get('name')}")
        
        # Pronoun resolution
        referents = bundle.get("referents", {})
        if referents:
            lines.append("Pronoun resolution:")
            for pronoun, name in list(referents.items())[:5]:
                lines.append(f"  - '{pronoun}' → {name}")
        
        # Goals
        goals = bundle.get("goals", [])
        if goals:
            lines.append("User goals:")
            for g in goals[:2]:
                lines.append(f"  - {g.get('description', '')[:60]}")
        
        # Instructions
        lines.append("")
        lines.append("Use this context to maintain conversation continuity.")
        lines.append("Resolve pronouns using the mapping above.")
        
        return "\n".join(lines)


# =============================================================================
# INTEGRATION WITH NOVA KERNEL
# =============================================================================

def create_persona_with_wm(llm_client: LLMClient) -> NovaPersona:
    """
    Create a NovaPersona instance configured for working memory.
    
    This is the factory function the kernel should use.
    """
    return NovaPersona(llm_client)
