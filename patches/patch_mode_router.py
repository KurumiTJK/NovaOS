# PATCH: core/mode_router.py
# Nova Council Mode Router Integration
#
# This patch integrates Council pipeline processing into the main message flow.

"""
================================================================================
INSTRUCTIONS: Apply the following changes to core/mode_router.py
================================================================================

1. ADD THESE IMPORTS at the top of the file (after other imports):

--------------------------------------------------------------------------------
# Nova Council integration
try:
    from council.mode_router_integration import (
        process_with_council,
        inject_council_context,
    )
    from council.state import get_council_state, CouncilMode
    _HAS_COUNCIL = True
except ImportError:
    _HAS_COUNCIL = False
    process_with_council = None
    inject_council_context = None
    get_council_state = None
    CouncilMode = None
--------------------------------------------------------------------------------


2. MODIFY the _handle_novaos_mode_strict function to integrate Council:

FIND the function _handle_novaos_mode_strict and ADD council processing
after any wizard checks but BEFORE kernel.interpret() is called.

Example location to insert (after wizard handling, before kernel call):

--------------------------------------------------------------------------------
def _handle_novaos_mode_strict(
    message: str,
    state: NovaState,
    kernel: "NovaKernel",
    persona: "NovaPersona",
) -> Dict[str, Any]:
    \"\"\"
    Handle input when NovaOS is ON (Strict mode).
    \"\"\"
    session_id = state.session_id or "default"
    
    # ... existing wizard handling code ...
    
    # === NOVA COUNCIL INTEGRATION START ===
    council_result = None
    clean_message = message
    council_context = {}
    
    if _HAS_COUNCIL and process_with_council:
        try:
            # Check if we're in a quest flow or command composer
            in_quest_flow = _is_in_quest_flow(session_id)
            in_command_composer = _is_in_command_composer(session_id)
            
            # Process through council
            council_result, clean_message, council_context = process_with_council(
                user_text=message,
                session_id=session_id,
                kernel=kernel,
                in_quest_flow=in_quest_flow,
                in_command_composer=in_command_composer,
            )
            
            # Log council mode
            print(f"[ModeRouter] council_mode={council_result.mode.value} gemini_used={council_result.gemini_used}", flush=True)
            
        except Exception as e:
            print(f"[ModeRouter] Council processing error (continuing without): {e}", file=sys.stderr, flush=True)
    # === NOVA COUNCIL INTEGRATION END ===
    
    # Use clean_message (flags stripped) for kernel processing
    result = kernel.interpret(clean_message, session_id=session_id)
    
    # ... rest of function ...
--------------------------------------------------------------------------------


3. ADD helper functions to detect quest/command flows:

--------------------------------------------------------------------------------
def _is_in_quest_flow(session_id: str) -> bool:
    \"\"\"Check if session is in quest composition flow.\"\"\"
    try:
        from kernel.quest_compose_wizard import get_compose_session
        session = get_compose_session(session_id)
        return session is not None and session.stage is not None
    except Exception:
        return False


def _is_in_command_composer(session_id: str) -> bool:
    \"\"\"Check if session is in command composer flow.\"\"\"
    # Currently no command composer wizard exists
    # This is a placeholder for future implementation
    return False
--------------------------------------------------------------------------------


4. MODIFY persona LLM calls to inject council context:

If you have a persona call that builds a system prompt, wrap it like this:

FIND:
--------------------------------------------------------------------------------
system_prompt = persona.build_system_prompt(...)
--------------------------------------------------------------------------------

ADD AFTER:
--------------------------------------------------------------------------------
# Inject council context if available
if _HAS_COUNCIL and inject_council_context and council_context:
    system_prompt = inject_council_context(system_prompt, council_context)
--------------------------------------------------------------------------------


5. ADD council mode to response metadata:

FIND any place where you build the response dict, and ADD:

--------------------------------------------------------------------------------
response = {
    "text": result_text,
    "ok": True,
    # ... other fields ...
    
    # Add council metadata
    "council_mode": council_result.mode.value if council_result else "OFF",
    "council_gemini_used": council_result.gemini_used if council_result else False,
}
--------------------------------------------------------------------------------

================================================================================
END OF PATCH
================================================================================
"""
