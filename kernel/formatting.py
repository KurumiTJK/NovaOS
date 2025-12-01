class OutputFormatter:

    @staticmethod
    def header(text: str) -> str:
        return f"**{text}**\n"

    @staticmethod
    def subheader(text: str) -> str:
        """Smaller section header used inside larger blocks."""
        return f"\n### {text}\n\n"
    
    @staticmethod
    def item(id, label, details=None):
        base = f"#{id} — {label}"
        if details:
            return f"{base}\n    {details}"
        return base

    @staticmethod
    def list(items: list[str]) -> str:
        return "\n".join(items)

    @staticmethod
    def key_value(key, value):
        return f"- {key}: {value}"

    @staticmethod
    def divider():
        return "―" * 20 + "\n"
