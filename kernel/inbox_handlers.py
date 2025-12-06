# kernel/inbox_handlers.py
"""
v0.8.0 — Inbox Command Handlers for NovaOS Life RPG

Commands:
- #capture / #in — Quick capture to inbox
- #inbox — List inbox items
- #inbox-process — Process an item (convert to quest/reminder/archive)
- #inbox-delete — Delete an item
- #inbox-clear — Clear processed items
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .command_types import CommandResponse


# =============================================================================
# HELPERS
# =============================================================================

def _base_response(cmd: str, summary: str, data: Dict[str, Any] = None) -> CommandResponse:
    return CommandResponse(
        ok=True,
        command=cmd,
        summary=summary,
        data=data or {},
    )


def _error_response(cmd: str, message: str, code: str) -> CommandResponse:
    return CommandResponse(
        ok=False,
        command=cmd,
        summary=message,
        error_code=code,
    )


# =============================================================================
# CAPTURE
# =============================================================================

def handle_capture(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Quick capture to inbox.
    
    Usage:
        #capture Buy milk
        #in Learn about JWT tokens
        #capture priority=1 Urgent: review PR
        #capture tags=work,urgent Fix the build
    """
    inbox = getattr(kernel, 'inbox_store', None)
    if not inbox:
        return _error_response(cmd_name, "Inbox not available.", "NO_INBOX")
    
    # Parse content and options
    content = ""
    tags = []
    priority = None
    
    if isinstance(args, dict):
        # Get content from positional args or explicit content param
        positional = args.get("_", [])
        if positional:
            content = " ".join(str(p) for p in positional)
        elif args.get("content"):
            content = args.get("content")
        elif args.get("text"):
            content = args.get("text")
        
        # Get tags
        raw_tags = args.get("tags", "")
        if raw_tags:
            if isinstance(raw_tags, list):
                tags = raw_tags
            else:
                tags = [t.strip() for t in str(raw_tags).split(",") if t.strip()]
        
        # Get priority
        raw_priority = args.get("priority") or args.get("p")
        if raw_priority:
            try:
                priority = int(raw_priority)
                if priority not in (1, 2, 3):
                    priority = None
            except (ValueError, TypeError):
                pass
    
    elif isinstance(args, str):
        content = args
    
    if not content:
        return _error_response(
            cmd_name,
            "Usage: `#capture <text>` or `#in <text>`\n\n"
            "Options: `priority=1|2|3` `tags=tag1,tag2`",
            "MISSING_CONTENT",
        )
    
    # Capture to inbox
    item = inbox.capture(
        content=content,
        tags=tags,
        source="manual",
        priority=priority,
    )
    
    # Get assistant mode for formatting
    mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
    
    if mode_mgr and mode_mgr.is_story_mode():
        summary = f"📥 **Captured to inbox!**\n\n> {item.content}"
        if tags:
            summary += f"\n\nTags: {', '.join(tags)}"
        if priority:
            summary += f"\nPriority: {item.priority_icon}"
        
        count = inbox.count_unprocessed()
        summary += f"\n\n*{count} item(s) in inbox*"
    else:
        summary = f"Captured: {item.content[:50]}{'...' if len(item.content) > 50 else ''}"
        summary += f" [id: {item.id}]"
    
    return _base_response(cmd_name, summary, item.to_dict())


# =============================================================================
# LIST INBOX
# =============================================================================

def handle_inbox(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    List inbox items.
    
    Usage:
        #inbox              — Show unprocessed items
        #inbox all          — Show all items including processed
        #inbox id=abc123    — Show specific item
    """
    inbox = getattr(kernel, 'inbox_store', None)
    if not inbox:
        return _error_response(cmd_name, "Inbox not available.", "NO_INBOX")
    
    # Check for specific item lookup
    item_id = None
    show_all = False
    
    if isinstance(args, dict):
        item_id = args.get("id")
        positional = args.get("_", [])
        if positional:
            if positional[0] == "all":
                show_all = True
            else:
                item_id = positional[0]
    elif isinstance(args, str):
        if args == "all":
            show_all = True
        else:
            item_id = args
    
    # Single item lookup
    if item_id:
        item = inbox.get(item_id)
        if not item:
            return _error_response(cmd_name, f"Item '{item_id}' not found.", "NOT_FOUND")
        
        lines = [
            f"**Inbox Item:** {item.id}",
            "",
            f"> {item.content}",
            "",
            f"**Created:** {item.age_str}",
        ]
        if item.tags:
            lines.append(f"**Tags:** {', '.join(item.tags)}")
        if item.priority:
            lines.append(f"**Priority:** {item.priority_icon}")
        if item.processed:
            lines.append(f"**Status:** Processed → {item.processed_to}")
        else:
            lines.append("**Status:** Unprocessed")
            lines.append("")
            lines.append("**Actions:**")
            lines.append(f"• `#inbox-process {item.id} quest` — Convert to quest")
            lines.append(f"• `#inbox-process {item.id} reminder` — Convert to reminder")
            lines.append(f"• `#inbox-process {item.id} archive` — Archive")
            lines.append(f"• `#inbox-delete {item.id}` — Delete")
        
        return _base_response(cmd_name, "\n".join(lines), item.to_dict())
    
    # List items
    if show_all:
        items = inbox.list_all()
        title = "Inbox (All Items)"
    else:
        items = inbox.list_unprocessed()
        title = "Inbox"
    
    # Get assistant mode
    mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
    
    if not items:
        if mode_mgr and mode_mgr.is_story_mode():
            return _base_response(
                cmd_name,
                "📭 **Inbox is empty!**\n\n"
                "Capture ideas with `#capture <text>` or `#in <text>`",
                {"items": []},
            )
        else:
            return _base_response(
                cmd_name,
                "Inbox empty. Use `#capture <text>` to add items.",
                {"items": []},
            )
    
    if mode_mgr and mode_mgr.is_story_mode():
        lines = [f"╔══ {title} ══╗", ""]
    else:
        lines = [f"## {title}", ""]
    
    for i, item in enumerate(items, 1):
        priority_icon = item.priority_icon if item.priority else ""
        status = "✓" if item.processed else ""
        
        # Truncate long content
        content = item.content
        if len(content) > 60:
            content = content[:57] + "..."
        
        if mode_mgr and mode_mgr.is_story_mode():
            lines.append(f"{i}. {priority_icon} {content} {status}")
            lines.append(f"   └─ {item.age_str} • `{item.id}`")
        else:
            lines.append(f"{i}. [{item.id}] {content} ({item.age_str})")
    
    lines.append("")
    lines.append("**Commands:**")
    lines.append("• `#inbox <id>` — View item details")
    lines.append("• `#capture <text>` — Add new item")
    if not show_all:
        lines.append("• `#inbox all` — Show all including processed")
    
    return _base_response(
        cmd_name,
        "\n".join(lines),
        {"items": [i.to_dict() for i in items], "count": len(items)},
    )


# =============================================================================
# PROCESS ITEM
# =============================================================================

def handle_inbox_process(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Process an inbox item (convert to quest, reminder, or archive).
    
    Usage:
        #inbox-process <id> quest     — Convert to quest (opens quest-compose)
        #inbox-process <id> reminder  — Convert to reminder
        #inbox-process <id> archive   — Mark as archived
    """
    inbox = getattr(kernel, 'inbox_store', None)
    if not inbox:
        return _error_response(cmd_name, "Inbox not available.", "NO_INBOX")
    
    # Parse args
    item_id = None
    action = None
    
    if isinstance(args, dict):
        item_id = args.get("id")
        action = args.get("action") or args.get("to")
        
        positional = args.get("_", [])
        if len(positional) >= 2:
            item_id = item_id or positional[0]
            action = action or positional[1]
        elif len(positional) == 1:
            if not item_id:
                item_id = positional[0]
            elif not action:
                action = positional[0]
    
    if not item_id:
        return _error_response(
            cmd_name,
            "Usage: `#inbox-process <id> <action>`\n\n"
            "Actions: `quest`, `reminder`, `archive`",
            "MISSING_ID",
        )
    
    item = inbox.get(item_id)
    if not item:
        return _error_response(cmd_name, f"Item '{item_id}' not found.", "NOT_FOUND")
    
    if item.processed:
        return _error_response(
            cmd_name,
            f"Item already processed → {item.processed_to}",
            "ALREADY_PROCESSED",
        )
    
    if not action:
        # Show processing options
        lines = [
            f"**Process inbox item:** {item.id}",
            "",
            f"> {item.content}",
            "",
            "**Choose action:**",
            f"• `#inbox-process {item.id} quest` — Create a quest from this",
            f"• `#inbox-process {item.id} reminder` — Create a reminder",
            f"• `#inbox-process {item.id} archive` — Archive (done/not needed)",
            f"• `#inbox-delete {item.id}` — Delete permanently",
        ]
        return _base_response(cmd_name, "\n".join(lines), item.to_dict())
    
    action = action.lower()
    
    if action == "quest":
        # Mark as processed and suggest quest-compose
        inbox.mark_processed(item_id, "quest:pending")
        
        return _base_response(
            cmd_name,
            f"✓ Item marked for quest conversion.\n\n"
            f"Run `#quest-compose` to create a quest based on:\n\n"
            f"> {item.content}",
            {"item": item.to_dict(), "action": "quest"},
        )
    
    elif action == "reminder":
        # Mark as processed and suggest reminder creation
        inbox.mark_processed(item_id, "reminder:pending")
        
        return _base_response(
            cmd_name,
            f"✓ Item marked for reminder.\n\n"
            f"Run `#remind` to create a reminder based on:\n\n"
            f"> {item.content}",
            {"item": item.to_dict(), "action": "reminder"},
        )
    
    elif action in ("archive", "done", "archived"):
        inbox.mark_processed(item_id, "archived")
        
        mode_mgr = getattr(kernel, 'assistant_mode_manager', None)
        if mode_mgr and mode_mgr.is_story_mode():
            summary = f"📦 **Archived:** {item.content[:40]}..."
        else:
            summary = f"Archived: {item.id}"
        
        return _base_response(cmd_name, summary, {"item_id": item_id, "action": "archived"})
    
    else:
        return _error_response(
            cmd_name,
            f"Unknown action '{action}'. Use: quest, reminder, or archive",
            "INVALID_ACTION",
        )


# =============================================================================
# DELETE ITEM
# =============================================================================

def handle_inbox_delete(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Delete an inbox item.
    
    Usage:
        #inbox-delete <id>
        #inbox-delete id=abc123
    """
    inbox = getattr(kernel, 'inbox_store', None)
    if not inbox:
        return _error_response(cmd_name, "Inbox not available.", "NO_INBOX")
    
    # Get item ID
    item_id = None
    if isinstance(args, dict):
        item_id = args.get("id")
        positional = args.get("_", [])
        if not item_id and positional:
            item_id = positional[0]
    elif isinstance(args, str):
        item_id = args
    
    if not item_id:
        return _error_response(
            cmd_name,
            "Usage: `#inbox-delete <id>`",
            "MISSING_ID",
        )
    
    item = inbox.get(item_id)
    if not item:
        return _error_response(cmd_name, f"Item '{item_id}' not found.", "NOT_FOUND")
    
    content_preview = item.content[:40] + "..." if len(item.content) > 40 else item.content
    inbox.delete(item_id)
    
    return _base_response(
        cmd_name,
        f"✓ Deleted: {content_preview}",
        {"deleted_id": item_id},
    )


# =============================================================================
# CLEAR PROCESSED
# =============================================================================

def handle_inbox_clear(cmd_name, args, session_id, context, kernel, meta) -> CommandResponse:
    """
    Clear processed items from inbox.
    
    Usage:
        #inbox-clear              — Clear all processed items
        #inbox-clear confirm=yes  — Skip confirmation
    """
    inbox = getattr(kernel, 'inbox_store', None)
    if not inbox:
        return _error_response(cmd_name, "Inbox not available.", "NO_INBOX")
    
    # Check for confirmation
    confirmed = False
    if isinstance(args, dict):
        confirmed = args.get("confirm", "").lower() in ("yes", "true", "1")
    
    # Count processed items
    all_items = inbox.list_all()
    processed_count = sum(1 for i in all_items if i.processed)
    
    if processed_count == 0:
        return _base_response(cmd_name, "No processed items to clear.", {"cleared": 0})
    
    if not confirmed:
        return _base_response(
            cmd_name,
            f"This will permanently delete {processed_count} processed item(s).\n\n"
            f"Run `#inbox-clear confirm=yes` to confirm.",
            {"pending_clear": processed_count},
        )
    
    cleared = inbox.clear_processed()
    
    return _base_response(
        cmd_name,
        f"✓ Cleared {cleared} processed item(s) from inbox.",
        {"cleared": cleared},
    )


# =============================================================================
# HANDLER REGISTRY
# =============================================================================

INBOX_HANDLERS = {
    "handle_capture": handle_capture,
    "handle_inbox": handle_inbox,
    "handle_inbox_process": handle_inbox_process,
    "handle_inbox_delete": handle_inbox_delete,
    "handle_inbox_clear": handle_inbox_clear,
}


def get_inbox_handlers():
    """Get all inbox handlers for registration."""
    return INBOX_HANDLERS
