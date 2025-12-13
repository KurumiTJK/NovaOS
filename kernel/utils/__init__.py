# kernel/utils/__init__.py
"""
NovaOS Utils Subpackage

Contains shared utilities used across the kernel:
- command_types: CommandRequest/CommandResponse dataclasses
- formatting: OutputFormatter helper class
- gemini_helper: Two-pass quest generation (Gemini→GPT)

All symbols are re-exported for backward compatibility.
"""

# Command types - always available
from .command_types import (
    CommandRequest,
    CommandResponse,
)

# Formatting - always available
from .formatting import OutputFormatter

# Gemini helper - safe import (optional SDK)
try:
    from .gemini_helper import (
        TwoPassConfig,
        load_config,
        is_gemini_available,
        generate_domains_two_pass,
        generate_steps_two_pass,
        inspect_gemini_draft,
    )
except ImportError:
    pass
