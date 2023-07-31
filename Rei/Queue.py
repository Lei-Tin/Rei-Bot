"""
This is the file for a Queue object, which stores information about the Queue in a specific guild
"""
from config import MAX_SONG_NAME_LENGTH
from utils import truncate


class Queue:
    """
    A class that represents a queue object for a guild
    """

    def __init__(self, voice_channel, text_channel) -> None:
        self.songs = []
        self.ids = []
        self.urls = []
        self.current = ''
        self.voice_channel = voice_channel
        self.text_channel = text_channel
        self.voice_client = None
        self.playing = True

    def show(self) -> str:
        """
        Show the current queue
        """
        return '\n'.join(
            [f'**{str(i + 1)}.** ' + truncate(s) for i, s in enumerate(self.songs)])
