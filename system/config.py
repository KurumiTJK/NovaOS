# system/config.py
import json
from pathlib import Path
from dataclasses import dataclass

CONFIG_DIR = Path("data")  # Make sure this points to the correct folder path

@dataclass
class Config:
    data_dir: Path
    env: str = "dev"
    debug: bool = True

    @classmethod
    def load(cls) -> "Config":
        # This is the path to config.json
        cfg_path = CONFIG_DIR / "config.json"

        # Check if the config file exists or is empty
        if not cfg_path.exists() or cfg_path.stat().st_size == 0:
            default = {"env": "dev", "debug": True}

            # Ensure the directory exists
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)  # Ensure data directory exists

            # Create and write default content to config.json
            with cfg_path.open("w", encoding="utf-8") as f:
                json.dump(default, f, indent=2)

            # Return the default config after writing it
            return cls(data_dir=CONFIG_DIR, **default)

        try:
            # Try loading the configuration file
            with cfg_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:  # In case of error (e.g., JSONDecodeError)
            raw = {"env": "dev", "debug": True}
            with cfg_path.open("w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2)

        return cls(data_dir=CONFIG_DIR, **raw)
