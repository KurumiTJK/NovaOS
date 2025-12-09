# backend/llm_client.py
"""
v0.6.7 — LLM Client with Robust Environment Loading

FIXED: Ensures .env is loaded from the correct location regardless of
working directory. This fixes the "Incorrect API key" error on remote
servers like Lightsail where the working directory may differ.

Two channels:
1. PERSONA: Nova talking to user → always gpt-5.1
2. SYSTEM: syscommand tasks → routed by ModelRouter

Logging:
    Every LLM call prints to terminal:
    [LLM] channel=<channel> model=<model>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# -----------------------------------------------------------------------------
# ROBUST .env Loading (v0.6.7 FIX)
# -----------------------------------------------------------------------------

def _get_project_root() -> Path:
    """
    Get the project root directory.
    
    This works regardless of the current working directory by finding
    the directory containing this file and going up to the project root.
    """
    # This file is at: <project_root>/backend/llm_client.py
    # So project root is the parent of the parent directory
    this_file = Path(__file__).resolve()
    backend_dir = this_file.parent
    project_root = backend_dir.parent
    return project_root


def _load_env_file() -> bool:
    """
    Load environment variables from .env file.
    
    v0.6.7: Uses absolute paths based on project root to ensure
    .env is found regardless of working directory.
    
    Returns True if .env was loaded, False otherwise.
    """
    project_root = _get_project_root()
    
    # Priority order for .env file locations
    possible_paths = [
        project_root / ".env",           # Primary: project root
        Path.cwd() / ".env",             # Fallback: current working directory
        Path.home() / ".env",            # Fallback: home directory
    ]
    
    loaded = False
    loaded_from = None
    
    for env_path in possible_paths:
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
                            # Remove quotes if present
                            if value and value[0] in ('"', "'") and value[-1] == value[0]:
                                value = value[1:-1]
                            # Only set if not already in environment
                            if key and key not in os.environ:
                                os.environ[key] = value
                loaded = True
                loaded_from = env_path
                break
            except Exception as e:
                print(f"[LLM] Warning: Could not read {env_path}: {e}", file=sys.stderr, flush=True)
    
    # Debug logging
    api_key = os.getenv("OPENAI_API_KEY", "")
    key_status = f"found ({len(api_key)} chars)" if api_key else "NOT FOUND"
    
    print(f"[LLM] Project root: {project_root}", flush=True)
    print(f"[LLM] .env loaded: {loaded} (from: {loaded_from})", flush=True)
    print(f"[LLM] OPENAI_API_KEY: {key_status}", flush=True)
    
    return loaded


# Load .env immediately on module import
_env_loaded = _load_env_file()


# -----------------------------------------------------------------------------
# OpenAI Import
# -----------------------------------------------------------------------------

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    OpenAI = None  # type: ignore


# -----------------------------------------------------------------------------
# Model Router Import
# -----------------------------------------------------------------------------

from .model_router import (
    MODEL_MINI,
    MODEL_THINKING,
    PERSONA_MODEL,
    ModelRouter,
    RoutingContext,
    get_router,
)


# -----------------------------------------------------------------------------
# LLM Client
# -----------------------------------------------------------------------------

class LLMClient:
    """
    v0.6.7 LLM Client with comprehensive logging.
    
    Logs ALL LLM calls to terminal with channel and model.
    """

    def __init__(self, router: Optional[ModelRouter] = None):
        if not _HAS_OPENAI:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            # More helpful error message
            project_root = _get_project_root()
            raise RuntimeError(
                f"OPENAI_API_KEY not set.\n"
                f"Checked locations:\n"
                f"  1. {project_root / '.env'}\n"
                f"  2. {Path.cwd() / '.env'}\n"
                f"  3. Environment variable OPENAI_API_KEY\n"
                f"Please create a .env file with: OPENAI_API_KEY=sk-..."
            )

        # Log key info (masked)
        key_preview = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        print(f"[LLM] Initializing client with key: {key_preview}", flush=True)
        
        self.client = OpenAI(api_key=api_key)
        self.router = router or get_router()

    def _call_api(
        self,
        model: str,
        system_prompt: str,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> str:
        """Make the actual OpenAI API call."""
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *messages,
                ],
                **kwargs,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            print(f"[LLM] ERROR model={model} error={e}", file=sys.stderr, flush=True)
            raise

    # -------------------------------------------------------------------------
    # MAIN ENTRY POINT - used by _llm_with_policy in syscommands.py
    # -------------------------------------------------------------------------

    def complete(
        self,
        system: str,
        user: str,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Main entry point used by _llm_with_policy in syscommands.py
        
        The model is pre-selected by kernel.get_model() and passed via kwargs["model"].
        This method ALWAYS logs the call.
        """
        # Extract model (set by kernel.get_model() via _llm_with_policy)
        model = kwargs.pop("model", None) or PERSONA_MODEL
        
        # LOG - this fires for EVERY LLM call
        print(f"[LLM] model={model}", flush=True)
        
        messages = [{"role": "user", "content": user}]

        text = self._call_api(
            model=model,
            system_prompt=system,
            messages=messages,
            **{k: v for k, v in kwargs.items()},
        )

        return {
            "text": text,
            "session_id": session_id,
            "model": model,
        }

    # -------------------------------------------------------------------------
    # Low-level chat method (backward compatible)
    # -------------------------------------------------------------------------

    def chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> str:
        """Low-level chat completion (backward compatible)."""
        model = kwargs.pop("model", PERSONA_MODEL)
        
        # LOG
        print(f"[LLM] chat model={model}", flush=True)
        
        return self._call_api(
            model=model,
            system_prompt=system_prompt,
            messages=messages,
            **kwargs,
        )

    # -------------------------------------------------------------------------
    # Persona Channel (optional, for future use)
    # -------------------------------------------------------------------------

    def complete_persona(
        self,
        system: str,
        user: str,
        messages: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
        model_override: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Persona channel - always uses gpt-5.1 by default."""
        model = model_override or PERSONA_MODEL
        
        print(f"[LLM] persona model={model}", flush=True)
        
        msg_list = messages or []
        msg_list = [*msg_list, {"role": "user", "content": user}]

        text = self._call_api(
            model=model,
            system_prompt=system,
            messages=msg_list,
            **kwargs,
        )

        return {
            "text": text,
            "session_id": session_id,
            "model": model,
            "channel": "persona",
        }

    # -------------------------------------------------------------------------
    # System Channel (optional, for future use)
    # -------------------------------------------------------------------------

    def complete_system(
        self,
        system: str,
        user: str,
        command: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
        think_mode: bool = False,
        explicit_model: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """System channel - uses ModelRouter for model selection."""
        ctx = RoutingContext(
            command=command,
            input_length=len(user),
            explicit_model=explicit_model,
            think_mode=think_mode,
        )
        model = self.router.route(ctx)

        cmd_str = command or "unknown"
        print(f"[LLM] system command={cmd_str} model={model}", flush=True)

        msg_list = messages or []
        msg_list = [*msg_list, {"role": "user", "content": user}]

        text = self._call_api(
            model=model,
            system_prompt=system,
            messages=msg_list,
            **kwargs,
        )

        return {
            "text": text,
            "session_id": session_id,
            "model": model,
            "channel": "system",
        }
