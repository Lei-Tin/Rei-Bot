"""
Configurations file for Rei
"""

TOKEN = "MTEzNTEyMjUwNzU0OTExODQ5NA.GNKJoD.5kJaFLea9J6rf-HD2fY2-Kwr7CMBx6l5BisczI"
MAX_SONG_NAME_LENGTH = 100
DOWNLOAD = False

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10',
    'options': '-vn'
}

YDL_OPTS_STREAM = {
    'format': 'bestaudio/best',
}