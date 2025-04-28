# RequestiPy

A Python application that monitors a Team Fortress 2 `console.log` file for chat commands to play audio, primarily intended for music requests using YouTube URLs or search terms via `yt-dlp`.

## Core Features

*   Monitors `console.log` for chat messages.
*   Parses commands like `!play`, `!skip`, `!stop`, `!queue`.
*   Downloads audio using `yt-dlp`.
*   Plays audio using `sounddevice`.
*   Admin user system for controlling playback commands.
*   Configurable via `config.json`.

## Setup

1.  Ensure Python 3 is installed.
2.  **Install Virtual Audio Cable:** You need a virtual audio cable to route the music playback into TF2's microphone input. A popular free option is VB-CABLE:
    *   Download and install VB-CABLE from: https://vb-audio.com/Cable/
3.  Install required Python packages: `pip install -r requirements.txt`
4.  **Configure `config.json`:**
    *   Set `game_dir` to your TF2 game directory path (e.g., `C:/Program Files (x86)/Steam/steamapps/common/Team Fortress 2/tf`).
    *   Set `admin_user` to your exact in-game username.
    *   Set `output_device_substring` to a unique part of the name of the virtual audio cable *input* device (e.g., `"CABLE Input"` for VB-CABLE). RequestiPy will search for an audio output device containing this text and use it for playback. If not found, it uses the system default output.
5.  Run the application: `python src/main.py`

## Team Fortress 2 Setup

For RequestiPy to read chat commands and for audio playback to work correctly within TF2, you need to configure TF2 as follows:

1.  **Enable Console Log:**
    *   Add `-condebug` to your TF2 launch options in Steam. This creates the `console.log` file that RequestiPy monitors.
    *   In the TF2 console (usually opened with the `~` key), run the command: `con_logfile "console.log"` (You might only need to do this once). This ensures the log file has the correct name.

2.  **Enable Voice/Audio Input:**
    *   Ensure your microphone (or virtual audio cable input like VB-CABLE) is enabled in TF2's voice settings.
    *   You might need to add `+voicerecord` to your TF2 launch options or execute `+voicerecord` in the console to ensure voice input is always active.

3.  **Hear Your Own Playback (Optional):**
    *   If you want to hear the music that RequestiPy is playing through your microphone/virtual cable, run this command in the TF2 console: `voice_loopback 1`
    *   Set it back to `voice_loopback 0` to disable hearing yourself.

## Acknowledgements

This project is a Python port/reimplementation inspired by the original C# RequestifyTF2 project by weespin. You can find the original project here: https://github.com/weespin/RequestifyTF2

Made with ♡ by Kozydot