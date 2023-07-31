"""
Configurations file for Rei
"""

TOKEN = "Your token here"
MAX_SONG_NAME_LENGTH = 50
DOWNLOAD = False

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10',
    'options': '-vn'
}
