import sys
import os
import time
import logging

# add project root to path so we can import stuff easier
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
import src.core_commands as core_commands # import our basic commands



def main():
    """main function to initialize and run requestipy."""
    # load the config file first, kinda important
    config = load_config()
    if not config:
        print("error: failed to load configuration. exiting.")
        sys.exit(1)

    # set up logging using the config settings
    setup_logging(config.get('log_level', 'INFO')) # default to info level if it's not in the config

    logging.info("starting requestipy...")
    logging.info("configuration loaded.")

    # get the main parts ready
    event_bus = EventBus()
    log_reader = LogReader(config, event_bus)
    command_manager = CommandManager(event_bus)
    executor = Executor(config, command_manager, event_bus) # executor needs the config too
    audio_player = AudioPlayer(config, event_bus) # audio player needs config and the event bus
    plugin_manager = PluginManager(command_manager, event_bus) # uses the default 'plugins' folder

    # register the basic commands
    core_commands.register(command_manager, audio_player)
    logging.info("core commands registered.")

    # load plugins after the basic commands are ready
    plugin_manager.load_plugins()
    logging.info("plugins loaded.")

    # start watching the log file
    log_reader.start_monitoring()
    logging.info("log monitoring started.")

    # keep the main script running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("shutting down requestipy...")
        # shut things down nicely, kinda in reverse order of startup
        log_reader.stop_monitoring()
        audio_player.shutdown()
        plugin_manager.unload_plugins() # unload the plugins
        # core_commands.unregister(command_manager) # optional: unregister basic commands if we need to
        # executor.shutdown() # executor doesn't need a special shutdown right now
        print("requestipy stopped.")

if __name__ == "__main__":
    main()