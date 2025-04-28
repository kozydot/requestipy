import logging
import sys
from collections import deque # import deque
import hashlib # import hashlib

LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s' # add log_format back
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# --- duplicate log filter ---
# cache size for duplicate detection
DUPLICATE_CACHE_SIZE = 10 # how many recent messages to remember

class DuplicateFilter(logging.Filter):
    """filters out log records identical to the last one within the cache size."""
    def __init__(self, name=""):
        super().__init__(name)
        self._cache: deque[str] = deque(maxlen=DUPLICATE_CACHE_SIZE)

    def filter(self, record):
        # create a hash based on level and message content
        log_string = f"{record.levelno}-{record.msg}"
        log_hash = hashlib.sha1(log_string.encode()).hexdigest()

        is_duplicate = log_hash in self._cache
        if not is_duplicate:
            self._cache.append(log_hash)

        # return false to filter out (suppress) the record if it's a duplicate
        return not is_duplicate

# --- end duplicate log filter ---


# set default level back to info
def setup_logging(log_level_str: str = 'INFO', log_file: str = None):
    """Configures the root logger.

    Args:
        log_level_str: The desired logging level as a string (e.g., 'DEBUG', 'INFO', 'WARNING').
        log_file: Optional path to a file to log messages to.
    """
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # create formatter
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # get root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # clear existing handlers (important if this function is called multiple times)
    if logger.hasHandlers():
        logger.handlers.clear()

    # configure console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    # add the duplicate filter to the console handler
    console_handler.addFilter(DuplicateFilter())
    logger.addHandler(console_handler)


    # configure file handler if path is provided
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logging.info(f"logging to file: {log_file}")
        except IOError as e:
            logging.error(f"failed to set up log file handler at {log_file}: {e}", exc_info=False)

    logging.info(f"logging setup complete. level set to {log_level_str.upper()}")

# example usage (can be removed or kept for testing)
if __name__ == '__main__':
    # test different levels and file logging
    setup_logging('DEBUG', 'requestify_debug.log')
    logging.debug("this is a debug message.")
    logging.info("this is an info message.")
    logging.warning("this is a warning message.")
    logging.error("this is an error message.")
    logging.critical("this is a critical message.")

    print("\nswitching to info level, console only...")
    setup_logging('INFO')
    logging.debug("this debug message should not appear.")
    logging.info("this info message should appear.")