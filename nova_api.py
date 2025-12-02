from flask import Flask, request, jsonify, send_from_directory
from pathlib import Path
from system.config import Config
from kernel.nova_kernel import NovaKernel
from backend.llm_client import LLMClient

BASE_DIR = Path(__file__).parent

app = Flask(
    __name__,
    static_folder=str(BASE_DIR / "web"),
    static_url_path=""
)

# Config points at your existing data folder
config = Config(data_dir=BASE_DIR / "data")

# Share the same LLMClient as your main app
llm_client = LLMClient()

# Kernel does all routing + persona fallback
kernel = NovaKernel(config=config, llm_client=llm_client)


@app.route("/")
def index():
    # Serve NovaOS/web/index.html
    return send_from_directory(app.static_folder, "index.html")


@app.post("/nova")
def nova_endpoint():
    """
    Body: { "text": "hey nova", "session_id": "iphone" }
    """
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    session_id = data.get("session_id", "iphone")

    if not text:
        return jsonify({"error": "No text provided"}), 400

    result = kernel.handle_input(text, session_id=session_id)
    # handle_input already returns a dict suitable for the UI
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
