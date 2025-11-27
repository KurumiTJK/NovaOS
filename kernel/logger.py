# kernel/logger.py
from pathlib import Path
from datetime import datetime
from system.config import Config

class KernelLogger:
    def __init__(self, config: Config):
        self.config = config
        self.log_file = config.data_dir / "kernel.log"

    def log_input(self, session_id: str, text: str):
        self._write(f"[INPUT] [{session_id}] {text}")

    def log_response(self, session_id: str, cmd_name: str, response):
        self._write(f"[RESPONSE] [{session_id}] cmd={cmd_name} ok={response.get('ok')}")

    def log_exception(self, session_id: str, cmd_name: str, exc: Exception):
        self._write(f"[EXCEPTION] [{session_id}] cmd={cmd_name} {exc!r}")

    def _write(self, line: str):
        ts = datetime.now().isoformat()
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {line}\n")
