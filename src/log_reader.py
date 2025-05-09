import logging
import os
import re
import time # Make sure time is imported
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Dict, Callable, List
from collections import deque # import deque for cache
import hashlib # for hashing lines

# assuming eventbus is in the same directory or accessible via sys.path
from src.event_bus import EventBus

logger = logging.getLogger(__name__)

# regex patterns
# Updated chat regex to capture SteamID (Full Format)
# Example: *DEAD* Player Name<U:1:12345><Blue> : !command args
CHAT_REGEX_FULL = re.compile(r"^(?:\*?(?:DEAD|TEAM|SPEC)\*? )?(?P<user>.+?)<(?P<steamid>U:\d+:\d+)>(?:<(?P<team>Red|Blue|Spectator|Console)>)? : (?P<message>.+)$") # Made team tag optional
CHAT_REGEX_SIMPLE = re.compile(r"^(?P<user>[^:]+?) : (?P<message>.+)$") # Simple format: User : Message
# user killed otheruser with weapon. (crit)
KILL_REGEX = re.compile(r"^(?P<killer>.+?) killed (?P<victim>.+?) with (?P<weapon>.+?)\.(?: \(crit\))?$")
# user connected
CONNECT_REGEX = re.compile(r"^(?P<user>.+?) connected$") # simple version
# user suicided.
SUICIDE_REGEX = re.compile(r"^(?P<user>.+?) suicided\.$")

# define event names (constants)
EVENT_CHAT_RECEIVED = "chat_received"
EVENT_COMMAND_DETECTED = "command_detected"
EVENT_PLAYER_KILL = "player_kill"
EVENT_PLAYER_CONNECT = "player_connect"
EVENT_PLAYER_SUICIDE = "player_suicide"
EVENT_UNDEFINED_MESSAGE = "undefined_message"

class LogFileEventHandler(FileSystemEventHandler):
    """handles file system events for the console.log file."""

    def __init__(self, file_path: str, process_new_line: Callable[[str], None]):
        self._file_path = file_path
        self._process_new_line = process_new_line
        self._last_size = 0
        self._file = None
        self._open_file()
        logger.info(f"LogFileEventHandler initialized for: {self._file_path}")

    def _open_file(self):
        """opens the log file and seeks to the end."""
        try:
            # ensure directory exists (though it should if tf2 is running)
            os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
            # open file if it exists, create if not (tf2 might create it)
            self._file = open(self._file_path, 'a+', encoding='utf-8') # open in append+read mode
            self._file.seek(0, os.SEEK_END) # go to the end
            self._last_size = self._file.tell()
            logger.info(f"opened log file {self._file_path} and seeked to end (position {self._last_size}).")
        except IOError as e:
            logger.error(f"error opening log file {self._file_path}: {e}")
            self._file = None # ensure file is none if open fails

    def _read_new_lines(self):
        """reads new lines added to the file since the last check."""
        if not self._file or self._file.closed:
            logger.warning("log file is not open. attempting to reopen...")
            self._open_file()
            if not self._file: # still couldn't open
                return # skip reading attempt

        try:
            current_size = os.path.getsize(self._file_path)
            if current_size < self._last_size:
                # file was likely truncated or replaced (e.g., tf2 restart)
                logger.warning(f"log file {self._file_path} size decreased. assuming truncation/replacement. resetting position.")
                self._file.seek(0, os.SEEK_END) # seek to new end
            elif current_size > self._last_size:
                # read the new content
                self._file.seek(self._last_size)
                new_content = self._file.read(current_size - self._last_size)
                logger.debug(f"read {len(new_content)} bytes from log file.") # log bytes read
                if new_content:
                    # log the raw content read before splitting lines
                    logger.debug(f"raw content read:\n---\n{new_content}\n---")
                    lines = new_content.splitlines()
                    # --- Add small delay to potentially coalesce rapid events ---
                    time.sleep(0.1)
                    # -----------------------------------------------------------
                    for i, line in enumerate(lines):
                         if line: # avoid processing empty lines
                            logger.debug(f"processing line {i+1}/{len(lines)}: '{line}'") # log each line being processed
                            self._process_new_line(line)

            self._last_size = self._file.tell() # update position after reading/seeking

        except FileNotFoundError:
             logger.error(f"log file {self._file_path} not found during read attempt. it might have been deleted.")
             if self._file and not self._file.closed:
                 self._file.close()
             self._file = None # mark as closed
             # optionally try to reopen immediately or wait for on_created
        except IOError as e:
            logger.error(f"ioerror reading log file {self._file_path}: {e}")
        except Exception as e:
            logger.error(f"unexpected error reading log file {self._file_path}: {e}", exc_info=True)


    def on_modified(self, event):
        """called when a file or directory is modified."""
        if event.src_path == self._file_path:
            # logger.debug(f"modification detected for {self._file_path}")
            self._read_new_lines()

    def on_created(self, event):
        """called when a file or directory is created."""
        if event.src_path == self._file_path:
            logger.info(f"log file {self._file_path} created. opening and seeking to end.")
            if self._file and not self._file.closed:
                self._file.close() # close previous handle if any
            self._open_file() # open the new file

    def close(self):
        """closes the file handle."""
        if self._file and not self._file.closed:
            logger.info(f"closing log file handle for {self._file_path}")
            self._file.close()
            self._file = None


# define cache size constant here or make it configurable
RECENT_LINE_CACHE_SIZE = 10

class LogReader:
    """monitors and parses the tf2 console log file."""

    def __init__(self, config: Dict, event_bus: EventBus):
        self._config = config
        self._event_bus = event_bus
        self._observer = None
        self._event_handler = None
        self._monitor_thread = None
        self._stop_event = threading.Event()
        # cache for recent line hashes to prevent duplicates
        self._recent_lines_cache: deque[str] = deque(maxlen=RECENT_LINE_CACHE_SIZE)

        self._log_path = self._get_log_path()
        if not self._log_path:
            logger.error("logreader initialization failed: could not determine log path.")
            # consider raising an exception or setting an error state

    def _get_log_path(self) -> str | None:
        """constructs the full path to the console.log file."""
        game_dir = self._config.get("game_dir")
        log_file = self._config.get("log_file_name", "console.log") # default to console.log
        if not game_dir:
            logger.error("tf2 'game_dir' not specified in configuration.")
            return None
        if not os.path.isdir(game_dir):
             logger.error(f"configured 'game_dir' does not exist or is not a directory: {game_dir}")
             return None
        return os.path.join(game_dir, log_file)

    def _process_line(self, line: str):
        """parses a single line from the log and publishes events."""
        # --- duplicate check removed ---
        # ... (duplicate check code commented out as before) ...
        # --- end duplicate check ---

        # proceed with processing every line read
        logger.debug(f"processing line: {line}")

        # --- Try matching different chat formats ---
        user_info = None
        message = None

        # Variables to store extracted data
        raw_user_name = None
        steamid = None
        team = None
        # 1a. Try matching the full format (with SteamID)
        match_full = CHAT_REGEX_FULL.match(line)
        if match_full:
            user = (match_full.group('user') or "").strip()
            message = (match_full.group('message') or "").strip()
            steamid = match_full.group('steamid')
            team = match_full.group('team') # Might be None if optional part didn't match
            raw_user_name = user # Store potentially tagged name

        # 1b. If full format didn't match, try simple format
        else: # No need for elif not user_info, just try simple if full failed
            match_simple = CHAT_REGEX_SIMPLE.match(line)
            if match_simple:
                user = (match_simple.group('user') or "").strip()
                message = (match_simple.group('message') or "").strip()
                raw_user_name = user # Store potentially tagged name
                steamid = None # No steamid in simple format
                team = None    # No team in simple format

        # --- If any chat format matched, clean username and create user_info ---
        if raw_user_name is not None and message is not None:
            # Apply tag stripping to raw_user_name
            user_name = raw_user_name # Start with raw name for stripping
            stripped_tags = [] # Store potentially multiple tags
            possible_tags = ["*DEAD*", "*TEAM*", "[TEAM]", "*SPEC*", "[SPEC]", "[DEAD]"]
            logger.debug(f"Starting tag stripping for raw name: '{user_name}'") # Debug log before loop

            # --- Loop to strip multiple tags ---
            while True:
                tag_found_in_pass = False
                current_name_before_pass = user_name # Store name before inner loop
                for tag in possible_tags:
                    # Check for tag with space
                    if user_name.startswith(tag + " "):
                        stripped_tags.append(tag)
                        user_name = user_name[len(tag)+1:].strip()
                        logger.debug(f"Stripped tag '{tag} ', remaining: '{user_name}'") # Debug log inside loop
                        tag_found_in_pass = True
                        break # Restart tag check from beginning with stripped name
                    # Check for tag without space (less common but possible)
                    elif user_name.startswith(tag):
                         stripped_tags.append(tag)
                         user_name = user_name[len(tag):].strip()
                         logger.debug(f"Stripped tag '{tag}', remaining: '{user_name}'") # Debug log inside loop
                         tag_found_in_pass = True
                         break # Restart tag check from beginning with stripped name

                # If no tag was found in this pass, exit the while loop
                if not tag_found_in_pass:
                    break
                # Safety break: If stripping didn't change the name, exit to prevent infinite loop
                if user_name == current_name_before_pass:
                    logger.warning(f"Tag stripping loop encountered potential infinite loop for '{raw_user_name}'. Breaking.")
                    break
            # --- End loop ---
            logger.debug(f"Finished tag stripping. Final name: '{user_name}', Tags: {stripped_tags}") # Debug log after loop

            if not user_name: # Safety check after stripping
                logger.warning(f"Could not extract final user name after stripping tags from: {raw_user_name}")
                return # Cannot proceed without a username

            # Create the final user_info dict
            # Join tags if needed, or just use the list, or the last one found
            final_tags = " ".join(stripped_tags) if stripped_tags else None
            user_info = {"name": user_name, "steamid": steamid, "tags": final_tags, "team": team}

        # --- Process if a chat format matched ---
        if user_info and message is not None:
            if message.startswith("!") and len(message) > 1:
                # Command detected
                parts = message.split(maxsplit=1)
                command = parts[0]
                args_str = parts[1].strip() if len(parts) > 1 else "" # strip args string too
                args_list = args_str.split() # simple space splitting for now
                logger.info(f"Command detected: user={user_info['name']}, command={command}, args={args_list}")
                logger.debug(f"publishing event_command_detected with user_info: {user_info}")
                self._event_bus.publish(EVENT_COMMAND_DETECTED, user=user_info, command=command, args=args_list)
            else:
                # Regular chat message
                 logger.info(f"Chat received: user={user_info['name']}, message='{message}'")
                 self._event_bus.publish(EVENT_CHAT_RECEIVED, user=user_info, message=message)
            return # line processed

        # --- If no chat format matched, check other patterns ---
        kill_match = KILL_REGEX.match(line)
        if kill_match:
            kill_data = kill_match.groupdict()
            logger.info(f"kill detected: {kill_data['killer']} killed {kill_data['victim']} with {kill_data['weapon']}")
            self._event_bus.publish(EVENT_PLAYER_KILL, killer=kill_data['killer'], victim=kill_data['victim'], weapon=kill_data['weapon'])
            return

        # add checks for connect_regex, suicide_regex etc. here...

        # if no specific pattern matched
        logger.debug(f"undefined message: {line}")
        self._event_bus.publish(EVENT_UNDEFINED_MESSAGE, message=line)


    def start_monitoring(self) -> threading.Thread | None:
        """
        Starts monitoring the log file in a separate thread.

        Returns:
            The monitoring thread object if started successfully, None otherwise.
        """
        if not self._log_path:
            logger.error("cannot start monitoring: log path is not configured correctly.")
            return None

        if self._observer and self._observer.is_alive():
            logger.warning("monitoring is already active.")
            return self._monitor_thread # Return existing thread if already running

        self._stop_event.clear()
        self._event_handler = LogFileEventHandler(self._log_path, self._process_line)
        self._observer = Observer()
        # watch the directory containing the file, as file modifications might
        # be detected more reliably this way, especially across different os/editors.
        watch_dir = os.path.dirname(self._log_path)
        self._observer.schedule(self._event_handler, watch_dir, recursive=False)

        # start observer in a background thread
        self._monitor_thread = threading.Thread(target=self._run_observer, daemon=True, name="LogReaderMonitorThread") # Give thread a name
        self._monitor_thread.start()
        logger.info(f"started monitoring log file: {self._log_path}")
        return self._monitor_thread # Return the newly created thread

    def _run_observer(self):
        """internal method to run the observer loop and add polling."""
        self._observer.start()
        logger.debug("watchdog observer started.")
        polling_interval = 2 # check file every 2 seconds as a fallback

        try:
            while not self._stop_event.is_set():
                # --- polling check ---
                # periodically check for new lines, even if no event was received.
                # the _read_new_lines method handles checking size and avoids re-reading.
                try:
                    if self._event_handler: # ensure handler exists
                        self._event_handler._read_new_lines()
                except Exception as e:
                     logger.error(f"error during periodic log poll check: {e}", exc_info=True)

                # --- wait ---
                # wait for the polling interval or until stop event is set
                self._stop_event.wait(timeout=polling_interval)

        except Exception as e:
            logger.error(f"error in observer/polling control thread: {e}", exc_info=True)
        finally:
            if self._observer.is_alive():
                self._observer.stop()
            self._observer.join() # wait for observer thread to finish
            if self._event_handler:
                self._event_handler.close() # close the file handle
            logger.debug("watchdog observer stopped.")


    def stop_monitoring(self):
        """stops monitoring the log file."""
        if self._observer and self._observer.is_alive():
            logger.info("stopping log file monitoring...")
            self._stop_event.set() # signal the observer loop to exit
            # observer stopping and joining happens in _run_observer finally block
            if self._monitor_thread:
                 self._monitor_thread.join(timeout=5) # wait for thread to finish
                 if self._monitor_thread.is_alive():
                     logger.warning("monitoring thread did not stop gracefully.")
            logger.info("log file monitoring stopped.")
        else:
            logger.info("log file monitoring was not active.")

# example usage (can be removed or kept for testing)
if __name__ == '__main__':
    # set up basic logging and event bus for testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    test_bus = EventBus()

    # dummy handlers
    def handle_cmd(user, command, args): print(f"command: user={user['name']}, cmd={command}, args={args}")
    def handle_chat(user, message): print(f"chat: user={user['name']}, msg='{message}'")
    def handle_kill(killer, victim, weapon): print(f"kill: {killer} killed {victim} with {weapon}")
    def handle_other(message): print(f"other: {message}")

    test_bus.subscribe(EVENT_COMMAND_DETECTED, handle_cmd)
    test_bus.subscribe(EVENT_CHAT_RECEIVED, handle_chat)
    test_bus.subscribe(EVENT_PLAYER_KILL, handle_kill)
    test_bus.subscribe(EVENT_UNDEFINED_MESSAGE, handle_other)

    # create a dummy config and log file for testing
    TEST_DIR = "temp_test_tf2_log"
    TEST_LOG_FILE = os.path.join(TEST_DIR, "console.log")
    if not os.path.exists(TEST_DIR): os.makedirs(TEST_DIR)
    # clear or create the log file
    with open(TEST_LOG_FILE, "w") as f: f.write("")

    test_config = {"game_dir": TEST_DIR, "log_file_name": "console.log"}

    # initialize and start reader
    reader = LogReader(test_config, test_bus)
    reader.start_monitoring()

    print(f"monitoring {TEST_LOG_FILE}. append lines to test (e.g., using another terminal or script). press ctrl+c to stop.")
    print("examples to append:")
    print('echo "testuser : hello there!" >> temp_test_tf2_log/console.log')
    print('echo "testuser : !play some song" >> temp_test_tf2_log/console.log')
    print('echo "player1 killed player2 with scattergun." >> temp_test_tf2_log/console.log')
    print('echo "this is some other log line" >> temp_test_tf2_log/console.log')


    try:
        # keep main thread alive for testing
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping test...")
    finally:
        reader.stop_monitoring()
        # clean up dummy file/dir
        # import shutil
        # if os.path.exists(test_dir): shutil.rmtree(test_dir)
        print("test finished.")
