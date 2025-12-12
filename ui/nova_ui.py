# ui/nova_ui.py
"""
NovaOS Desktop UI — v0.9.0

Now uses the dual-mode architecture:
- Default: Persona mode (pure conversation)
- After #boot: NovaOS mode (kernel + modules)
- After #shutdown: Back to Persona mode

The UI shows the current mode in the title bar.
"""

import tkinter as tk
from tkinter import scrolledtext
from pprint import pformat
import traceback

# v0.9.0: Import mode router
from core.mode_router import handle_user_message, get_or_create_state

# v0.12.0: Dashboard auto-show on launch
from kernel.dashboard_handlers import get_auto_dashboard_on_launch


class NovaApp:
    def __init__(self, kernel, persona, config):
        """
        Initialize NovaApp with dual-mode support.
        
        Args:
            kernel: NovaKernel instance (for NovaOS mode)
            persona: NovaPersona instance (for both modes)
            config: Config instance
        """
        self.kernel = kernel
        self.persona = persona
        self.config = config
        self.root = tk.Tk()
        
        # v0.4.6: debug mode flag (default OFF = clean UX)
        self.debug_mode = tk.BooleanVar(value=False)

        self._build_layout()

        # Session ID for this desktop instance
        self.session_id = "desktop"
        
        # v0.9.0: Get or create state for this session
        self.state = get_or_create_state(self.session_id)
        
        # Update title after state is created
        self._update_title()

    def _update_title(self):
        """Update window title with current mode."""
        if hasattr(self, 'state') and self.state:
            mode = self.state.mode_name
            self.root.title(f"NovaOS Desktop — {mode} Mode")
        else:
            self.root.title("NovaOS Desktop")

    def _build_layout(self):
        # Output area
        self.output = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, height=25, width=80)
        self.output.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Configure tags for styling
        self.output.tag_configure("user", foreground="#0066cc")
        self.output.tag_configure("nova", foreground="#006633")
        self.output.tag_configure("system", foreground="#666666", font=("TkDefaultFont", 9, "italic"))
        self.output.tag_configure("mode", foreground="#993399", font=("TkDefaultFont", 9, "bold"))
        self.output.tag_configure("error", foreground="#cc0000")

        # Input frame
        input_frame = tk.Frame(self.root)
        input_frame.pack(fill=tk.X, padx=5, pady=5)

        self.entry = tk.Entry(input_frame, font=("TkDefaultFont", 10))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", self._on_submit)
        
        # Focus the entry on start
        self.entry.focus_set()

        # Debug checkbox (right side)
        debug_checkbox = tk.Checkbutton(
            input_frame,
            text="Debug",
            variable=self.debug_mode,
            onvalue=True,
            offvalue=False,
        )
        debug_checkbox.pack(side=tk.RIGHT, padx=(5, 0))

        send_btn = tk.Button(input_frame, text="Send", command=self._on_submit)
        send_btn.pack(side=tk.RIGHT, padx=(5, 0))

    def _on_submit(self, event=None):
        """Handle user input submission."""
        text = self.entry.get().strip()
        if not text:
            return

        # Display user input
        self._append_text(f"You: {text}\n", "user")
        self.entry.delete(0, tk.END)

        try:
            # v0.9.0: Route through mode router instead of direct kernel call
            response = handle_user_message(
                message=text,
                state=self.state,
                kernel=self.kernel,
                persona=self.persona,
            )
            
            # Update title if mode changed
            self._update_title()
            
            # Render the response
            self._render_response(response)
            
        except Exception as e:
            # Show error in UI
            error_msg = f"Error: {str(e)}"
            self._append_text(f"{error_msg}\n\n", "error")
            
            if self.debug_mode.get():
                self._append_text(f"Traceback:\n{traceback.format_exc()}\n", "system")

    def _render_response(self, response: dict):
        """
        Render the response from the mode router.
        
        v0.9.0: Updated to handle mode router response format.
        """
        if not response:
            self._append_text("Nova: (no response)\n\n", "error")
            return
        
        # Check for mode change events
        event = response.get("event")
        if event == "boot":
            self._append_text("[NovaOS activated]\n", "mode")
        elif event == "shutdown":
            self._append_text("[NovaOS deactivated — Persona mode]\n", "mode")
        
        # Get the response text
        # Try multiple possible keys for compatibility
        text = self._extract_text(response)
        
        if text:
            self._append_text(f"Nova: {text}\n\n", "nova")
        elif response.get("error"):
            self._append_text(f"Error: {response.get('error')}\n\n", "error")
        else:
            self._append_text("Nova: (empty response)\n\n", "system")
        
        # Debug mode: show extra info
        if self.debug_mode.get():
            self._render_debug_info(response)

    def _extract_text(self, response: dict) -> str:
        """Extract text from response, handling various formats."""
        # Direct text field
        if response.get("text"):
            return response["text"]
        
        # Summary field (from syscommands)
        if response.get("summary"):
            return response["summary"]
        
        # Content dict with summary
        content = response.get("content")
        if isinstance(content, dict) and content.get("summary"):
            return content["summary"]
        
        # Data dict with summary
        data = response.get("data")
        if isinstance(data, dict) and data.get("summary"):
            return data["summary"]
        
        return ""

    def _render_debug_info(self, response: dict):
        """Render debug information about the response."""
        debug_lines = ["─── Debug ───"]
        
        # Mode info
        mode = response.get("mode", "unknown")
        handled_by = response.get("handled_by", "unknown")
        debug_lines.append(f"Mode: {mode} | Handled by: {handled_by}")
        
        # OK status
        ok = response.get("ok")
        if ok is not None:
            debug_lines.append(f"OK: {ok}")
        
        # Command info (if present)
        command = response.get("command")
        if command:
            debug_lines.append(f"Command: {command}")
        
        # Type info
        resp_type = response.get("type")
        if resp_type:
            debug_lines.append(f"Type: {resp_type}")
        
        # Extra data (if present)
        extra = response.get("data") or response.get("extra") or response.get("payload")
        if extra and isinstance(extra, dict):
            debug_lines.append("Data:")
            for key, value in list(extra.items())[:10]:  # Limit to 10 items
                # Truncate long values
                val_str = str(value)
                if len(val_str) > 80:
                    val_str = val_str[:80] + "..."
                debug_lines.append(f"  {key}: {val_str}")
        
        debug_lines.append("─────────────\n")
        self._append_text("\n".join(debug_lines) + "\n", "system")

    def _append_text(self, text: str, tag: str = None):
        """Append text to the output area with optional styling."""
        self.output.configure(state=tk.NORMAL)
        if tag:
            self.output.insert(tk.END, text, tag)
        else:
            self.output.insert(tk.END, text)
        self.output.configure(state=tk.DISABLED)
        self.output.see(tk.END)

    def run(self):
        """Start the application main loop."""
        # Show initial message
        if self.state.novaos_enabled:
            # v0.12.0: Show dashboard on launch if configured
            dashboard = get_auto_dashboard_on_launch(kernel=self.kernel, state=self.state)
            if dashboard:
                self._append_text(f"{dashboard}\n\n", "system")
            else:
                self._append_text("NovaOS is running. Type #help for commands.\n\n", "system")
        else:
            self._append_text(
                "Welcome! I'm Nova. We're in Persona mode — just us talking.\n"
                "Type #boot to activate NovaOS with all its features.\n\n",
                "system"
            )
        
        self.root.mainloop()


# ─────────────────────────────────────────────────────────────────────────────
# BACKWARD COMPATIBILITY
# ─────────────────────────────────────────────────────────────────────────────

def create_app_legacy(kernel, config):
    """
    Legacy factory for backward compatibility.
    
    If code calls NovaApp with just (kernel, config), this adapter
    creates the persona from the kernel's llm_client.
    """
    from persona.nova_persona import NovaPersona
    
    # Get LLM client from kernel
    llm_client = getattr(kernel, 'llm_client', None)
    if not llm_client:
        raise ValueError("Kernel must have llm_client for legacy mode")
    
    persona = NovaPersona(llm_client)
    return NovaApp(kernel=kernel, persona=persona, config=config)
