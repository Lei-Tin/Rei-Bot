"""
The main file for the bot
"""
# Change the version string every update
version = 'v1.5.1 (Oct 18, 2026)'

import asyncio
from ctypes.util import find_library

from typing import Union

from config import *
from Queue import Queue
from utils import truncate
from playlists import PlaylistError, PlaylistSong, PlaylistStore
from playlist_links import PLAYLIST_LINK_MESSAGE, normalize_song_url
from playlist_ui import PlaylistEditor
from playback_audio import playback_audio_options

import discord
from discord import app_commands

import os
from pathlib import Path
import re
import yt_dlp
import logging
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import platform

emoji_pattern = re.compile("["
                           u"\U0001F600-\U0001F64F"  # emoticons
                           u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                           u"\U0001F680-\U0001F6FF"  # transport & map symbols
                           u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                           "]+", flags=re.UNICODE)

intents = discord.Intents.default()

FILE_DIR = os.path.dirname(os.path.realpath(__file__))
playlist_store = PlaylistStore(Path(FILE_DIR) / 'Guilds')

if os.path.isfile(os.path.join(FILE_DIR, 'discord_token')):
    with open(os.path.join(FILE_DIR, 'discord_token')) as f:
        content = f.readline().strip()
        if content != '':
            TOKEN = content

# TEST_GUILD = discord.Object(id=1135123159671119955)

# If you want to use TEST_GUILD, be sure to add it to the end of the tree command decorators
# Example:
# @tree.command(name="play",
#               description="Play a music with the provided link",
#               guild=TEST_GUILD)

# Using a TEST_GUILD makes it so that Discord refreshes the client with the slash commands faster

intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Mapping from guild id to queue and other information
q = {}  # Maps from int to Queue

if platform.system() == 'Darwin':
    discord.opus.load_opus('/opt/homebrew/Cellar/opus/1.4/lib/libopus.0.dylib')
    if not discord.opus.is_loaded():
        raise RuntimeError('Opus failed to load')

if platform.system() == 'Linux':
    discord.opus.load_opus(find_library('opus'))
    if not discord.opus.is_loaded():
        raise RuntimeError('Opus failed to load')

@client.event
async def on_ready() -> None:
    """
    Event triggered when the bot is ready
    """
    # await tree.sync(guild=TEST_GUILD)
    await tree.sync()  # Use the above line if you only want it to work in one guild

    logger.info('Rei Bot is ready!')
    logger.info(f'Version: {version}')
    Path('/tmp/reibot-ready').touch()


@client.event
async def on_disconnect() -> None:
    Path('/tmp/reibot-ready').unlink(missing_ok=True)


@client.event
async def on_resumed() -> None:
    Path('/tmp/reibot-ready').touch()


@client.event
async def on_voice_state_update(member: discord.Member,
                                before: Union[discord.VoiceState, None],
                                after: Union[discord.VoiceState, None]) -> None:
    """
    Event triggered when a member's voice state is updated
    Used for the bot to clear things when the bot is kicked
    :param member:
    :param before:
    :param after:
    :return:
    """
    if client.user is None or member.id != client.user.id:
        return
    if before.channel is None or after.channel is not None:
        return
    queue = q.get(member.guild.id)
    # A delayed disconnect event must not retire a newly connected session.
    current_voice = member.voice
    if current_voice is not None and current_voice.channel is not None:
        return
    if queue is not None and queue.voice_client is not None and queue.voice_channel == before.channel:
        await close_queue(member.guild.id, queue)

@tree.command(name="version",
              description="Prints the version of the bot")
async def print_version(interaction: discord.Interaction) -> None:
    """
    Prints the version of the bot
    """
    await interaction.response.send_message(content=f"Version: {version}")

def queue_is_active(guild_id: int, queue: Queue) -> bool:
    return q.get(guild_id) is queue and not queue.closed


def track_queue_task(queue: Queue, coroutine) -> asyncio.Task:
    task = asyncio.create_task(coroutine)
    queue.tasks.add(task)

    def finished(task):
        queue.tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None and not isinstance(error, (PlaylistError, asyncio.TimeoutError)):
                logger.error('Playback task failed', exc_info=error)

    task.add_done_callback(finished)
    return task


async def close_queue_locked(guild_id: int, queue: Queue) -> None:
    """Retire a session before stopping audio or cancelling its loaders. Requires queue.lock."""
    if q.get(guild_id) is not queue:
        return
    queue.closed = True
    queue.playing = False
    queue.playback_token = None
    queue.current = ''
    queue.pending_songs = 0
    queue.songs.clear()
    queue.ids.clear()
    queue.urls.clear()
    queue.youtube_urls.clear()
    for task in tuple(queue.tasks):
        if task is not asyncio.current_task():
            task.cancel()
    try:
        if queue.voice_client is not None:
            await queue.voice_client.disconnect(force=True)
    except Exception:
        logger.exception('Could not disconnect voice in guild %s', guild_id)
    finally:
        if q.get(guild_id) is queue:
            del q[guild_id]


async def close_queue(guild_id: int, queue: Queue) -> None:
    if q.get(guild_id) is not queue:
        return
    if queue.closed:
        # Another transition is already disconnecting; let its cleanup finish.
        async with queue.lock:
            tasks = tuple(task for task in queue.tasks if task is not asyncio.current_task())
    else:
        # Snapshot before cancellation: a task may release the lock before its done callback runs.
        tasks = tuple(task for task in queue.tasks if task is not asyncio.current_task())
        queue.closed = True
        for task in tasks:
            task.cancel()
        async with queue.lock:
            await close_queue_locked(guild_id, queue)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        queue.tasks.difference_update(tasks)


def get_playback_queue(interaction: discord.Interaction) -> Queue:
    voice = getattr(interaction.user, 'voice', None)
    if interaction.guild_id is None or voice is None or voice.channel is None:
        raise PlaylistError('You are not in a voice channel!')
    queue = q.get(interaction.guild_id)
    if queue is not None:
        if queue.closed:
            raise PlaylistError('The previous queue is disconnecting. Please try again in a moment.')
        if queue.voice_channel != voice.channel:
            raise PlaylistError('Please wait until the current queue in the other channel is finished!')
        return queue
    queue = Queue(voice.channel, interaction.channel)
    q[interaction.guild_id] = queue
    return queue


def append_song(queue: Queue, info: dict) -> None:
    queue.songs.append(info['title'])
    queue.ids.append(info['id'])
    queue.youtube_urls.append(info['webpage_url'])
    queue.urls.append(info['url'])


async def announce_now_playing(queue: Queue, song: str, original_link: str) -> None:
    remaining = len(queue.songs) + queue.pending_songs
    noun = 'song' if remaining == 1 else 'songs'
    title = truncate(emoji_pattern.sub(r"", song))
    await send_playback_message(queue,
        f'Now playing: "[{title}]({original_link})"!\n{remaining} {noun} remaining',
        suppress_embeds=True,
    )


async def send_playback_message(queue: Queue, content: str, **kwargs) -> None:
    try:
        await queue.text_channel.send(content, **kwargs)
    except discord.HTTPException:
        logger.warning('Could not send a playback message')


async def play_music(guild_id: int, queue: Queue, *, finished=None, error=None) -> None:
    """The only playback transition. Queue state is changed exclusively on the event loop."""
    async with queue.lock:
        if not queue_is_active(guild_id, queue):
            return
        if finished is not None:
            if queue.playback_token is not finished:
                return
            queue.playing = False
            queue.playback_token = None
            queue.current = ''
            if error is not None:
                logger.warning('Audio playback failed in guild %s: %s', guild_id, type(error).__name__)
        if queue.playing:
            return
        if not queue.songs:
            if queue.pending_songs:
                # A loader will call us again when the next result is ready.
                return
            was_connected = queue.voice_client is not None
            await close_queue_locked(guild_id, queue)
            if was_connected:
                await send_playback_message(queue, 'Queue is now empty!')
            return
        if len(queue.voice_channel.members) < 2:
            await close_queue_locked(guild_id, queue)
            return

        source = None
        try:
            if queue.voice_client is None:
                queue.voice_client = await track_queue_task(queue, queue.voice_channel.connect(
                    timeout=VOICE_CALL_TIMEOUT, reconnect=True, self_mute=True, self_deaf=True))
                if not queue_is_active(guild_id, queue):
                    return
            voice_client = queue.voice_client
            if not voice_client.is_connected():
                raise discord.ClientException('Not connected to voice.')

            loop = asyncio.get_running_loop()
            token = object()

            def schedule_finished(audio_error):
                if queue_is_active(guild_id, queue):
                    track_queue_task(queue, play_music(guild_id, queue, finished=token, error=audio_error))

            def after(audio_error):
                # discord.py calls this on its audio thread. Never read or mutate the queue here.
                try:
                    loop.call_soon_threadsafe(schedule_finished, audio_error)
                except RuntimeError:
                    pass  # The process's event loop has already shut down.

            source = discord.FFmpegPCMAudio(queue.urls[0], **playback_audio_options(download=DOWNLOAD))
            voice_client.play(source, after=after)
            song = queue.songs.pop(0)
            queue.ids.pop(0)
            queue.urls.pop(0)
            original_link = queue.youtube_urls.pop(0)
            queue.current = song
            queue.playing = True
            queue.playback_token = token
        except Exception:
            if source is not None:
                source.cleanup()
            logger.exception('Could not start audio in guild %s', guild_id)
            await close_queue_locked(guild_id, queue)
            await send_playback_message(queue, 'Failed to play the music. Please try again.')
            return
        await announce_now_playing(queue, song, original_link)


async def load_playback_song(guild_id: int, link: str) -> dict:
    return await asyncio.wait_for(
        asyncio.to_thread(extract_playback_song, guild_id, link), timeout=SONG_LOAD_TIMEOUT)


async def finish_loading(guild_id: int, queue: Queue, count: int = 1) -> None:
    if queue_is_active(guild_id, queue):
        queue.pending_songs -= count
        try:
            await play_music(guild_id, queue)
        except asyncio.CancelledError:
            if queue_is_active(guild_id, queue):
                raise


@tree.command(name="play", description="Play a music with the provided link")
@app_commands.guild_only()
@app_commands.describe(link='The link you want to be played')
async def play(interaction: discord.Interaction, link: str) -> None:
    await interaction.response.send_message('Processing...')
    guild_id = interaction.guild_id
    try:
        queue = get_playback_queue(interaction)
    except PlaylistError as error:
        await interaction.edit_original_response(content=str(error))
        return
    queue.pending_songs += 1
    try:
        info = await track_queue_task(queue, load_playback_song(guild_id, link))
        if not queue_is_active(guild_id, queue):
            await interaction.edit_original_response(content='The queue was cleared or disconnected while loading.')
            return
        append_song(queue, info)
    except asyncio.CancelledError:
        if queue_is_active(guild_id, queue):
            raise
        await interaction.edit_original_response(content='The queue was cleared or disconnected while loading.')
        return
    except asyncio.TimeoutError:
        await interaction.edit_original_response(content='Loading this song timed out. Please try again.')
        return
    except PlaylistError as error:
        await interaction.edit_original_response(content=str(error))
        return
    except Exception:
        logger.exception('Could not load audio in guild %s', guild_id)
        await interaction.edit_original_response(content='Could not load this song. Please try again.')
        return
    finally:
        await finish_loading(guild_id, queue)
    if queue.closed:
        await interaction.edit_original_response(content='Playback stopped before this song could start.')
        return
    await interaction.edit_original_response(content=f'Successfully enqueued "**{truncate(info["title"])}**"!')


@tree.command(name="queue",
              description="Shows the current queue")
async def queue(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Processing...")
    
    guild_id = interaction.guild_id
    logger.info(f'Printing current queue for guild with ID: {guild_id}')

    queue = q.get(guild_id, None)
    if queue is None:
        await interaction.edit_original_response(content="There is no queue!")
    else:
        current = truncate(queue.current) if queue.current else 'Loading the next song...'
        pending = f'\n{queue.pending_songs} song(s) still loading.' if queue.pending_songs else ''
        await interaction.edit_original_response(content=f"""
Currently playing: **{current}**
Coming up:
{queue.show()}{pending}""")


@tree.command(name="skip",
              description="Skips the current music playing")
async def skip(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Processing...")

    guild_id = interaction.guild_id
    logger.info(f'Skipping one song in guild with ID: {guild_id}')

    queue = q.get(guild_id)
    if queue is None:
        await interaction.edit_original_response(content='There is no queue!')
        return
    async with queue.lock:
        if not queue_is_active(guild_id, queue) or not queue.playing:
            message = 'There is no song playing!'
        else:
            # Only the audio after callback advances the queue, including when stop() is called.
            queue.voice_client.stop()
            message = 'Skipped'
    await interaction.edit_original_response(content=message)


@tree.command(name="clear", description="Clears the current queue")
async def clear(interaction: discord.Interaction) -> None:
    await interaction.response.send_message('Processing...')
    queue = q.get(interaction.guild_id)
    if queue is None:
        await interaction.edit_original_response(content='There is no queue!')
        return
    connected = queue.voice_client is not None
    await close_queue(interaction.guild_id, queue)
    await interaction.edit_original_response(
        content='Queue cleared! (and disconnected)' if connected else 'Queue cleared! (did not disconnect)')


@tree.command(name="remove",
              description="Remove a song from the queue")
@app_commands.describe(index='The index of the song you want to remove')
async def remove(interaction: discord.Interaction, index: int) -> None:
    """
    Removes a song from the queue with the given index
    :param interaction:
    :param index:
    :return:
    """

    guild_id = interaction.guild_id

    logger.info(f"Removing a song with index {index} in guild with ID: {guild_id}")

    await interaction.response.send_message("Processing...")

    queue = q.get(guild_id, None)
    if queue is None or queue.closed:
        await interaction.edit_original_response(content="There is no queue!")
        return

    if not 0 <= index - 1 < len(queue.songs):
        await interaction.edit_original_response(content="Invalid Index!")
        return

    song = queue.songs.pop(index - 1)
    queue.ids.pop(index - 1)
    queue.urls.pop(index - 1)
    queue.youtube_urls.pop(index - 1)
    await interaction.edit_original_response(
        content=f'Successfully removed "{song}" at index **{index}**!')

def extract_song_info(link: str, options: dict, *, download=False) -> dict:
    link = normalize_song_url(link)
    options = dict(options, noplaylist=True, lazy_playlist=True,
                   socket_timeout=15, retries=1, extractor_retries=1, ignoreerrors=False)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            visited = set()
            extractor_key = None
            for _ in range(5):
                if link in visited:
                    raise PlaylistError('This link redirects in a loop. Use the original video URL.')
                visited.add(link)
                # Inspect the result before yt-dlp can expand a playlist, including redirected links.
                info = ydl.extract_info(link, download=False, process=False, ie_key=extractor_key)
                if not isinstance(info, dict) or not info:
                    raise PlaylistError('The URL did not return a playable song.')
                result_type = info.get('_type', 'video')
                if 'entries' in info or result_type in ('playlist', 'multi_video', 'compat_list'):
                    raise PlaylistError(PLAYLIST_LINK_MESSAGE)
                if result_type in ('url', 'url_transparent'):
                    link = normalize_song_url(info.get('url'))
                    extractor_key = info.get('ie_key')
                    continue
                if result_type != 'video':
                    raise PlaylistError('The URL did not return a playable song.')
                # Validate formats only for this video; never resolve collection entries.
                info = ydl.process_video_result(info, download=download)
                if not isinstance(info, dict):
                    raise PlaylistError('The URL did not return a playable song.')
                title, song_id = info.get('title'), info.get('id')
                if not isinstance(title, str) or not title.strip() or not song_id:
                    raise PlaylistError('The URL did not return a playable song.')
                url = normalize_song_url(info.get('webpage_url') or info.get('original_url') or link)
                info.update(title=title.strip(), id=str(song_id), webpage_url=url)
                return info
            raise PlaylistError('This link redirects too many times. Use the original video URL.')
    except (yt_dlp.utils.YoutubeDLError, OSError, TimeoutError) as error:
        raise PlaylistError('Could not load this song. Check the URL and try again.') from error


def extract_playlist_song(link: str) -> PlaylistSong:
    info = extract_song_info(link, YDL_OPTS_STREAM)
    return PlaylistSong(info['title'], info['id'], info['webpage_url'])


def extract_playback_song(guild_id: int, link: str) -> dict:
    options = dict(YDL_OPTS_STREAM)
    if DOWNLOAD:
        folder = Path(FILE_DIR) / 'Guilds' / str(guild_id)
        folder.mkdir(parents=True, exist_ok=True)
        options.update(outtmpl=str(folder / '%(id)s.%(ext)s'),
                       postprocessors=[{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}])
    info = extract_song_info(link, options, download=DOWNLOAD)
    if DOWNLOAD:
        info['url'] = str(folder / f'{info["id"]}.mp3')
    if not isinstance(info.get('url'), str) or not info['url']:
        raise PlaylistError('The URL did not return playable audio.')
    logger.info('Selected audio in guild %s: codec=%s, bitrate=%s kbps, sample_rate=%s Hz',
                guild_id, info.get('acodec'), info.get('abr'), info.get('asr'))
    return info


async def open_playlist_editor(interaction: discord.Interaction, name=None, page=1) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message('Use this command in a server.', ephemeral=True)
        return
    if page < 1:
        await interaction.response.send_message('The page number is invalid!', ephemeral=True)
        return
    try:
        editor = PlaylistEditor(playlist_store, interaction.guild_id, interaction.user.id,
                                extract_playlist_song, name=name, page=page - 1)
        embed = editor.render()
    except PlaylistError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await interaction.response.send_message(embed=embed, view=editor, ephemeral=True)
    editor.message = await interaction.original_response()


@tree.command(name="playlist", description="Browse and edit playlists with buttons and menus")
@app_commands.guild_only()
@app_commands.describe(name='Optional playlist to open directly')
async def playlist(interaction: discord.Interaction, name: str = None) -> None:
    await open_playlist_editor(interaction, name)


@tree.command(name="playlist-add", description="Adds a song to a playlist, creating it if needed")
@app_commands.guild_only()
@app_commands.describe(name='The name of the playlist', link='The music video link')
async def pl_add(interaction: discord.Interaction, name: str, link: str) -> None:
    try:
        playlist_store.validate_name(name)
    except PlaylistError as error:
        await interaction.response.send_message(str(error))
        return
    await interaction.response.defer(thinking=True)
    try:
        song = await asyncio.wait_for(asyncio.to_thread(extract_playlist_song, link), timeout=45)
        playlist_store.append(interaction.guild_id, name, [song], create=True)
    except asyncio.TimeoutError:
        await interaction.edit_original_response(content='Loading this song timed out. Please try again.')
        return
    except PlaylistError as error:
        await interaction.edit_original_response(content=str(error))
        return
    except Exception:
        logger.exception('Could not add a song to a playlist')
        await interaction.edit_original_response(content='Could not add this song. Please try again.')
        return
    await interaction.edit_original_response(
        content=f'Successfully added "**{truncate(song.name)}**" to playlist "**{name}**"')


@tree.command(name="playlist-view", description="Opens an interactive editor for a playlist")
@app_commands.guild_only()
@app_commands.describe(name='The name of the playlist', page='The page number (10 songs per page)')
async def pl_view(interaction: discord.Interaction, name: str, page: int = 1) -> None:
    await open_playlist_editor(interaction, name, page)


@tree.command(name="playlist-show", description="Browse available playlists and open an editor")
@app_commands.guild_only()
async def pl_show(interaction: discord.Interaction) -> None:
    await open_playlist_editor(interaction)


@tree.command(name="playlist-remove", description="Removes a song from a playlist by its number")
@app_commands.guild_only()
@app_commands.describe(name='The name of the playlist', index='The song number, starting at 1')
async def pl_remove(interaction: discord.Interaction, name: str, index: int) -> None:
    try:
        snapshot = playlist_store.read(interaction.guild_id, name)
        if not 1 <= index <= len(snapshot.songs):
            raise PlaylistError('The song number is invalid!')
        song = snapshot.songs[index - 1]
        playlist_store.remove(interaction.guild_id, name, [index - 1], revision=snapshot.revision)
    except PlaylistError as error:
        await interaction.response.send_message(str(error))
        return
    await interaction.response.send_message(
        f'Successfully removed "{truncate(song.name)}" at index {index}!')


async def add_songs_to_queue(guild_id: int, queue: Queue, songs) -> None:
    """Resolve sequentially off-loop; only this coroutine can apply its results to this session."""
    remaining = len(songs)
    try:
        for song in songs:
            if not queue_is_active(guild_id, queue):
                return
            try:
                info = await load_playback_song(guild_id, song.url)
            except Exception as error:
                if not isinstance(error, (PlaylistError, asyncio.TimeoutError)):
                    logger.exception('Could not load playlist audio in guild %s', guild_id)
                if queue_is_active(guild_id, queue):
                    await send_playback_message(queue, f'Failed to load "{truncate(song.name)}". Skipping this song.')
            else:
                if not queue_is_active(guild_id, queue):
                    return
                append_song(queue, info)
            finally:
                if queue_is_active(guild_id, queue):
                    queue.pending_songs -= 1
                remaining -= 1
            await play_music(guild_id, queue)
    finally:
        # Cancellation does not kill a running yt-dlp thread. Its result can never mutate the queue.
        await finish_loading(guild_id, queue, remaining)


@tree.command(name="playlist-enqueue",
              description="Enqueues the playlist with the given name in the current queue")
@app_commands.guild_only()
@app_commands.describe(name='The name of the playlist',
                       shuffle='If the songs will be enqueued in random orders')
async def pl_enqueue(interaction: discord.Interaction, name: str, shuffle: bool) -> None:
    await interaction.response.send_message('Processing...')
    guild_id = interaction.guild_id
    try:
        queue = get_playback_queue(interaction)
    except PlaylistError as error:
        await interaction.edit_original_response(content=str(error))
        return
    # Reserve the session during file I/O as well, so /clear also cancels a slow CSV read.
    queue.pending_songs += 1
    reservation = 1
    try:
        snapshot = await track_queue_task(queue, asyncio.to_thread(playlist_store.read, guild_id, name))
        if not queue_is_active(guild_id, queue):
            await interaction.edit_original_response(content='The queue was cleared or disconnected while loading.')
            return
        if not snapshot.songs:
            raise PlaylistError(f'The playlist "{name}" is empty. Add songs with /playlist.')
        songs = list(snapshot.songs)
        if shuffle:
            random.shuffle(songs)
        queue.pending_songs += len(songs) - reservation
        reservation = 0  # The loader now owns the entire batch's pending count.
        track_queue_task(queue, add_songs_to_queue(guild_id, queue, songs))
    except asyncio.CancelledError:
        if queue_is_active(guild_id, queue):
            raise
        await interaction.edit_original_response(content='The queue was cleared or disconnected while loading.')
        return
    except PlaylistError as error:
        await interaction.edit_original_response(content=str(error))
        return
    finally:
        if reservation:
            await finish_loading(guild_id, queue, reservation)
    await interaction.edit_original_response(content=f'Enqueueing {len(songs)} songs from "{name}"!')


@playlist.autocomplete('name')
@pl_view.autocomplete('name')
@pl_add.autocomplete('name')
@pl_remove.autocomplete('name')
@pl_enqueue.autocomplete('name')
async def playlist_names(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    return [app_commands.Choice(name=name, value=name)
            for name in playlist_store.names(interaction.guild_id)
            if current.casefold() in name.casefold()][:25]


if __name__ == '__main__':

    # OAuth is no longer working (as of November 2024)

    # Run a dry run for obtaining OAuth2 Device Token
    # logger.info('Waiting for OAuth2 Authentication...')
    # with yt_dlp.YoutubeDL(YDL_OPTS_STREAM) as ydl:
    #     info_dict = ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False)
    # logger.info('OAuth2 Authenticated!')

    client.run(TOKEN)
