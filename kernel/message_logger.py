# kernel/message_logger.py
"""
NovaOS Message Logger v0.8.2

Logs assistant (Nova) messages to JSONL files for future fine-tuning.
One file per day: data/logs/nova_messages_YYYY-MM-DD.jsonl

Design principles:
- NEVER crash NovaOS - all errors are caught and swallowed
- Minimal footprint - only logs assistant messages
- Append-only writes for safety
- UTC timestamps for consistency
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class MessageLogger:
    """
    Logs assistant messages to daily JSONL files.
    
    Usage:
        logger = MessageLogger(base_dir="data/logs")
        logger.log_assistant_message(
            text="Hello! How can I help?",
            user_last_message="hey nova",
            assistant_mode="story",
            persona_mode="relax",
            session_id="abc123",
        )
    
    Output file: data/logs/nova_messages_2025-01-15.jsonl
    """
    
    KERNEL_VERSION = "0.8.2"
    
    def __init__(self, base_dir: str = "data/logs") -> None:
        """
        Initialize the message logger.
        
        Args:
            base_dir: Directory for log files (created if missing)
        """
        self.base_dir = Path(base_dir)
        self._ensure_directory()
    
    def _ensure_directory(self) -> None:
        """Create log directory if it doesn't exist."""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Silently ignore - we'll handle errors during write
            pass
    
    def _get_log_path(self) -> Path:
        """Get today's log file path (UTC date)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.base_dir / f"nova_messages_{today}.jsonl"
    
    def _get_timestamp(self) -> str:
        """Get current UTC timestamp in ISO8601 format."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    
    def log_assistant_message(
        self,
        text: str,
        *,
        user_last_message: Optional[str] = None,
        assistant_mode: Optional[str] = None,
        persona_mode: Optional[str] = None,
        active_section: Optional[str] = None,
        quest_id: Optional[str] = None,
        module_id: Optional[str] = None,
        model_name: Optional[str] = None,
        session_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log a single assistant (Nova) message to a JSONL file.
        
        This method MUST NEVER crash NovaOS. On any error, it catches
        and silently ignores (or prints a debug warning in dev mode).
        
        Args:
            text: Nova's reply text (required)
            user_last_message: The user input that triggered this reply
            assistant_mode: "story" or "utility" from AssistantModeManager
            persona_mode: "relax" or "focus" from NovaPersona
            active_section: Current help section if any
            quest_id: Active quest ID if any
            module_id: Active module ID if any
            model_name: LLM model used for this response
            session_id: Session identifier
            extra: Additional metadata to include
        """
        try:
            # Build the log entry
            entry: Dict[str, Any] = {
                "timestamp": self._get_timestamp(),
                "role": "assistant",
                "text": text,
                "user_last_message": user_last_message,
                "assistant_mode": assistant_mode,
                "persona_mode": persona_mode,
                "active_section": active_section,
                "quest_id": quest_id,
                "module_id": module_id,
                "model_name": model_name,
                "session_id": session_id,
                "metadata": {
                    "kernel_version": self.KERNEL_VERSION,
                },
            }
            
            # Merge extra into metadata
            if extra:
                entry["metadata"].update(extra)
            
            # Write to file
            log_path = self._get_log_path()
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                
        except Exception:
            # NEVER crash NovaOS - silently ignore logging errors
            # In production, you might want to log to stderr or a fallback
            pass
    
    def get_recent_logs(self, days: int = 1, limit: int = 100) -> list[Dict[str, Any]]:
        """
        Read recent log entries (utility method for debugging).
        
        Args:
            days: Number of days to look back
            limit: Maximum entries to return
            
        Returns:
            List of log entries (most recent first)
        """
        entries = []
        try:
            from datetime import timedelta
            
            for day_offset in range(days):
                date = datetime.now(timezone.utc) - timedelta(days=day_offset)
                date_str = date.strftime("%Y-%m-%d")
                log_path = self.base_dir / f"nova_messages_{date_str}.jsonl"
                
                if log_path.exists():
                    with open(log_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entries.append(json.loads(line))
                                except json.JSONDecodeError:
                                    continue
                
                if len(entries) >= limit:
                    break
            
            # Sort by timestamp descending and limit
            entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return entries[:limit]
            
        except Exception:
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get basic statistics about logged messages.
        
        Returns:
            Dict with message counts by mode, etc.
        """
        try:
            entries = self.get_recent_logs(days=7, limit=1000)
            
            stats = {
                "total_messages": len(entries),
                "by_assistant_mode": {},
                "by_persona_mode": {},
                "log_directory": str(self.base_dir),
            }
            
            for entry in entries:
                am = entry.get("assistant_mode") or "unknown"
                pm = entry.get("persona_mode") or "unknown"
                
                stats["by_assistant_mode"][am] = stats["by_assistant_mode"].get(am, 0) + 1
                stats["by_persona_mode"][pm] = stats["by_persona_mode"].get(pm, 0) + 1
            
            return stats
            
        except Exception:
            return {"error": "Could not compute stats"}
