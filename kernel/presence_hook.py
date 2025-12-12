# kernel/presence_hook.py
"""
NovaOS Presence XP Hook v1.0.0

This module provides a hook to automatically award presence XP on the
first meaningful interaction of each day.

USAGE:
Import and call `check_presence_xp(kernel)` early in message processing:

    from kernel.presence_hook import check_presence_xp
    presence_result = check_presence_xp(kernel)
    if presence_result:
        # First interaction today - XP was awarded
        pass

The hook is idempotent - calling it multiple times per day has no effect
after the first award.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("nova.presence")


def check_presence_xp(kernel: Any) -> Optional[Dict[str, Any]]:
    """
    Check and award presence XP if this is the first interaction today.
    
    This should be called early in message processing to ensure presence XP
    is awarded on the first meaningful interaction.
    
    Args:
        kernel: NovaKernel instance
    
    Returns:
        XP result dict if awarded, None if already awarded today or if
        timerhythm module is not available.
    
    Example:
        result = check_presence_xp(kernel)
        if result:
            print(f"Presence XP awarded: +{result.get('xp_gained', 10)} XP")
    """
    try:
        from kernel.timerhythm_handlers import get_timerhythm_manager
        
        # Get data_dir from kernel if available
        data_dir = None
        if hasattr(kernel, 'config') and hasattr(kernel.config, 'data_dir'):
            data_dir = kernel.config.data_dir
        
        manager = get_timerhythm_manager(data_dir)
        return manager.check_and_award_presence_xp(kernel)
    
    except ImportError:
        logger.debug("Timerhythm handlers not available for presence check")
        return None
    except Exception as e:
        logger.error("Error checking presence XP: %s", e)
        return None


def was_presence_awarded_today(kernel: Any) -> bool:
    """
    Check if presence XP was already awarded today.
    
    Args:
        kernel: NovaKernel instance
    
    Returns:
        True if presence XP was already awarded today, False otherwise.
    """
    try:
        from kernel.timerhythm_handlers import get_timerhythm_manager
        
        data_dir = None
        if hasattr(kernel, 'config') and hasattr(kernel.config, 'data_dir'):
            data_dir = kernel.config.data_dir
        
        manager = get_timerhythm_manager(data_dir)
        return manager.was_presence_awarded_today()
    
    except ImportError:
        return False
    except Exception as e:
        logger.error("Error checking presence status: %s", e)
        return False


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "check_presence_xp",
    "was_presence_awarded_today",
]
