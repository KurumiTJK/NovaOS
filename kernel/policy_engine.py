# kernel/policy_engine.py
from system.config import Config

class PolicyEngine:
    def __init__(self, config: Config):
        self.config = config

    def postprocess_nl_response(self, text: str, context) -> str:
        """
        Hook to enforce high-level policy or transform output.
        For now, just return as-is.
        """
        # Later: mask secrets, enforce brevity/structure, etc.
        return text
