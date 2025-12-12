# PATCH: kernel/dashboard_handlers.py
# Nova Council Dashboard Integration
#
# This patch adds Council status to the dashboard MODE section.
# Apply by modifying the _render_system_health function.

"""
================================================================================
INSTRUCTIONS: Apply the following changes to kernel/dashboard_handlers.py
================================================================================

1. ADD THIS IMPORT at the top of the file (after other imports):

--------------------------------------------------------------------------------
# Nova Council integration
try:
    from council.dashboard_integration import get_council_display_status
    _HAS_COUNCIL = True
except ImportError:
    _HAS_COUNCIL = False
    get_council_display_status = None
--------------------------------------------------------------------------------


2. MODIFY the _render_system_health function:

FIND THIS SECTION:
--------------------------------------------------------------------------------
def _render_system_health(view: ViewMode, kernel: Any, state: Any = None) -> str:
    \"\"\"Render the System/Mode section.\"\"\"
    # Get persona status
    persona_on = False
    if state and hasattr(state, "novaos_enabled"):
        persona_on = not state.novaos_enabled
    
    persona_status = "ON" if persona_on else "OFF"
    
    lines = [_section_border()]
    lines.append(_line("MODE"))
    lines.append(_line(f"  Persona: {persona_status}"))
--------------------------------------------------------------------------------

REPLACE WITH:
--------------------------------------------------------------------------------
def _render_system_health(view: ViewMode, kernel: Any, state: Any = None, session_id: str = None) -> str:
    \"\"\"Render the System/Mode section with Council status.\"\"\"
    # Get persona status
    persona_on = False
    if state and hasattr(state, "novaos_enabled"):
        persona_on = not state.novaos_enabled
    
    persona_status = "ON" if persona_on else "OFF"
    
    # Get Council status (Nova Council integration)
    council_status = "OFF"
    if _HAS_COUNCIL and session_id and get_council_display_status:
        try:
            council_status = get_council_display_status(session_id)
        except Exception:
            pass
    
    lines = [_section_border()]
    lines.append(_line("MODE"))
    lines.append(_line(f"  Persona: {persona_status} | Council: {council_status}"))
--------------------------------------------------------------------------------


3. UPDATE the render_dashboard function to pass session_id:

FIND:
--------------------------------------------------------------------------------
    renderers = {
        "header": lambda: _render_header(view, kernel, state),
        "today_readiness": lambda: _render_today_readiness(view, kernel),
        "module_status": lambda: _render_module_status(view, kernel),
        "finance_snapshot": lambda: _render_finance_snapshot(view, kernel),
        "system_health": lambda: _render_system_health(view, kernel, state),
    }
--------------------------------------------------------------------------------

REPLACE WITH:
--------------------------------------------------------------------------------
    renderers = {
        "header": lambda: _render_header(view, kernel, state),
        "today_readiness": lambda: _render_today_readiness(view, kernel),
        "module_status": lambda: _render_module_status(view, kernel),
        "finance_snapshot": lambda: _render_finance_snapshot(view, kernel),
        "system_health": lambda: _render_system_health(view, kernel, state, session_id),
    }
--------------------------------------------------------------------------------


4. UPDATE render_dashboard signature:

FIND:
--------------------------------------------------------------------------------
def render_dashboard(
    view: ViewMode = "compact",
    kernel: Any = None,
    state: Any = None,
    sections: Optional[list] = None,
) -> str:
--------------------------------------------------------------------------------

REPLACE WITH:
--------------------------------------------------------------------------------
def render_dashboard(
    view: ViewMode = "compact",
    kernel: Any = None,
    state: Any = None,
    sections: Optional[list] = None,
    session_id: str = None,
) -> str:
--------------------------------------------------------------------------------

================================================================================
END OF PATCH
================================================================================
"""
