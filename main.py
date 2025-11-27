# main.py
from system.config import Config
from kernel.nova_kernel import NovaKernel
from ui.nova_ui import NovaApp

def main():
    # Load configuration
    config = Config.load()

    # Initialize kernel
    kernel = NovaKernel(config=config)

    # Initialize and start UI
    app = NovaApp(kernel=kernel, config=config)
    app.run()

if __name__ == "__main__":
    main()
