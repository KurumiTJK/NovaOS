# council/mode_router_integration.py
"""
Nova Council — Mode Router Integration

Integrates council pipelines into the existing NovaOS mode routing.

This module provides functions to be called from core/mode_router.py
to inject council processing into the message handling flow.

Key integration points:
1. Pre-process user text (strip flags, detect mode)
2. Run council pipeline (get Gemini context if applicable)
3. Inject extra_context into GPT-5 calls
4. Track council state for dashboard

Usage in mode_router.py:
    from council.mode_router_integration import process_with_council
    
    result, clean_text, council_ctx = process_with_council(
        user_text=message,
        session_id=session_id,
        in_quest_flow=is_in_quest_flow(),
    )
    
    # Use clean_text for further processing
    # Use council_ctx as extra_context in LLM calls
"""

import sys
from typing import Any, Callable, Dict, Optional, Tuple

from council.state import CouncilMode, CouncilState, get_council_state
from council.router import detect_council_mode, is_command_intent
from council.orchestrator import (
    PipelineResult,
    run_council_pipeline,
    run_live_max_pipeline,
)


# -----------------------------------------------------------------------------
# Context Retrieval for LIVE-MAX
# -----------------------------------------------------------------------------

def _get_command_design_context(kernel: Any = None) -> Dict[str, str]:
    """
    Retrieve code context for command design (LIVE-MAX mode).
    
    This collects:
    - SYS_HANDLERS registry
    - Command list/registry
    - Router/dispatcher logic
    - Dashboard helpers
    
    Args:
        kernel: NovaKernel instance for file access
        
    Returns:
        Dict mapping context_name -> code snippet
    """
    context: Dict[str, str] = {}
    
    # Try to read SYS_HANDLERS from syscommands.py
    try:
        import inspect
        from kernel.syscommands import SYS_HANDLERS
        
        # Get the handler names
        handler_names = list(SYS_HANDLERS.keys())
        context["sys_handlers_registry"] = f"SYS_HANDLERS keys: {handler_names}"
        
    except Exception as e:
        print(f"[CouncilContext] Failed to load SYS_HANDLERS: {e}", file=sys.stderr, flush=True)
    
    # Try to get command metadata from the kernel
    try:
        from kernel.syscommand_router import load_all_commands
        
        all_commands = load_all_commands()
        if all_commands:
            cmd_list = list(all_commands.keys())[:50]  # Limit for context size
            context["command_registry"] = f"Registered commands: {cmd_list}"
            
    except Exception as e:
        print(f"[CouncilContext] Failed to load command registry: {e}", file=sys.stderr, flush=True)
    
    # Try to read dashboard helpers
    try:
        from pathlib import Path
        
        dashboard_path = Path(__file__).parent.parent / "kernel" / "dashboard_handlers.py"
        if dashboard_path.exists():
            # Read first 100 lines for structure reference
            with open(dashboard_path, 'r') as f:
                lines = f.readlines()[:100]
            context["dashboard_helpers"] = "".join(lines)
            
    except Exception as e:
        print(f"[CouncilContext] Failed to load dashboard helpers: {e}", file=sys.stderr, flush=True)
    
    return context


# -----------------------------------------------------------------------------
# Main Integration Function
# -----------------------------------------------------------------------------

def process_with_council(
    user_text: str,
    session_id: str,
    kernel: Any = None,
    in_quest_flow: bool = False,
    in_command_composer: bool = False,
) -> Tuple[PipelineResult, str, Dict[str, Any]]:
    """
    Process user message through the council system.
    
    This is the main integration point to be called from mode_router.py.
    
    Args:
        user_text: Raw user input (may contain @flags)
        session_id: Current session ID
        kernel: NovaKernel instance
        in_quest_flow: True if inside quest composition wizard
        in_command_composer: True if inside command composer wizard
        
    Returns:
        (pipeline_result, clean_text, extra_context)
        
        - pipeline_result: Result from council pipeline
        - clean_text: User text with flags stripped
        - extra_context: Dict to inject into GPT-5 context
    """
    # Create context retrieval callback for LIVE-MAX
    def get_context_callback() -> Dict[str, str]:
        return _get_command_design_context(kernel)
    
    # Run council pipeline
    result, clean_text = run_council_pipeline(
        user_text=user_text,
        session_id=session_id,
        in_quest_flow=in_quest_flow,
        in_command_composer=in_command_composer,
        get_context_callback=get_context_callback,
    )
    
    # Build extra_context for GPT-5
    extra_context: Dict[str, Any] = {}
    
    if result.success and result.extra_context:
        extra_context.update(result.extra_context)
    
    # Add pipeline metadata
    extra_context["_council_mode"] = result.mode.value
    extra_context["_council_gemini_used"] = result.gemini_used
    
    return result, clean_text, extra_context


# -----------------------------------------------------------------------------
# GPT-5 Context Injection Helpers
# -----------------------------------------------------------------------------

def inject_council_context(
    system_prompt: str,
    extra_context: Dict[str, Any],
) -> str:
    """
    Inject council context into GPT-5 system prompt.
    
    Args:
        system_prompt: Base system prompt
        extra_context: Extra context from council pipeline
        
    Returns:
        Modified system prompt with council context appended
    """
    if not extra_context:
        return system_prompt
    
    # Skip internal metadata keys
    skip_keys = {"_council_mode", "_council_gemini_used"}
    
    context_parts = []
    
    # Add Gemini quest notes if present
    if "gemini_quest_notes" in extra_context:
        notes = extra_context["gemini_quest_notes"]
        context_parts.append(
            f"\n\n[COUNCIL: Quest Ideation Notes (from Gemini Flash)]\n"
            f"Use these notes to synthesize a complete quest:\n"
            f"```json\n{_format_json(notes)}\n```"
        )
    
    # Add Gemini live packet if present
    if "gemini_live_packet" in extra_context:
        packet = extra_context["gemini_live_packet"]
        context_parts.append(
            f"\n\n[COUNCIL: Research Context (from Gemini Pro)]\n"
            f"Use these facts and options to inform your response:\n"
            f"```json\n{_format_json(packet)}\n```"
        )
    
    # Add code context if present (LIVE-MAX)
    if "code_context" in extra_context:
        code_ctx = extra_context["code_context"]
        context_parts.append(
            f"\n\n[COUNCIL: Code Context for Command Design]\n"
            f"Reference this when designing the command:\n"
        )
        for name, snippet in code_ctx.items():
            context_parts.append(f"\n--- {name} ---\n{snippet[:2000]}")  # Limit size
    
    if context_parts:
        return system_prompt + "".join(context_parts)
    
    return system_prompt


def _format_json(data: Any) -> str:
    """Format data as JSON string for context injection."""
    import json
    try:
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        return str(data)


# -----------------------------------------------------------------------------
# LIVE-MAX GPT-5 Pass Prompts
# -----------------------------------------------------------------------------

LIVEMAX_DESIGN_SYSTEM_PROMPT = """You are designing a new NovaOS command. Your output must include:

1. COMMAND SPECIFICATION:
   - Command name (with # prefix)
   - Description
   - Usage patterns
   - Arguments and their types
   - Return format

2. INTEGRATION POINTS:
   - Handler function name
   - File location
   - Updates to SYS_HANDLERS dict
   - Menu/section registration

3. ERROR HANDLING:
   - Expected error cases
   - Error messages
   - Fallback behaviors

4. FORMATTING RULES:
   - Terminal output format (no markdown)
   - Width constraints
   - NovaOS style compliance

Output as a structured specification that can be directly implemented."""


LIVEMAX_VERIFY_SYSTEM_PROMPT = """You are verifying a NovaOS command specification for correctness.

Check for:
1. NAMING COLLISIONS:
   - Does the command name conflict with existing commands?
   - Is the handler name unique?

2. REGISTRY CONSISTENCY:
   - Is the SYS_HANDLERS entry correct?
   - Is the section registration valid?

3. FORMAT COMPLIANCE:
   - Is output terminal-friendly (no stray markdown)?
   - Does it follow NovaOS conventions?

4. EDGE CASES:
   - Are all error cases handled?
   - Are argument validations complete?

Output either:
- "VERIFIED: No issues found" + the unchanged spec
- "CORRECTIONS NEEDED:" + specific corrections + corrected spec"""


def get_design_pass_prompt() -> str:
    """Get system prompt for GPT-5 design pass."""
    return LIVEMAX_DESIGN_SYSTEM_PROMPT


def get_verify_pass_prompt() -> str:
    """Get system prompt for GPT-5 verify pass."""
    return LIVEMAX_VERIFY_SYSTEM_PROMPT


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    "process_with_council",
    "inject_council_context",
    "get_design_pass_prompt",
    "get_verify_pass_prompt",
]
