# Rei-Bot v1.2.1

A Discord Bot that is used to play music

Written in Python, not configured for public usage.

# Features

- Play music from YouTube (Supports URL, but not playlist)
- Have a queue of songs
- Choose to download the songs or stream directly
- Supports URL from YouTube playlists, enqueues all of them

# Commands

Please use "/" to see the available commands after adding the bot to the server

- /play [URL] - Play something from URL
- /skip - Skips the currently playing song
- /queue - Shows the current list of songs
- /clear - To clear the whole queue
- /remove [index] - To remove a song from the queue with an index

# Requirements

Application is developed on ARM Mac, and is currently not tested on other platforms.

- macOS Ventura 13.4
- Python 3.11.4
- discord.py 2.3.1
- yt-dlp 2023.7.6
- ffmpeg 6.0
- opus (Needs to install through homebrew and navigate through)
