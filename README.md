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
2.  Install required packages: `pip install -r requirements.txt`
3.  Configure `config.json` with your TF2 game directory path (`game_dir`), admin username (`admin_user`), and desired audio output device substring (`output_device_substring`).
4.  Run the application: `python src/main.py`

*(Further details on configuration, usage, and potential plugin development can be added here.)*