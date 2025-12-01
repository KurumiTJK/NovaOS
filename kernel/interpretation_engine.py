# kernel/interpretation_engine.py

from __future__ import annotations
from typing import Optional, Dict, Any

from .command_types import CommandRequest

class InterpretationEngine:
    """
    v0.5 - Natural Language → Command Interpreter
    ------------------------------------------------
    This runs BEFORE explicit syscommand matching and BEFORE
    persona fallback.

    Responsibilities:
    - Try to map natural text to:
        • core syscommands ("status", "help", etc.)
        • workflow commands ("flow", "advance", "halt")
        • mode/env commands ("mode", "setenv")
        • custom prompt/macro commands (loaded from commands_custom.json)
    - Does NOT execute anything. Only returns a CommandRequest or None.
    - Must NEVER break routing invariants.
    """

    def __init__(self, commands: Dict[str, Dict[str, Any]], custom_commands: Dict[str, Any]):
        self.commands = commands                  # normalized core registry
        self.custom = custom_commands or {}       # prompt + macro commands

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------
    def interpret(self, text: str, session_id: str) -> Optional[CommandRequest]:
        lowered = text.lower().strip()

        # 1. Direct match by command name (simple NL like "status please")
        direct = self._match_direct(lowered, text, session_id)
        if direct:
            return direct

        # 2. Custom Prompt/Macro commands
        custom = self._match_custom(lowered, text, session_id)
        if custom:
            return custom

        # 3. v0.5 Interpretation Commands (interpret/derive/frame/synthesize/forecast)
        interp_cmd = self._match_interpretation_keywords(lowered, text, session_id)
        if interp_cmd:
            return interp_cmd

        # 4. Mode / Environment / System
        env_cmd = self._match_env_and_mode(lowered, text, session_id)
        if env_cmd:
            return env_cmd

        # 5. Not interpretable → None → Kernel routes to persona
        return None

    # ---------------------------------------------------------
    # 1) Direct command recognition ("status", "help", "boot")
    # ---------------------------------------------------------
    def _match_direct(self, lowered: str, raw: str, session_id: str):
        for cmd in self.commands.keys():
            if lowered == cmd or lowered.startswith(cmd + " "):
                # build args (v0.5 simple: pass tail as full_input)
                tail = raw[len(cmd):].strip()
                args = {"full_input": tail} if tail else {}
                return CommandRequest(
                    cmd_name=cmd,
                    args=args,
                    session_id=session_id,
                    raw_text=raw,
                    meta=self.commands.get(cmd)
                )
        return None

    # ---------------------------------------------------------
    # 2) Custom commands (prompt/macro)
    # ---------------------------------------------------------
    def _match_custom(self, lowered: str, raw: str, session_id: str):
        """
        v0.5 — match custom commands from commands_custom.json

        - Uses self.custom: { name: meta_dict, ... }
        - Skips disabled commands (enabled=false)
        - Ensures handler is set (default: handle_prompt_command for prompt commands)
        """
        for name, meta in self.custom.items():
            # Skip disabled commands
            if not meta.get("enabled", True):
                continue

            # Match either exact name or "name ..." with extra text
            if lowered == name or lowered.startswith(name + " "):
                # Strip the command name off the front; rest is "full_input"
                tail = raw[len(name):].strip()
                args = {"full_input": tail} if tail else {}

                # ---- THIS IS THE IMPORTANT PART ----
                # Safely clone meta so we don't mutate the registry dict
                meta_for_request = dict(meta)

                # If no handler specified in commands_custom.json, default to prompt handler
                meta_for_request["handler"] = meta_for_request.get(
                    "handler",
                    "handle_prompt_command"
                )
                # ------------------------------------

                return CommandRequest(
                    cmd_name=name,
                    args=args,
                    session_id=session_id,
                    raw_text=raw,
                    meta=meta_for_request,
                )

        return None

    # ---------------------------------------------------------
    # 3) Interpretation commands for v0.5
    # ---------------------------------------------------------
    def _match_interpretation_keywords(self, lowered: str, raw: str, session_id: str):
        mapping = {
            "interpret": "interpret",
            "derive": "derive",
            "reframe": "frame",
            "frame": "frame",
            "synthesize": "synthesize",
            "forecast": "forecast",
        }
        for key, cmd in mapping.items():
            if lowered.startswith(key):
                tail = raw[len(key):].strip()
                args = {"input": tail} if tail else {}
                return CommandRequest(
                    cmd_name=cmd,
                    args=args,
                    session_id=session_id,
                    raw_text=raw,
                    meta=self.commands.get(cmd),
                )
        return None

    # ---------------------------------------------------------
    # 4) Modes & Environment
    # ---------------------------------------------------------
    def _match_env_and_mode(self, lowered: str, raw: str, session_id: str):
        # Example NL → "mode deep_work"
        if lowered.startswith("mode "):
            mode_name = lowered.replace("mode", "", 1).strip()
            args = {"name": mode_name}
            return CommandRequest(
                cmd_name="mode",
                args=args,
                session_id=session_id,
                raw_text=raw,
                meta=self.commands.get("mode"),
            )
        # "show environment" → env
        if "environment" in lowered or "env" == lowered:
            return CommandRequest(
                cmd_name="env",
                args={},
                session_id=session_id,
                raw_text=raw,
                meta=self.commands.get("env"),
            )
        return None
