# kernel/memory_manager.py
import json
from pathlib import Path
from typing import Dict, Any
from system.config import Config

class MemoryManager:
    def __init__(self, config: Config):
        self.config = config
        self.mem_dir = config.data_dir / "memory"
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        self.semantic_file = self.mem_dir / "semantic.json"
        self.procedural_file = self.mem_dir / "procedural.json"
        self.episodic_file = self.mem_dir / "episodic.json"
        self._ensure_files()

    def _ensure_files(self):
        """Ensure that memory files exist and are initialized."""
        files = [
            self.semantic_file,
            self.procedural_file,
            self.episodic_file
        ]
        
        for path in files:
            # Check if file exists or is empty
            if not path.exists() or path.stat().st_size == 0:
                with path.open("w", encoding="utf-8") as f:
                    json.dump([], f)  # Initialize with empty list

    def get_health(self) -> Dict[str, Any]:
        """Return memory health (number of entries in each memory file)."""
        try:
            semantic_entries = len(self._load(self.semantic_file))
            procedural_entries = len(self._load(self.procedural_file))
            episodic_entries = len(self._load(self.episodic_file))
            return {
                "semantic_entries": semantic_entries,
                "procedural_entries": procedural_entries,
                "episodic_entries": episodic_entries
            }
        except Exception as e:
            return {"error": f"Error while fetching memory health: {str(e)}"}

    def maybe_store_nl_interaction(self, user_text: str, llm_output: str, context) -> None:
        """Log a natural language interaction into episodic memory."""
        try:
            entries = self._load(self.episodic_file)
            entries.append({
                "user": user_text,
                "nova": llm_output,
            })
            self._save(self.episodic_file, entries)
        except Exception as e:
            print(f"Error while logging NL interaction: {e}")

    def _load(self, path: Path):
        """Load JSON data from a file."""
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error reading {path}: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error while loading {path}: {e}")
            return []

    def _save(self, path: Path, data):
        """Save JSON data to a file."""
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving data to {path}: {e}")
