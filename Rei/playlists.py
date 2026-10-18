"""CSV playlist storage shared by slash commands and the interactive editor."""

import csv
import hashlib
import io
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from config import MAX_SONG_NAME_LENGTH


class PlaylistError(ValueError):
    """An error that can be shown to the person editing a playlist."""


@dataclass(frozen=True)
class PlaylistSong:
    name: str
    id: str
    url: str


@dataclass(frozen=True)
class PlaylistSnapshot:
    name: str
    songs: tuple[PlaylistSong, ...]
    revision: str


class PlaylistStore:
    HEADER = ['name', 'id', 'orig_url']

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.RLock()

    @staticmethod
    def validate_name(name: str) -> None:
        if not name.isalnum() or len(name) > MAX_SONG_NAME_LENGTH:
            raise PlaylistError(f'Playlist names must be alphanumeric and at most {MAX_SONG_NAME_LENGTH} characters.')

    def _path(self, guild_id: int, name: str) -> Path:
        self.validate_name(name)
        return self.root / str(guild_id) / 'playlists' / f'{name}.csv'

    def names(self, guild_id: int) -> list[str]:
        folder = self.root / str(guild_id) / 'playlists'
        with self._lock:
            return sorted((p.stem for p in folder.glob('*.csv')
                           if p.is_file() and p.stem.isalnum()
                           and len(p.stem) <= MAX_SONG_NAME_LENGTH), key=str.casefold)

    def read(self, guild_id: int, name: str) -> PlaylistSnapshot:
        with self._lock:
            try:
                data = self._path(guild_id, name).read_bytes()
            except FileNotFoundError:
                raise PlaylistError(f'The playlist "{name}" does not exist!') from None
            try:
                rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'), newline='')))
                if not rows or rows[0] != self.HEADER:
                    raise ValueError('Invalid header')
                songs = tuple(PlaylistSong(*row) for row in rows[1:] if row)
            except (UnicodeError, csv.Error, TypeError, ValueError):
                raise PlaylistError('This playlist has an invalid CSV format.') from None
            return PlaylistSnapshot(name, songs, hashlib.sha256(data).hexdigest())

    def _write(self, guild_id: int, name: str, songs) -> PlaylistSnapshot:
        path = self._path(guild_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                             dir=path.parent, suffix='.tmp', delete=False) as f:
                temporary = Path(f.name)
                writer = csv.writer(f)
                writer.writerow(self.HEADER)
                writer.writerows((song.name, song.id, song.url) for song in songs)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return self.read(guild_id, name)

    def create(self, guild_id: int, name: str) -> PlaylistSnapshot:
        with self._lock:
            if self._path(guild_id, name).exists():
                raise PlaylistError(f'The playlist "{name}" already exists!')
            return self._write(guild_id, name, [])

    def append(self, guild_id: int, name: str, songs: list[PlaylistSong], *, create=False) -> PlaylistSnapshot:
        with self._lock:
            if create and not self._path(guild_id, name).exists():
                current = ()
            else:
                current = self.read(guild_id, name).songs
            return self._write(guild_id, name, [*current, *songs])

    def _checked(self, guild_id: int, name: str, revision: str | None) -> PlaylistSnapshot:
        snapshot = self.read(guild_id, name)
        if revision is not None and snapshot.revision != revision:
            raise PlaylistError('This playlist changed in another editor. Refreshed the list; select the songs again.')
        return snapshot

    def remove(self, guild_id: int, name: str, indices: list[int], *, revision=None) -> PlaylistSnapshot:
        with self._lock:
            current = self._checked(guild_id, name, revision)
            selected = set(indices)
            if not selected or any(index < 0 or index >= len(current.songs) for index in selected):
                raise PlaylistError('The song number is invalid!')
            return self._write(guild_id, name, [song for i, song in enumerate(current.songs) if i not in selected])

    def move(self, guild_id: int, name: str, index: int, destination: int, *, revision: str) -> PlaylistSnapshot:
        with self._lock:
            current = self._checked(guild_id, name, revision)
            if not 0 <= index < len(current.songs) or not 0 <= destination < len(current.songs):
                raise PlaylistError(f'Choose a position between 1 and {len(current.songs)}.')
            songs = list(current.songs)
            songs.insert(destination, songs.pop(index))
            return self._write(guild_id, name, songs)
