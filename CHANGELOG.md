# Changelog

All notable changes to this project will be documented in this file.

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
