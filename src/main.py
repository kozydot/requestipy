import sys
import os
import time
import logging

# Add project root to path for easier imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from src.config import load_config
from src.logger import setup_logging
from src.event_bus import EventBus
from src.log_reader import LogReader
from src.command_manager import CommandManager
from src.executor import Executor
from src.audio_player import AudioPlayer
from src.plugin_manager import PluginManager
import src.core_commands as core_commands # Import the core commands module



def main():
    """Main function to initialize and run RequestifyPy."""
    # Load configuration first
    config = load_config()
    if not config:
        print("ERROR: Failed to load configuration. Exiting.")
        sys.exit(1)

    # Setup logging based on config
    setup_logging(config.get('log_level', 'INFO')) # Default to INFO if not set

    logging.info("Starting RequestifyPy...")
    logging.info("Configuration loaded.")

    # Initialize core components
    event_bus = EventBus()
    log_reader = LogReader(config, event_bus)
    command_manager = CommandManager(event_bus)
    executor = Executor(config, command_manager, event_bus) # Pass config too
    audio_player = AudioPlayer(config, event_bus) # Pass config and event_bus
    plugin_manager = PluginManager(command_manager, event_bus) # Uses default 'plugins' dir

    # Register core commands
    core_commands.register(command_manager, audio_player)
    logging.info("Core commands registered.")

    # Load plugins (after core commands are registered)
    plugin_manager.load_plugins()
    logging.info("Plugins loaded.")

    # Start log monitoring
    log_reader.start_monitoring()
    logging.info("Log monitoring started.")

    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down RequestifyPy...")
        # Add shutdown logic (in reverse order of startup if dependencies exist)
        log_reader.stop_monitoring()
        audio_player.shutdown()
        plugin_manager.unload_plugins() # Call unload for plugins
        # core_commands.unregister(command_manager) # Optional: Unregister core commands if needed
        # executor.shutdown() # Executor currently doesn't require explicit shutdown
        print("RequestifyPy stopped.")

if __name__ == "__main__":
    main()