# kernel/utils/kv_factory.py
"""
NovaOS KV Store Factory — v1.0.0

Returns the appropriate KVStore implementation based on KV_PROVIDER env var.
"""

from __future__ import annotations

from typing import Optional

from .kv_store import KVStore, KVConfig


# Singleton instance
_kv_instance: Optional[KVStore] = None


def get_kv_store(config: Optional[KVConfig] = None) -> KVStore:
    """
    Get or create the KV store singleton.
    
    Args:
        config: Optional config (uses env vars if not provided)
        
    Returns:
        KVStore instance
        
    Raises:
        ValueError: If provider is unknown
        ImportError: If required SDK is not installed
    """
    global _kv_instance
    
    if _kv_instance is not None:
        return _kv_instance
    
    if config is None:
        config = KVConfig.from_env()
    
    if not config.is_configured():
        raise ValueError(
            "KV store not configured. Set KV_URL and KV_TOKEN environment variables."
        )
    
    provider = config.provider.lower()
    
    if provider == "upstash":
        from .kv_upstash import UpstashKVStore
        _kv_instance = UpstashKVStore(config)
        
    elif provider == "rediscloud":
        from .kv_rediscloud import RedisCloudKVStore
        _kv_instance = RedisCloudKVStore(config)
        
    else:
        raise ValueError(
            f"Unknown KV provider: {provider}. "
            f"Supported: upstash, rediscloud"
        )
    
    return _kv_instance


def reset_kv_store() -> None:
    """Reset the singleton (for testing)."""
    global _kv_instance
    _kv_instance = None


def is_kv_configured() -> bool:
    """Check if KV store is configured via environment."""
    config = KVConfig.from_env()
    return config.is_configured()


__all__ = [
    "get_kv_store",
    "reset_kv_store",
    "is_kv_configured",
]
