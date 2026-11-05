"""
This is the file for a Queue object, which stores information about the Queue in a specific guild
"""
import asyncio

from config import MAX_DISPLAY_LENGTH
from utils import truncate


class Queue:
    """
    A class that represents a queue object for a guild
    """

    def __init__(self, voice_channel, text_channel) -> None:
        self.songs = []
        self.ids = []
        self.urls = []
        self.youtube_urls = []
        self.gains = []
        self.current = ''
        self.pending_songs = 0  # Playlist songs still being loaded.
        self.preparing_songs = 0
        self.preload_changed = asyncio.Event()
        self.voice_channel = voice_channel
        self.text_channel = text_channel
        self.voice_client = None
        self.playing = False
        self.starting = False
        # Playback state belongs to the event loop; threads only return media information.
        self.lock = asyncio.Lock()
        self.closed = False
        self.playback_token = None
        self.tasks = set()

    def show(self) -> str:
        """
        Show the current queue, only limited to MAX_DISPLAY_LENGTH to prevent Discord's 2000 character limit
        """
        return '\n'.join(
            [f'**{str(i + 1)}.** ' + truncate(s) for i, s in enumerate(self.songs[:MAX_DISPLAY_LENGTH])]) \
            + (f'\n... and {len(self.songs) - MAX_DISPLAY_LENGTH} more' if len(self.songs) > MAX_DISPLAY_LENGTH else '')
