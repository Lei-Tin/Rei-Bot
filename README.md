# Rei-Bot v1.5.6

A Discord Bot that is used to play music

Written in Python, not configured for public usage. Currently hosted on Microsoft Azure on selected servers to provide music playing features. 

# Features

- Play music from YouTube
- Have a queue of songs
- Choose to download the songs or stream directly
- Match the volume of different songs automatically
- Create and edit saved playlists with buttons, menus, and popups
- Does not support YouTube search query links
- Does not support playing in multiple channels in the same server at the same time

Song volume is matched with one fixed gain for each song, targeting -16 LUFS while leaving room for loud peaks. The song's own quiet and loud sections stay intact. Adjust `AUDIO_TARGET_LUFS` in `Rei/config.py` to change the target. No noise suppression or vocal filters are applied.

The first play measures the whole song before audio starts. Measurements are saved in `Rei/Guilds/audio_loudness.csv`, on the existing persistent volume in Azure, and reused after restarting. The cache stores loudness and peak measurements, so changing the target does not require another scan. Different audio formats are measured separately; temporary playback URLs are fetched again each time. If measurement fails or takes longer than 90 seconds, the song plays at its original volume. Live streams and sources without a known duration also keep their original volume.

# Commands

Please use "/" to see the available commands after adding the bot to the server

- /play [URL] - Play something from URL. Note: **DOES NOT SUPPORT** whole YouTube Playlist links. YouTube Mix links enqueue only the current video
- /skip - Skips the currently playing song
- /queue - Shows the current list of songs
- /clear - To clear the whole queue
- /remove [index] - To remove a song from the queue with an index
- /playlist [name] - To open the playlist editor, with an optional playlist name
- /playlist-add [name] [URL] - To add a song with the given URL to the specified playlist. Note: **DOES NOT SUPPORT** YouTube Playlist links at the moment
- /playlist-remove [name] [index] - To remove a song from the playlist with the given name and index
- /playlist-show - To show all the playlists available in the current server and choose one to edit
- /playlist-view [name] [page] - To open the playlist editor with a given name and an optional page number
- /playlist-enqueue [name] [shuffle] - To enqueue a playlist to the currently playing queue, with an option to shuffle or not

## Playlist editor

Use "/playlist" to choose a playlist or create a new one. The editor shows 10 songs per page and is only visible to the person who opened it.

- Add songs - To add up to 10 song URLs at once, one URL per line
- Remove selected - To remove the songs selected in the dropdown menu
- Move song - To move a selected song to a given position
- Previous / Next - To browse the songs in the playlist
- Close - To close the editor without deleting the playlist

Changes are saved automatically. Removing the last song keeps an empty playlist. Editing a playlist does not change the songs already in the queue; use "/playlist-enqueue" to enqueue the saved playlist.

Playlist songs load in the background. The bot prepares the first song, then joins voice and starts playing. It prepares up to two upcoming songs instead of processing the whole playlist at once. If the next song is still loading, the bot waits for it. Failed songs are skipped, and "/clear" cancels the loading queue as well.

Note: **DOES NOT SUPPORT** importing whole YouTube playlists or channels. A video link with a playlist attached (`watch?v=...&list=...`) adds only that video. If a link fails or times out, the editor shows which line failed and still adds the other valid songs.

The editor expires after 10 minutes of inactivity. Use "/playlist" to open it again. If someone else changes the playlist, refresh and select the songs again before removing or moving them.

# Requirements

Application is developed on ARM Mac and Windows 11. 

It is tested to run perfectly on Windows 11, Mac OS Ventura 13.4, Alpine Linux. 

- Python 3.11.4
- discord.py 2.7.1
- davey 0.1.7 (voice encryption)
- yt-dlp (latest stable release in Docker)
- ffmpeg 6.0
- PyNaCl 1.5.0
- opus library (If on Linux system, might need to install through package manager)

# Testing

To install the test dependency and run the tests:

```sh
python3 -m pip install 'discord.py[voice]==2.7.1' 'davey==0.1.7'
python3 -m unittest discover -s tests -v
```

The tests cover playback, skipping, cancellation, and playlist editing without connecting to Discord or YouTube. Install FFmpeg to also run the audio tests, which check volume matching with generated WAV files.

To preview the playlist editor locally:

```sh
python3 tools/preview_playlist.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in a browser to try the buttons and menus. The preview uses temporary sample playlists and demo song titles, without connecting to Discord or YouTube. The appearance may be slightly different from Discord; use a test bot and server to check it in the client.

Press Ctrl+C to stop the preview. If port 8765 is already in use, add `--port 8766` to the command.
