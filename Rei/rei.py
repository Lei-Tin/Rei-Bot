"""
The main file for the bot
"""
import asyncio

from typing import Union, List, Callable, Coroutine

from config import *
from Queue import Queue
from utils import truncate

import discord
from discord import app_commands

import os
import re
import yt_dlp
import logging
import random
import functools

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import csv

import platform

emoji_pattern = re.compile("["
                           u"\U0001F600-\U0001F64F"  # emoticons
                           u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                           u"\U0001F680-\U0001F6FF"  # transport & map symbols
                           u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                           "]+", flags=re.UNICODE)

intents = discord.Intents.default()

FILE_DIR = os.path.dirname(os.path.realpath(__file__))

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

# My opus library is in homebrew as I'm in M1 Mac
# You can comment this out in Windows, I think

if platform.system() == 'Darwin':
    discord.opus.load_opus('/opt/homebrew/Cellar/opus/1.4/lib/libopus.0.dylib')
    if not discord.opus.is_loaded():
        raise RuntimeError('Opus failed to load')

if platform.system() == 'Linux':
    discord.opus.load_opus('/usr/lib/libopus.so.0.9.0')
    if not discord.opus.is_loaded():
        raise RuntimeError('Opus failed to load')

# Change the version string every update
version = 'January 1, 2025 11:30 PM'

@client.event
async def on_ready() -> None:
    """
    Event triggered when the bot is ready
    """
    # await tree.sync(guild=TEST_GUILD)
    await tree.sync()  # Use the above line if you only want it to work in one guild

    logger.info('Rei Bot is ready!')
    logger.info(f'Version: {version}')


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
    guild_id = member.guild.id

    if before.channel is not None and after.channel is None and member.bot is True and member.name == 'Rei-Bot':
        logger.info(f'Member "{member.name}" has disconnected in guild with ID: {guild_id}')

        queue = q.get(guild_id, None)
        if queue is None:
            return
        
        for task in queue.tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Resetting queue
        del q[guild_id]

@tree.command(name="version",
              description="Prints the version of the bot")
async def print_version(interaction: discord.Interaction) -> None:
    """
    Prints the version of the bot
    """
    await interaction.response.send_message(content=f"Version: {version}")

def to_thread(func: Callable) -> Coroutine:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)
    return wrapper

def play_song(guild_id: int) -> None:
    """
    Play a song in the queue
    Synchronous function, the automated callback when a song is finished
    :param guild_id:
    :return:
    """
    queue = q.get(guild_id, None)
    if queue is None:
        return

    voice_client = queue.voice_client
    if not voice_client or not voice_client.is_connected():
        return

    # We only continue playing if there are more than 1 people in the voice channel, including the bot, that is 2
    if len(queue.songs) > 0 and len(queue.voice_channel.members) >= 2:
        queue.playing = True

        song = queue.songs.pop(0) if queue.songs else ''
        id = queue.ids.pop(0) if queue.ids else ''
        original_link = queue.youtube_urls.pop(0) if queue.youtube_urls else ''

        queue.current = song

        if DOWNLOAD:
            path = [FILE_DIR, 'Guilds', str(guild_id), f"{id}.mp3"]
            voice_client.play(discord.FFmpegPCMAudio(os.path.join(*path)),
                              after=lambda e: play_song(guild_id))
        else:
            url = queue.urls.pop(0) if queue.urls else ''
            voice_client.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS),
                              after=lambda e: play_song(guild_id))

        asyncio.run_coroutine_threadsafe(
            queue.text_channel.send(f'Now playing: "[{truncate(emoji_pattern.sub(r"", song))}]({original_link})"!'),
            client.loop)
    else:
        asyncio.run_coroutine_threadsafe(voice_client.disconnect(), client.loop)
        asyncio.run_coroutine_threadsafe(
            queue.text_channel.send(f'Queue is now empty!'),
            client.loop)
        queue.playing = False
        
        del q[guild_id]


async def play_music(guild_id: int):
    """
    Play a song in the queue, the asynchronous function, first called when /play is called
    :param guild_id:
    :return:
    """
    logger.info(f'Initializing play for guild with ID: {guild_id}')

    queue = q.get(guild_id, None)
    if queue is None:
        return

    voice_client = queue.voice_client

    if len(queue.songs) > 0 and len(queue.voice_channel.members) >= 2:
        queue.playing = True

        song = queue.songs.pop(0) if queue.songs else ''
        id = queue.ids.pop(0) if queue.ids else ''
        original_link = queue.youtube_urls.pop(0) if queue.youtube_urls else ''

        queue.current = song

        if DOWNLOAD:
            path = [FILE_DIR, 'Guilds', str(guild_id), f"{id}.mp3"]
            voice_client.play(discord.FFmpegPCMAudio(os.path.join(*path)),
                              after=lambda e: play_song(guild_id))
        else:
            url = queue.urls.pop(0) if queue.urls else ''
            voice_client.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS),
                              after=lambda e: play_song(guild_id))

        await queue.text_channel.send(f'Now playing: "[{truncate(emoji_pattern.sub(r"", song))}]({original_link})"!')
    else:
        queue.playing = False


@tree.command(name="play",
              description="Play a music with the provided link")
@app_commands.describe(link='The link you want to be played')
async def play(interaction: discord.Interaction, link: str) -> None:
    """
    Play a music with the provided link
    The parameters will be passed in from the message
    """
    await interaction.response.send_message("Processing...")

    guild_id = interaction.guild_id

    logger.info(f'Attempt to enqueue a song for guild with ID: {guild_id}')
    logger.info(f'Attempt to enqueue a song with the link: {link}')

    voice = interaction.user.voice

    if voice is None:
        await interaction.edit_original_response(content='You are not in a voice channel!')
        return
    else:
        voice_channel = voice.channel

    text_channel = interaction.channel

    queue = q.get(guild_id, None)
    if queue is None or queue.voice_channel is None:
        queue = Queue(voice_channel, text_channel)
        q[guild_id] = queue
    else:
        if queue.voice_channel != voice_channel:
            await interaction.edit_original_response(
                content='Please wait until the current queue in the other channel is finished!'
            )
            return

    if DOWNLOAD:
        path = [FILE_DIR, 'Guilds', str(guild_id)]
        os.makedirs(os.path.join(*path), exist_ok=True)

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(*path, '%(id)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
            'download_archive': os.path.join(*path, 'archive.txt'),
        }
    else:
        ydl_opts = YDL_OPTS_STREAM

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Disable search queries
            if 'search_query' in link:
                raise yt_dlp.utils.DownloadError('Search queries are not allowed!')

            info_dict = ydl.extract_info(link, download=False)

            song = info_dict.get('title', None)
            id = info_dict.get('id', None)
            original_url = info_dict.get('original_url', None)

            if DOWNLOAD:
                ydl.download([link])

            queue = q.get(guild_id, None)
            if not queue.playing:

                queue.songs.append(song)
                queue.ids.append(id)
                queue.youtube_urls.append(original_url)
                if not DOWNLOAD:
                    url = info_dict.get('url', None)
                    queue.urls.append(url)

                try:
                    if queue.voice_client is None:
                        voice_client = await voice_channel.connect(timeout=VOICE_CALL_TIMEOUT,
                                                                   reconnect=True,
                                                                   self_mute=True,
                                                                   self_deaf=True)
                        queue.voice_client = voice_client
                    await play_music(guild_id)

                except discord.ClientException as e:
                    await interaction.edit_original_response(content='Failed to play the music!')
                    return
            else:
                queue.songs.append(song)
                queue.ids.append(id)
                queue.youtube_urls.append(original_url)

                if not DOWNLOAD:
                    url = info_dict.get('url', None)
                    queue.urls.append(url)
                    
            logger.info(f'Successfully enqueue a song for guild with ID: {guild_id}')
            await interaction.edit_original_response(
                content=f'Successfully enqueued "**{truncate(song)}**"!'
            )

    except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as error:
        await interaction.edit_original_response(
            content=f'{error} | Failed to retrieve information from the link!')


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
        await interaction.edit_original_response(content=f"""
Currently playing: **{truncate(queue.current)}**
Coming up:
{queue.show()}""")


@tree.command(name="skip",
              description="Skips the current music playing")
async def skip(interaction: discord.Interaction) -> None:
    await interaction.response.send_message("Processing...")

    guild_id = interaction.guild_id
    logger.info(f'Skipping one song in guild with ID: {guild_id}')

    queue = q.get(guild_id, None)

    if queue is None:
        await interaction.edit_original_response(content="There is no queue!")
    else:
        if queue.voice_client is not None and queue.voice_client.is_playing():
            queue.voice_client.stop()

            await interaction.edit_original_response(content="Skipped")

            await play_music(guild_id)
        else:
            await interaction.edit_original_response(content="Something went wrong!")


@tree.command(name="clear",
              description="Clears the current queue")
async def clear(interaction: discord.Interaction) -> None:
    """
    Clears the current queue
    :param interaction:
    """
    await interaction.response.send_message("Processing...")

    guild_id = interaction.guild_id
    logger.info(f"Clearing the queue in guild with ID: {guild_id}")
    
    queue = q.get(guild_id, None)

    if queue is None:
        await interaction.edit_original_response(content="There is no queue!")
    else:
        if queue.voice_client is not None:
            await queue.voice_client.disconnect()
            await interaction.edit_original_response(content="Queue cleared! (and disconnected)")

            if guild_id in q:
                del q[guild_id]

        else:
            if guild_id in q:
                del q[guild_id]

            await interaction.edit_original_response(content="Queue cleared! (did not disconnect)")


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
    if queue is None or queue.playing is False:
        await interaction.edit_original_response(content="There is no queue!")
        return

    if not 0 <= index - 1 < len(queue.songs):
        await interaction.edit_original_response(content="Invalid Index!")
        return

    song = queue.songs.pop(index - 1)
    id = queue.ids.pop(index - 1)
    url = queue.urls.pop(index - 1)
    youtube_url = queue.youtube_urls.pop(index - 1)
    await interaction.edit_original_response(
        content=f'Successfully removed "{song}" at index **{index}**!')

@tree.command(name="playlist-add",
              description="Adds a song to a playlist with a given name, creates it if it does not exist")
@app_commands.describe(name='The name of the playlist',
                       link='The music video link')
async def pl_add(interaction: discord.Interaction, name: str, link: str) -> None:
    """
    Adds a song to a playlist

    Does multiple things: 
    1. Create the folder for playlists under the current guild if not exists
    2. Check if the file exists with the "name".txt
        a. If exists, append to it
        b. If not exists, create and write in it
    """
    if not name.isalnum():
        await interaction.response.send_message("The name of the playlist must be alphanumeric!")
        return

    if len(name) > MAX_SONG_NAME_LENGTH:
        await interaction.response.send_message(f"The name of the playlist can only be lesser than {MAX_SONG_NAME_LENGTH} characters!")
        return

    await interaction.response.send_message("Processing...")

    with yt_dlp.YoutubeDL(YDL_OPTS_STREAM) as ydl:
        try:
            # Disable search queries
            if 'search_query' in link:
                raise yt_dlp.utils.DownloadError('Search queries are not allowed!')

            info_dict = ydl.extract_info(link, download=False)

            if 'entries' in info_dict:
                await interaction.edit_original_response(content='Playlist links are not allowed!')
                return
        except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError, yt_dlp.utils.YoutubeDLError) as error:
            await interaction.edit_original_response(
            content=f'{error} | Failed to retrieve information from the link!')
            return

    guild_id = interaction.guild_id

    path = [FILE_DIR, 'Guilds', str(guild_id), 'playlists']
    os.makedirs(os.path.join(*path), exist_ok=True)

    path += [f'{name}.csv']

    song = info_dict.get('title', None)
    id = info_dict.get('id', None)
    original_url = info_dict.get('original_url', None)

    if os.path.isfile(os.path.join(*path)):
        # If the file exists with name.csv, append to it
        with open(os.path.join(*path), 'a+', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([song, id, original_url])
    else:
        with open(os.path.join(*path), 'w+', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['name', 'id', 'orig_url'])
            writer.writerow([song, id, original_url])

    await interaction.edit_original_response(content=f'Successfully added "**{truncate(song)}**" to playlist "**{name}**"')

@tree.command(name="playlist-view",
              description="Views the playlist with the given name, shows a list of the songs added")
@app_commands.describe(name='The name of the playlist', 
                       page='The page number (Each page is 10 songs)')
async def pl_view(interaction: discord.Interaction, name: str, page: int) -> None:
    """
    Checks the songs included in the playlist with the given name
    """
    if not name.isalnum():
        await interaction.response.send_message("The name of the playlist must be alphanumeric!")
        return

    if len(name) > MAX_SONG_NAME_LENGTH:
        await interaction.response.send_message(f"The name of the playlist can only be lesser than {MAX_SONG_NAME_LENGTH} characters!")
        return
    
    if page < 1:
        await interaction.response.send_message("The page number is invalid!")
        return

    guild_id = interaction.guild_id

    await interaction.response.send_message("Processing...")

    path = [FILE_DIR, 'Guilds', str(guild_id), 'playlists']
    os.makedirs(os.path.join(*path), exist_ok=True)

    path += [f'{name}.csv']

    if not os.path.isfile(os.path.join(*path)):
        await interaction.edit_original_response(content=f'The playlist named "{name}" does not exist!')
        return

    names = []
    with open(os.path.join(*path), 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            names.append(row["name"])

    if page > len(names) // MAX_DISPLAY_LENGTH + 1 or len(names) % MAX_DISPLAY_LENGTH == 0 and page > len(names) // MAX_DISPLAY_LENGTH:
        await interaction.edit_original_response(content=f'The page number is invalid!')
        return
    
    # Ceiling division
    total_pages = len(names) // MAX_DISPLAY_LENGTH + (len(names) % MAX_DISPLAY_LENGTH != 0) * 1

    names = names[(page - 1) * MAX_DISPLAY_LENGTH:page * MAX_DISPLAY_LENGTH]

    await interaction.edit_original_response(
            content=f'Playlist "{name}", Page {page}/{total_pages}:\n' + '\n'.join([f'**{str(int((page - 1) * MAX_DISPLAY_LENGTH) + i + 1)}. **' + truncate(n) for i, n in enumerate(names)])
        )
    

@tree.command(name="playlist-show",
              description="Shows all of the playlists available")
async def pl_show(interaction: discord.Interaction) -> None:
    guild_id = interaction.guild_id
    await interaction.response.send_message("Processing...")

    path = [FILE_DIR, 'Guilds', str(guild_id), 'playlists']
    os.makedirs(os.path.join(*path), exist_ok=True)

    files = os.listdir(os.path.join(*path))
    if len(files) == 0:
        await interaction.edit_original_response(content='No playlists are available!')
        return
    await interaction.edit_original_response(content=f'Available playlists currently:\n' + '\n'.join([f'**{str(i + 1)}. **' + os.path.splitext(f)[0] for i, f in enumerate(files)]))

@tree.command(name="playlist-remove",
              description="Removes a specific song from a playlist with a given index")
@app_commands.describe(name='The name of the playlist', 
                       index='The index of the song you want to remove')
async def pl_remove(interaction: discord.Interaction, name: str, index: int) -> None:
    guild_id = interaction.guild_id

    if not name.isalnum():
        await interaction.response.send_message("The name of the playlist must be alphanumeric!")
        return

    if len(name) > MAX_SONG_NAME_LENGTH:
        await interaction.response.send_message(f"The name of the playlist can only be lesser than {MAX_SONG_NAME_LENGTH} characters!")
        return

    await interaction.response.send_message("Processing...")

    path = [FILE_DIR, 'Guilds', str(guild_id), 'playlists']
    os.makedirs(os.path.join(*path), exist_ok=True)

    path += [f'{name}.csv']

    if not os.path.isfile(os.path.join(*path)):
        await interaction.edit_original_response(content=f'The playlist "{name}" does not exist!')
        return

    entries = []
    with open(os.path.join(*path), 'r+') as f:
        reader = csv.reader(f)
        for row in reader:
            entries.append(row)

    if not 0 <= index < len(entries):
        await interaction.edit_original_response(content=f'The index is invalid!')
        return
    
    song_name, id, link = entries.pop(index)

    if len(entries) > 1:
        with open(os.path.join(*path), 'w+', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(entries)
    else:
        os.remove(os.path.join(*path))

    await interaction.edit_original_response(content=f'Successfully removed "{truncate(song_name)}" at index {index}!')

@to_thread
def add_songs_to_queue(guild_id: int, songs: List[str]):
    """Helper function for the playlist enqueue, enqueues songs slowly, 5 songs at a time"""

    if len(songs) == 0:
        return

    queue = q.get(guild_id, None)
    if queue is None:
        return
    
    logger.info(f"Enqueueing 5 songs for {guild_id} from the playlist")
    
    for i in range(min(5, len(songs))):
        song_name, song_id, youtube_url = songs[i]

        try:

            with yt_dlp.YoutubeDL(YDL_OPTS_STREAM) as ydl:
                info_dict = ydl.extract_info(youtube_url, download=False)
                
                song = info_dict.get('title', None)
                id = info_dict.get('id', None)
                original_url = info_dict.get('original_url', None)

                if not queue.playing:
                    queue.songs.append(song)
                    queue.ids.append(id)
                    queue.youtube_urls.append(original_url)
                    if not DOWNLOAD:
                        url = info_dict.get('url', None)
                        queue.urls.append(url)
                else:
                    queue.songs.append(song)
                    queue.ids.append(id)
                    queue.youtube_urls.append(original_url)

                    if not DOWNLOAD:
                        url = info_dict.get('url', None)
                        queue.urls.append(url)
        except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as error:
            logger.error(f'Failed to enqueue song "{song_name}" in guild with ID: {guild_id}')
            logger.error(f'Error: {error}')

            # Print to the text channel that this song failed
            asyncio.run_coroutine_threadsafe(
                queue.text_channel.send(f'{error} | Failed to enqueue song "{song_name}"!'),
                client.loop)
            
            continue

    task = client.loop.create_task(add_songs_to_queue(guild_id, songs[5:]))
    queue.tasks.append(task)


@tree.command(name="playlist-enqueue",
              description="Enqueues the playlist with the given name in the current queue")
@app_commands.describe(name='The name of the playlist', 
                       shuffle='If the songs will be enqueued in random orders')
async def pl_enqueue(interaction: discord.Interaction, name: str, shuffle: bool) -> None:
    guild_id = interaction.guild_id

    if not name.isalnum():
        await interaction.response.send_message("The name of the playlist must be alphanumeric!")
        return

    if len(name) > MAX_SONG_NAME_LENGTH:
        await interaction.response.send_message(f"The name of the playlist can only be lesser than {MAX_SONG_NAME_LENGTH} characters!")
        return

    await interaction.response.send_message("Processing...")

    path = [FILE_DIR, 'Guilds', str(guild_id), 'playlists']
    os.makedirs(os.path.join(*path), exist_ok=True)

    path += [f'{name}.csv']

    if not os.path.isfile(os.path.join(*path)):
        await interaction.edit_original_response(content=f'The playlist "{name}" does not exist!')
        return

    entries = []
    with open(os.path.join(*path), 'r+') as f:
        reader = csv.reader(f)
        for row in reader:
            entries.append(row)

    voice = interaction.user.voice

    if voice is None:
        await interaction.edit_original_response(content='You are not in a voice channel!')
        return
    else:
        voice_channel = voice.channel

    text_channel = interaction.channel

    if len(entries) == 1:
        logger.error(f'Only the header row exists for file "{name}.csv"!')
        return

    if shuffle:
        entries = [entries[0]] + random.sample(entries[1:], len(entries) - 1)

    song_name, song_id, youtube_url = entries[1]

    try:
        with yt_dlp.YoutubeDL(YDL_OPTS_STREAM) as ydl:
            # Disable search queries
            info_dict = ydl.extract_info(youtube_url, download=False)
            
            song = info_dict.get('title', None)
            id = info_dict.get('id', None)
            original_url = info_dict.get('original_url', None)

            queue = q.get(guild_id, None)
            if queue is None:
                queue = Queue(voice_channel, text_channel)
                q[guild_id] = queue

            if not queue.playing:
                queue.songs.append(song)
                queue.ids.append(id)
                queue.youtube_urls.append(original_url)
                if not DOWNLOAD:
                    url = info_dict.get('url', None)
                    queue.urls.append(url)
            else:
                queue.songs.append(song)
                queue.ids.append(id)
                queue.youtube_urls.append(original_url)

                if not DOWNLOAD:
                    url = info_dict.get('url', None)
                    queue.urls.append(url)

    except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as error:
        await interaction.edit_original_response(
            content=f'{error} | Failed to retrieve information from the link!')
        return
    
    try:
        if queue.voice_client is None:
            voice_client = await voice_channel.connect(timeout=VOICE_CALL_TIMEOUT,
                                                        reconnect=True,
                                                        self_mute=True,
                                                        self_deaf=True)
            queue.voice_client = voice_client

            await play_music(guild_id)

    except discord.ClientException as e:
        await interaction.edit_original_response(content='Failed to play the music!')
        return

    logger.info("Calling add_songs_to_queue to enqueue the rest of the songs")
    
    # Using a task to make it run concurrently
    task = client.loop.create_task(add_songs_to_queue(guild_id, entries[2:]))
    queue.tasks.append(task)

    logger.info("Got out of add_songs_to_queue")

    await interaction.edit_original_response(content=f'Successfully enqueued {len(entries) - 1} songs!')


if __name__ == '__main__':

    # OAuth is no longer working (as of November 2024)

    # Run a dry run for obtaining OAuth2 Device Token
    # logger.info('Waiting for OAuth2 Authentication...')
    # with yt_dlp.YoutubeDL(YDL_OPTS_STREAM) as ydl:
    #     info_dict = ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False)
    # logger.info('OAuth2 Authenticated!')

    client.run(TOKEN)
