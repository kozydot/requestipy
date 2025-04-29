import logging
import threading
import os
import tempfile
import uuid # Import uuid for unique filenames
import time # Import time for sleep
import yt_dlp # requires yt-dlp package
from gtts import gTTS, gTTSError # Import gTTS
from pydub import AudioSegment # Import pydub
from typing import List, Dict, Any
import sounddevice as sd # Import sounddevice for direct playback
import soundfile as sf   # Import soundfile for reading WAV data

# assuming commandmanager and audioplayer are accessible via imports or passed in
from src.command_manager import CommandManager
from src.audio_player import AudioPlayer

logger = logging.getLogger(__name__)

# --- !play command logic ---

# global variable to hold the audioplayer instance (or pass it into register)
# this is simpler than using events for direct command->action flow
_audio_player_instance: AudioPlayer | None = None

# temporary directory for downloads and tts files
TEMP_DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "requestify_py_downloads")
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

def _download_audio(url_or_search: str) -> str | None:
    """downloads audio using yt-dlp and returns the file path."""
    logger.info(f"attempting to download/extract audio for: {url_or_search}")

    # configure yt-dlp options
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
    final_file_path = None # Path to return
    info_dict = None # initialize info_dict to prevent unboundlocalerror
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # execute the download/extraction
            info_dict = ydl.extract_info(url_or_search, download=True) # this might raise downloaderror

            # --- Determine the final path ---
            if 'requested_downloads' in info_dict and info_dict['requested_downloads']:
                 downloaded_file_path = info_dict['requested_downloads'][0]['filepath']
                 logger.info(f"yt-dlp finished. Extracted audio path: {downloaded_file_path}")
            elif 'filepath' in info_dict: # Fallback
                 downloaded_file_path = info_dict['filepath']
                 logger.warning(f"yt-dlp finished, using 'filepath': {downloaded_file_path}. Check if correct format.")
            else:
                 logger.error(f"Could not determine downloaded file path from yt-dlp info for: {url_or_search}")
                 logger.debug(f"yt-dlp info_dict: {info_dict}")
                 return None

            # Check for expected WAV file after postprocessing
            expected_path = os.path.splitext(downloaded_file_path)[0] + '.wav'
            if os.path.exists(expected_path):
                 logger.info(f"Confirmed extracted WAV file exists: {expected_path}")
                 final_file_path = expected_path
            elif os.path.exists(downloaded_file_path):
                 logger.warning(f"Postprocessing to WAV might have failed. Using original downloaded file: {downloaded_file_path}")
                 final_file_path = downloaded_file_path # Return original if WAV not found
            else:
                 logger.error(f"Neither expected WAV nor original download path found after yt-dlp: {expected_path} / {downloaded_file_path}")
                 return None

        # --- Add delay after ydl context manager exits ---
        # Give ffmpeg/postprocessor time to release file locks
        time.sleep(0.5)
        logger.debug("Short delay added after yt-dlp processing.")
        # -------------------------------------------------

        return final_file_path # Return the determined path

    except PermissionError as e:
        logger.error(f"permissionerror during yt-dlp postprocessing for '{url_or_search}': {e}", exc_info=True)
        # --- Fix TypeError: Check if info_dict exists before accessing ---
        if info_dict and 'filepath' in info_dict and os.path.exists(info_dict['filepath']):
             logger.warning(f"returning original download path due to permissionerror: {info_dict['filepath']}")
             return info_dict.get('filepath') # use .get() for safety
        # -----------------------------------------------------------------
        return None
    except yt_dlp.utils.DownloadError as e:
        err_str = str(e)
        if "warning: unable to obtain file audio codec with ffprobe" in err_str:
             logger.warning(f"yt-dlp downloaderror contained ffprobe warning for '{url_or_search}': {err_str}")
             return None
        elif "unable to rename file" in err_str:
             logger.error(f"yt-dlp file rename error for '{url_or_search}': {err_str}")
             return None
        else:
             logger.error(f"yt-dlp downloaderror for '{url_or_search}': {err_str}")
             return None
    except Exception as e:
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
            # --- Add another small delay before queueing ---
            time.sleep(0.2)
            # ---------------------------------------------
            if os.path.exists(file_path):
                logger.info(f"Queueing downloaded file: {file_path}")
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

# --- !tts command logic ---

def cmd_tts(user: Dict[str, Any], args: List[str]):
    """handles the !tts command."""
    global _audio_player_instance
    if not _audio_player_instance:
        logger.error("audioplayer instance not available for !tts command.")
        # todo: notify user?
        return

    if not args:
        logger.warning(f"user {user['name']} used !tts without text.")
        # todo: send help message to user?
        return

    text_to_speak = " ".join(args)
    logger.info(f"user {user['name']} requested tts: '{text_to_speak}'")

    # run tts generation and conversion in a separate thread
    def generate_convert_and_play():
        mp3_file_path = None # Initialize path variable
        wav_file_path = None # Initialize path variable
        try:
            logger.debug(f"generating tts for: '{text_to_speak}'")
            tts = gTTS(text=text_to_speak, lang='en') # using english language
            # generate unique filename for mp3
            mp3_filename = f"tts_{uuid.uuid4()}.mp3"
            mp3_file_path = os.path.join(TEMP_DOWNLOAD_DIR, mp3_filename)

            logger.debug(f"saving tts audio to mp3: {mp3_file_path}")
            tts.save(mp3_file_path)

            if os.path.exists(mp3_file_path):
                logger.info(f"tts mp3 audio saved successfully: {mp3_file_path}")

                # Convert MP3 to WAV using pydub
                try:
                    logger.debug(f"converting {mp3_file_path} to wav...")
                    sound: AudioSegment = AudioSegment.from_mp3(mp3_file_path)
                    # --- Boost TTS Volume ---
                    boost_db = 6.0 # Boost by 6 dB (adjust as needed)
                    boosted_sound = sound + boost_db
                    wav_filename = os.path.splitext(mp3_filename)[0] + ".wav"
                    logger.debug(f"Boosting TTS volume by {boost_db} dB")
                    wav_file_path = os.path.join(TEMP_DOWNLOAD_DIR, wav_filename)
                    boosted_sound.export(wav_file_path, format="wav") # Export boosted sound
                    logger.info(f"converted tts audio to wav: {wav_file_path}")

                    # Queue the WAV file for playback
                    # --- Modification: Play directly instead of queueing ---
                    if os.path.exists(wav_file_path):
                        try:
                            logger.debug(f"Attempting direct playback of TTS WAV: {wav_file_path}")
                            # --- Get the configured output device ---
                            device_id = _audio_player_instance.get_output_device_id()
                            logger.debug(f"Using output device ID: {device_id} for TTS playback.")
                            # ----------------------------------------
                            data, samplerate = sf.read(wav_file_path, dtype='float32')
                            # --- Play on the configured device ---
                            sd.play(data, samplerate, blocking=True, device=device_id) # Play and wait
                            logger.info(f"Finished direct playback of TTS: {wav_file_path}")
                            # --- Add WAV cleanup after successful playback ---
                            try:
                                os.remove(wav_file_path)
                                logger.debug(f"Cleaned up temporary TTS WAV file: {wav_file_path}")
                            except Exception as del_wav_e:
                                logger.error(f"Error deleting temporary TTS WAV file {wav_file_path}: {del_wav_e}")
                        except Exception as play_e:
                            logger.error(f"Error during direct sounddevice playback of {wav_file_path}: {play_e}", exc_info=True)
                    else:
                        logger.error(f"wav file path reported but not found after conversion: {wav_file_path}")

                except Exception as convert_e:
                    logger.error(f"error converting mp3 to wav for '{mp3_file_path}': {convert_e}", exc_info=True)
                    # todo: notify user of conversion failure?
                finally:
                    # Clean up the intermediate MP3 file regardless of conversion success
                    if os.path.exists(mp3_file_path):
                        try:
                            os.remove(mp3_file_path)
                            logger.debug(f"cleaned up temporary mp3 file: {mp3_file_path}")
                        except Exception as del_e:
                            logger.error(f"error deleting temporary mp3 file {mp3_file_path}: {del_e}")

            else:
                 logger.error(f"tts mp3 file path reported but not found after saving: {mp3_file_path}")

        except gTTSError as e:
             logger.error(f"gtts error generating speech for '{text_to_speak}': {e}", exc_info=True)
             # todo: notify user of failure?
        except Exception as e:
             logger.error(f"unexpected error during tts processing for '{text_to_speak}': {e}", exc_info=True)
             # todo: notify user of failure?
             # Clean up potentially created files if error occurred before cleanup block
             if mp3_file_path and os.path.exists(mp3_file_path):
                 try: os.remove(mp3_file_path)
                 except Exception: pass
             if wav_file_path and os.path.exists(wav_file_path):
                 try: os.remove(wav_file_path)
                 except Exception: pass


    tts_thread = threading.Thread(target=generate_convert_and_play, daemon=True)
    tts_thread.start()


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
        admin_only=False, # Allow all users
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
    command_manager.register_command(
        name="tts",
        func=cmd_tts,
        aliases=[], # no aliases for now
        help_text="converts text to speech and plays it. usage: !tts <text to speak>",
        admin_only=False, # Allow all users
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
     command_manager.unregister_command("skip")
     command_manager.unregister_command("tts") # unregister tts too
     logger.info("core commands unregistered.")


# example usage (can be removed or kept for testing)
if __name__ == '__main__':
    # Requires ffmpeg/ffprobe to be installed and in PATH for pydub conversion
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

    # mock components for testing
    class MockAudioPlayer:
        def play_file(self, file_path):
            print(f"--- mock audio player: play request for {file_path} ---")
            # simulate check if file exists
            if os.path.exists(file_path):
                 print(f"--- mock audio player: playing {file_path} ---")
                 # Clean up the dummy tts file in test
                 if "tts_" in os.path.basename(file_path) and file_path.endswith(".wav"):
                     try: os.remove(file_path)
                     except Exception: pass
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

    print("\n--- testing !tts command ---")
    tts_cmd = mock_cmd_manager.get_command("tts")
    if tts_cmd:
        print("simulating command execution for '!tts hello this is a test'")
        # Test the command function itself (which starts a thread)
        tts_cmd.execute({"name": "testuser"}, ["hello", "this", "is", "a", "test"])
        import time
        time.sleep(5) # wait for tts thread in test (adjust time as needed)
    else:
        print("!tts command not registered.")


    print("\ncore commands test finished.")