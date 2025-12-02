# kernel/context_manager.py
from typing import Dict, Any
from system.config import Config
from pathlib import Path
import json

class ContextManager:
    def __init__(self, config: Config):
        self.config = config
        self._sessions: Dict[str, Dict[str, Any]] = {}  # Stores session data

        # Path to the modules file
        self.modules_file = Path(self.config.data_dir) / "modules.json"
        self.memory_file = self.config.data_dir / "memory.json"  # New memory file for storing session data
        self._ensure_files()

    def _ensure_files(self):
        # Ensure the modules file exists
        if not self.modules_file.exists() or self.modules_file.stat().st_size == 0:
            with self.modules_file.open("w", encoding="utf-8") as f:
                json.dump([], f)  # Initialize as empty list

        # Ensure the memory file exists
        if not self.memory_file.exists() or self.memory_file.stat().st_size == 0:
            with self.memory_file.open("w", encoding="utf-8") as f:
                json.dump({}, f)  # Initialize as empty dictionary

    def get_context(self, session_id: str) -> Dict[str, Any]:
        # Get or create the session context
        if session_id not in self._sessions:
            self._sessions[session_id] = {"booted": False, "memory": {}}
        else:
            return self._sessions[session_id]

    def reset_session(self, session_id: str) -> None:
        print(f"[CTX] reset_session({session_id})")
        self._sessions[session_id] = {"booted": False, "memory": {}}

    def mark_booted(self, session_id: str) -> None:
        # Mark the session as "booted"
        ctx = self.get_context(session_id)
        ctx["booted"] = True

    def get_module_summary(self):
        # Return the list of modules (empty list if no modules)
        with self.modules_file.open("r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception:
                return []

    def get_memory(self, session_id: str) -> Dict[str, Any]:
        # Return memory for a specific session
        context = self.get_context(session_id)
        return context.get("memory", {})

    def update_memory(self, session_id: str, new_memory: Dict[str, Any]) -> None:
        # Update the memory for a specific session
        context = self.get_context(session_id)
        context["memory"].update(new_memory)

    def build_system_prompt(self, session_id: str) -> str:
        """
        Build the system prompt based on the session's memory and context.
        You can extend this to include workflows, memory entries, etc.
        """
        context = self.get_context(session_id)
        memory = context.get("memory", {})

        # Create a simple system prompt using the session's memory
        prompt = "You are NovaOS, an AI system. You have the following context:\n"
        
        if memory:
            prompt += "\nMemory:\n"
            for key, value in memory.items():
                prompt += f"- {key}: {value}\n"

        prompt += "\nPlease assist the user with their request."
        return prompt
