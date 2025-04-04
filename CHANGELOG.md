# Changelog

All notable changes to this project will be documented in this file.

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
