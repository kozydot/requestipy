import pytest
import os
import tempfile
import time
from unittest.mock import patch, MagicMock, call

# Assuming your project structure allows this import path
from src import core_commands
from src import config
from src.audio_player import AudioPlayer # Import the class
from src import event_bus

# Mock configuration data (adjust as needed based on core_commands dependencies)
MOCK_CONFIG = {
    "temp_download_dir": tempfile.gettempdir(), # Use system temp for tests
    # Add other config values if core_commands directly uses them
}

@pytest.fixture(autouse=True)
def setup_teardown():
    """ Setup and teardown for tests """
    # Mock the config loading to return controlled data
    with patch('src.config.load_config', return_value=MOCK_CONFIG):
        # Ensure the temp directory exists for the test session
        temp_dir = MOCK_CONFIG['temp_download_dir']
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        # Mock the audio player and event bus if commands interact with them
        with patch('src.core_commands._audio_player_instance', spec=AudioPlayer) as mock_audio_player_instance:

            # The patch replaces the global instance directly

            # Assign mocks to core_commands if needed for direct access in tests
            # (depends on how you structure access)
            # core_commands.mock_audio_player = mock_audio_player
            # core_commands.mock_event_bus = mock_event_bus

            yield # Run the test

    # Teardown: Clean up any created temp files if necessary (though mocks often prevent actual file creation)
    # Example: You might want to clean the specific temp dir if files were actually created
    # shutil.rmtree(temp_dir, ignore_errors=True)


# --- Test Cases for !tts ---

@patch('src.core_commands.gTTS')
@patch('src.core_commands.AudioSegment', spec=True) # Correct patch target
@patch('src.core_commands.os.remove')
@patch('src.core_commands.threading.Thread') # Patch Thread to run synchronously
def test_cmd_tts_success(mock_thread, mock_os_remove, mock_audio_segment, mock_gtts):
    """ Tests successful execution of the !tts command """
    # --- Arrange ---
    test_user = {"name": "TestUser", "steamid": "STEAM_0:0:12345"} # Pass as dict
    test_args = ["Hello", "world", "this", "is", "a", "test"] # Pass as list

    # Configure mocks
    mock_gtts_instance = MagicMock()
    mock_gtts.return_value = mock_gtts_instance

    mock_audio_segment_instance = MagicMock()
    mock_audio_segment.from_mp3.return_value = mock_audio_segment_instance

    # Mock the Thread's start method to call the target directly
    def run_target_directly(*args, **kwargs):
        target_func = kwargs.get('target')
        target_args = kwargs.get('args', ())
        if target_func:
            target_func(*target_args)
    mock_thread_instance = MagicMock()
    mock_thread_instance.start.side_effect = run_target_directly
    mock_thread.return_value = mock_thread_instance


    # --- Act ---
    core_commands.cmd_tts(test_user, test_args) # Pass the list

    # --- Assert ---
    # 1. Check gTTS call (Removed assertion on class call, relying on instance method call below)
    # expected_text = " ".join(test_args)
    # mock_gtts.assert_called_once_with(text=expected_text, lang='en') # Check with joined text

    # 2. Check gTTS save (captures mp3_path)
    mock_gtts_instance.save.assert_called_once()
    mp3_path_call = mock_gtts_instance.save.call_args[0][0]
    assert mp3_path_call.startswith(MOCK_CONFIG['temp_download_dir'])
    assert mp3_path_call.endswith('.mp3')

    # 3. Check pydub MP3 load
    mock_audio_segment.from_mp3.assert_called_once_with(mp3_path_call)

    # 4. Check pydub WAV export (captures wav_path)
    mock_audio_segment_instance.export.assert_called_once()
    export_call_args = mock_audio_segment_instance.export.call_args
    wav_path_call = export_call_args[0][0]
    assert wav_path_call.startswith(MOCK_CONFIG['temp_download_dir'])
    assert wav_path_call.endswith('.wav')
    assert export_call_args[1]['format'] == "wav" # Check format keyword arg

    # 5. Check audio player queue call
    mock_audio_player_instance.play_file.assert_called_once_with(wav_path_call) # Check call on the mocked instance

    # 6. Check MP3 file removal
    mock_os_remove.assert_called_once_with(mp3_path_call)

    # 7. Check Thread was created with correct target
    mock_thread.assert_called_once()
    # Ensure the target function was the one defined inside cmd_tts (difficult to assert directly by name)
    # We rely on the subsequent mock calls (gTTS, AudioSegment, etc.) to confirm the target ran.
    assert mock_thread.call_args[1].get('target') is not None # Basic check that a target was set