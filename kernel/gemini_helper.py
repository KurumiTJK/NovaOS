# kernel/gemini_helper.py
"""
SHIM: This module has moved to kernel/utils/gemini_helper.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.utils.gemini_helper directly.
"""

from kernel.utils.gemini_helper import (
    # Config
    TwoPassConfig,
    load_config,
    CONFIG,
    # Main functions
    is_gemini_available,
    generate_domains_two_pass,
    generate_steps_two_pass,
    inspect_gemini_draft,
    # Prompts (if needed externally)
    GEMINI_DOMAIN_SYSTEM,
    GEMINI_STEPS_SYSTEM,
    GPT_DOMAIN_POLISH_SYSTEM,
    GPT_STEPS_POLISH_SYSTEM,
)

__all__ = [
    "TwoPassConfig",
    "load_config",
    "CONFIG",
    "is_gemini_available",
    "generate_domains_two_pass",
    "generate_steps_two_pass",
    "inspect_gemini_draft",
    "GEMINI_DOMAIN_SYSTEM",
    "GEMINI_STEPS_SYSTEM",
    "GPT_DOMAIN_POLISH_SYSTEM",
    "GPT_STEPS_POLISH_SYSTEM",
]
