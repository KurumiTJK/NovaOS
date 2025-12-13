# kernel/utils/__init__.py
"""
NovaOS Utils Subpackage

Contains shared utilities used across the kernel:
- command_types: CommandRequest/CommandResponse dataclasses
- formatting: OutputFormatter helper class
- gemini_helper: Two-pass quest generation (Gemini→GPT)
- kv_store: KV store protocol/interface
- kv_factory: KV store factory
- job_queue: Async job management

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

# KV Store - safe import (optional SDK)
try:
    from .kv_store import KVConfig, KVStore
    from .kv_factory import get_kv_store, is_kv_configured
except ImportError:
    pass

# Job Queue - safe import (requires KV)
try:
    from .job_queue import (
        create_job,
        enqueue_job,
        create_and_enqueue_job,
        get_job,
        dequeue_job,
        set_job_progress,
        set_job_done,
        set_job_error,
    )
except ImportError:
    pass
