# PATCH: nova_api.py
# Nova Council API Integration
#
# This patch adds a status endpoint and integrates Council reset on app start.

"""
================================================================================
INSTRUCTIONS: Apply the following changes to nova_api.py
================================================================================

1. ADD THIS IMPORT near the top (after other imports):

--------------------------------------------------------------------------------
# Nova Council integration
try:
    from council import (
        get_council_state,
        clear_all_states as clear_council_states,
        CouncilMode,
    )
    from providers.gemini_client import get_gemini_status
    _HAS_COUNCIL = True
except ImportError:
    _HAS_COUNCIL = False
    get_council_state = None
    clear_council_states = None
    get_gemini_status = None
--------------------------------------------------------------------------------


2. ADD Council reset on app startup:

FIND the main startup code (near `if __name__ == "__main__":`) and ADD:

--------------------------------------------------------------------------------
# Reset Council state on fresh app launch
if _HAS_COUNCIL and clear_council_states:
    clear_council_states()
    print("[NovaAPI] Council state cleared (fresh launch)", flush=True)
--------------------------------------------------------------------------------


3. ADD a Council status endpoint:

--------------------------------------------------------------------------------
@app.route("/api/council/status", methods=["GET"])
def get_council_status():
    \"\"\"Get Nova Council status and configuration.\"\"\"
    if not _HAS_COUNCIL:
        return jsonify({
            "ok": False,
            "error": "Nova Council not installed",
            "council_available": False,
        })
    
    # Get session ID from query param or use default
    session_id = request.args.get("session_id", "default")
    
    try:
        state = get_council_state(session_id)
        gemini_status = get_gemini_status() if get_gemini_status else {}
        
        return jsonify({
            "ok": True,
            "council_available": True,
            "session_id": session_id,
            "state": {
                "mode": state.get_display_mode(),
                "used": state.used,
                "gemini_calls": state.gemini_calls,
                "cache_hits": state.cache_hits,
                "errors": state.errors,
            },
            "gemini": gemini_status,
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "council_available": True,
        })


@app.route("/api/council/reset", methods=["POST"])
def reset_council():
    \"\"\"Reset Council state for a session or all sessions.\"\"\"
    if not _HAS_COUNCIL:
        return jsonify({
            "ok": False,
            "error": "Nova Council not installed",
        })
    
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id")
        reset_all = data.get("all", False)
        
        if reset_all:
            clear_council_states()
            return jsonify({"ok": True, "message": "All Council states reset"})
        elif session_id:
            from council import reset_council_state
            reset_council_state(session_id)
            return jsonify({"ok": True, "message": f"Council state reset for session {session_id}"})
        else:
            return jsonify({"ok": False, "error": "Provide session_id or all=true"})
            
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
--------------------------------------------------------------------------------


4. UPDATE the /api/chat endpoint to include council mode in response:

FIND the response building section in your chat handler and ADD council metadata:

--------------------------------------------------------------------------------
# In the chat response handler, add to the response dict:
response_data = {
    "ok": True,
    "text": response_text,
    "mode": mode,
    # ... other fields ...
    
    # Council metadata (if available)
    "council": {
        "mode": council_result.mode.value if council_result else "OFF",
        "gemini_used": council_result.gemini_used if council_result else False,
    } if _HAS_COUNCIL else None,
}
--------------------------------------------------------------------------------

================================================================================
END OF PATCH
================================================================================
"""
