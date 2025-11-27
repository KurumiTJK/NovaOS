# ui/nova_ui.py
import tkinter as tk
from tkinter import scrolledtext

class NovaApp:
    def __init__(self, kernel, config):
        self.kernel = kernel
        self.config = config
        self.root = tk.Tk()
        self.root.title("NovaOS Desktop")

        self._build_layout()

        # Simple session id for now (single session)
        self.session_id = "default"

    def _build_layout(self):
        self.output = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, height=25)
        self.output.pack(fill=tk.BOTH, expand=True)

        input_frame = tk.Frame(self.root)
        input_frame.pack(fill=tk.X)

        self.entry = tk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", self._on_submit)

        send_btn = tk.Button(input_frame, text="Send", command=self._on_submit)
        send_btn.pack(side=tk.RIGHT)

    def _on_submit(self, event=None):
        text = self.entry.get().strip()
        if not text:
            return

        self._append_text(f"You: {text}\n")
        self.entry.delete(0, tk.END)

        response = self.kernel.handle_input(text, session_id=self.session_id)
        self._render_kernel_response(response)

    def _render_kernel_response(self, response: dict):
        # Error handling
        if not response.get("ok", False):
            self._append_text(
                f"NovaOS ERROR: {response.get('error', {}).get('message', 'Unknown error')}\n"
            )
            return

        content = response.get("content", {})
        summary = content.get("summary", "")

        # Always print summary line first
        self._append_text(f"Nova: {summary}\n")

        # ---- EXTRA FIELDS RENDERING ----
        # (Everything except summary/command/type)

        for key, value in content.items():
            if key in ("summary", "command", "type"):
                continue  # skip internal fields

            # HELP COMMAND → commands list
            if key == "commands" and isinstance(value, list):
                self._append_text("\nSyscommands:\n")
                for cmd in sorted(value, key=lambda c: c.get("name", "")):
                    name = cmd.get("name", "")
                    desc = cmd.get("description", "")
                    cat = cmd.get("category", "misc")
                    self._append_text(f"  • {name} [{cat}] — {desc}\n")
                continue

            # STATUS COMMAND → memory_health + modules
            if key == "memory_health" and isinstance(value, dict):
                self._append_text("\nMemory Health:\n")
                for mkey, mval in value.items():
                    self._append_text(f"  • {mkey}: {mval}\n")
                continue

            if key == "modules" and isinstance(value, list):
                self._append_text("\nModules:\n")
                if not value:
                    self._append_text("  • (no modules registered)\n")
                else:
                    for module in value:
                        name = module.get("name", "(unnamed)")
                        self._append_text(f"  • {name}\n")
                continue

            # Catch-all for any future fields
            self._append_text(f"\n{key}:\n{value}\n")

    def _append_text(self, text: str):
        self.output.insert(tk.END, text)
        self.output.see(tk.END)

    def run(self):
        self.root.mainloop()
