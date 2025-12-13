# kernel/utils/kv_upstash.py
"""
NovaOS KV Store — Upstash Redis Implementation

Uses the Upstash REST API via upstash-redis SDK.

Install: pip install upstash-redis
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .kv_store import KVStore, KVConfig


class UpstashKVStore(KVStore):
    """
    Upstash Redis implementation of KVStore.
    
    Uses Upstash's REST API which is serverless-friendly.
    """
    
    def __init__(self, config: KVConfig):
        super().__init__(config)
        self._client = None
        self._init_client()
    
    def _init_client(self) -> None:
        """Initialize Upstash Redis client."""
        try:
            from upstash_redis import Redis
            
            self._client = Redis(
                url=self.config.url,
                token=self.config.token,
            )
            print(f"[KV:Upstash] Connected to {self.config.url[:30]}...", flush=True)
            
        except ImportError:
            raise ImportError(
                "upstash-redis package not installed. "
                "Install with: pip install upstash-redis"
            )
        except Exception as e:
            print(f"[KV:Upstash] Connection error: {e}", flush=True)
            raise
    
    @property
    def client(self):
        """Get the Upstash Redis client."""
        if self._client is None:
            self._init_client()
        return self._client
    
    # =========================================================================
    # KVStore Implementation
    # =========================================================================
    
    def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Get JSON value for key."""
        try:
            prefixed = self._prefixed_key(key)
            value = self.client.get(prefixed)
            
            if value is None:
                return None
            
            # Upstash may return string or already parsed dict
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                return json.loads(value)
            
            return None
            
        except Exception as e:
            print(f"[KV:Upstash] get_json error for {key}: {e}", flush=True)
            return None
    
    def set_json(
        self, 
        key: str, 
        value: Dict[str, Any], 
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """Set JSON value for key with optional TTL."""
        try:
            prefixed = self._prefixed_key(key)
            json_str = json.dumps(value, default=str)
            
            ttl = ttl_seconds or self.config.default_ttl
            
            if ttl > 0:
                self.client.setex(prefixed, ttl, json_str)
            else:
                self.client.set(prefixed, json_str)
            
            return True
            
        except Exception as e:
            print(f"[KV:Upstash] set_json error for {key}: {e}", flush=True)
            return False
    
    def delete(self, key: str) -> bool:
        """Delete a key."""
        try:
            prefixed = self._prefixed_key(key)
            result = self.client.delete(prefixed)
            return result > 0
            
        except Exception as e:
            print(f"[KV:Upstash] delete error for {key}: {e}", flush=True)
            return False
    
    def incr(
        self, 
        key: str, 
        amount: int = 1, 
        ttl_seconds: Optional[int] = None
    ) -> int:
        """Increment a counter."""
        try:
            prefixed = self._prefixed_key(key)
            
            if amount == 1:
                new_val = self.client.incr(prefixed)
            else:
                new_val = self.client.incrby(prefixed, amount)
            
            # Set TTL if specified and this is a new key
            if ttl_seconds:
                self.client.expire(prefixed, ttl_seconds)
            
            return new_val
            
        except Exception as e:
            print(f"[KV:Upstash] incr error for {key}: {e}", flush=True)
            return 0
    
    def rpush(self, key: str, value: str) -> int:
        """Push value to the right of a list."""
        try:
            prefixed = self._prefixed_key(key)
            return self.client.rpush(prefixed, value)
            
        except Exception as e:
            print(f"[KV:Upstash] rpush error for {key}: {e}", flush=True)
            return 0
    
    def lpop(self, key: str) -> Optional[str]:
        """Pop value from the left of a list."""
        try:
            prefixed = self._prefixed_key(key)
            value = self.client.lpop(prefixed)
            
            if value is None:
                return None
            
            # Ensure we return a string
            if isinstance(value, bytes):
                return value.decode("utf-8")
            return str(value)
            
        except Exception as e:
            print(f"[KV:Upstash] lpop error for {key}: {e}", flush=True)
            return None
    
    # =========================================================================
    # Upstash-specific methods
    # =========================================================================
    
    def ping(self) -> bool:
        """Test connection to Upstash."""
        try:
            result = self.client.ping()
            return result == "PONG" or result is True
        except Exception as e:
            print(f"[KV:Upstash] ping error: {e}", flush=True)
            return False
    
    def get_queue_length(self, queue_name: str) -> int:
        """Get length of a queue."""
        try:
            prefixed = self._prefixed_key(f"queue:{queue_name}")
            return self.client.llen(prefixed) or 0
        except Exception:
            return 0


__all__ = ["UpstashKVStore"]
