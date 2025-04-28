import logging
import os
import re
import time
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
# fifth attempt at chat_regex: match optional tag+space non-capturing, capture user after
CHAT_REGEX = re.compile(r"^(?:\*?(?:DEAD|TEAM|SPEC)\*? )?(?P<user>.+?) : (?P<message>.+)$")
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
        # the duplicate check was preventing repeated identical commands.
        # removing it to allow commands like !skip to be used consecutively.
        # try:
        #     line_hash = hashlib.sha1(line.encode('utf-8', errors='ignore')).hexdigest()
        #     if line_hash in self._recent_lines_cache:
        #         # logger.debug(f"skipping duplicate line: {line}") # can be noisy
        #         return # skip processing this duplicate line
        #     # add new hash to cache (deque automatically handles max size)
        #     self._recent_lines_cache.append(line_hash)
        # except exception as e:
        #     # log error during hashing/cache check but proceed with processing anyway
        #     logger.error(f"error during duplicate line check for '{line}': {e}", exc_info=true)
        # --- end duplicate check ---

        # proceed with processing every line read
        logger.debug(f"processing line: {line}")

        # 1. check for chat/commands
        chat_match = CHAT_REGEX.match(line)
        if chat_match:
            # extract user and message directly
            user = (chat_match.group('user') or "").strip()
            message = (chat_match.group('message') or "").strip()

            # determine tag separately by checking start of original line
            tags = None
            user_name = user # start with the potentially tagged name from regex group
            tag_prefix = None
            # add more variations if needed (e.g., no asterisk, different brackets)
            if line.startswith("*DEAD* "): tag_prefix = "*DEAD* "
            elif line.startswith("*TEAM* "): tag_prefix = "*TEAM* "
            elif line.startswith("[TEAM] "): tag_prefix = "[TEAM] " # handle brackets
            elif line.startswith("*SPEC* "): tag_prefix = "*SPEC* "
            elif line.startswith("[SPEC] "): tag_prefix = "[SPEC] " # handle brackets
            elif line.startswith("[DEAD] "): tag_prefix = "[DEAD] " # handle brackets

            if tag_prefix:
                tags = tag_prefix.strip() # store the tag without trailing space
                # remove the prefix from the start of the user name
                if user_name.startswith(tag_prefix):
                     user_name = user_name[len(tag_prefix):].strip()
                else:
                     # fallback if space wasn't captured correctly (shouldn't happen often)
                     logger.warning(f"tag prefix '{tag_prefix}' detected but not found at start of user '{user}'. stripping tag only.")
                     # use the detected tag (without space) for removal attempt
                     user_name = user_name.replace(tags, "").strip()

            if not user_name: # safety check after potential removal
                 logger.warning(f"could not extract final user name from chat line: {line}")
                 return

            # check if it's a command (using the stripped message)
            if message.startswith("!") and len(message) > 1:
                parts = message.split(maxsplit=1)
                command = parts[0]
                args_str = parts[1].strip() if len(parts) > 1 else "" # strip args string too
                args_list = args_str.split() # simple space splitting for now

                # use the cleaned user_name
                user_info = {"name": user_name, "tags": tags}

                logger.info(f"command detected: user={user_name}, command={command}, args={args_list}") # log cleaned name
                logger.debug(f"publishing event_command_detected with user_info: {user_info}")
                self._event_bus.publish(EVENT_COMMAND_DETECTED, user=user_info, command=command, args=args_list)
            else:
                # regular chat message
                 # use the cleaned user_name here too
                 user_info = {"name": user_name, "tags": tags}
                 logger.info(f"chat received: user={user_name}, message='{message}'") # log cleaned name
                 self._event_bus.publish(EVENT_CHAT_RECEIVED, user=user_info, message=message)
            return # line processed

        # 2. check for kills (add other regex checks similarly)
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


    def start_monitoring(self):
        """starts monitoring the log file in a separate thread."""
        if not self._log_path:
            logger.error("cannot start monitoring: log path is not configured correctly.")
            return

        if self._observer and self._observer.is_alive():
            logger.warning("monitoring is already active.")
            return

        self._stop_event.clear()
        self._event_handler = LogFileEventHandler(self._log_path, self._process_line)
        self._observer = Observer()
        # watch the directory containing the file, as file modifications might
        # be detected more reliably this way, especially across different os/editors.
        watch_dir = os.path.dirname(self._log_path)
        self._observer.schedule(self._event_handler, watch_dir, recursive=False)

        # start observer in a background thread
        self._monitor_thread = threading.Thread(target=self._run_observer, daemon=True)
        self._monitor_thread.start()
        logger.info(f"started monitoring log file: {self._log_path}")

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
