import logging
import sys
from collections import deque # Import deque
import hashlib # Import hashlib

LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s' # Add LOG_FORMAT back
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# --- Duplicate Log Filter ---
# Cache size for duplicate detection
DUPLICATE_CACHE_SIZE = 10 # How many recent messages to remember

class DuplicateFilter(logging.Filter):
    """Filters out log records identical to the last one within the cache size."""
    def __init__(self, name=""):
        super().__init__(name)
        self._cache: deque[str] = deque(maxlen=DUPLICATE_CACHE_SIZE)

    def filter(self, record):
        # Create a hash based on level and message content
        log_string = f"{record.levelno}-{record.msg}"
        log_hash = hashlib.sha1(log_string.encode()).hexdigest()

        is_duplicate = log_hash in self._cache
        if not is_duplicate:
            self._cache.append(log_hash)

        # Return False to filter out (suppress) the record if it's a duplicate
        return not is_duplicate

# --- End Duplicate Log Filter ---


# Set default level back to INFO
def setup_logging(log_level_str: str = 'INFO', log_file: str = None):
    """Configures the root logger.

    Args:
        log_level_str: The desired logging level as a string (e.g., 'DEBUG', 'INFO', 'WARNING').
        log_file: Optional path to a file to log messages to.
    """
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Clear existing handlers (important if this function is called multiple times)
    if logger.hasHandlers():
        logger.handlers.clear()

    # Configure console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    # Add the duplicate filter to the console handler
    console_handler.addFilter(DuplicateFilter())
    logger.addHandler(console_handler)


    # Configure file handler if path is provided
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logging.info(f"Logging to file: {log_file}")
        except IOError as e:
            logging.error(f"Failed to set up log file handler at {log_file}: {e}", exc_info=False)

    logging.info(f"Logging setup complete. Level set to {log_level_str.upper()}")

# Example usage (can be removed or kept for testing)
if __name__ == '__main__':
    # Test different levels and file logging
    setup_logging('DEBUG', 'requestify_debug.log')
    logging.debug("This is a debug message.")
    logging.info("This is an info message.")
    logging.warning("This is a warning message.")
    logging.error("This is an error message.")
    logging.critical("This is a critical message.")

    print("\nSwitching to INFO level, console only...")
    setup_logging('INFO')
    logging.debug("This debug message should NOT appear.")
    logging.info("This info message should appear.")