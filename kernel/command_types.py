# kernel/command_types.py
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class CommandRequest:
    """
    Structured request for a syscommand.
    """
    cmd_name: str
    args: str
    session_id: str
    raw_text: str
    meta: Dict[str, Any] | None = None


@dataclass
class CommandResponse:
    """
    Structured response for a syscommand.
    Kernel will convert this to a dict for the UI.
    """
    ok: bool
    command: str
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    type: str = "syscommand"
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Adapter so the UI can keep expecting the old dict shape.
        """
        if self.ok:
            content = {
                "command": self.command,
                "summary": self.summary,
            }
            if self.data:
                content.update(self.data)
            return {
                "ok": True,
                "type": self.type,
                "content": content,
            }
        else:
            return {
                "ok": False,
                "error": {
                    "code": self.error_code or "ERROR",
                    "message": self.error_message or self.summary,
                },
            }
