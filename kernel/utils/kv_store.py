# kernel/utils/kv_store.py
"""
NovaOS KV Store Protocol — v1.0.0

Abstract interface for key-value storage backends.
All Redis/KV access must go through this interface.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class KVConfig:
    """Configuration for KV store connection."""
    provider: str  # "upstash" or "rediscloud"
    url: str
    token: Optional[str] = None  # Required for Upstash
    prefix: str = "nova"
    default_ttl: int = 3600  # 1 hour
    
    @classmethod
    def from_env(cls) -> "KVConfig":
        """Load config from environment variables."""
        return cls(
            provider=os.getenv("KV_PROVIDER", "upstash"),
            url=os.getenv("KV_URL", ""),
            token=os.getenv("KV_TOKEN"),
            prefix=os.getenv("KV_PREFIX", "nova"),
            default_ttl=int(os.getenv("JOB_TTL_SECONDS", "3600")),
        )
    
    def is_configured(self) -> bool:
        """Check if KV store is properly configured."""
        if not self.url:
            return False
        if self.provider == "upstash" and not self.token:
            return False
        return True


class KVStore(ABC):
    """
    Abstract base class for KV store implementations.
    
    All methods should handle key prefixing internally.
    """
    
    def __init__(self, config: KVConfig):
        self.config = config
        self.prefix = config.prefix
    
    def _prefixed_key(self, key: str) -> str:
        """Add prefix to key to prevent collisions."""
        return f"{self.prefix}:{key}"
    
    # =========================================================================
    # ABSTRACT METHODS - Must be implemented by subclasses
    # =========================================================================
    
    @abstractmethod
    def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get JSON value for key.
        
        Args:
            key: Key without prefix (prefix added automatically)
            
        Returns:
            Parsed JSON dict or None if not found
        """
        pass
    
    @abstractmethod
    def set_json(
        self, 
        key: str, 
        value: Dict[str, Any], 
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        Set JSON value for key with optional TTL.
        
        Args:
            key: Key without prefix
            value: Dict to store as JSON
            ttl_seconds: Optional TTL (uses default if None)
            
        Returns:
            True if successful
        """
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Delete a key.
        
        Args:
            key: Key without prefix
            
        Returns:
            True if key existed and was deleted
        """
        pass
    
    @abstractmethod
    def incr(
        self, 
        key: str, 
        amount: int = 1, 
        ttl_seconds: Optional[int] = None
    ) -> int:
        """
        Increment a counter.
        
        Args:
            key: Key without prefix
            amount: Amount to increment by
            ttl_seconds: Optional TTL for new keys
            
        Returns:
            New value after increment
        """
        pass
    
    @abstractmethod
    def rpush(self, key: str, value: str) -> int:
        """
        Push value to the right of a list (queue tail).
        
        Args:
            key: Key without prefix
            value: Value to push (string)
            
        Returns:
            Length of list after push
        """
        pass
    
    @abstractmethod
    def lpop(self, key: str) -> Optional[str]:
        """
        Pop value from the left of a list (queue head).
        
        Args:
            key: Key without prefix
            
        Returns:
            Value or None if list is empty
        """
        pass
    
    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================
    
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        return self.get_json(key) is not None
    
    def queue_push(self, queue_name: str, job_id: str) -> int:
        """Push job_id to a queue."""
        return self.rpush(f"queue:{queue_name}", job_id)
    
    def queue_pop(self, queue_name: str) -> Optional[str]:
        """Pop job_id from a queue."""
        return self.lpop(f"queue:{queue_name}")


# Type alias for dependency injection
KVStoreType = KVStore


__all__ = [
    "KVConfig",
    "KVStore",
    "KVStoreType",
]
