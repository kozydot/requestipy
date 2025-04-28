import logging
import os
import re
import time
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Dict, Callable, List
from collections import deque # Import deque for cache
import hashlib # For hashing lines

# Assuming EventBus is in the same directory or accessible via sys.path
from src.event_bus import EventBus

logger = logging.getLogger(__name__)

# Regex patterns
# Fifth attempt at CHAT_REGEX: Match optional tag+space non-capturing, capture user after
CHAT_REGEX = re.compile(r"^(?:\*?(?:DEAD|TEAM|SPEC)\*? )?(?P<user>.+?) : (?P<message>.+)$")
# User killed OtherUser with weapon. (crit)
KILL_REGEX = re.compile(r"^(?P<killer>.+?) killed (?P<victim>.+?) with (?P<weapon>.+?)\.(?: \(crit\))?$")
# User connected
CONNECT_REGEX = re.compile(r"^(?P<user>.+?) connected$") # Simple version
# User suicided.
SUICIDE_REGEX = re.compile(r"^(?P<user>.+?) suicided\.$")

# Define event names (constants)
EVENT_CHAT_RECEIVED = "chat_received"
EVENT_COMMAND_DETECTED = "command_detected"
EVENT_PLAYER_KILL = "player_kill"
EVENT_PLAYER_CONNECT = "player_connect"
EVENT_PLAYER_SUICIDE = "player_suicide"
EVENT_UNDEFINED_MESSAGE = "undefined_message"

class LogFileEventHandler(FileSystemEventHandler):
    """Handles file system events for the console.log file."""

    def __init__(self, file_path: str, process_new_line: Callable[[str], None]):
        self._file_path = file_path
        self._process_new_line = process_new_line
        self._last_size = 0
        self._file = None
        self._open_file()
        logger.info(f"LogFileEventHandler initialized for: {self._file_path}")

    def _open_file(self):
        """Opens the log file and seeks to the end."""
        try:
            # Ensure directory exists (though it should if TF2 is running)
            os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
            # Open file if it exists, create if not (TF2 might create it)
            self._file = open(self._file_path, 'a+', encoding='utf-8') # Open in append+read mode
            self._file.seek(0, os.SEEK_END) # Go to the end
            self._last_size = self._file.tell()
            logger.info(f"Opened log file {self._file_path} and seeked to end (position {self._last_size}).")
        except IOError as e:
            logger.error(f"Error opening log file {self._file_path}: {e}")
            self._file = None # Ensure file is None if open fails

    def _read_new_lines(self):
        """Reads new lines added to the file since the last check."""
        if not self._file or self._file.closed:
            logger.warning("Log file is not open. Attempting to reopen...")
            self._open_file()
            if not self._file: # Still couldn't open
                return # Skip reading attempt

        try:
            current_size = os.path.getsize(self._file_path)
            if current_size < self._last_size:
                # File was likely truncated or replaced (e.g., TF2 restart)
                logger.warning(f"Log file {self._file_path} size decreased. Assuming truncation/replacement. Resetting position.")
                self._file.seek(0, os.SEEK_END) # Seek to new end
            elif current_size > self._last_size:
                # Read the new content
                self._file.seek(self._last_size)
                new_content = self._file.read(current_size - self._last_size)
                logger.debug(f"Read {len(new_content)} bytes from log file.") # Log bytes read
                if new_content:
                    # Log the raw content read before splitting lines
                    logger.debug(f"Raw content read:\n---\n{new_content}\n---")
                    lines = new_content.splitlines()
                    for i, line in enumerate(lines):
                         if line: # Avoid processing empty lines
                            logger.debug(f"Processing line {i+1}/{len(lines)}: '{line}'") # Log each line being processed
                            self._process_new_line(line)

            self._last_size = self._file.tell() # Update position after reading/seeking

        except FileNotFoundError:
             logger.error(f"Log file {self._file_path} not found during read attempt. It might have been deleted.")
             if self._file and not self._file.closed:
                 self._file.close()
             self._file = None # Mark as closed
             # Optionally try to reopen immediately or wait for on_created
        except IOError as e:
            logger.error(f"IOError reading log file {self._file_path}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error reading log file {self._file_path}: {e}", exc_info=True)


    def on_modified(self, event):
        """Called when a file or directory is modified."""
        if event.src_path == self._file_path:
            # logger.debug(f"Modification detected for {self._file_path}")
            self._read_new_lines()

    def on_created(self, event):
        """Called when a file or directory is created."""
        if event.src_path == self._file_path:
            logger.info(f"Log file {self._file_path} created. Opening and seeking to end.")
            if self._file and not self._file.closed:
                self._file.close() # Close previous handle if any
            self._open_file() # Open the new file

    def close(self):
        """Closes the file handle."""
        if self._file and not self._file.closed:
            logger.info(f"Closing log file handle for {self._file_path}")
            self._file.close()
            self._file = None


# Define cache size constant here or make it configurable
RECENT_LINE_CACHE_SIZE = 10

class LogReader:
    """Monitors and parses the TF2 console log file."""

    def __init__(self, config: Dict, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._observer = None
        self._event_handler = None
        self._monitor_thread = None
        self._stop_event = threading.Event()
        # Cache for recent line hashes to prevent duplicates
        self._recent_lines_cache: deque[str] = deque(maxlen=RECENT_LINE_CACHE_SIZE)

        self._log_path = self._get_log_path()
        if not self._log_path:
            logger.error("LogReader initialization failed: Could not determine log path.")
            # Consider raising an exception or setting an error state

    def _get_log_path(self) -> str | None:
        """Constructs the full path to the console.log file."""
        game_dir = self._config.get("game_dir")
        log_file = self._config.get("log_file_name", "console.log") # Default to console.log
        if not game_dir:
            logger.error("TF2 'game_dir' not specified in configuration.")
            return None
        if not os.path.isdir(game_dir):
             logger.error(f"Configured 'game_dir' does not exist or is not a directory: {game_dir}")
             return None
        return os.path.join(game_dir, log_file)

    def _process_line(self, line: str):
        """Parses a single line from the log and publishes events."""
        # --- Duplicate Check Removed ---
        # The duplicate check was preventing repeated identical commands.
        # Removing it to allow commands like !skip to be used consecutively.
        # try:
        #     line_hash = hashlib.sha1(line.encode('utf-8', errors='ignore')).hexdigest()
        #     if line_hash in self._recent_lines_cache:
        #         # logger.debug(f"Skipping duplicate line: {line}") # Can be noisy
        #         return # Skip processing this duplicate line
        #     # Add new hash to cache (deque automatically handles max size)
        #     self._recent_lines_cache.append(line_hash)
        # except Exception as e:
        #     # Log error during hashing/cache check but proceed with processing anyway
        #     logger.error(f"Error during duplicate line check for '{line}': {e}", exc_info=True)
        # --- End Duplicate Check ---

        # Proceed with processing every line read
        logger.debug(f"Processing line: {line}")

        # 1. Check for Chat/Commands
        chat_match = CHAT_REGEX.match(line)
        if chat_match:
            # Extract user and message directly
            user = (chat_match.group('user') or "").strip()
            message = (chat_match.group('message') or "").strip()

            # Determine tag separately by checking start of original line
            tags = None
            user_name = user # Start with the potentially tagged name from regex group
            tag_prefix = None
            # Add more variations if needed (e.g., no asterisk, different brackets)
            if line.startswith("*DEAD* "): tag_prefix = "*DEAD* "
            elif line.startswith("*TEAM* "): tag_prefix = "*TEAM* "
            elif line.startswith("[TEAM] "): tag_prefix = "[TEAM] " # Handle brackets
            elif line.startswith("*SPEC* "): tag_prefix = "*SPEC* "
            elif line.startswith("[SPEC] "): tag_prefix = "[SPEC] " # Handle brackets
            elif line.startswith("[DEAD] "): tag_prefix = "[DEAD] " # Handle brackets

            if tag_prefix:
                tags = tag_prefix.strip() # Store the tag without trailing space
                # Remove the prefix from the start of the user name
                if user_name.startswith(tag_prefix):
                     user_name = user_name[len(tag_prefix):].strip()
                else:
                     # Fallback if space wasn't captured correctly (shouldn't happen often)
                     logger.warning(f"Tag prefix '{tag_prefix}' detected but not found at start of user '{user}'. Stripping tag only.")
                     # Use the detected tag (without space) for removal attempt
                     user_name = user_name.replace(tags, "").strip()

            if not user_name: # Safety check after potential removal
                 logger.warning(f"Could not extract final user name from chat line: {line}")
                 return

            # Check if it's a command (using the stripped message)
            if message.startswith("!") and len(message) > 1:
                parts = message.split(maxsplit=1)
                command = parts[0]
                args_str = parts[1].strip() if len(parts) > 1 else "" # Strip args string too
                args_list = args_str.split() # Simple space splitting for now

                # Use the cleaned user_name
                user_info = {"name": user_name, "tags": tags}

                logger.info(f"Command detected: User={user_name}, Command={command}, Args={args_list}") # Log cleaned name
                logger.debug(f"Publishing EVENT_COMMAND_DETECTED with user_info: {user_info}")
                self._event_bus.publish(EVENT_COMMAND_DETECTED, user=user_info, command=command, args=args_list)
            else:
                # Regular chat message
                 # Use the cleaned user_name here too
                 user_info = {"name": user_name, "tags": tags}
                 logger.info(f"Chat received: User={user_name}, Message='{message}'") # Log cleaned name
                 self._event_bus.publish(EVENT_CHAT_RECEIVED, user=user_info, message=message)
            return # Line processed

        # 2. Check for Kills (add other regex checks similarly)
        kill_match = KILL_REGEX.match(line)
        if kill_match:
            kill_data = kill_match.groupdict()
            logger.info(f"Kill detected: {kill_data['killer']} killed {kill_data['victim']} with {kill_data['weapon']}")
            self._event_bus.publish(EVENT_PLAYER_KILL, killer=kill_data['killer'], victim=kill_data['victim'], weapon=kill_data['weapon'])
            return

        # Add checks for CONNECT_REGEX, SUICIDE_REGEX etc. here...

        # If no specific pattern matched
        logger.debug(f"Undefined message: {line}")
        self._event_bus.publish(EVENT_UNDEFINED_MESSAGE, message=line)


    def start_monitoring(self):
        """Starts monitoring the log file in a separate thread."""
        if not self._log_path:
            logger.error("Cannot start monitoring: Log path is not configured correctly.")
            return

        if self._observer and self._observer.is_alive():
            logger.warning("Monitoring is already active.")
            return

        self._stop_event.clear()
        self._event_handler = LogFileEventHandler(self._log_path, self._process_line)
        self._observer = Observer()
        # Watch the directory containing the file, as file modifications might
        # be detected more reliably this way, especially across different OS/editors.
        watch_dir = os.path.dirname(self._log_path)
        self._observer.schedule(self._event_handler, watch_dir, recursive=False)

        # Start observer in a background thread
        self._monitor_thread = threading.Thread(target=self._run_observer, daemon=True)
        self._monitor_thread.start()
        logger.info(f"Started monitoring log file: {self._log_path}")

    def _run_observer(self):
        """Internal method to run the observer loop and add polling."""
        self._observer.start()
        logger.debug("Watchdog observer started.")
        polling_interval = 2 # Check file every 2 seconds as a fallback

        try:
            while not self._stop_event.is_set():
                # --- Polling Check ---
                # Periodically check for new lines, even if no event was received.
                # The _read_new_lines method handles checking size and avoids re-reading.
                try:
                    if self._event_handler: # Ensure handler exists
                        self._event_handler._read_new_lines()
                except Exception as e:
                     logger.error(f"Error during periodic log poll check: {e}", exc_info=True)

                # --- Wait ---
                # Wait for the polling interval or until stop event is set
                self._stop_event.wait(timeout=polling_interval)

        except Exception as e:
            logger.error(f"Error in observer/polling control thread: {e}", exc_info=True)
        finally:
            if self._observer.is_alive():
                self._observer.stop()
            self._observer.join() # Wait for observer thread to finish
            if self._event_handler:
                self._event_handler.close() # Close the file handle
            logger.debug("Watchdog observer stopped.")


    def stop_monitoring(self):
        """Stops monitoring the log file."""
        if self._observer and self._observer.is_alive():
            logger.info("Stopping log file monitoring...")
            self._stop_event.set() # Signal the observer loop to exit
            # Observer stopping and joining happens in _run_observer finally block
            if self._monitor_thread:
                 self._monitor_thread.join(timeout=5) # Wait for thread to finish
                 if self._monitor_thread.is_alive():
                     logger.warning("Monitoring thread did not stop gracefully.")
            logger.info("Log file monitoring stopped.")
        else:
            logger.info("Log file monitoring was not active.")

# Example usage (can be removed or kept for testing)
if __name__ == '__main__':
    # Set up basic logging and event bus for testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    test_bus = EventBus()

    # Dummy handlers
    def handle_cmd(user, command, args): print(f"COMMAND: User={user['name']}, Cmd={command}, Args={args}")
    def handle_chat(user, message): print(f"CHAT: User={user['name']}, Msg='{message}'")
    def handle_kill(killer, victim, weapon): print(f"KILL: {killer} killed {victim} with {weapon}")
    def handle_other(message): print(f"OTHER: {message}")

    test_bus.subscribe(EVENT_COMMAND_DETECTED, handle_cmd)
    test_bus.subscribe(EVENT_CHAT_RECEIVED, handle_chat)
    test_bus.subscribe(EVENT_PLAYER_KILL, handle_kill)
    test_bus.subscribe(EVENT_UNDEFINED_MESSAGE, handle_other)

    # Create a dummy config and log file for testing
    TEST_DIR = "temp_test_tf2_log"
    TEST_LOG_FILE = os.path.join(TEST_DIR, "console.log")
    if not os.path.exists(TEST_DIR): os.makedirs(TEST_DIR)
    # Clear or create the log file
    with open(TEST_LOG_FILE, "w") as f: f.write("")

    test_config = {"game_dir": TEST_DIR, "log_file_name": "console.log"}

    # Initialize and start reader
    reader = LogReader(test_config, test_bus)
    reader.start_monitoring()

    print(f"Monitoring {TEST_LOG_FILE}. Append lines to test (e.g., using another terminal or script). Press Ctrl+C to stop.")
    print("Examples to append:")
    print('echo "TestUser : Hello there!" >> temp_test_tf2_log/console.log')
    print('echo "TestUser : !play some song" >> temp_test_tf2_log/console.log')
    print('echo "Player1 killed Player2 with scattergun." >> temp_test_tf2_log/console.log')
    print('echo "This is some other log line" >> temp_test_tf2_log/console.log')


    try:
        # Keep main thread alive for testing
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping test...")
    finally:
        reader.stop_monitoring()
        # Clean up dummy file/dir
        # import shutil
        # if os.path.exists(TEST_DIR): shutil.rmtree(TEST_DIR)
        print("Test finished.")
