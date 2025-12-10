# backend/llm_client.py
"""
v0.10.1 — LLM Client with Streaming Support

🔥 v0.10.1 CHANGES:
- Added streaming support for long-running operations
- New stream_complete_system() method returns a generator
- Keeps connections alive during quest-compose generation

v0.9.0 CHANGES:
- PERSONA MODE: Always gpt-5.1, NO FALLBACK, hard error on failure
- STRICT MODE: Uses ModelRouter with deterministic routing
- Enhanced logging: logs model + command for every call
- Removed all fallback behavior

Two channels:
1. PERSONA: Nova talking to user → ALWAYS gpt-5.1 (hard error if fails)
2. SYSTEM: syscommand tasks → routed by ModelRouter (no fallback)

Logging:
    Every LLM call prints to terminal:
    [LLM] channel=<channel> command=<cmd> model=<model>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


# -----------------------------------------------------------------------------
# ROBUST .env Loading
# -----------------------------------------------------------------------------

def _get_project_root() -> Path:
    """
    Get the project root directory.
    
    This works regardless of the current working directory by finding
    the directory containing this file and going up to the project root.
    """
    this_file = Path(__file__).resolve()
    backend_dir = this_file.parent
    project_root = backend_dir.parent
    return project_root


def _load_env_file() -> bool:
    """
    Load environment variables from .env file.
    
    Uses absolute paths based on project root to ensure
    .env is found regardless of working directory.
    
    Returns True if .env was loaded, False otherwise.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("[LLM] WARNING: python-dotenv not installed", file=sys.stderr, flush=True)
        return False

    project_root = _get_project_root()
    env_path = project_root / ".env"
    
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"[LLM] Loaded .env from {env_path}", flush=True)
        return True
    
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        load_dotenv(cwd_env, override=True)
        print(f"[LLM] Loaded .env from {cwd_env}", flush=True)
        return True
    
    print(f"[LLM] WARNING: No .env file found", file=sys.stderr, flush=True)
    return False


# Load env on import
_load_env_file()


# -----------------------------------------------------------------------------
# OpenAI Import
# -----------------------------------------------------------------------------

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    OpenAI = None


# -----------------------------------------------------------------------------
# Model Router Import
# -----------------------------------------------------------------------------

from .model_router import (
    ModelRouter,
    RoutingContext,
    get_router,
    PERSONA_MODEL,
    MODEL_MINI,
    MODEL_THINKING,
    HEAVY_LLM_COMMANDS,
    ModelRoutingError,
)


# -----------------------------------------------------------------------------
# Custom Exceptions
# -----------------------------------------------------------------------------

class LLMError(Exception):
    """Base exception for LLM errors."""
    pass


class PersonaModeError(LLMError):
    """Raised when persona mode LLM call fails (NO FALLBACK)."""
    pass


class StrictModeError(LLMError):
    """Raised when strict mode LLM call fails (NO FALLBACK)."""
    pass


# -----------------------------------------------------------------------------
# LLM Client
# -----------------------------------------------------------------------------

class LLMClient:
    """
    v0.10.1 LLM Client — Deterministic Model Selection + Streaming
    
    Channels:
    - PERSONA: Always gpt-5.1, hard error on failure
    - SYSTEM: Routed by ModelRouter (heavy→gpt-5.1, light→gpt-4.1-mini)
    
    Logs ALL LLM calls to terminal with channel, command, and model.
    """

    def __init__(self, router: Optional[ModelRouter] = None):
        if not _HAS_OPENAI:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
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
        channel: str = "unknown",
        command: str = "unknown",
        **kwargs,
    ) -> str:
        """
        Make the actual OpenAI API call.
        
        v0.9.0: Filters out incompatible kwargs before calling the API.
        Only passes standard Chat Completions parameters.
        """
        # Filter out any incompatible kwargs that might cause API errors
        # Standard Chat Completions params only
        allowed_params = {
            "temperature",
            "max_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "stop",
            "n",
            "stream",
            "logprobs",
            "top_logprobs",
            "response_format",
            "seed",
            "tools",
            "tool_choice",
            "user",
        }
        
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_params}
        
        # Log any filtered params for debugging
        removed = set(kwargs.keys()) - set(filtered_kwargs.keys())
        if removed:
            print(f"[LLM] WARNING: Filtered incompatible kwargs: {removed}", file=sys.stderr, flush=True)
        
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *messages,
                ],
                **filtered_kwargs,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            print(
                f"[LLM] ERROR channel={channel} command={command} model={model} error={e}",
                file=sys.stderr,
                flush=True,
            )
            raise

    def _call_api_streaming(
        self,
        model: str,
        system_prompt: str,
        messages: List[Dict[str, str]],
        channel: str = "unknown",
        command: str = "unknown",
        **kwargs,
    ) -> Generator[str, None, None]:
        """
        Make a streaming OpenAI API call.
        
        v0.10.1: Returns a generator that yields text chunks.
        """
        allowed_params = {
            "temperature",
            "max_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "stop",
            "n",
            "logprobs",
            "top_logprobs",
            "response_format",
            "seed",
            "tools",
            "tool_choice",
            "user",
        }
        
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_params}
        
        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *messages,
                ],
                stream=True,
                **filtered_kwargs,
            )
            
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except Exception as e:
            print(
                f"[LLM] ERROR channel={channel} command={command} model={model} error={e}",
                file=sys.stderr,
                flush=True,
            )
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
        If no model is passed, defaults to PERSONA_MODEL (gpt-5.1).
        
        This method ALWAYS logs the call.
        """
        model = kwargs.pop("model", None) or PERSONA_MODEL
        command = kwargs.pop("command", None) or "unknown"
        
        # LOG - this fires for EVERY LLM call
        print(f"[LLM] channel=complete command={command} model={model}", flush=True)
        
        messages = [{"role": "user", "content": user}]

        text = self._call_api(
            model=model,
            system_prompt=system,
            messages=messages,
            channel="complete",
            command=command,
            **kwargs,
        )

        return {
            "text": text,
            "session_id": session_id,
            "model": model,
            "channel": "complete",
        }

    # -------------------------------------------------------------------------
    # Low-level chat method (backward compatible)
    # -------------------------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, str]] = None,
        system_prompt: str = "",
        model: str = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Low-level chat completion (backward compatible).
        
        v0.10.1: Updated to handle both old and new call patterns.
        """
        # Handle various call patterns
        if messages is None:
            messages = []
        
        model = model or kwargs.pop("model", PERSONA_MODEL)
        command = kwargs.pop("command", None) or "unknown"
        
        # LOG
        print(f"[LLM] channel=chat command={command} model={model}", flush=True)
        
        text = self._call_api(
            model=model,
            system_prompt=system_prompt,
            messages=messages,
            channel="chat",
            command=command,
            **kwargs,
        )
        
        return {
            "content": text,
            "text": text,
            "model": model,
        }

    # -------------------------------------------------------------------------
    # PERSONA CHANNEL — ALWAYS gpt-5.1, NO FALLBACK
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
        """
        Persona channel — ALWAYS uses gpt-5.1 by default.
        
        v0.9.0: NO FALLBACK. If the call fails, raises PersonaModeError.
        """
        # Persona mode: ALWAYS gpt-5.1 unless explicitly overridden
        model = model_override or PERSONA_MODEL
        
        print(f"[LLM] channel=persona command=persona_chat model={model}", flush=True)
        
        msg_list = messages or []
        msg_list = [*msg_list, {"role": "user", "content": user}]

        try:
            text = self._call_api(
                model=model,
                system_prompt=system,
                messages=msg_list,
                channel="persona",
                command="persona_chat",
                **kwargs,
            )
        except Exception as e:
            # NO FALLBACK — raise hard error
            raise PersonaModeError(
                f"Persona mode LLM call failed with model={model}. "
                f"Error: {e}. NO FALLBACK available."
            ) from e

        return {
            "text": text,
            "session_id": session_id,
            "model": model,
            "channel": "persona",
        }

    # -------------------------------------------------------------------------
    # SYSTEM CHANNEL — Routed by ModelRouter, NO FALLBACK
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
        """
        System channel — uses ModelRouter for model selection.
        
        v0.9.0: DETERMINISTIC routing, NO FALLBACK.
        - Heavy commands (quest-compose, flow, etc.) → gpt-5.1
        - Light commands (help, status, etc.) → gpt-4.1-mini
        - think_mode=True → gpt-5.1
        
        Raises StrictModeError if LLM call fails.
        """
        # Use ModelRouter for deterministic routing
        ctx = RoutingContext(
            command=command,
            input_length=len(user),
            explicit_model=explicit_model,
            think_mode=think_mode,
        )
        
        try:
            model = self.router.route(ctx)
        except ModelRoutingError as e:
            raise StrictModeError(f"Model routing failed: {e}") from e

        cmd_str = command or "unknown"
        print(f"[LLM] channel=system command={cmd_str} model={model}", flush=True)

        msg_list = messages or []
        msg_list = [*msg_list, {"role": "user", "content": user}]

        try:
            text = self._call_api(
                model=model,
                system_prompt=system,
                messages=msg_list,
                channel="system",
                command=cmd_str,
                **kwargs,
            )
        except Exception as e:
            # NO FALLBACK — raise hard error
            raise StrictModeError(
                f"Strict mode LLM call failed for command='{cmd_str}' with model={model}. "
                f"Error: {e}. NO FALLBACK available."
            ) from e

        return {
            "text": text,
            "session_id": session_id,
            "model": model,
            "channel": "system",
            "command": cmd_str,
        }

    # -------------------------------------------------------------------------
    # STREAMING SYSTEM CHANNEL — For long-running operations
    # -------------------------------------------------------------------------

    def stream_complete_system(
        self,
        system: str,
        user: str,
        command: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        think_mode: bool = False,
        explicit_model: Optional[str] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        """
        Streaming system channel — returns a generator of text chunks.
        
        v0.10.1: For long-running operations like quest-compose.
        Keeps the connection alive by yielding chunks as they arrive.
        
        Usage:
            for chunk in llm_client.stream_complete_system(...):
                yield f"data: {chunk}\n\n"  # SSE format
        """
        ctx = RoutingContext(
            command=command,
            input_length=len(user),
            explicit_model=explicit_model,
            think_mode=think_mode,
        )
        
        try:
            model = self.router.route(ctx)
        except ModelRoutingError as e:
            raise StrictModeError(f"Model routing failed: {e}") from e

        cmd_str = command or "unknown"
        print(f"[LLM] channel=stream_system command={cmd_str} model={model}", flush=True)

        msg_list = messages or []
        msg_list = [*msg_list, {"role": "user", "content": user}]

        try:
            yield from self._call_api_streaming(
                model=model,
                system_prompt=system,
                messages=msg_list,
                channel="stream_system",
                command=cmd_str,
                **kwargs,
            )
        except Exception as e:
            raise StrictModeError(
                f"Streaming LLM call failed for command='{cmd_str}' with model={model}. "
                f"Error: {e}."
            ) from e

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def get_model_for_command(self, command: str, think_mode: bool = False) -> str:
        """
        Get the model that would be used for a given command.
        Useful for debugging/inspection.
        """
        ctx = RoutingContext(
            command=command,
            think_mode=think_mode,
        )
        return self.router.route(ctx)

    def is_heavy_command(self, command: str) -> bool:
        """Check if command uses gpt-5.1."""
        return self.router.is_heavy_command(command)

    def is_light_command(self, command: str) -> bool:
        """Check if command uses gpt-4.1-mini."""
        return self.router.is_light_command(command)
