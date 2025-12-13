# kernel/memory_syscommands.py
"""
NovaOS v0.11.0 — Memory Management Syscommand Handlers

New commands for ChatGPT-style memory management:
- #profile — View/add/edit/delete profile memories (identity + preferences)
- #memories — Full memory management UI
- #search-mem — Keyword-based memory search
- #memory-maintain — Run decay/archiving
- #session-end — End session with WM → LTM promotion

All handlers follow the standard signature:
    handler(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.nova_kernel import NovaKernel

logger = logging.getLogger("nova.memory.syscommands")

# =============================================================================
# SAFE IMPORTS WITH FALLBACKS
# =============================================================================

# Import CommandResponse
try:
    from kernel.command_types import CommandResponse
except ImportError:
    try:
        from ..command_types import CommandResponse
    except ImportError:
        # Fallback: define a minimal CommandResponse matching actual NovaOS signature
        from dataclasses import dataclass, field
        
        @dataclass
        class CommandResponse:
            ok: bool = True
            command: str = ""
            summary: str = ""
            data: Dict[str, Any] = field(default_factory=dict)
            error_code: Optional[str] = None
            error_message: Optional[str] = None
            type: str = "syscommand"
            
            def to_dict(self):
                if self.ok:
                    content = {"command": self.command, "summary": self.summary}
                    if self.data:
                        content.update(self.data)
                    return {"ok": True, "type": self.type, "content": content}
                else:
                    return {"ok": False, "error": {"code": self.error_code or "ERROR", "message": self.error_message or self.summary}}

# Import memory helpers
_HAS_MEMORY_HELPERS = False
try:
    from kernel.memory_helpers import (
        get_profile_memories,
        search_by_keywords,
        run_memory_decay,
    )
    _HAS_MEMORY_HELPERS = True
except ImportError:
    try:
        from .memory_helpers import (
            get_profile_memories,
            search_by_keywords,
            run_memory_decay,
        )
        _HAS_MEMORY_HELPERS = True
    except ImportError:
        logger.warning("memory_helpers not available - some commands may fail")
        def get_profile_memories(*args, **kwargs): return []
        def search_by_keywords(*args, **kwargs): return []
        def run_memory_decay(*args, **kwargs): return {"decayed_salience": 0, "marked_stale": 0, "archived": 0, "errors": 0}

# Import WM functions for session-end
_HAS_WM = False
try:
    from kernel.nova_wm import get_wm, wm_clear
    _HAS_WM = True
except ImportError:
    try:
        from .nova_wm import get_wm, wm_clear
        _HAS_WM = True
    except ImportError:
        logger.warning("nova_wm not available - #session-end may fail")
        def get_wm(*args, **kwargs): return None
        def wm_clear(*args, **kwargs): pass

# Import episodic snapshot
_HAS_EPISODIC = False
try:
    from kernel.nova_wm_episodic import episodic_snapshot
    _HAS_EPISODIC = True
except ImportError:
    try:
        from .nova_wm_episodic import episodic_snapshot
        _HAS_EPISODIC = True
    except ImportError:
        logger.warning("nova_wm_episodic not available - #session-end snapshot may fail")
        def episodic_snapshot(*args, **kwargs): return (False, "episodic_snapshot not available", None)


# =============================================================================
# RESPONSE HELPER
# =============================================================================

def _base_response(cmd_name: str, summary: str, extra: Optional[Dict[str, Any]] = None) -> CommandResponse:
    """Build a standard CommandResponse."""
    return CommandResponse(
        ok=True,
        command=cmd_name,
        summary=summary,
        data=extra or {},
        type=cmd_name,
    )


def _error_response(cmd_name: str, message: str, error_code: str = "ERROR") -> CommandResponse:
    """Build an error CommandResponse."""
    return CommandResponse(
        ok=False,
        command=cmd_name,
        summary=message,
        error_code=error_code,
        error_message=message,
        type=cmd_name,
    )


# =============================================================================
# #profile HANDLER
# =============================================================================

def handle_profile(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: "NovaKernel",
    meta: Any,
) -> CommandResponse:
    """
    View, add, edit, or delete profile memories (identity + preferences).
    
    Usage:
        #profile                    — List all profile memories
        #profile add type=identity content="..." — Add a profile memory
        #profile add type=preference content="..." — Add a preference memory
        #profile delete id=<id>     — Delete a profile memory
        #profile edit id=<id> content="..." — Edit a profile memory
    
    Profile memories are semantic memories tagged with:
    - profile:identity (name, role, employer, goals, etc.)
    - profile:preference (likes, dislikes, preferences for Nova)
    """
    mm = kernel.memory_manager
    
    # Parse action
    action = None
    mem_id = None
    new_content = None
    profile_type = None
    
    if isinstance(args, dict):
        mem_id = args.get("id")
        new_content = args.get("content") or args.get("payload")
        profile_type = args.get("type")
        
        # Handle positional: #profile add/delete/edit/view
        positional = args.get("_", [])
        if positional:
            first_arg = str(positional[0]).lower()
            if first_arg in ("delete", "edit", "view", "add"):
                action = first_arg
        
        # Try to parse id from string
        if mem_id is not None:
            try:
                mem_id = int(mem_id)
            except (ValueError, TypeError):
                mem_id = None
    
    # ─────────────────────────────────────────────────────────────────────
    # ADD (new in v0.11.0)
    # ─────────────────────────────────────────────────────────────────────
    if action == "add":
        if not new_content:
            return _error_response(cmd_name, "Usage: #profile add type=identity content=\"...\"", "MISSING_CONTENT")
        
        # Determine tag based on type
        if profile_type and profile_type.lower() == "preference":
            tag = "profile:preference"
        else:
            tag = "profile:identity"  # Default to identity
        
        try:
            item = mm.store(
                payload=new_content.strip(),
                mem_type="semantic",
                tags=[tag],
                salience=0.9,
                trace={"source": "manual_profile_add"},
            )
            logger.info("Added profile memory #%d (%s): %s", item.id, tag, new_content[:50])
            return _base_response(
                cmd_name,
                f"✓ Profile memory added (#{item.id}, {tag}): \"{new_content[:60]}{'...' if len(new_content) > 60 else ''}\"",
                {"id": item.id, "tag": tag}
            )
        except Exception as e:
            logger.warning("Error adding profile memory: %s", e, exc_info=True)
            return _error_response(cmd_name, f"Failed to add profile memory: {e}", "ADD_FAILED")
    
    # ─────────────────────────────────────────────────────────────────────
    # DELETE
    # ─────────────────────────────────────────────────────────────────────
    if action == "delete":
        if mem_id is None:
            return _error_response(cmd_name, "Usage: #profile delete id=<id>", "MISSING_ID")
        
        # Verify it's a profile memory
        trace_info = mm.trace(mem_id)
        if not trace_info:
            return _error_response(cmd_name, f"Memory #{mem_id} not found.", "NOT_FOUND")
        
        tags = trace_info.get("tags", [])
        if not any(t.startswith("profile:") for t in tags):
            return _error_response(
                cmd_name, 
                f"Memory #{mem_id} is not a profile memory. Use #memories delete id={mem_id} for general memories.",
                "NOT_PROFILE"
            )
        
        # Delete
        removed = mm.forget(ids=[mem_id])
        if removed > 0:
            logger.info("Deleted profile memory #%d", mem_id)
            return _base_response(cmd_name, f"✓ Profile memory #{mem_id} deleted.", {"deleted": mem_id})
        else:
            return _error_response(cmd_name, f"Failed to delete memory #{mem_id}.", "DELETE_FAILED")
    
    # ─────────────────────────────────────────────────────────────────────
    # EDIT
    # ─────────────────────────────────────────────────────────────────────
    if action == "edit":
        if mem_id is None:
            return _error_response(cmd_name, "Usage: #profile edit id=<id> content=\"...\"", "MISSING_ID")
        if not new_content:
            return _error_response(cmd_name, "Usage: #profile edit id=<id> content=\"...\"", "MISSING_CONTENT")
        
        # Verify it's a profile memory
        trace_info = mm.trace(mem_id)
        if not trace_info:
            return _error_response(cmd_name, f"Memory #{mem_id} not found.", "NOT_FOUND")
        
        tags = trace_info.get("tags", [])
        if not any(t.startswith("profile:") for t in tags):
            return _error_response(
                cmd_name,
                f"Memory #{mem_id} is not a profile memory.",
                "NOT_PROFILE"
            )
        
        # Update via engine (need to access internal engine)
        try:
            # Get the item from engine
            engine = mm._engine
            item = engine.index.get(mem_id)
            if item:
                item.payload = new_content.strip()
                engine.long_term.update(item)
                engine.index.update(item)
                logger.info("Edited profile memory #%d", mem_id)
                return _base_response(
                    cmd_name, 
                    f"✓ Profile memory #{mem_id} updated.",
                    {"id": mem_id, "new_payload": new_content[:80]}
                )
            else:
                return _error_response(cmd_name, f"Memory #{mem_id} not found in index.", "NOT_FOUND")
        except Exception as e:
            logger.warning("Error editing profile memory #%d: %s", mem_id, e, exc_info=True)
            return _error_response(cmd_name, f"Failed to edit memory: {e}", "EDIT_FAILED")
    
    # ─────────────────────────────────────────────────────────────────────
    # LIST (default)
    # ─────────────────────────────────────────────────────────────────────
    try:
        profile_memories = get_profile_memories(mm, limit=50)
    except Exception as e:
        logger.warning("Error getting profile memories: %s", e, exc_info=True)
        return _error_response(cmd_name, f"Failed to retrieve profile memories: {e}", "RETRIEVE_FAILED")
    
    if not profile_memories:
        lines = [
            "═══ USER PROFILE ═══",
            "",
            "No profile memories stored yet.",
            "",
            "Profile memories are auto-extracted when you say things like:",
            "  • \"My name is Thomas Kang\"",
            "  • \"I work at Tevora\"",
            "  • \"I prefer a warm, gentle tone\"",
            "",
            "Or manually add with:",
            "  #profile add type=identity content=\"My name is...\"",
            "  #profile add type=preference content=\"I prefer...\"",
        ]
    else:
        lines = [
            "═══ USER PROFILE ═══",
            "",
        ]
        
        # Separate identity and preference
        identity_items = []
        preference_items = []
        
        for m in profile_memories:
            # PATCHED: increased from 60 to 150 for better readability
            payload_preview = m.payload[:150] + "..." if len(m.payload) > 150 else m.payload
            entry = f"  #{m.id}: {payload_preview}"
            
            if any("profile:identity" in t for t in m.tags):
                identity_items.append(entry)
            else:
                preference_items.append(entry)
        
        if identity_items:
            lines.append("**Identity:**")
            lines.extend(identity_items)
            lines.append("")
        
        if preference_items:
            lines.append("**Preferences:**")
            lines.extend(preference_items)
            lines.append("")
        
        lines.append("─────────────────────────")
        lines.append(f"Total: {len(profile_memories)} profile memories")
        lines.append("")
        lines.append("Commands: #profile add | delete id=N | edit id=N content=\"...\"")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "count": len(profile_memories),
        "ids": [m.id for m in profile_memories],
    })


# =============================================================================
# #memories HANDLER
# =============================================================================

def handle_memories(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: "NovaKernel",
    meta: Any,
) -> CommandResponse:
    """
    Full memory management UI — list, view, edit, delete all memories.
    
    Usage:
        #memories                     — List active memories (paginated)
        #memories profile             — Show profile memories only
        #memories type=<type>         — Filter by type (semantic/procedural/episodic)
        #memories view id=<id>        — Show full memory details
        #memories edit id=<id> content="..." — Edit a memory's payload
        #memories delete id=<id>      — Delete (or archive) a memory
    """
    mm = kernel.memory_manager
    
    # Parse arguments
    action = None
    mem_type = None
    mem_id = None
    new_content = None
    filter_profile = False
    limit = 20
    
    if isinstance(args, dict):
        mem_type = args.get("type")
        mem_id = args.get("id")
        new_content = args.get("content") or args.get("payload")
        
        raw_limit = args.get("limit")
        if raw_limit:
            try:
                limit = int(raw_limit)
            except ValueError:
                pass
        
        # Parse id
        if mem_id is not None:
            try:
                mem_id = int(mem_id)
            except (ValueError, TypeError):
                mem_id = None
        
        # Check positional args for action
        positional = args.get("_", [])
        if positional:
            first_arg = str(positional[0]).lower()
            if first_arg in ("view", "edit", "delete"):
                action = first_arg
            elif first_arg == "profile":
                filter_profile = True
    
    # ─────────────────────────────────────────────────────────────────────
    # VIEW
    # ─────────────────────────────────────────────────────────────────────
    if action == "view":
        if mem_id is None:
            return _error_response(cmd_name, "Usage: #memories view id=<id>", "MISSING_ID")
        
        trace_info = mm.trace(mem_id)
        if not trace_info:
            return _error_response(cmd_name, f"Memory #{mem_id} not found.", "NOT_FOUND")
        
        # Get full item
        try:
            item = mm._engine.index.get(mem_id)
            if not item:
                return _error_response(cmd_name, f"Memory #{mem_id} not in index.", "NOT_FOUND")
            
            lines = [
                f"═══ MEMORY #{mem_id} ═══",
                "",
                f"**Type:** {item.type}",
                f"**Status:** {item.status}",
                f"**Salience:** {item.salience:.2f}",
                f"**Tags:** {', '.join(item.tags)}",
                f"**Created:** {item.timestamp}",
                f"**Last used:** {item.last_used_at or 'never'}",
                f"**Module:** {item.module_tag or 'none'}",
                "",
                "**Payload:**",
                item.payload,
                "",
                "─────────────────────────",
                f"Trace: {trace_info.get('trace', {})}",
            ]
            
            return _base_response(cmd_name, "\n".join(lines), {"memory": trace_info})
            
        except Exception as e:
            logger.warning("Error viewing memory #%d: %s", mem_id, e, exc_info=True)
            return _error_response(cmd_name, f"Error viewing memory: {e}", "VIEW_FAILED")
    
    # ─────────────────────────────────────────────────────────────────────
    # EDIT
    # ─────────────────────────────────────────────────────────────────────
    if action == "edit":
        if mem_id is None:
            return _error_response(cmd_name, "Usage: #memories edit id=<id> content=\"...\"", "MISSING_ID")
        if not new_content:
            return _error_response(cmd_name, "Usage: #memories edit id=<id> content=\"...\"", "MISSING_CONTENT")
        
        try:
            engine = mm._engine
            item = engine.index.get(mem_id)
            if not item:
                return _error_response(cmd_name, f"Memory #{mem_id} not found.", "NOT_FOUND")
            
            item.payload = new_content.strip()
            engine.long_term.update(item)
            engine.index.update(item)
            
            logger.info("Edited memory #%d", mem_id)
            return _base_response(
                cmd_name,
                f"✓ Memory #{mem_id} updated.",
                {"id": mem_id, "new_payload": new_content[:80]}
            )
        except Exception as e:
            logger.warning("Error editing memory #%d: %s", mem_id, e, exc_info=True)
            return _error_response(cmd_name, f"Failed to edit memory: {e}", "EDIT_FAILED")
    
    # ─────────────────────────────────────────────────────────────────────
    # DELETE
    # ─────────────────────────────────────────────────────────────────────
    if action == "delete":
        if mem_id is None:
            return _error_response(cmd_name, "Usage: #memories delete id=<id>", "MISSING_ID")
        
        # Archive instead of hard delete (safer)
        try:
            success = mm.update_status(mem_id, "archived")
            if success:
                logger.info("Archived memory #%d", mem_id)
                return _base_response(
                    cmd_name,
                    f"✓ Memory #{mem_id} archived. (Use #forget id={mem_id} to permanently delete.)",
                    {"id": mem_id, "status": "archived"}
                )
            else:
                return _error_response(cmd_name, f"Memory #{mem_id} not found.", "NOT_FOUND")
        except Exception as e:
            logger.warning("Error archiving memory #%d: %s", mem_id, e, exc_info=True)
            return _error_response(cmd_name, f"Failed to archive: {e}", "ARCHIVE_FAILED")
    
    # ─────────────────────────────────────────────────────────────────────
    # LIST (default)
    # ─────────────────────────────────────────────────────────────────────
    
    try:
        # Build filter
        if filter_profile:
            memories = get_profile_memories(mm, limit=limit)
        else:
            memories = mm.recall(mem_type=mem_type, status="active", limit=limit)
    except Exception as e:
        logger.warning("Error retrieving memories: %s", e, exc_info=True)
        return _error_response(cmd_name, f"Failed to retrieve memories: {e}", "RETRIEVE_FAILED")
    
    if not memories:
        lines = [
            "═══ MEMORY STORE ═══",
            "",
            "No memories found.",
            "",
            "Store memories with:",
            "  #store type=semantic tags=work content=\"...\"",
            "",
            "Or let Nova auto-extract from conversation.",
        ]
    else:
        lines = [
            "═══ MEMORY STORE ═══",
            "",
        ]
        
        for m in memories:
            tags_str = ", ".join(m.tags[:3])
            if len(m.tags) > 3:
                tags_str += f" +{len(m.tags) - 3}"
            
            # PATCHED: increased from 50 to 150 for better readability
            payload_preview = m.payload[:150] + "..." if len(m.payload) > 150 else m.payload
            salience = getattr(m, 'salience', 0.5) or 0.5
            
            lines.append(f"#{m.id} [{m.type}] sal={salience:.1f} ({tags_str})")
            lines.append(f"    \"{payload_preview}\"")
        
        lines.append("")
        lines.append("─────────────────────────")
        lines.append(f"Showing {len(memories)} memories")
        lines.append("")
        lines.append("Commands: #memories view id=N | edit id=N content=\"...\" | delete id=N")
    
    return _base_response(cmd_name, "\n".join(lines), {
        "count": len(memories),
        "ids": [m.id for m in memories],
    })


# =============================================================================
# #search-mem HANDLER
# =============================================================================

def handle_search_mem(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: "NovaKernel",
    meta: Any,
) -> CommandResponse:
    """
    Search memories by keywords.
    
    Usage:
        #search-mem query="Steven project"
        #search-mem query="API security" type=procedural
        #search-mem query="completed" limit=10
    """
    try:
        mm = kernel.memory_manager
        
        # Parse arguments
        query = None
        mem_type = None
        limit = 10
        
        if isinstance(args, dict):
            query = args.get("query") or args.get("q")
            mem_type = args.get("type")
            
            # Check positional
            positional = args.get("_", [])
            if positional and not query:
                query = " ".join(str(p) for p in positional)
            
            raw_limit = args.get("limit")
            if raw_limit:
                try:
                    limit = int(raw_limit)
                except ValueError:
                    pass
        
        if not query:
            return _error_response(cmd_name, "Usage: #search-mem query=\"your search terms\"", "MISSING_QUERY")
        
        # Search
        results = search_by_keywords(mm, query, mem_type=mem_type, limit=limit)
        
        if not results:
            return _base_response(
                cmd_name,
                f"No memories found matching \"{query}\".",
                {"query": query, "count": 0}
            )
        
        lines = [
            f"═══ SEARCH: \"{query}\" ═══",
            "",
        ]
        
        for item, score in results:
            tags_str = ", ".join(item.tags[:2]) if item.tags else ""
            # PATCHED: increased from 60 to 150 for better readability
            payload_preview = item.payload[:150] + "..." if len(item.payload) > 150 else item.payload
            lines.append(f"#{item.id} [{item.type}] score={score:.1f} ({tags_str})")
            lines.append(f"    \"{payload_preview}\"")
        
        lines.append("")
        lines.append(f"Found {len(results)} matching memories.")
        
        return _base_response(cmd_name, "\n".join(lines), {
            "query": query,
            "count": len(results),
            "ids": [item.id for item, _ in results],
        })
    except Exception as e:
        logger.warning("Error in search-mem: %s", e, exc_info=True)
        return _error_response(cmd_name, f"Search failed: {e}", "SEARCH_ERROR")


# =============================================================================
# #memory-maintain HANDLER
# =============================================================================

def handle_memory_maintain(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: "NovaKernel",
    meta: Any,
) -> CommandResponse:
    """
    Run memory decay and archiving maintenance.
    
    Usage:
        #memory-maintain
    
    This applies decay rules:
    - Old unused memories have salience reduced
    - Very old memories marked stale
    - Low-salience stale memories archived
    """
    try:
        mm = kernel.memory_manager
        
        results = run_memory_decay(mm)
        
        lines = [
            "═══ MEMORY MAINTENANCE ═══",
            "",
            f"✓ Salience decayed: {results.get('decayed_salience', 0)} memories",
            f"✓ Marked stale: {results.get('marked_stale', 0)} memories",
            f"✓ Archived: {results.get('archived', 0)} memories",
        ]
        
        if results.get('errors', 0) > 0:
            lines.append(f"⚠ Errors encountered: {results['errors']}")
        
        lines.append("")
        lines.append("Memory store is now optimized.")
        
        return _base_response(cmd_name, "\n".join(lines), results)
    except Exception as e:
        logger.warning("Error in memory-maintain: %s", e, exc_info=True)
        return _error_response(cmd_name, f"Maintenance failed: {e}", "MAINTAIN_ERROR")


# =============================================================================
# #session-end HANDLER
# =============================================================================

def handle_session_end(
    cmd_name: str,
    args: Dict[str, Any],
    session_id: str,
    context: Dict[str, Any],
    kernel: "NovaKernel",
    meta: Any,
) -> CommandResponse:
    """
    End the current session:
    1. Snapshot WM into LTM as an episodic memory
    2. Clear WM for a fresh start
    
    Usage:
        #session-end
    
    Note: This does NOT shut down Nova or change modes.
    Use #shutdown for that.
    """
    mm = kernel.memory_manager
    
    try:
        # Get WM
        wm = get_wm(session_id)
        
        if wm.turn_count == 0:
            return _base_response(
                cmd_name,
                "No conversation to save — Working Memory is empty.",
                {"saved": False}
            )
        
        # Get behavior engine if available
        behavior_engine = None
        try:
            from kernel.nova_wm_behavior import get_behavior_engine
            behavior_engine = get_behavior_engine(session_id)
        except ImportError:
            try:
                from .nova_wm_behavior import get_behavior_engine
                behavior_engine = get_behavior_engine(session_id)
            except ImportError:
                pass
        
        # Take snapshot
        module_tag = wm.current_module
        extra_tags = [f"session:{session_id}"]
        
        success, message, memory_id = episodic_snapshot(
            session_id=session_id,
            memory_manager=mm,
            wm=wm,
            behavior_engine=behavior_engine,
            topic=None,  # Auto-detect
            module=module_tag,
            extra_tags=extra_tags,
        )
        
        if not success:
            logger.warning("Failed to save WM snapshot: %s", message)
            # Still clear WM even if snapshot fails
        else:
            logger.info("Saved session snapshot to memory #%d", memory_id)
        
        # Clear WM
        wm_clear(session_id)
        
        lines = [
            "═══ SESSION ENDED ═══",
            "",
        ]
        
        if success:
            lines.append(f"✓ Working memory snapshot saved to episodic memory #{memory_id}.")
        else:
            lines.append(f"⚠ Could not save snapshot: {message}")
        
        lines.append("✓ Working memory cleared.")
        lines.append("")
        lines.append("Fresh context ready. Start a new conversation anytime!")
        
        return _base_response(cmd_name, "\n".join(lines), {
            "saved": success,
            "memory_id": memory_id,
            "wm_cleared": True,
        })
        
    except Exception as e:
        logger.warning("Error in session-end: %s", e, exc_info=True)
        
        # Try to clear WM anyway
        try:
            wm_clear(session_id)
        except Exception:
            pass
        
        return _error_response(
            cmd_name,
            f"Session ended with errors: {e}. Working memory was cleared.",
            "ERROR"
        )


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

MEMORY_SYSCOMMAND_HANDLERS = {
    "handle_profile": handle_profile,
    "handle_memories": handle_memories,
    "handle_search_mem": handle_search_mem,
    "handle_memory_maintain": handle_memory_maintain,
    "handle_session_end": handle_session_end,
}


def get_memory_syscommand_handlers() -> Dict[str, Any]:
    """Get handlers for registration in SYS_HANDLERS."""
    return MEMORY_SYSCOMMAND_HANDLERS


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    "handle_profile",
    "handle_memories",
    "handle_search_mem",
    "handle_memory_maintain",
    "handle_session_end",
    "get_memory_syscommand_handlers",
    "MEMORY_SYSCOMMAND_HANDLERS",
]
