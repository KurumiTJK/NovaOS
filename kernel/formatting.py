class OutputFormatter:

    @staticmethod
    def header(text: str) -> str:
        # Top-level section header
        return f"**{text}**\n"

    @staticmethod
    def subheader(text: str) -> str:
        """
        v0.5.2 – Lightweight subheader helper.

        Renders a simple section title with an underline, e.g.:

        Core Commands
        -------------
        """
        line = "-" * len(text)
        return f"\n{text}\n{line}\n"

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
        # Simple horizontal divider
        return "\n" + ("-" * 40) + "\n"
