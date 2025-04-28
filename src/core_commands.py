import logging
import threading
import os
import tempfile
import yt_dlp # requires yt-dlp package
from typing import List, Dict, Any

# assuming commandmanager and audioplayer are accessible via imports or passed in
from src.command_manager import CommandManager
from src.audio_player import AudioPlayer

logger = logging.getLogger(__name__)

# --- !play command logic ---

# global variable to hold the audioplayer instance (or pass it into register)
# this is simpler than using events for direct command->action flow
_audio_player_instance: AudioPlayer | None = None

# temporary directory for downloads
TEMP_DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "requestify_py_downloads")
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

def _download_audio(url_or_search: str) -> str | None:
    """downloads audio using yt-dlp and returns the file path."""
    logger.info(f"attempting to download/extract audio for: {url_or_search}")

    # configure yt-dlp options
    # -f bestaudio: select the best quality audio-only format
    # -x: extract audio
    # --audio-format mp3/wav/opus: specify desired audio format (wav/opus often better for direct playback)
    # --output: specify download path template
    # --no-playlist: download only single video if url is part of playlist
    # --default-search "ytsearch": use youtube search if not a url
    # --audio-quality 0: best audio quality for extraction
    # --quiet: suppress console output
    # --no-warnings: suppress warnings
    # --no-check-certificate: sometimes needed for network issues
    # --geo-bypass: attempt to bypass geo-restrictions
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(TEMP_DOWNLOAD_DIR, '%(id)s.%(ext)s'), # save as id.ext
        'noplaylist': True,
        'default_search': 'ytsearch1', # search youtube and get first result
        'quiet': True,
        'no_warnings': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav', # extract to wav for easier playback with soundfile
            'preferredquality': '192', # standard quality
        }],
        'logger': logging.getLogger('yt_dlp'), # integrate yt-dlp logging
        # 'nocheckcertificate': True, # uncomment if needed
        # 'geo_bypass': True, # uncomment if needed
    }

    downloaded_file_path = None
    info_dict = None # initialize info_dict to prevent unboundlocalerror
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # execute the download/extraction
            info_dict = ydl.extract_info(url_or_search, download=True) # this might raise downloaderror

            # --- this part only runs if extract_info succeeds ---
            # check if download actually happened and get the path
            # yt-dlp might put the final path in 'requested_downloads' after postprocessing
            if 'requested_downloads' in info_dict and info_dict['requested_downloads']:
                 downloaded_file_path = info_dict['requested_downloads'][0]['filepath']
                 logger.info(f"yt-dlp finished. extracted audio path: {downloaded_file_path}")
            elif 'filepath' in info_dict: # fallback if not in requested_downloads
                 downloaded_file_path = info_dict['filepath']
                 logger.warning(f"yt-dlp finished, using 'filepath': {downloaded_file_path}. check if correct format.")
            else:
                 # sometimes the path is the 'filename' key if download=false, but we need download=true for postprocessing
                 # if still not found, log an error
                 logger.error(f"could not determine downloaded file path from yt-dlp info for: {url_or_search}")
                 logger.debug(f"yt-dlp info_dict: {info_dict}") # log for debugging
                 return None

            # ensure the expected file (e.g., .wav) exists after postprocessing
            expected_path = os.path.splitext(downloaded_file_path)[0] + '.wav'
            if os.path.exists(expected_path):
                 logger.info(f"confirmed extracted wav file exists: {expected_path}")
                 return expected_path
            elif os.path.exists(downloaded_file_path):
                 # if the original extension file exists but not the wav, postprocessing might have failed
                 logger.warning(f"postprocessing to wav might have failed. using original downloaded file: {downloaded_file_path}")
                 return downloaded_file_path # return original if wav not found
            else:
                 logger.error(f"neither expected wav nor original download path found after yt-dlp: {expected_path} / {downloaded_file_path}")
                 return None

    # catch specific permissionerror which might occur if files are locked (e.g., by antivirus or race condition)
    except PermissionError as e:
        logger.error(f"permissionerror during yt-dlp postprocessing for '{url_or_search}': {e}", exc_info=True)
        # attempt to return the original downloaded path if it exists, as conversion failed
        if 'filepath' in info_dict and os.path.exists(info_dict['filepath']):
             logger.warning(f"returning original download path due to permissionerror: {info_dict['filepath']}")
             return info_dict.get('filepath') # use .get() for safety
        return None
    except yt_dlp.utils.DownloadError as e:
        # handle potential ffprobe errors *within* the except block
        err_str = str(e)
        if "warning: unable to obtain file audio codec with ffprobe" in err_str:
             # log the warning, but don't try to access info_dict as it might not exist
             logger.warning(f"yt-dlp downloaderror contained ffprobe warning for '{url_or_search}': {err_str}")
             # cannot reliably determine output path here, so return none
             return None
        elif "unable to rename file" in err_str:
             logger.error(f"yt-dlp file rename error for '{url_or_search}': {err_str}")
             # file might be locked, return none
             return None
        else:
             # log other download errors
             logger.error(f"yt-dlp downloaderror for '{url_or_search}': {err_str}")
             return None
    except Exception as e:
        # catch any other unexpected errors during download/extraction
        logger.error(f"unexpected error during yt-dlp processing for '{url_or_search}': {e}", exc_info=True)
        return None


def cmd_play(user: Dict[str, Any], args: List[str]):
    """handles the !play command."""
    global _audio_player_instance
    if not _audio_player_instance:
        logger.error("audioplayer instance not available for !play command.")
        # todo: notify user?
        return

    if not args:
        logger.warning(f"user {user['name']} used !play without arguments.")
        # todo: send help message to user?
        return

    query = " ".join(args)
    logger.info(f"user {user['name']} requested to play: {query}")

    # run download in a separate thread to avoid blocking the command executor
    def download_and_play():
        file_path = _download_audio(query)
        if file_path:
            if os.path.exists(file_path):
                _audio_player_instance.play_file(file_path)
                # todo: optionally add cleanup for downloaded files later
            else:
                 logger.error(f"downloaded file path reported but not found: {file_path}")
        else:
            logger.error(f"failed to get audio file for query: {query}")
            # todo: notify user of failure?

    download_thread = threading.Thread(target=download_and_play, daemon=True)
    download_thread.start()

# --- !stop command logic ---

def cmd_stop(user: Dict[str, Any], args: List[str]):
    """handles the !stop command."""
    global _audio_player_instance
    if not _audio_player_instance:
        logger.error("audioplayer instance not available for !stop command.")
        return

    logger.info(f"user {user['name']} requested to stop playback.")
    # stop current playback and clear the queue
    _audio_player_instance.stop_playback(clear_queue=True)

# --- !queue command logic ---

def cmd_queue(user: Dict[str, Any], args: List[str]):
    """handles the !queue command."""
    global _audio_player_instance
    if not _audio_player_instance:
        logger.error("audioplayer instance not available for !queue command.")
        return

    queue_snapshot = _audio_player_instance.get_queue_snapshot()

    if not queue_snapshot:
        logger.info(f"[queue command] playback queue is empty.")
        # todo: send message back to user in chat when possible
    else:
        log_message = "[queue command] current queue:\n"
        for i, item in enumerate(queue_snapshot):
            # try to get just the filename
            filename = os.path.basename(item)
            log_message += f"  {i+1}. {filename}\n"
        logger.info(log_message.strip())
        # todo: send message back to user in chat when possible

# --- !skip command logic ---

def cmd_skip(user: Dict[str, Any], args: List[str]):
    """handles the !skip command."""
    global _audio_player_instance
    if not _audio_player_instance:
        logger.error("audioplayer instance not available for !skip command.")
        return

    logger.info(f"user {user['name']} requested to skip track.")
    # stop current playback *without* clearing the queue
    _audio_player_instance.stop_playback(clear_queue=False)


# --- registration ---

def register(command_manager: CommandManager, audio_player: AudioPlayer):
    """registers the core commands with the commandmanager."""
    global _audio_player_instance
    _audio_player_instance = audio_player # store the audio player instance

    command_manager.register_command(
        name="play",
        func=cmd_play,
        aliases=["p"],
        help_text="plays audio from a youtube url or search query. usage: !play <url_or_search_terms>",
        admin_only=True, # mark as admin only
        source="core"
    )
    command_manager.register_command(
        name="stop",
        func=cmd_stop,
        aliases=["s"],
        help_text="stops the current audio playback and clears the queue.",
        admin_only=True, # mark as admin only
        source="core"
    )
    command_manager.register_command(
        name="queue",
        func=cmd_queue,
        aliases=["q", "list"],
        help_text="shows the current playback queue in the console.",
        admin_only=True, # keep admin only for consistency? or allow all? let's keep admin for now.
        source="core"
    )
    command_manager.register_command(
        name="skip",
        func=cmd_skip,
        aliases=["next"],
        help_text="skips the currently playing song.",
        admin_only=True, # usually admin only
        source="core"
    )
    # register other core commands here if needed
    logger.info("core commands registered.")

def unregister(command_manager: CommandManager):
     """unregisters core commands."""
     # example - implement if needed for dynamic reloading
     command_manager.unregister_command("play")
     command_manager.unregister_command("stop")
     command_manager.unregister_command("queue")
     command_manager.unregister_command("skip") # add skip here too
     logger.info("core commands unregistered.")


# example usage (can be removed or kept for testing)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # mock components for testing
    class MockAudioPlayer:
        def play_file(self, file_path):
            print(f"--- mock audio player: play request for {file_path} ---")
            # simulate check if file exists
            if os.path.exists(file_path):
                 print(f"--- mock audio player: playing {file_path} ---")
            else:
                 print(f"--- mock audio player: file not found {file_path} ---")

    class MockEventBus: pass # not used directly by core_commands
    mock_bus = MockEventBus()
    mock_cmd_manager = CommandManager(mock_bus)
    mock_audio_player = MockAudioPlayer()

    # register core commands
    register(mock_cmd_manager, mock_audio_player)

    print("\n--- testing !play command ---")
    play_cmd = mock_cmd_manager.get_command("play")
    if play_cmd:
        print("simulating command execution for '!play never gonna give you up'")
        # need to run in main thread for testing download directly here
        # in real app, the thread inside cmd_play handles it
        _download_audio("never gonna give you up") # test download part

        # test the command function itself (which starts a thread)
        # play_cmd.execute({"name": "testuser"}, ["never", "gonna", "give", "you", "up"])
        # time.sleep(10) # wait for download thread in test (adjust time as needed)

    else:
        print("!play command not registered.")

    print("\ncore commands test finished.")