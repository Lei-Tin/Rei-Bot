"""
This is the utility file for Rei, which contains functions that are used in multiple files
"""

from config import MAX_SONG_NAME_LENGTH


def truncate(s: str) -> str:
    """
    Truncate a string to the specified length
    """
    if len(s) > MAX_SONG_NAME_LENGTH:
        return s[:MAX_SONG_NAME_LENGTH - 3] + '...'
    return s
