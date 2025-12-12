"""
NovaOS LLM Client — v0.10.3

Updated with:
- Explicit timeout on OpenAI API calls (90s, less than Gunicorn's 120s)
- Custom LLMTimeoutError exception for timeout/network failures
- Proper exception handling for APITimeoutError, APIConnectionError
- v0.10.3: Fixed max_tokens → max_completion_tokens for gpt-5.1/o-series models
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional


# -----------------------------------------------------------------------------
# Path Resolution
# -----------------------------------------------------------------------------

def _get_project_root() -> Path:
    """
    Get the absolute path to the project root.
    
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
    from openai import OpenAI, APIConnectionError, APITimeoutError
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    OpenAI = None
    APIConnectionError = Exception
    APITimeoutError = Exception

# Also import httpx for network-level timeout handling
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False
    httpx = None


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


class LLMTimeoutError(LLMError):
    """
    Raised when an LLM API call times out or fails due to network issues.
    
    v0.10.2: New exception for graceful timeout handling.
    This allows Flask routes to catch this specifically and return JSON errors.
    """
    pass


class PersonaModeError(LLMError):
    """Raised when persona mode LLM call fails (NO FALLBACK)."""
    pass


class StrictModeError(LLMError):
    """Raised when strict mode LLM call fails (NO FALLBACK)."""
    pass


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# LLM client timeout in seconds - MUST be less than Gunicorn worker timeout
# Gunicorn should be set to 120s, so we use 90s here
LLM_CLIENT_TIMEOUT = 90


# -----------------------------------------------------------------------------
# LLM Client
# -----------------------------------------------------------------------------

class LLMClient:
    """
    v0.10.2 LLM Client — Deterministic Model Selection + Streaming + Timeout Handling
    
    Channels:
    - PERSONA: Always gpt-5.1, hard error on failure
    - SYSTEM: Routed by ModelRouter (heavy→gpt-5.1, light→gpt-4.1-mini)
    
    Logs ALL LLM calls to terminal with channel, command, and model.
    
    v0.10.2 Changes:
    - Added explicit timeout (90s) to all API calls
    - Catches APITimeoutError, APIConnectionError, and httpx.TimeoutException
    - Raises LLMTimeoutError on timeout/network failures for clean JSON error handling
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
        print(f"[LLM] Client timeout: {LLM_CLIENT_TIMEOUT}s", flush=True)
        
        # Initialize OpenAI client with default timeout
        self.client = OpenAI(
            api_key=api_key,
            timeout=LLM_CLIENT_TIMEOUT,  # v0.10.2: Explicit timeout
        )
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
        
        v0.10.2: Added timeout handling and custom exception.
        - Uses explicit timeout (90s) on all calls
        - Catches APITimeoutError, APIConnectionError, httpx.TimeoutException
        - Raises LLMTimeoutError on timeout/network failures
        
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
        
        # v0.10.3: gpt-5.1 and o-series models require max_completion_tokens, not max_tokens
        if "max_tokens" in filtered_kwargs:
            if "gpt-5" in model or "o1" in model or "o3" in model:
                filtered_kwargs["max_completion_tokens"] = filtered_kwargs.pop("max_tokens")
        
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
                timeout=LLM_CLIENT_TIMEOUT,  # v0.10.2: Explicit timeout per call
                **filtered_kwargs,
            )
            return resp.choices[0].message.content or ""
        
        # v0.10.2: Catch timeout and connection errors specifically
        except APITimeoutError as e:
            print(
                f"[LLM] TIMEOUT channel={channel} command={command} model={model} error={e}",
                file=sys.stderr,
                flush=True,
            )
            raise LLMTimeoutError(
                f"LLM request timed out after {LLM_CLIENT_TIMEOUT}s. "
                f"Channel={channel}, command={command}, model={model}"
            ) from e
        
        except APIConnectionError as e:
            print(
                f"[LLM] CONNECTION ERROR channel={channel} command={command} model={model} error={e}",
                file=sys.stderr,
                flush=True,
            )
            raise LLMTimeoutError(
                f"LLM connection failed (network error). "
                f"Channel={channel}, command={command}, model={model}. Error: {e}"
            ) from e
        
        except Exception as e:
            # Check if it's an httpx timeout (can happen at lower level)
            if _HAS_HTTPX and isinstance(e, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout)):
                print(
                    f"[LLM] HTTPX TIMEOUT channel={channel} command={command} model={model} error={e}",
                    file=sys.stderr,
                    flush=True,
                )
                raise LLMTimeoutError(
                    f"LLM request failed (httpx network error). "
                    f"Channel={channel}, command={command}, model={model}. Error: {e}"
                ) from e
            
            # Re-raise other exceptions as-is
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
        
        v0.10.2: Added timeout handling for streaming calls.
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
        
        # v0.10.3: gpt-5.1 and o-series models require max_completion_tokens, not max_tokens
        if "max_tokens" in filtered_kwargs:
            if "gpt-5" in model or "o1" in model or "o3" in model:
                filtered_kwargs["max_completion_tokens"] = filtered_kwargs.pop("max_tokens")
        
        try:
            stream = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *messages,
                ],
                stream=True,
                timeout=LLM_CLIENT_TIMEOUT,  # v0.10.2: Explicit timeout
                **filtered_kwargs,
            )
            
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        
        # v0.10.2: Catch timeout and connection errors
        except APITimeoutError as e:
            print(
                f"[LLM] STREAMING TIMEOUT channel={channel} command={command} model={model} error={e}",
                file=sys.stderr,
                flush=True,
            )
            raise LLMTimeoutError(
                f"LLM streaming request timed out after {LLM_CLIENT_TIMEOUT}s. "
                f"Channel={channel}, command={command}, model={model}"
            ) from e
        
        except APIConnectionError as e:
            print(
                f"[LLM] STREAMING CONNECTION ERROR channel={channel} command={command} model={model} error={e}",
                file=sys.stderr,
                flush=True,
            )
            raise LLMTimeoutError(
                f"LLM streaming connection failed (network error). "
                f"Channel={channel}, command={command}, model={model}. Error: {e}"
            ) from e
                    
        except Exception as e:
            # Check for httpx timeout
            if _HAS_HTTPX and isinstance(e, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout)):
                print(
                    f"[LLM] STREAMING HTTPX TIMEOUT channel={channel} command={command} model={model} error={e}",
                    file=sys.stderr,
                    flush=True,
                )
                raise LLMTimeoutError(
                    f"LLM streaming request failed (httpx network error). "
                    f"Channel={channel}, command={command}, model={model}. Error: {e}"
                ) from e
            
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
        model = model_override or PERSONA_MODEL
        command = kwargs.pop("command", None) or "persona"
        
        # LOG - this fires for EVERY persona call
        print(f"[LLM] channel=persona command={command} model={model}", flush=True)
        
        msg_list = messages or []
        msg_list = [*msg_list, {"role": "user", "content": user}]
        
        try:
            text = self._call_api(
                model=model,
                system_prompt=system,
                messages=msg_list,
                channel="persona",
                command=command,
                **kwargs,
            )
        except LLMTimeoutError:
            # Re-raise timeout errors as-is so Flask can handle them
            raise
        except Exception as e:
            raise PersonaModeError(
                f"Persona LLM call failed with model={model}. Error: {e}. "
                f"NO FALLBACK — persona mode requires gpt-5.1."
            ) from e
        
        return {
            "text": text,
            "session_id": session_id,
            "model": model,
            "channel": "persona",
        }

    # -------------------------------------------------------------------------
    # SYSTEM CHANNEL — Model routed by ModelRouter
    # -------------------------------------------------------------------------

    def complete_system(
        self,
        system: str,
        user: str,
        messages: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
        command: Optional[str] = None,
        explicit_model: Optional[str] = None,
        think_mode: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        System channel — model selected by ModelRouter.
        
        v0.9.0: Deterministic routing.
        - Heavy commands (quest-compose, generate-steps, etc.) → gpt-5.1
        - Light commands (everything else) → gpt-4.1-mini
        - Think mode → gpt-5.1 (o1-style reasoning)
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
        except LLMTimeoutError:
            # Re-raise timeout errors as-is
            raise
        except Exception as e:
            raise StrictModeError(
                f"System LLM call failed for command='{cmd_str}' with model={model}. "
                f"Error: {e}."
            ) from e

        return {
            "text": text,
            "session_id": session_id,
            "model": model,
            "channel": "system",
            "command": cmd_str,
        }

    # -------------------------------------------------------------------------
    # STREAMING SYSTEM CHANNEL
    # -------------------------------------------------------------------------

    def stream_complete_system(
        self,
        system: str,
        user: str,
        messages: Optional[List[Dict[str, str]]] = None,
        session_id: Optional[str] = None,
        command: Optional[str] = None,
        explicit_model: Optional[str] = None,
        think_mode: bool = False,
        **kwargs,
    ) -> Generator[str, None, None]:
        """
        Streaming system channel.
        
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
        except LLMTimeoutError:
            # Re-raise timeout errors as-is
            raise
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
