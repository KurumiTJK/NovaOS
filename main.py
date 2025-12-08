# main.py
"""
NovaOS Desktop Entry Point — v0.9.0

Now uses the dual-mode architecture:
- Default: Persona mode (pure conversation)
- After #boot: NovaOS mode (kernel + modules)
- After #shutdown: Back to Persona mode
"""

from system.config import Config
from kernel.nova_kernel import NovaKernel
from backend.llm_client import LLMClient
from persona.nova_persona import NovaPersona
from ui.nova_ui import NovaApp


def main():
    # Load configuration
    config = Config.load()

    # Initialize shared LLM client
    llm_client = LLMClient()

    # Initialize kernel (for NovaOS mode)
    kernel = NovaKernel(config=config, llm_client=llm_client)

    # Initialize persona (for both modes)
    persona = NovaPersona(llm_client)

    # Initialize and start UI with all components
    app = NovaApp(
        kernel=kernel,
        persona=persona,
        config=config,
    )
    app.run()


if __name__ == "__main__":
    main()
