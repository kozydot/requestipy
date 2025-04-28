import logging
import threading
import os
import tempfile
import yt_dlp # Requires yt-dlp package
from typing import List, Dict, Any

# Assuming CommandManager and AudioPlayer are accessible via imports or passed in
from src.command_manager import CommandManager
from src.audio_player import AudioPlayer

logger = logging.getLogger(__name__)

# --- !play Command Logic ---

# Global variable to hold the AudioPlayer instance (or pass it into register)
# This is simpler than using events for direct command->action flow
_audio_player_instance: AudioPlayer | None = None

# Temporary directory for downloads
TEMP_DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "requestify_py_downloads")
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

def _download_audio(url_or_search: str) -> str | None:
    """Downloads audio using yt-dlp and returns the file path."""
    logger.info(f"Attempting to download/extract audio for: {url_or_search}")

    # Configure yt-dlp options
    # -f bestaudio: Select the best quality audio-only format
    # -x: Extract audio
    # --audio-format mp3/wav/opus: Specify desired audio format (wav/opus often better for direct playback)
    # --output: Specify download path template
    # --no-playlist: Download only single video if URL is part of playlist
    # --default-search "ytsearch": Use YouTube search if not a URL
    # --audio-quality 0: Best audio quality for extraction
    # --quiet: Suppress console output
    # --no-warnings: Suppress warnings
    # --no-check-certificate: Sometimes needed for network issues
    # --geo-bypass: Attempt to bypass geo-restrictions
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(TEMP_DOWNLOAD_DIR, '%(id)s.%(ext)s'), # Save as ID.ext
        'noplaylist': True,
        'default_search': 'ytsearch1', # Search YouTube and get first result
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav', # Extract to WAV for easier playback with soundfile
            'preferredquality': '192', # Standard quality
        }],
        'logger': logging.getLogger('yt_dlp'), # Integrate yt-dlp logging
        # 'nocheckcertificate': True, # Uncomment if needed
        # 'geo_bypass': True, # Uncomment if needed
    }

    downloaded_file_path = None
    info_dict = None # Initialize info_dict to prevent UnboundLocalError
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Execute the download/extraction
            info_dict = ydl.extract_info(url_or_search, download=True) # This might raise DownloadError

            # --- This part only runs if extract_info succeeds ---
            # Check if download actually happened and get the path
            # yt-dlp might put the final path in 'requested_downloads' after postprocessing
            if 'requested_downloads' in info_dict and info_dict['requested_downloads']:
                 downloaded_file_path = info_dict['requested_downloads'][0]['filepath']
                 logger.info(f"yt-dlp finished. Extracted audio path: {downloaded_file_path}")
            elif 'filepath' in info_dict: # Fallback if not in requested_downloads
                 downloaded_file_path = info_dict['filepath']
                 logger.warning(f"yt-dlp finished, using 'filepath': {downloaded_file_path}. Check if correct format.")
            else:
                 # Sometimes the path is the 'filename' key if download=False, but we need download=True for postprocessing
                 # If still not found, log an error
                 logger.error(f"Could not determine downloaded file path from yt-dlp info for: {url_or_search}")
                 logger.debug(f"yt-dlp info_dict: {info_dict}") # Log for debugging
                 return None

            # Ensure the expected file (e.g., .wav) exists after postprocessing
            expected_path = os.path.splitext(downloaded_file_path)[0] + '.wav'
            if os.path.exists(expected_path):
                 logger.info(f"Confirmed extracted WAV file exists: {expected_path}")
                 return expected_path
            elif os.path.exists(downloaded_file_path):
                 # If the original extension file exists but not the WAV, postprocessing might have failed
                 logger.warning(f"Postprocessing to WAV might have failed. Using original downloaded file: {downloaded_file_path}")
                 return downloaded_file_path # Return original if WAV not found
            else:
                 logger.error(f"Neither expected WAV nor original download path found after yt-dlp: {expected_path} / {downloaded_file_path}")
                 return None

    # Catch specific PermissionError which might occur if files are locked (e.g., by antivirus or race condition)
    except PermissionError as e:
        logger.error(f"PermissionError during yt-dlp postprocessing for '{url_or_search}': {e}", exc_info=True)
        # Attempt to return the original downloaded path if it exists, as conversion failed
        if 'filepath' in info_dict and os.path.exists(info_dict['filepath']):
             logger.warning(f"Returning original download path due to PermissionError: {info_dict['filepath']}")
             return info_dict.get('filepath') # Use .get() for safety
        return None
    except yt_dlp.utils.DownloadError as e:
        # Handle potential ffprobe errors *within* the except block
        err_str = str(e)
        if "WARNING: unable to obtain file audio codec with ffprobe" in err_str:
             # Log the warning, but don't try to access info_dict as it might not exist
             logger.warning(f"yt-dlp DownloadError contained ffprobe warning for '{url_or_search}': {err_str}")
             # Cannot reliably determine output path here, so return None
             return None
        elif "Unable to rename file" in err_str:
             logger.error(f"yt-dlp file rename error for '{url_or_search}': {err_str}")
             # File might be locked, return None
             return None
        else:
             # Log other download errors
             logger.error(f"yt-dlp DownloadError for '{url_or_search}': {err_str}")
             return None
    except Exception as e:
        # Catch any other unexpected errors during download/extraction
        logger.error(f"Unexpected error during yt-dlp processing for '{url_or_search}': {e}", exc_info=True)
        return None


def cmd_play(user: Dict[str, Any], args: List[str]):
    """Handles the !play command."""
    global _audio_player_instance
    if not _audio_player_instance:
        logger.error("AudioPlayer instance not available for !play command.")
        # TODO: Notify user?
        return

    if not args:
        logger.warning(f"User {user['name']} used !play without arguments.")
        # TODO: Send help message to user?
        return

    query = " ".join(args)
    logger.info(f"User {user['name']} requested to play: {query}")

    # Run download in a separate thread to avoid blocking the command executor
    def download_and_play():
        file_path = _download_audio(query)
        if file_path:
            if os.path.exists(file_path):
                _audio_player_instance.play_file(file_path)
                # TODO: Optionally add cleanup for downloaded files later
            else:
                 logger.error(f"Downloaded file path reported but not found: {file_path}")
        else:
            logger.error(f"Failed to get audio file for query: {query}")
            # TODO: Notify user of failure?

    download_thread = threading.Thread(target=download_and_play, daemon=True)
    download_thread.start()

# --- !stop Command Logic ---

def cmd_stop(user: Dict[str, Any], args: List[str]):
    """Handles the !stop command."""
    global _audio_player_instance
    if not _audio_player_instance:
        logger.error("AudioPlayer instance not available for !stop command.")
        return

    logger.info(f"User {user['name']} requested to stop playback.")
    # Stop current playback and clear the queue
    _audio_player_instance.stop_playback(clear_queue=True)

# --- !queue Command Logic ---

def cmd_queue(user: Dict[str, Any], args: List[str]):
    """Handles the !queue command."""
    global _audio_player_instance
    if not _audio_player_instance:
        logger.error("AudioPlayer instance not available for !queue command.")
        return

    queue_snapshot = _audio_player_instance.get_queue_snapshot()

    if not queue_snapshot:
        logger.info(f"[Queue Command] Playback queue is empty.")
        # TODO: Send message back to user in chat when possible
    else:
        log_message = "[Queue Command] Current Queue:\n"
        for i, item in enumerate(queue_snapshot):
            # Try to get just the filename
            filename = os.path.basename(item)
            log_message += f"  {i+1}. {filename}\n"
        logger.info(log_message.strip())
        # TODO: Send message back to user in chat when possible

# --- !skip Command Logic ---

def cmd_skip(user: Dict[str, Any], args: List[str]):
    """Handles the !skip command."""
    global _audio_player_instance
    if not _audio_player_instance:
        logger.error("AudioPlayer instance not available for !skip command.")
        return

    logger.info(f"User {user['name']} requested to skip track.")
    # Stop current playback *without* clearing the queue
    _audio_player_instance.stop_playback(clear_queue=False)


# --- Registration ---

def register(command_manager: CommandManager, audio_player: AudioPlayer):
    """Registers the core commands with the CommandManager."""
    global _audio_player_instance
    _audio_player_instance = audio_player # Store the audio player instance

    command_manager.register_command(
        name="play",
        func=cmd_play,
        aliases=["p"],
        help_text="Plays audio from a YouTube URL or search query. Usage: !play <url_or_search_terms>",
        admin_only=True, # Mark as admin only
        source="core"
    )
    command_manager.register_command(
        name="stop",
        func=cmd_stop,
        aliases=["s"],
        help_text="Stops the current audio playback and clears the queue.",
        admin_only=True, # Mark as admin only
        source="core"
    )
    command_manager.register_command(
        name="queue",
        func=cmd_queue,
        aliases=["q", "list"],
        help_text="Shows the current playback queue in the console.",
        admin_only=True, # Keep admin only for consistency? Or allow all? Let's keep admin for now.
        source="core"
    )
    command_manager.register_command(
        name="skip",
        func=cmd_skip,
        aliases=["next"],
        help_text="Skips the currently playing song.",
        admin_only=True, # Usually admin only
        source="core"
    )
    # Register other core commands here if needed
    logger.info("Core commands registered.")

def unregister(command_manager: CommandManager):
     """Unregisters core commands."""
     # Example - implement if needed for dynamic reloading
     command_manager.unregister_command("play")
     command_manager.unregister_command("stop")
     command_manager.unregister_command("queue")
     command_manager.unregister_command("skip") # Add skip here too
     logger.info("Core commands unregistered.")


# Example usage (can be removed or kept for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # Mock components for testing
    class MockAudioPlayer:
        def play_file(self, file_path):
            print(f"--- MOCK AUDIO PLAYER: Play request for {file_path} ---")
            # Simulate check if file exists
            if os.path.exists(file_path):
                 print(f"--- MOCK AUDIO PLAYER: Playing {file_path} ---")
            else:
                 print(f"--- MOCK AUDIO PLAYER: File not found {file_path} ---")

    class MockEventBus: pass # Not used directly by core_commands
    mock_bus = MockEventBus()
    mock_cmd_manager = CommandManager(mock_bus)
    mock_audio_player = MockAudioPlayer()

    # Register core commands
    register(mock_cmd_manager, mock_audio_player)

    print("\n--- Testing !play command ---")
    play_cmd = mock_cmd_manager.get_command("play")
    if play_cmd:
        print("Simulating command execution for '!play Never Gonna Give You Up'")
        # Need to run in main thread for testing download directly here
        # In real app, the thread inside cmd_play handles it
        _download_audio("Never Gonna Give You Up") # Test download part

        # Test the command function itself (which starts a thread)
        # play_cmd.execute({"name": "TestUser"}, ["Never", "Gonna", "Give", "You", "Up"])
        # time.sleep(10) # Wait for download thread in test (adjust time as needed)

    else:
        print("!play command not registered.")

    print("\nCore commands test finished.")