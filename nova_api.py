# nova_api.py
"""
NovaOS Flask API Server — v0.9.1

Now uses the dual-mode architecture:
- Default: Persona mode (pure conversation)
- After #boot: NovaOS mode (kernel + modules)
- After #shutdown: Back to Persona mode

v0.9.1: Added explicit .env loading at startup to ensure API keys are available
before any LLM client is created. Fixes "Incorrect API key" errors on remote servers.
"""

import os
import sys
from pathlib import Path

# -----------------------------------------------------------------------------
# CRITICAL: Load .env BEFORE any other imports that might use API keys
# -----------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.resolve()


def _ensure_env_loaded():
    """
    Load .env file before any imports that might need API keys.
    
    This is called at module level, before Flask or LLMClient imports,
    to ensure environment variables are set early.
    """
    env_path = BASE_DIR / ".env"
    
    if env_path.exists():
        try:
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        # Remove quotes
                        if value and value[0] in ('"', "'") and value[-1] == value[0]:
                            value = value[1:-1]
                        if key:
                            os.environ[key] = value
            print(f"[NovaAPI] Loaded .env from: {env_path}", flush=True)
        except Exception as e:
            print(f"[NovaAPI] Warning: Could not load .env: {e}", file=sys.stderr, flush=True)
    else:
        print(f"[NovaAPI] Warning: .env not found at {env_path}", file=sys.stderr, flush=True)
    
    # Verify API key is loaded
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        print(f"[NovaAPI] OPENAI_API_KEY: found ({len(api_key)} chars)", flush=True)
    else:
        print(f"[NovaAPI] WARNING: OPENAI_API_KEY not found!", file=sys.stderr, flush=True)


# Load environment FIRST
_ensure_env_loaded()


# -----------------------------------------------------------------------------
# Now safe to import modules that use API keys
# -----------------------------------------------------------------------------

from flask import Flask, request, jsonify, send_from_directory

from system.config import Config
from kernel.nova_kernel import NovaKernel
from backend.llm_client import LLMClient
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
    """
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    session_id = data.get("session_id", "web-default")

    if not text:
        return jsonify({"error": "No text provided", "text": ""}), 400

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
        "version": "0.9.1",
        "base_dir": str(BASE_DIR),
        "api_key_configured": bool(api_key),
        "api_key_length": len(api_key) if api_key else 0,
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
