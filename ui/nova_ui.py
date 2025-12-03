# ui/nova_ui.py
import tkinter as tk
from tkinter import scrolledtext
from pprint import pformat  # for nicer debug output


class NovaApp:
    def __init__(self, kernel, config):
        self.kernel = kernel
        self.config = config
        self.root = tk.Tk()
        self.root.title("NovaOS Desktop")

        # v0.4.6: debug mode flag (default OFF = clean UX)
        self.debug_mode = tk.BooleanVar(value=False)

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

        # Debug checkbox (right side)
        debug_checkbox = tk.Checkbutton(
            input_frame,
            text="Debug",
            variable=self.debug_mode,
            onvalue=True,
            offvalue=False,
        )
        debug_checkbox.pack(side=tk.RIGHT)

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
        """
        v0.4.6 — Global Command Output Cleanup + Debug Mode

        Default:
            - Only display the human-facing `summary` string.
        Debug mode:
            - Also display all other fields in `content` (items, workflows, reminders, etc.)
              in a readable, pretty-printed block.
        """
        # Error handling
        if not response.get("ok", False):
            self._append_text(
                f"NovaOS ERROR: {response.get('error', {}).get('message', 'Unknown error')}\n"
            )
            return

        content = response.get("content", {})
        summary = content.get("summary", "")

        # ✅ Always show the formatted summary first
        if summary:
            self._append_text(f"Nova: {summary}\n")
        else:
            self._append_text("Nova: (no summary)\n")

        # 🐛 Debug: show underlying content data (except summary)
        if self.debug_mode.get():
            debug_lines = []
            for key, value in content.items():
                if key == "summary":
                    continue
                debug_lines.append(f"{key}:\n{pformat(value)}")

            if debug_lines:
                self._append_text("\n[DEBUG]\n")
                self._append_text("\n\n".join(debug_lines) + "\n")

    def _append_text(self, text: str):
        self.output.insert(tk.END, text)
        self.output.see(tk.END)

    def run(self):
        self.root.mainloop()
