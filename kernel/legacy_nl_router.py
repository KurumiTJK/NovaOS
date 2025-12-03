# kernel/legacy_nl_router.py
"""
# LEGACY_NL_ROUTING_V0_5
# =====================
#
# This file contains the legacy natural language routing code from v0.5.1.
# It has been quarantined here as part of v0.6 migration.
#
# Migration Path:
# 1. Run both new and legacy NL routers in parallel
# 2. Set USE_LEGACY_NL = False in config
# 3. Verify system stability for a few days
# 4. If no regressions, delete this file
#
# DO NOT modify this code. It is preserved for fallback purposes only.
"""

from typing import Dict, Any, Optional
import re

from .command_types import CommandRequest


def legacy_interpret_nl_to_command(
    text: str,
    session_id: str,
    commands: Dict[str, Any],
) -> Optional[CommandRequest]:
    """
    v0.5.1 — Legacy NL → Command Interpreter
    
    Handles natural language patterns and maps them to syscommands.
    Returns None if no match (falls through to persona).
    
    LEGACY CODE — DO NOT MODIFY
    """
    lowered = text.lower().strip()

    # =================================================================
    # SYSTEM / STATUS PATTERNS
    # =================================================================

    if any(p in lowered for p in [
        "what's my status", "whats my status", "my status",
        "system status", "how's my system", "hows my system",
        "how am i doing", "check system", "nova status"
    ]):
        return CommandRequest(
            cmd_name="status",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("status"),
        )

    if any(p in lowered for p in [
        "what can you do", "show commands", "list commands",
        "help me", "what commands", "available commands"
    ]):
        return CommandRequest(
            cmd_name="help",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("help"),
        )

    if any(p in lowered for p in [
        "why do you exist", "what are you", "what is novaos",
        "who are you", "your purpose", "why novaos"
    ]):
        return CommandRequest(
            cmd_name="why",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("why"),
        )

    # =================================================================
    # ENVIRONMENT / MODE PATTERNS
    # =================================================================

    if any(p in lowered for p in [
        "show environment", "show env", "what mode",
        "current mode", "what's my mode", "whats my mode"
    ]):
        return CommandRequest(
            cmd_name="env",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("env"),
        )

    mode_patterns = [
        (r"(?:switch to|enter|go into|set mode to|activate)\s+(deep.?work|focus)", "deep_work"),
        (r"(?:switch to|enter|go into|set mode to|activate)\s+(reflection|reflect)", "reflection"),
        (r"(?:switch to|enter|go into|set mode to|activate)\s+(debug)", "debug"),
        (r"(?:switch to|enter|go into|set mode to|activate)\s+(normal)", "normal"),
        (r"(?:i need to|let's|time to)\s+(focus|concentrate|deep work)", "deep_work"),
        (r"(?:i need to|let's|time to)\s+(reflect|think)", "reflection"),
    ]
    for pattern, mode_name in mode_patterns:
        if re.search(pattern, lowered):
            return CommandRequest(
                cmd_name="mode",
                args={"name": mode_name},
                session_id=session_id,
                raw_text=text,
                meta=commands.get("mode"),
            )

    # =================================================================
    # WORKFLOW PATTERNS
    # =================================================================

    if lowered.strip() in ("list workflows", "show workflows", "what workflows do i have", "my workflows"):
        return CommandRequest(
            cmd_name="workflow-list",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("workflow-list"),
        )

    m = re.match(r"^(?:delete|remove)\s+workflow\s+(\d+)\b", lowered)
    if m:
        wid = int(m.group(1))
        return CommandRequest(
            cmd_name="workflow-delete",
            args={"id": wid},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("workflow-delete"),
        )

    m = re.match(r"^(?:start|begin|launch)\s+(?:my\s+)?(?:workflow\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+workflow)?$", lowered)
    if m:
        workflow_name = m.group(1).strip()
        if workflow_name and workflow_name not in ("a", "the", "my"):
            return CommandRequest(
                cmd_name="flow",
                args={"id": workflow_name.replace(" ", "_"), "name": workflow_name},
                session_id=session_id,
                raw_text=text,
                meta=commands.get("flow"),
            )

    if any(p in lowered for p in [
        "advance workflow", "next step", "move forward",
        "continue workflow", "proceed", "next phase"
    ]):
        m = re.search(r"workflow\s+(\S+)", lowered)
        wid = m.group(1) if m else None
        return CommandRequest(
            cmd_name="advance",
            args={"id": wid} if wid else {},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("advance"),
        )

    if any(p in lowered for p in ["pause workflow", "halt workflow", "stop workflow"]):
        m = re.search(r"workflow\s+(\S+)", lowered)
        wid = m.group(1) if m else None
        return CommandRequest(
            cmd_name="halt",
            args={"id": wid} if wid else {},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("halt"),
        )

    if re.match(r"^(?:create|make|build|plan)\s+(?:a\s+)?(?:workflow|plan)\s+(?:for\s+)?(.+)$", lowered):
        m = re.match(r"^(?:create|make|build|plan)\s+(?:a\s+)?(?:workflow|plan)\s+(?:for\s+)?(.+)$", lowered)
        goal = m.group(1).strip() if m else text
        return CommandRequest(
            cmd_name="compose",
            args={"goal": goal},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("compose"),
        )

    # =================================================================
    # TIME RHYTHM PATTERNS
    # =================================================================

    if any(p in lowered for p in [
        "where am i in time", "time presence", "what cycle",
        "current cycle", "my rhythm", "time rhythm"
    ]):
        return CommandRequest(
            cmd_name="presence",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("presence"),
        )

    if any(p in lowered for p in ["check pulse", "workflow health", "system pulse", "pulse check"]):
        return CommandRequest(
            cmd_name="pulse",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("pulse"),
        )

    if any(p in lowered for p in [
        "what should i do", "suggest next", "prioritize",
        "what's next", "whats next", "suggest action"
    ]):
        return CommandRequest(
            cmd_name="align",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("align"),
        )

    # =================================================================
    # MEMORY PATTERNS
    # =================================================================

    m = re.match(r"^remember\s+(.+)", lowered)
    if m:
        payload = m.group(1).strip()
        tags = ["general"]
        mem_type = "semantic"

        for tag_type in ["finance", "real_estate", "health", "work", "personal"]:
            if tag_type.replace("_", " ") in lowered or tag_type in lowered:
                tags = [tag_type]
                break

        if "procedural" in lowered:
            mem_type = "procedural"
        elif "episodic" in lowered:
            mem_type = "episodic"

        return CommandRequest(
            cmd_name="store",
            args={"payload": payload, "type": mem_type, "tags": tags},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("store"),
        )

    if re.match(r"^(?:recall|show|get)\s+(?:my\s+)?(.+)\s+memories", lowered):
        tags = None
        mem_type = None

        for tag_type in ["finance", "real_estate", "health", "work", "personal"]:
            if tag_type.replace("_", " ") in lowered or tag_type in lowered:
                tags = [tag_type]
                break

        if "semantic" in lowered:
            mem_type = "semantic"
        elif "procedural" in lowered:
            mem_type = "procedural"
        elif "episodic" in lowered:
            mem_type = "episodic"

        args: Dict[str, Any] = {}
        if mem_type:
            args["type"] = mem_type
        if tags:
            args["tags"] = tags

        if args:
            return CommandRequest(
                cmd_name="recall",
                args=args,
                session_id=session_id,
                raw_text=text,
                meta=commands.get("recall"),
            )

    m = re.match(r"^(?:forget|delete|remove)\s+memory\s+#?(\d+)", lowered)
    if m:
        mem_id = int(m.group(1))
        return CommandRequest(
            cmd_name="forget",
            args={"ids": [mem_id]},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("forget"),
        )

    # =================================================================
    # REMINDER PATTERNS
    # =================================================================

    if lowered.startswith("remind me"):
        text_no_prefix = lowered.replace("remind me", "", 1).strip()
        if text_no_prefix.startswith("to "):
            text_no_prefix = text_no_prefix[3:]

        if " at " in text_no_prefix:
            title_part, when_part = text_no_prefix.split(" at ", 1)
            return CommandRequest(
                cmd_name="remind-add",
                args={"title": title_part.strip(), "when": when_part.strip()},
                session_id=session_id,
                raw_text=text,
                meta=commands.get("remind-add"),
            )
        elif " in " in text_no_prefix:
            title_part, when_part = text_no_prefix.split(" in ", 1)
            return CommandRequest(
                cmd_name="remind-add",
                args={"title": title_part.strip(), "when": f"in {when_part.strip()}"},
                session_id=session_id,
                raw_text=text,
                meta=commands.get("remind-add"),
            )

    if any(p in lowered for p in ["show reminders", "list reminders", "my reminders", "what reminders"]):
        return CommandRequest(
            cmd_name="remind-list",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("remind-list"),
        )

    # =================================================================
    # MODULE PATTERNS
    # =================================================================

    if any(p in lowered for p in ["list modules", "show modules", "what modules", "my modules"]):
        return CommandRequest(
            cmd_name="map",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("map"),
        )

    m = re.match(r"^(?:create|forge|make)\s+(?:a\s+)?module\s+(?:called\s+|named\s+)?([a-zA-Z0-9_\-]+)", lowered)
    if m:
        key = m.group(1).strip()
        return CommandRequest(
            cmd_name="forge",
            args={"key": key, "name": key, "mission": f"Module for {key}"},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("forge"),
        )

    m = re.match(r"^(?:inspect|show|describe)\s+module\s+([a-zA-Z0-9_\-]+)", lowered)
    if m:
        key = m.group(1).strip()
        return CommandRequest(
            cmd_name="inspect",
            args={"key": key},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("inspect"),
        )

    # =================================================================
    # INTERPRETATION PATTERNS
    # =================================================================

    if lowered.startswith(("analyze ", "break down ", "what does this mean")):
        content = re.sub(r"^(analyze|break down|what does this mean)\s*:?\s*", "", lowered)
        if content:
            return CommandRequest(
                cmd_name="interpret",
                args={"input": content},
                session_id=session_id,
                raw_text=text,
                meta=commands.get("interpret"),
            )

    if "first principles" in lowered:
        content = re.sub(r".*first principles\s*(about|on)?\s*", "", lowered)
        if content:
            return CommandRequest(
                cmd_name="derive",
                args={"input": content},
                session_id=session_id,
                raw_text=text,
                meta=commands.get("derive"),
            )

    if lowered.startswith("reframe ") or "look at" in lowered and "differently" in lowered:
        content = re.sub(r"^reframe\s*:?\s*", "", lowered)
        content = re.sub(r"look at\s*(.+)\s*differently.*", r"\1", content)
        if content and content != lowered:
            return CommandRequest(
                cmd_name="frame",
                args={"input": content},
                session_id=session_id,
                raw_text=text,
                meta=commands.get("frame"),
            )

    if lowered.startswith(("predict ", "forecast ")) or "what might happen" in lowered:
        content = re.sub(r"^(predict|forecast)\s*:?\s*", "", lowered)
        content = re.sub(r"what might happen\s*(with|to|if)?\s*", "", content)
        if content and content != lowered:
            return CommandRequest(
                cmd_name="forecast",
                args={"input": content},
                session_id=session_id,
                raw_text=text,
                meta=commands.get("forecast"),
            )

    # =================================================================
    # SNAPSHOT PATTERNS
    # =================================================================

    if any(p in lowered for p in ["save state", "create snapshot", "backup system", "snapshot"]):
        return CommandRequest(
            cmd_name="snapshot",
            args={},
            session_id=session_id,
            raw_text=text,
            meta=commands.get("snapshot"),
        )

    # =================================================================
    # NO MATCH
    # =================================================================
    return None
