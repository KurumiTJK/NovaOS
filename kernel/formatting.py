# kernel/formatting.py
"""
SHIM: This module has moved to kernel/utils/formatting.py

This file re-exports all symbols for backward compatibility.
New code should import from kernel.utils.formatting directly.
"""

from kernel.utils.formatting import OutputFormatter

__all__ = ["OutputFormatter"]
