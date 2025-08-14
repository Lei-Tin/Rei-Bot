"""
Configurations file for Rei
"""

TOKEN = "Your token here"
MAX_SONG_NAME_LENGTH = 100
MAX_DISPLAY_LENGTH = 15  # Used to limit displays to 15 songs

DOWNLOAD = False

VOICE_CALL_TIMEOUT = 60

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10',
    'options': '-vn'
}

YDL_OPTS_STREAM = {
    'format': 'bestaudio/best',
    'noplaylist': True, # Prevents downloading of playlists
    'no_warnings': True,
    'cookiefile': './Rei/cookies.txt', 
    'extractor_args': {'youtube:player_client': 'tv,web,web_safari'},
}