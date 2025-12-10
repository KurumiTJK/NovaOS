"""
NovaOS Flask API — v0.10.3

Updated with:
- JSON error responses for LLM timeout/network failures
- Global exception handler to prevent HTML error pages
- Enhanced SSE streaming for QuestCompose wizard "generate" action
- Proper error envelope format: {"ok": false, "error": "...", "message": "..."}
"""

import json
import os
import sys
from pathlib import Path

# -----------------------------------------------------------------------------
# Path Setup — Must happen BEFORE any other imports
# -----------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


# -----------------------------------------------------------------------------
# Environment Loading — Must happen BEFORE importing modules that use API keys
# -----------------------------------------------------------------------------

def _ensure_env_loaded():
    """
    Ensure .env is loaded before any other imports.
    This is critical for LLMClient initialization.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("[NovaAPI] WARNING: python-dotenv not installed", file=sys.stderr, flush=True)
        return
    
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"[NovaAPI] Loaded .env from {env_path}", flush=True)
    else:
        cwd_env = Path.cwd() / ".env"
        if cwd_env.exists():
            load_dotenv(cwd_env, override=True)
            print(f"[NovaAPI] Loaded .env from {cwd_env}", flush=True)
        else:
            print(f"[NovaAPI] WARNING: No .env file found", file=sys.stderr, flush=True)


# Load environment FIRST
_ensure_env_loaded()


# -----------------------------------------------------------------------------
# Now safe to import modules that use API keys
# -----------------------------------------------------------------------------

from flask import Flask, request, jsonify, send_from_directory, Response

from system.config import Config
from kernel.nova_kernel import NovaKernel
from backend.llm_client import LLMClient, LLMTimeoutError, LLMError, PersonaModeError, StrictModeError
from persona.nova_persona import NovaPersona

# v0.9.0: Import mode router
from core.mode_router import handle_user_message, get_or_create_state


app = Flask(
    __name__,
    static_folder=str(BASE_DIR / "web"),
    static_url_path=""
)

# ─────────────────────────────────────────────────────────────────────────────
# INITIALIZATION
# ─────────────────────────────────────────────────────────────────────────────

# Config points at your existing data folder
config = Config(data_dir=BASE_DIR / "data")

# Shared LLM client (API key is now guaranteed to be loaded)
llm_client = LLMClient()

# Kernel (for NovaOS mode)
kernel = NovaKernel(config=config, llm_client=llm_client)

# Persona (for both modes) - uses the SAME llm_client
persona = NovaPersona(llm_client)


# ─────────────────────────────────────────────────────────────────────────────
# v0.10.2: GLOBAL ERROR HANDLERS — Ensure JSON responses, never HTML
# ─────────────────────────────────────────────────────────────────────────────

@app.errorhandler(Exception)
def handle_exception(e):
    """
    Global exception handler to ensure all errors return JSON, not HTML.
    
    v0.10.2: This prevents the frontend from receiving HTML error pages
    that cause 'Unexpected token <' errors when calling response.json().
    """
    # Log the error
    print(f"[NovaAPI] Unhandled exception: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    import traceback
    traceback.print_exc()
    
    # Return JSON error response
    return jsonify({
        "ok": False,
        "error": "server_error",
        "message": f"An unexpected server error occurred: {str(e)}",
        "text": "Nova encountered an unexpected error. Please try again.",
    }), 500


@app.errorhandler(404)
def handle_404(e):
    """Return JSON for 404 errors on API routes."""
    if request.path.startswith('/nova'):
        return jsonify({
            "ok": False,
            "error": "not_found",
            "message": f"Endpoint not found: {request.path}",
            "text": "Nova endpoint not found.",
        }), 404
    # For non-API routes, return the index.html for SPA routing
    return send_from_directory(app.static_folder, "index.html")


@app.errorhandler(500)
def handle_500(e):
    """Return JSON for 500 errors."""
    return jsonify({
        "ok": False,
        "error": "server_error",
        "message": "Internal server error",
        "text": "Nova encountered a server error. Please try again.",
    }), 500


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the web UI."""
    return send_from_directory(app.static_folder, "index.html")


@app.post("/nova")
def nova_endpoint():
    """
    Main chat endpoint.
    
    Body: { "text": "hey nova", "session_id": "iphone" }
    
    Returns: {
        "text": "response text",
        "mode": "Persona" | "NovaOS",
        "handled_by": "persona" | "kernel" | "mode_router",
        ...
    }
    
    v0.10.2: Now catches LLM timeout/network errors and returns JSON error envelope
    instead of letting Flask return HTML 500 pages.
    """
    try:
        data = request.get_json(force=True) or {}
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "invalid_json",
            "message": f"Invalid JSON in request body: {e}",
            "text": "Nova received invalid JSON. Please try again.",
        }), 400
    
    text = (data.get("text") or "").strip()
    session_id = data.get("session_id", "web-default")

    if not text:
        return jsonify({
            "ok": False,
            "error": "no_text",
            "message": "No text provided",
            "text": "",
        }), 400

    try:
        # Get or create state for this session
        state = get_or_create_state(session_id)
        
        # Route through the mode router
        result = handle_user_message(
            message=text,
            state=state,
            kernel=kernel,
            persona=persona,
        )
        
        return jsonify(result)
    
    # v0.10.2: Catch LLM timeout/network errors specifically
    except LLMTimeoutError as e:
        print(f"[NovaAPI] LLM timeout: {e}", file=sys.stderr, flush=True)
        return jsonify({
            "ok": False,
            "error": "llm_timeout",
            "message": "Nova timed out talking to the LLM. Please try again.",
            "text": "Nova timed out while processing your request. The AI service may be slow or unavailable. Please try again in a moment.",
        }), 502
    
    except PersonaModeError as e:
        print(f"[NovaAPI] Persona mode error: {e}", file=sys.stderr, flush=True)
        return jsonify({
            "ok": False,
            "error": "persona_error",
            "message": str(e),
            "text": "Nova's persona mode encountered an error. Please try again.",
        }), 502
    
    except StrictModeError as e:
        print(f"[NovaAPI] Strict mode error: {e}", file=sys.stderr, flush=True)
        return jsonify({
            "ok": False,
            "error": "strict_mode_error",
            "message": str(e),
            "text": "Nova's strict mode encountered an error. Please try again.",
        }), 502
    
    except LLMError as e:
        print(f"[NovaAPI] LLM error: {e}", file=sys.stderr, flush=True)
        return jsonify({
            "ok": False,
            "error": "llm_error",
            "message": str(e),
            "text": "Nova encountered an LLM error. Please try again.",
        }), 502
    
    except Exception as e:
        # Catch-all for any other errors — return JSON, not HTML
        print(f"[NovaAPI] Unexpected error in /nova: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({
            "ok": False,
            "error": "server_error",
            "message": f"Unexpected server error: {str(e)}",
            "text": "Nova encountered an unexpected error. Please try again.",
        }), 500


# ─────────────────────────────────────────────────────────────────────────────
# SSE STREAMING ENDPOINT — v0.10.3 (Enhanced for QuestCompose)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/nova/stream")
def nova_stream_endpoint():
    """
    Server-Sent Events streaming endpoint for long-running operations.
    
    v0.10.3: Enhanced to support QuestCompose wizard streaming with progress events.
    
    Body: { "text": "generate", "session_id": "...", "stream_mode": "quest_compose" }
    
    Returns: SSE stream with events:
        - event: progress      - Progress updates { message, percent }
        - event: wizard_log    - QuestCompose log messages { session_id, message }
        - event: wizard_update - Partial content updates { session_id, content }
        - event: wizard_complete - Final result { session_id, result }
        - event: wizard_error  - Error occurred { session_id, error, message }
        - event: complete      - Generic completion (non-wizard)
        - event: error         - Generic error
    
    Usage (JavaScript):
        const response = await fetch('/nova/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: 'generate', session_id: '...', stream_mode: 'quest_compose' })
        });
    """
    try:
        data = request.get_json(force=True) or {}
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": "invalid_json",
            "message": f"Invalid JSON in request body: {e}",
        }), 400
    
    text = (data.get("text") or "").strip()
    session_id = data.get("session_id", "web-default")
    stream_mode = data.get("stream_mode", "")  # v0.10.3: Optional mode hint

    if not text:
        return jsonify({"error": "No text provided"}), 400

    def generate():
        """Generator for SSE events."""
        try:
            # Send initial progress
            yield _sse_event("progress", {"message": "Starting...", "percent": 0})
            
            # Get or create state
            state = get_or_create_state(session_id)
            
            # === v0.10.3: QuestCompose Streaming Support ===
            # Check if this is a QuestCompose wizard streaming request
            if stream_mode == "quest_compose" or _is_quest_compose_generate(text, session_id):
                yield from _stream_quest_compose_wizard(text, session_id, state)
                return
            
            # Check if this is a streaming-enabled command (legacy path)
            if text.startswith("#quest-compose"):
                # Use streaming quest compose
                yield from _stream_quest_compose(text, session_id, state)
            else:
                # For non-streaming commands, just do normal processing
                yield _sse_event("progress", {"message": "Processing...", "percent": 50})
                
                result = handle_user_message(
                    message=text,
                    state=state,
                    kernel=kernel,
                    persona=persona,
                )
                
                yield _sse_event("complete", result)
        
        # v0.10.2: Catch LLM timeout errors in streaming
        except LLMTimeoutError as e:
            print(f"[NovaAPI] Stream LLM timeout: {e}", file=sys.stderr, flush=True)
            yield _sse_event("wizard_error", {
                "session_id": session_id,
                "error": "llm_timeout",
                "message": "Nova timed out talking to the LLM. Please try again.",
            })
        
        except (PersonaModeError, StrictModeError, LLMError) as e:
            print(f"[NovaAPI] Stream LLM error: {e}", file=sys.stderr, flush=True)
            yield _sse_event("wizard_error", {
                "session_id": session_id,
                "error": "llm_error",
                "message": str(e),
            })
                
        except Exception as e:
            print(f"[NovaAPI] Stream error: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()
            yield _sse_event("wizard_error", {
                "session_id": session_id,
                "error": "server_error",
                "message": str(e),
            })
    
    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
        }
    )


def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# v0.10.3: QuestCompose Streaming Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_quest_compose_generate(text: str, session_id: str) -> bool:
    """
    Check if this is a QuestCompose wizard "generate" action at Step 3.
    
    Returns True if:
    - There's an active QuestCompose wizard session
    - The session is at stage="steps", substage="choice" or ""
    - The user input is "generate", "gen", "g", or "auto"
    """
    try:
        from kernel.quest_compose_wizard import (
            has_active_compose_session,
            get_compose_session,
        )
        
        if not has_active_compose_session(session_id):
            return False
        
        session = get_compose_session(session_id)
        if not session:
            return False
        
        # Check if we're at the steps stage, waiting for generate/manual choice
        if session.stage != "steps":
            return False
        
        if session.substage not in ("", "choice"):
            return False
        
        # Check if the input is a "generate" command
        choice = text.lower().strip()
        return choice in ("generate", "gen", "g", "auto")
    
    except Exception as e:
        print(f"[NovaAPI] Error checking quest compose state: {e}", file=sys.stderr, flush=True)
        return False


def _stream_quest_compose_wizard(text: str, session_id: str, state):
    """
    Stream the QuestCompose wizard "generate" action with real-time progress.
    
    v0.10.3: This is the main streaming handler for QuestCompose step generation.
    
    Yields SSE events as the wizard processes:
    - wizard_log: Progress messages from the generation pipeline
    - wizard_update: Partial content (e.g., outline steps as they're generated)
    - wizard_complete: Final result with generated steps
    - wizard_error: Error occurred during generation
    """
    from kernel.quest_compose_wizard import (
        get_compose_session,
        set_compose_session,
        _generate_steps_with_llm_streaming,
        _format_steps_with_actions,
        _base_response,
    )
    
    cmd_name = "#quest-compose"
    
    try:
        yield _sse_event("wizard_log", {
            "session_id": session_id,
            "message": "[QuestCompose] Starting streaming generation...",
        })
        yield _sse_event("progress", {"message": "Initializing...", "percent": 5})
        
        # Get the wizard session
        session = get_compose_session(session_id)
        if not session:
            yield _sse_event("wizard_error", {
                "session_id": session_id,
                "error": "no_session",
                "message": "No active QuestCompose wizard session found.",
            })
            return
        
        # Create a streaming progress callback that yields SSE events
        def progress_callback(message: str, percent: int):
            """Callback invoked by _generate_steps_with_llm_streaming for progress."""
            # This is called from within the generator, so we can't yield here directly
            # Instead, we'll use a different approach - see below
            pass
        
        # Generate steps with streaming
        yield _sse_event("wizard_log", {
            "session_id": session_id,
            "message": f"[QuestCompose] Generating steps for: {session.draft.get('title', 'Untitled')}",
        })
        yield _sse_event("progress", {"message": "Phase 1: Analyzing objectives...", "percent": 10})
        
        # Use the streaming generator version
        generated_steps = []
        generation_error = None
        
        try:
            # Call the streaming version which yields progress events
            for event in _generate_steps_with_llm_streaming(session.draft, kernel, session_id):
                if event["type"] == "log":
                    yield _sse_event("wizard_log", {
                        "session_id": session_id,
                        "message": event["message"],
                    })
                elif event["type"] == "progress":
                    yield _sse_event("progress", {
                        "message": event["message"],
                        "percent": event["percent"],
                    })
                elif event["type"] == "update":
                    yield _sse_event("wizard_update", {
                        "session_id": session_id,
                        "content": event["content"],
                    })
                elif event["type"] == "steps":
                    generated_steps = event["steps"]
                elif event["type"] == "error":
                    generation_error = event["message"]
                    break
        
        except LLMTimeoutError as e:
            yield _sse_event("wizard_error", {
                "session_id": session_id,
                "error": "llm_timeout",
                "message": "Nova timed out while generating steps. Please try again.",
            })
            return
        
        except Exception as e:
            print(f"[NovaAPI] Quest compose generation error: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()
            yield _sse_event("wizard_error", {
                "session_id": session_id,
                "error": "generation_error",
                "message": f"Error generating steps: {str(e)}",
            })
            return
        
        # Handle generation result
        if generation_error:
            yield _sse_event("wizard_error", {
                "session_id": session_id,
                "error": "generation_failed",
                "message": generation_error,
            })
            return
        
        if generated_steps:
            # Success! Update the session
            session.draft["steps"] = generated_steps
            session.substage = "confirm_generated"
            set_compose_session(session_id, session)
            
            # Format steps for display
            step_list = _format_steps_with_actions(generated_steps, verbose=True)
            
            # Build the response
            response_text = (
                f"**Generated {len(generated_steps)} steps:**\n\n{step_list}\n"
                f"Type **accept** to use these, **regenerate** to try again, or **manual** to define your own:"
            )
            
            result = _base_response(
                cmd_name,
                response_text,
                {"wizard_active": True, "stage": "steps", "substage": "confirm_generated"}
            )
            
            yield _sse_event("progress", {"message": "Complete!", "percent": 100})
            yield _sse_event("wizard_complete", {
                "session_id": session_id,
                "result": {
                    "ok": result.ok,
                    "text": result.summary,
                    "summary": result.summary,
                    "data": result.data if hasattr(result, 'data') else {},
                    "steps_count": len(generated_steps),
                }
            })
        else:
            # Generation returned no steps
            error_msg = "Could not generate steps. Please try again or use manual mode."
            
            yield _sse_event("wizard_error", {
                "session_id": session_id,
                "error": "no_steps",
                "message": error_msg,
            })
    
    except Exception as e:
        print(f"[NovaAPI] Quest compose stream error: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        yield _sse_event("wizard_error", {
            "session_id": session_id,
            "error": "server_error",
            "message": str(e),
        })


def _stream_quest_compose(text: str, session_id: str, state):
    """
    Stream quest-compose operation with progress updates (legacy path).
    
    Yields SSE events as the quest is being composed.
    """
    try:
        from kernel.quest_compose_wizard import (
            handle_quest_compose,
            get_compose_session,
            has_active_compose_session,
        )
        
        yield _sse_event("progress", {"message": "Initializing quest composer...", "percent": 10})
        
        # Check if wizard is already active
        if has_active_compose_session(session_id):
            # Process wizard input
            from kernel.quest_compose_wizard import process_compose_wizard_input
            result = process_compose_wizard_input(session_id, text.replace("#quest-compose", "").strip(), kernel)
            if result:
                yield _sse_event("complete", {
                    "text": result.summary,
                    "ok": result.ok,
                    "data": result.data if hasattr(result, 'data') else {},
                })
                return
        
        # Start new wizard or process command
        yield _sse_event("progress", {"message": "Processing quest composition...", "percent": 30})
        
        # For streaming generation, we need to intercept the step generation
        # and yield progress updates
        result = handle_user_message(
            message=text,
            state=state,
            kernel=kernel,
            persona=persona,
        )
        
        yield _sse_event("progress", {"message": "Finalizing...", "percent": 90})
        yield _sse_event("complete", result)
        
    except LLMTimeoutError as e:
        print(f"[NovaAPI] Quest compose LLM timeout: {e}", file=sys.stderr, flush=True)
        yield _sse_event("error", {
            "error": "llm_timeout",
            "message": "Nova timed out while composing your quest. Please try again.",
        })
    except Exception as e:
        print(f"[NovaAPI] Quest compose stream error: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        yield _sse_event("error", {"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# STATUS/HEALTH ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/nova/status")
def status_endpoint():
    """
    Get current status for a session.
    
    Query params:
        session_id: The session to check (default: "web-default")
    
    Returns: {
        "mode": "Persona" | "NovaOS",
        "novaos_enabled": bool,
        "session_id": str
    }
    """
    session_id = request.args.get("session_id", "web-default")
    state = get_or_create_state(session_id)
    
    return jsonify({
        "mode": state.mode_name,
        "novaos_enabled": state.novaos_enabled,
        "session_id": session_id,
    })


@app.get("/nova/health")
def health_endpoint():
    """
    Health check endpoint.
    
    Returns basic server status and configuration info.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    return jsonify({
        "status": "ok",
        "version": "0.10.3",
        "base_dir": str(BASE_DIR),
        "api_key_configured": bool(api_key),
        "api_key_length": len(api_key) if api_key else 0,
        "streaming_enabled": True,
        "quest_compose_streaming": True,  # v0.10.3
    })


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[NovaAPI] Starting server...", flush=True)
    print(f"[NovaAPI] Base directory: {BASE_DIR}", flush=True)
    print(f"[NovaAPI] Static folder: {BASE_DIR / 'web'}", flush=True)
    
    # Run with debug=False in production
    app.run(host="0.0.0.0", port=5000, debug=True)
