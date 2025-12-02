# ui/nova_ui.py
import tkinter as tk
from pprint import pformat  # for nicer debug output


class NovaApp:
    """
    v0.4.6 → UI Refresh:
    - Chat-style message bubbles instead of a single text blob
    - Max-width, padding, and spacing for ChatGPT-like readability
    - Debug toggle preserved (shows underlying content block)
    """

    BG_WINDOW = "#f2f2f7"   # window background
    BG_CHAT = "#f2f2f7"     # chat area background
    BG_NOVA = "#f7f7fa"     # Nova bubble background
    BG_USER = "#dbeafe"     # User bubble background (soft blue)
    BG_SYSTEM = "#fee2e2"   # Error/system bubble background (soft red)
    BG_DEBUG = "#111827"    # Debug block background (dark)

    FG_TEXT = "#111827"     # main text color
    FG_MUTED = "#4b5563"    # small/secondary text
    FG_DEBUG = "#e5e7eb"    # debug text color (on dark bg)

    WRAP_WIDTH = 650        # approximate ChatGPT-style max content width

    def __init__(self, kernel, config):
        self.kernel = kernel
        self.config = config

        self.root = tk.Tk()
        self.root.title("NovaOS Desktop")
        self.root.configure(bg=self.BG_WINDOW)
        self.root.minsize(800, 600)

        # v0.4.6: debug mode flag (default OFF = clean UX)
        self.debug_mode = tk.BooleanVar(value=False)

        self._build_layout()

        # Simple session id for now (single session)
        self.session_id = "default"

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_layout(self):
        # Top banner / title
        header = tk.Frame(self.root, bg=self.BG_WINDOW)
        header.pack(side=tk.TOP, fill=tk.X, pady=(8, 4))

        title_label = tk.Label(
            header,
            text="NovaOS Desktop",
            bg=self.BG_WINDOW,
            fg=self.FG_TEXT,
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        )
        title_label.pack(side=tk.LEFT, padx=(16, 8))

        subtitle_label = tk.Label(
            header,
            text="Chat-grade readability • Commands • Debug mode",
            bg=self.BG_WINDOW,
            fg=self.FG_MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        )
        subtitle_label.pack(side=tk.LEFT)

        # Main chat area (scrollable)
        main = tk.Frame(self.root, bg=self.BG_WINDOW)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Canvas + scrollable frame for messages
        self.chat_canvas = tk.Canvas(
            main,
            bg=self.BG_CHAT,
            highlightthickness=0,
            bd=0,
        )
        scrollbar = tk.Scrollbar(main, orient="vertical", command=self.chat_canvas.yview)
        self.chat_canvas.configure(yscrollcommand=scrollbar.set)

        self.chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Frame inside canvas to hold message bubbles
        self.chat_frame = tk.Frame(self.chat_canvas, bg=self.BG_CHAT)
        self.chat_window = self.chat_canvas.create_window(
            (0, 0),
            window=self.chat_frame,
            anchor="nw",
        )

        # Make scrolling work
        self.chat_frame.bind(
            "<Configure>",
            lambda e: self.chat_canvas.configure(
                scrollregion=self.chat_canvas.bbox("all")
            ),
        )
        self.chat_canvas.bind("<Configure>", self._on_canvas_configure)

        # Mousewheel scroll (Windows / general)
        self.chat_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # Input area at the bottom
        input_frame = tk.Frame(self.root, bg=self.BG_WINDOW)
        input_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 8), padx=8)

        self.entry = tk.Entry(
            input_frame,
            font=("Segoe UI", 11),
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.entry.bind("<Return>", self._on_submit)

        # Debug checkbox (right side)
        debug_checkbox = tk.Checkbutton(
            input_frame,
            text="Debug",
            variable=self.debug_mode,
            onvalue=True,
            offvalue=False,
            bg=self.BG_WINDOW,
            fg=self.FG_MUTED,
            activebackground=self.BG_WINDOW,
            activeforeground=self.FG_TEXT,
            font=("Segoe UI", 9),
        )
        debug_checkbox.pack(side=tk.RIGHT, padx=(8, 0))

        send_btn = tk.Button(
            input_frame,
            text="Send",
            command=self._on_submit,
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=4,
        )
        send_btn.pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Canvas / scrolling helpers
    # ------------------------------------------------------------------
    def _on_canvas_configure(self, event):
        """
        Keep the inner chat_frame width synced with the canvas width
        so bubbles don't get cut off weirdly.
        """
        canvas_width = event.width
        self.chat_canvas.itemconfig(self.chat_window, width=canvas_width)

    def _on_mousewheel(self, event):
        # Windows scroll direction
        self.chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------
    def _on_submit(self, event=None):
        text = self.entry.get().strip()
        if not text:
            return

        # Render the user message as a right-aligned bubble
        self._add_message(role="user", text=text)

        self.entry.delete(0, tk.END)

        response = self.kernel.handle_input(text, session_id=self.session_id)
        self._render_kernel_response(response)

    # ------------------------------------------------------------------
    # Rendering messages
    # ------------------------------------------------------------------
    def _render_kernel_response(self, response: dict):
        """
        v0.4.6 — Global Command Output Cleanup + Debug Mode

        Default:
            - Only display the human-facing `summary` string
              as a Nova bubble.

        Debug mode:
            - Also display all other fields in `content` (items, workflows,
              reminders, etc.) in a separate debug block bubble.
        """
        # Error handling
        if not response.get("ok", False):
            error_msg = response.get("error", {}).get("message", "Unknown error")
            self._add_message(
                role="system",
                text=f"NovaOS ERROR: {error_msg}",
            )
            return

        content = response.get("content", {}) or {}
        summary = content.get("summary", "")

        # Nova main reply bubble
        if summary:
            self._add_message(role="nova", text=summary)
        else:
            self._add_message(role="nova", text="(no summary)")

        # Debug: show underlying content data (except summary)
        if self.debug_mode.get():
            debug_lines = []
            for key, value in content.items():
                if key == "summary":
                    continue
                debug_lines.append(f"{key}:\n{pformat(value)}")

            if debug_lines:
                debug_text = "\n\n".join(debug_lines)
                self._add_message(
                    role="debug",
                    text=debug_text,
                )

    def _add_message(self, role: str, text: str, kind: str = "normal"):
        """
        Create a ChatGPT-style bubble with:
        - Soft background
        - Padding
        - Max-width via wraplength
        - Vertical spacing between messages

        New behavior:
        - Never auto-scroll. Your scroll position is preserved.
        """
        # Container row for alignment
        row = tk.Frame(self.chat_frame, bg=self.BG_CHAT)
        row.pack(fill=tk.X, pady=(0, 10), padx=16)

        is_user = role == "user"
        is_nova = role == "nova"
        is_system = role == "system"
        is_debug = role == "debug"

        if is_user:
            bubble_bg = self.BG_USER
            fg = self.FG_TEXT
            header_text = "You"
        elif is_system:
            bubble_bg = self.BG_SYSTEM
            fg = self.FG_TEXT
            header_text = "System"
        elif is_debug:
            bubble_bg = self.BG_DEBUG
            fg = self.FG_DEBUG
            header_text = "Debug"
        else:
            bubble_bg = self.BG_NOVA
            fg = self.FG_TEXT
            header_text = "Nova"

        # Inner bubble frame (card)
        bubble_outer = tk.Frame(row, bg=self.BG_CHAT)
        bubble_outer.pack(side=tk.RIGHT if is_user else tk.LEFT, fill=tk.NONE)

        bubble = tk.Frame(
            bubble_outer,
            bg=bubble_bg,
            bd=0,
            padx=14,
            pady=10,
        )
        bubble.pack()

        # Header label (small, muted)
        header_label = tk.Label(
            bubble,
            text=header_text,
            bg=bubble_bg,
            fg=self.FG_MUTED if not is_debug else self.FG_DEBUG,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        header_label.pack(anchor="w")

        # Main text label
        text_label = tk.Label(
            bubble,
            text=text,
            bg=bubble_bg,
            fg=fg,
            font=("Segoe UI", 10),
            justify="left",
            wraplength=self.WRAP_WIDTH,
            anchor="w",
        )
        text_label.pack(anchor="w", pady=(2, 0))

        if is_debug:
            text_label.configure(
                font=("Consolas", 9),
                justify="left",
            )

        # Just re-layout; do NOT change scroll position
        self.chat_canvas.update_idletasks()
        # ❌ no self.chat_canvas.yview_moveto(1.0)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self):
        self.root.mainloop()
