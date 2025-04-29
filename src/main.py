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
from src.core_commands import TEMP_DOWNLOAD_DIR # Import the temp dir path
from src.log_reader import LogReader
from src.command_manager import CommandManager
from src.executor import Executor
from src.audio_player import AudioPlayer
from src.plugin_manager import PluginManager
import src.core_commands as core_commands # import our basic commands

logger = logging.getLogger(__name__) # Define logger at module level
def cleanup_temp_folder():
    """Removes all files and subdirectories within the TEMP_DOWNLOAD_DIR."""
    logger.info(f"Attempting to clean up temporary folder: {TEMP_DOWNLOAD_DIR}")
    if not os.path.exists(TEMP_DOWNLOAD_DIR):
        logger.info("Temporary folder does not exist, nothing to clean.")
        return

    cleaned_count = 0
    error_count = 0
    for item_name in os.listdir(TEMP_DOWNLOAD_DIR):
        item_path = os.path.join(TEMP_DOWNLOAD_DIR, item_name)
        try:
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path) # Remove file or link
                logger.debug(f"Removed temp file: {item_path}")
                cleaned_count += 1
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path) # Remove directory and all its contents
                logger.debug(f"Removed temp directory: {item_path}")
                cleaned_count += 1
        except Exception as e:
            logger.error(f"Failed to remove temporary item {item_path}: {e}")
            error_count += 1

    if error_count == 0 and cleaned_count > 0:
        logger.info(f"Successfully cleaned {cleaned_count} items from temporary folder.")
    elif cleaned_count == 0 and error_count == 0:
         logger.info("Temporary folder was already empty.")
    else:
        logger.warning(f"Cleaned {cleaned_count} items, but failed to remove {error_count} items from temporary folder.")


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
        logging.info("Received shutdown signal (KeyboardInterrupt)...")
    finally:
        # --- Shutdown Sequence ---
        logging.info("Starting shutdown sequence...")
        # shut things down nicely, kinda in reverse order of startup
        if 'log_reader' in locals() and log_reader:
            log_reader.stop_monitoring()
        if 'audio_player' in locals() and audio_player:
            audio_player.shutdown()
        if 'plugin_manager' in locals() and plugin_manager:
            plugin_manager.unload_plugins() # unload the plugins
        # core_commands.unregister(command_manager) # optional: unregister basic commands if we need to
        # executor.shutdown() # executor doesn't need a special shutdown right now

        # --- Cleanup Temp Folder ---
        cleanup_temp_folder()

        logging.info("Requestipy shutdown complete.")
        print("Requestipy stopped.")


if __name__ == "__main__":
    main()