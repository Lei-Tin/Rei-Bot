"""
Configurations file for Rei
"""

TOKEN = "Your token here"
MAX_SONG_NAME_LENGTH = 100
MAX_DISPLAY_LENGTH = 15  # Used to limit displays to 15 songs

DOWNLOAD = False

VOICE_CALL_TIMEOUT = 60
SONG_LOAD_TIMEOUT = 45
AUDIO_START_TIMEOUT = 15
PRELOAD_SONGS = 2

# Match perceived volume between songs. Set to False to keep the source's volume.
NORMALIZE_AUDIO = True
AUDIO_TARGET_LUFS = -16
AUDIO_TRUE_PEAK_DBTP = -1.5
AUDIO_MEASUREMENT_TIMEOUT = 90

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10',
    'options': '-vn', 
}

YDL_OPTS_STREAM = {
    'format': 'bestaudio/best',
    'noplaylist': True, # Prevents downloading of playlists
    'no_warnings': True,
    'cookiefile': './Rei/cookies.txt', 
    'js_runtimes': {'deno': {'path': '/root/.deno/bin'}},
}
