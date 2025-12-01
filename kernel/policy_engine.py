import re
from typing import Any, Dict, Optional

from system.config import Config


class PolicyEngine:
    """
    v0.5.1 Policy Engine

    Responsible for:
    - Pre-LLM sanitization (masking secrets, emails, tokens).
    - Post-LLM normalization (persona consistency, no fake command execution).
    """

    def __init__(self, config: Config):
        self.config = config

        # Pre-compile regex patterns for performance and clarity
        self._email_pattern = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
        # Very simple API-like key pattern (e.g., sk_xxx, pk_xxx, rk_xxx)
        self._api_key_pattern = re.compile(r"\b(?:sk|rk|pk)_[A-Za-z0-9]{16,}\b")
        # Generic "long token" pattern (24+ alnum chars)
        self._long_token_pattern = re.compile(r"\b[a-zA-Z0-9]{24,}\b", re.MULTILINE)

        # Disclaimer patterns like "as an AI language model..."
        self._ai_disclaimer_pattern = re.compile(
            r"\bas (an )?ai (large )?language model\b",
            re.IGNORECASE,
        )

    # ------------------------------------------------------------------
    # v0.5.1 — Public API used by NovaKernel
    # ------------------------------------------------------------------
    def pre_llm(self, input_text: str, meta: Optional[Dict[str, Any]] = None) -> str:
        """
        Pre-LLM hook: sanitize user input before sending to the LLM.
        - Mask emails.
        - Mask API key-like / long token-like strings.
        """
        if not input_text:
            return input_text

        text = input_text

        # Mask emails
        text = self._email_pattern.sub("[MASKED:EMAIL]", text)

        # Mask obvious API keys (sk_..., pk_..., rk_...)
        text = self._api_key_pattern.sub("[MASKED:API_KEY]", text)

        # Mask generic long tokens (to avoid leaking arbitrary secrets)
        text = self._long_token_pattern.sub("[MASKED:TOKEN]", text)

        return text

    def post_llm(self, output_text: str, meta: Optional[Dict[str, Any]] = None) -> str:
        """
        Post-LLM hook: normalize persona voice and avoid misleading claims.
        - Soften "AI language model" disclaimers into Nova persona voice.
        - Avoid claims that Nova actually executed NovaOS commands directly.
        """
        if not output_text:
            return output_text

        text = output_text

        # Normalize "as an AI language model" into a softer Nova voice
        text = self._normalize_persona_disclaimers(text)

        # Avoid misleading "I ran/execute command X for you" phrasing
        text = self._neutralize_command_execution_claims(text)

        return text

    # ------------------------------------------------------------------
    # v0.3 compatibility hook (still used in some paths)
    # ------------------------------------------------------------------
    def postprocess_nl_response(self, text: str, context: Any) -> str:
        """
        Legacy hook kept for backward compatibility with older kernel code.
        Internally, this delegates to `post_llm`.
        """
        try:
            meta = {"source": "legacy_postprocess", "context": context}
            return self.post_llm(text, meta)
        except Exception:
            # Fail-open for safety: if anything goes wrong, return original text
            return text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _normalize_persona_disclaimers(self, text: str) -> str:
        """
        Replace generic 'as an AI language model...' phrasing with a more
        Nova-appropriate voice, without changing the underlying meaning.
        """
        def _replace(match: re.Match) -> str:
            # We keep the idea of limitations but in Nova's voice.
            return "as Nova, I do have some limits"

        return self._ai_disclaimer_pattern.sub(_replace, text)

    def _neutralize_command_execution_claims(self, text: str) -> str:
        """
        Ensure the persona doesn't claim to actually execute NovaOS syscommands.
        Example transformations:
        - "I'll run the status command for you" ->
          "I can't run NovaOS commands directly from here, but you can run the status command yourself."
        """

        pattern = re.compile(
            r"\b(I(?:'m| am)? going to|I'll|I will|I can)\s+"
            r"(run|execute|call)\s+the\s+([#\w\-]+)\s+command\b",
            re.IGNORECASE,
        )

        def _replacer(match: re.Match) -> str:
            cmd = match.group(3)
            return (
                f"I can't run NovaOS commands directly from here, "
                f"but you can run the {cmd} command yourself."
            )

        return pattern.sub(_replacer, text)
