# Rei-Bot v1.3.1

A Discord Bot that is used to play music

Written in Python, not configured for public usage.

# Features

- Play music from YouTube (Supports URL, but not playlist)
- Have a queue of songs
- Choose to download the songs or stream directly
- Supports URL from YouTube playlists, enqueues all of them
- Does not support YouTube search query links
- Does not support playing in multiple channels in the same server at the same time

# Commands

Please use "/" to see the available commands after adding the bot to the server

- /play [URL] - Play something from URL
- /skip - Skips the currently playing song
- /queue - Shows the current list of songs
- /clear - To clear the whole queue
- /remove [index] - To remove a song from the queue with an index
- /playlist-add [name] [URL] - To add a song with the given URL to the specified playlist
- /playlist-remove [name] [index] - To remove a song from the playlist with the given name and index
- /playlist-show - To show all the playlists available in the current server
- /playlist-view [name] - To show the songs in the playlist with a given name
- /playlist-enqueue [name] [shuffle] - To enqueue a playlist to the currently playing queue, with an option to shuffle or not

# Requirements

Application is developed on ARM Mac. The bot will also work on Windows 11, but needs some setup with FFMpeg, which includes altering the PATH.  

- macOS Ventura 13.4
- Python 3.11.4
- discord.py 2.3.1
- yt-dlp 2023.7.6
- ffmpeg 6.0
- opus (Needs to install through homebrew and navigate through)
