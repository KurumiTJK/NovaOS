# nova_api.py
"""
NovaOS Flask API Server — v0.9.0

Now uses the dual-mode architecture:
- Default: Persona mode (pure conversation)
- After #boot: NovaOS mode (kernel + modules)
- After #shutdown: Back to Persona mode
"""

from flask import Flask, request, jsonify, send_from_directory
from pathlib import Path

from system.config import Config
from kernel.nova_kernel import NovaKernel
from backend.llm_client import LLMClient
from persona.nova_persona import NovaPersona

# v0.9.0: Import mode router
from core.mode_router import handle_user_message, get_or_create_state

BASE_DIR = Path(__file__).parent

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

# Shared LLM client
llm_client = LLMClient()

# Kernel (for NovaOS mode)
kernel = NovaKernel(config=config, llm_client=llm_client)

# Persona (for both modes)
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
    
    Query: ?session_id=iphone
    
    Returns: {
        "session_id": "iphone",
        "mode": "Persona" | "NovaOS",
        "novaos_enabled": true | false
    }
    """
    session_id = request.args.get("session_id", "web-default")
    state = get_or_create_state(session_id)
    
    return jsonify({
        "session_id": state.session_id,
        "mode": state.mode_name,
        "novaos_enabled": state.novaos_enabled,
    })


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("NovaOS API Server v0.9.0")
    print("Dual-mode architecture enabled")
    print("  - Default: Persona mode")
    print("  - #boot: Activate NovaOS")
    print("  - #shutdown: Return to Persona mode")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True)
