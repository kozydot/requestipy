# RequestiPy

A Python application that monitors a Team Fortress 2 `console.log` file for chat commands to play audio, primarily intended for music requests using YouTube URLs or search terms via `yt-dlp`, and text-to-speech messages.

## Core Features

*   Monitors `console.log` for chat messages (handles multiple formats).
*   Parses commands like `!play`, `!tts`, `!skip`, `!stop`, `!queue`.
*   Downloads audio for `!play` using `yt-dlp` and converts to WAV.
*   Generates speech for `!tts` using `gTTS` and converts to WAV.
*   Plays requested audio (`!play`) through a queue using `sounddevice`.
*   Plays TTS messages (`!tts`) immediately and **concurrently** over any playing music using `sounddevice`.
*   Admin user system (`admin_user` in config) for controlling playback (`!stop`, `!skip`, `!queue`).
*   Allows **all users** to use `!play` and `!tts`.
*   Implements a **30-second rate limit** per username for non-admin users to prevent spam.
*   Prevents duplicate commands sent in rapid succession.
*   Configurable via `config.json`.

## Setup

1.  **Install Python:** Ensure Python 3.10+ is installed.
2.  **Install FFmpeg:** `pydub` (used for TTS audio conversion) requires FFmpeg. Download it from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html) and ensure `ffmpeg.exe` (and `ffprobe.exe`) is accessible in your system's PATH.
3.  **Install Virtual Audio Cable:** You need a virtual audio cable to route the music/TTS playback into TF2's microphone input. A popular free option is VB-CABLE:
    *   Download and install VB-CABLE from: [https://vb-audio.com/Cable/](https://vb-audio.com/Cable/)
4.  **Install Python Packages:** Open a terminal or command prompt in the `requestify-py` directory and run:
    ```bash
    pip install -r requirements.txt
    ```
    This installs `watchdog`, `sounddevice`, `soundfile`, `yt-dlp`, `gTTS`, and `pydub`.
5.  **Configure `config.json`:**
    *   Copy `config.example.json` to `config.json` if it doesn't exist (or create `config.json`).
    *   Set `game_dir` to your TF2 game directory path (e.g., `C:/Program Files (x86)/Steam/steamapps/common/Team Fortress 2/tf`). Use forward slashes `/`.
    *   Set `admin_user` to your exact in-game username (case-sensitive). This user bypasses rate limits and can use control commands.
    *   Set `output_device_substring` to a unique part of the name of the virtual audio cable *input* device (e.g., `"CABLE Input"` for VB-CABLE). RequestiPy will search for an audio output device containing this text and use it for playback. If not found, or if left empty, it uses the system default output. You can see available device names when RequestiPy starts.
    *   (Optional) Adjust `log_level` (e.g., "INFO", "DEBUG").
6.  **Run the Application:** Open a terminal in the `requestify-py` directory and run:
    ```bash
    python src/main.py
    ```

## Team Fortress 2 Setup

For RequestiPy to read chat commands and for audio playback to work correctly within TF2, you need to configure TF2 as follows:

1.  **Enable Console Log:**
    *   Add `-condebug` to your TF2 launch options in Steam (Right-click TF2 > Properties > General > Launch Options). This creates the `console.log` file that RequestiPy monitors.
    *   In the TF2 console (usually opened with the `~` key), run the command: `con_logfile "console.log"` (You might only need to do this once). This ensures the log file has the correct name.
2.  **Enable Voice/Audio Input:**
    *   In TF2's audio settings, set your microphone input device to the virtual audio cable *output* (e.g., "CABLE Output (VB-Audio Virtual Cable)").
    *   Ensure voice communication is enabled (e.g., push-to-talk or open mic).
    *   You might need to add `+voicerecord` to your TF2 launch options or execute `+voicerecord` in the console to ensure voice input is always active, especially if not using push-to-talk.
3.  **Hear Your Own Playback (Optional):**
    *   If you want to hear the music/TTS that RequestiPy is playing through your virtual cable, run this command in the TF2 console: `voice_loopback 1`
    *   Set it back to `voice_loopback 0` to disable hearing yourself.

## Commands

*   `!play <youtube_url_or_search>` (Alias: `!p`): Queues audio from YouTube. (Usable by: All, Rate Limit: Non-admins 30s)
*   `!tts <message>`: Speaks the message concurrently over any playing audio. (Usable by: All, Rate Limit: Non-admins 30s)
*   `!stop` (Alias: `!s`): Stops current playback and clears the queue. (Usable by: Admin Only)
*   `!skip` (Alias: `!next`): Skips the currently playing track in the queue. (Usable by: Admin Only)
*   `!queue` (Alias: `!q`, `!list`): Shows the current playback queue in the RequestiPy console. (Usable by: Admin Only)

## Acknowledgements

This project is a Python port/reimplementation inspired by the original C# RequestifyTF2 project by weespin. You can find the original project here: https://github.com/weespin/RequestifyTF2

Made with ♡ by Kozydot