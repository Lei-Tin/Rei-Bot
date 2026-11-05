# Changelog

All notable changes to this project will be documented in this file.

## [1.5.7] - 2026-11-04

### Changed

- Start joining voice while preparing the first song again, using the native voice client. Concurrent requests share one connection; clearing or failing the queue cancels an unfinished connection.
- Keep one fixed gain per song, targeting -16 LUFS with peak headroom, cached measurements, and preparation of two upcoming playlist songs.

## [1.5.6] - 2026-11-04

### Fixed

- Pin the Discord voice encryption dependency to `davey==0.1.7`, matching the working v1.5.1 and v1.5.2 images. New builds had silently picked up 0.2.0 through `discord.py[voice]`.
- Install the same voice dependencies in CI and check dependency compatibility during tests and image builds.

## [1.5.5] - 2026-11-04

### Changed

- Restore the native voice connection and direct FFmpeg playback flow: prepare the first song, then connect and play. Keep fixed song gain, cached loudness measurements, and preparation of two upcoming playlist songs.
- Apply automatic volume matching without a separate enable/disable switch. Remove temporary playback diagnostics.

## [1.5.4] - 2026-11-04

### Fixed

- Check the first audio frame before announcing playback. Skip songs that return no audio or time out, and clean up preparation when the queue is cleared.
- Limit background playlist preparation to two upcoming songs and run loudness scans at a lower CPU priority, leaving more resources for playback.

## [1.5.3] - 2026-11-04

### Added

- Cache whole-track loudness and true-peak measurements in `Rei/Guilds/audio_loudness.csv`, on the existing persistent volume. Reuse measurements across restarts and changes to the loudness target.

### Changed

- Start joining voice while the first song is being resolved for `/play` and `/playlist-enqueue`. Concurrent requests reuse the connection.
- Replace dynamic volume adjustment with one fixed gain per song, preserving quiet introductions and louder sections. Limit gain to leave peak headroom.

### Fixed

- Cancel unfinished voice connections when loading fails or the queue is cleared, and disconnect partially connected clients during cleanup.
- Cancel FFmpeg measurement when a queue is cleared. Measurement failures, timeouts, or cache errors do not prevent playback; unmeasured tracks keep their original volume.

## [1.5.2] - 2026-10-31

### Fixed

- Fixed `/playlist-enqueue` and `/play` clearing the queue before joining when only one listener is in voice. Check for a human listener instead of counting the bot before it connects.
- Recheck listeners after connecting and report when playback stops because nobody is listening.

## [1.5.1] - 2026-10-18

### Added

- Added automatic song volume matching for streamed and downloaded audio, with a switch and loudness target in `Rei/config.py`.
- Log the selected audio codec, bitrate, and sample rate to help check source quality.

### Fixed

- Song extraction and playlist loading no longer block other bot commands. Songs load sequentially in the background with timeouts, and unavailable songs are skipped.
- Fixed `/skip` and the audio callback both advancing the queue. Playback and connection changes now share one transition per server.
- Clearing or disconnecting retires the queue and cancels its tasks. Late results and callbacks cannot add songs to a new queue.
- Wait for songs still being loaded before disconnecting, and clean up completed background tasks.
- Keep queue fields aligned when removing a song in download mode.

## [1.5] - 2026-10-18

### Added

- Added `/playlist [name]` to create and edit playlists with an embed, dropdown menus, buttons, and popups. Supports adding up to 10 song URLs at once, removing selected songs, moving songs, and browsing 10 songs per page.
- Added a local playlist editor preview with temporary sample playlists.

### Changed

- `/playlist-show` and `/playlist-view [name] [page]` now open the playlist editor. `/playlist-enqueue [name] [shuffle]` is still used to enqueue a saved playlist.
- Now playing messages no longer show a link preview and show the number of songs remaining, including playlist songs still being loaded.
- Playlist changes are saved automatically. Removing the last song keeps an empty playlist.

### Fixed

- Videos opened inside a YouTube playlist add only the current video. Whole-playlist and channel links show a message asking for a video URL.
- Failed or timed-out links do not prevent other valid songs from being added. The editor remains usable after an error and prevents duplicate submissions.
- Refresh the playlist before removing or moving songs if another editor changed it, to prevent editing the wrong song.
- Fixed `/playlist-remove` accepting index 0 and removing the CSV header.

## [1.4.1] - 2024-11-18

### Changed

- Instead of OAuth's temporary solution to YouTube's link issue, use cookies instead. 

## [1.4] - 2024-07-15

### Changed

- Removed the capability to use `/play` for a YouTube playlist link, replaced it with the capability to play YouTube Mix links. This only enqueues the video currently watching. 

## [1.3.2] - 2023-11-05

### Fixed

- Performance improvements for `/playlist-enqueue [name] [shuffle]`. Now instead of processing every single song at once, it processes the very first song, then queues up the other songs concurrently in the background. 
- Utilized task scheduling (specifically for the enqueues) that corresponds to each guild, cancels all of them when a disconnection event occurs (ensure no `None` type access).

## [1.3.1] - 2023-10-29

### Added

- Playlist enqueue can now shuffle the playlist. The command is changed to `/playlist-enqueue [name] [shuffle]`
- Added complete GitHub Actions to upload to Docker Hub Image Repository
- Deployed the bot on Microsoft Azure (currently in local testing, but can run 24x7 with online storage with playlists)

### Fixed

- Changed the logic for resetting the bot, removed the whole `Queue` object when we need a reset

## [1.3] - 2023-10-22

### Added

- Playlist features implemented using CSV files stored under each guild's directory. 
- Added `/playlist-add [name] [URL]` to add a song to the playlist
- Added `/playlist-remove [name] [index]` to remove a song from the playlist
- Added `/playlist-show` to show all the playlists available in the current server
- Added `/playlist-view [name]` to show the songs in the playlist with a given name
- Added `/playlist-enqueue [name]` to enqueue a playlist to the currently playing queue

### Fixed

- Fixed a bug where if you execute the script from a different directory, the `Guilds` folder will be in a wrong directory. 

## [1.2.2] - 2023-08-04

### Added

- Now the bot puts a link to the song in the message sent when playing the song
- Adds a check for the bot stay in the current voice channel until the queue finishes
- Removed the ability to provide a search query link

### Fixed

- Fixed a bug where the bot crashes if the video title contains emojis

### Discovered bug

- The bot will sometimes refuse to respond to any commands, diconnecting the bot then calling `/play` again will fix it. 

## [1.2.1] - 2023-08-01

### Added

- Supports playlist links
- Revised the output format of most functions

### Fixed

- An error raised when the voice client is None for some reasons

## [1.2] - 2023-07-31

### Added

- Added /clear command to clear the whole queue
- Added /remove command to remove a song from the queue with an index
- Added stream mode to choose to stream the audio or download the audio (Download mode works more stable but will take up more space)
- Added utils.py to store the utility functions

### Fixed

- Disconnect from the server normally when the queue is empty
- Fixed a bug where the queue functions weirdly when disconnected

## [1.1] - 2023-07-31

### Added

- Added /skip command to skip the currently playing song

### Fixed

- Fixed a bug where the bot will fail to function once kicked from the voice channel

## [1.0] - 2023-07-30

### Added

- Initial Release
- Play music from YouTube with /play
- Have a queue of songs with /queue
