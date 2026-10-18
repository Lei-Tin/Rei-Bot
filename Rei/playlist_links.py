"""Validate song links before either the real extractor or the local preview runs."""

import re
from urllib.parse import parse_qs, urlencode, urlsplit

from playlists import PlaylistError

PLAYLIST_LINK_MESSAGE = (
    'Playlist and channel links cannot be added here. '
    'Open a video in the playlist and paste its video URL.'
)


def normalize_song_url(link: str) -> str:
    if not isinstance(link, str):
        raise PlaylistError('Enter a valid song URL.')
    link = link.strip()
    if link.startswith('<') and link.endswith('>'):
        link = link[1:-1]
    if not link or any(character.isspace() or ord(character) < 32 for character in link):
        raise PlaylistError('Enter one song URL per line.')
    try:
        parsed = urlsplit(link)
        host = (parsed.hostname or '').lower().rstrip('.')
        parsed.port  # Validate malformed and out-of-range ports before contacting an extractor.
    except ValueError:
        raise PlaylistError('Enter a valid song URL.') from None
    if parsed.scheme not in ('http', 'https') or not host or parsed.username or parsed.password:
        raise PlaylistError('Enter a valid http or https song URL.')
    query = parse_qs(parsed.query, keep_blank_values=True)
    if 'search_query' in query:
        raise PlaylistError('Search links cannot be added. Open a video and paste its URL.')

    youtube = host == 'youtube.com' or host.endswith('.youtube.com')
    youtube_embed = host == 'youtube-nocookie.com' or host.endswith('.youtube-nocookie.com')
    short = host in ('youtu.be', 'www.youtu.be')
    if youtube or youtube_embed or short:
        parts = parsed.path.strip('/').split('/')
        if parts == ['embed', 'videoseries']:
            raise PlaylistError(PLAYLIST_LINK_MESSAGE)
        if short and len(parts) == 1:
            video_id = parts[0]
        elif parts == ['watch']:
            ids = query.get('v', [])
            video_id = ids[0] if len(ids) == 1 else ''
        elif len(parts) == 2 and parts[0] in ('shorts', 'live', 'embed', 'v'):
            video_id = parts[1]
        else:
            raise PlaylistError(PLAYLIST_LINK_MESSAGE)
        if not video_id or not re.fullmatch(r'[A-Za-z0-9_-]+', video_id):
            if 'list' in query:
                raise PlaylistError(PLAYLIST_LINK_MESSAGE)
            raise PlaylistError('Use a YouTube video URL with a video ID.')
        # A video opened inside a playlist adds only that video. Drop playlist/radio context.
        return 'https://www.youtube.com/watch?' + urlencode({'v': video_id})
    return parsed._replace(fragment='').geturl()
