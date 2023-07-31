"""
The main file for the bot
"""
import asyncio

from typing import Union

from config import *
from Queue import Queue
from utils import truncate

import discord
from discord import app_commands

import os
import yt_dlp

intents = discord.Intents.default()

# TEST_GUILD = discord.Object(id=[Your Guild ID HERE])

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
discord.opus.load_opus('/opt/homebrew/Cellar/opus/1.4/lib/libopus.0.dylib')
if not discord.opus.is_loaded():
    raise RuntimeError('Opus failed to load')


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

    if before.channel is not None and after.channel is None and member.bot is True:
        queue = q.get(guild_id, None)

        queue.playing = False
        queue.songs = []
        queue.ids = []
        queue.urls = []
        queue.current = ''


@client.event
async def on_ready() -> None:
    """
    Event triggered when the bot is ready
    """
    # await tree.sync(guild=TEST_GUILD)
    await tree.sync()  # Use the above line if you only want it to work in one guild
    print("Rei Bot is ready!")


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
    if not voice_client.is_connected():
        return

    if len(queue.songs) > 0:
        queue.playing = True

        song = queue.songs.pop(0) if queue.songs else ''
        id = queue.ids.pop(0) if queue.ids else ''

        queue.current = song

        if DOWNLOAD:
            path = ['Guilds', str(guild_id), f"{id}.mp3"]
            voice_client.play(discord.FFmpegPCMAudio(os.path.join(*path)),
                              after=lambda e: play_song(guild_id))
        else:
            url = queue.urls.pop(0) if queue.urls else ''
            voice_client.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS),
                              after=lambda e: play_song(guild_id))

        asyncio.run_coroutine_threadsafe(
            queue.text_channel.send(f'Now playing: "{truncate(song)}"!'),
            client.loop)
    else:
        asyncio.run_coroutine_threadsafe(voice_client.disconnect(), client.loop)
        asyncio.run_coroutine_threadsafe(
            queue.text_channel.send(f'Queue is now empty!'),
            client.loop)
        queue.playing = False


async def play_music(guild_id: int):
    """
    Play a song in the queue, the asynchronous function, first called when /play is called
    :param guild_id:
    :return:
    """
    print('Initializing play')

    queue = q.get(guild_id, None)
    if queue is None:
        return

    voice_client = queue.voice_client

    if len(queue.songs) > 0:
        queue.playing = True

        song = queue.songs.pop(0) if queue.songs else ''
        id = queue.ids.pop(0) if queue.ids else ''

        queue.current = song

        if DOWNLOAD:
            path = ['Guilds', str(guild_id), f"{id}.mp3"]
            voice_client.play(discord.FFmpegPCMAudio(os.path.join(*path)),
                              after=lambda e: play_song(guild_id))
        else:
            url = queue.urls.pop(0) if queue.urls else ''
            voice_client.play(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS),
                              after=lambda e: play_song(guild_id))

        await queue.text_channel.send(f'Now playing: "{truncate(song)}"!')
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
    print('Attempt to enqueue a song')

    voice = interaction.user.voice

    await interaction.response.send_message("Processing...")
    if voice is None:
        await interaction.edit_original_response(content='You are not in a voice channel!')
        return
    else:
        voice_channel = voice.channel

    text_channel = interaction.channel

    # interaction.message.content stores the information
    # interaction.response.send_message sends a message
    # interaction.guild_id gives the id of this message's guild
    guild_id = interaction.guild_id

    path = ['Guilds', str(guild_id)]

    os.makedirs(os.path.join(*path), exist_ok=True)

    if DOWNLOAD:
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'outtmpl': os.path.join(*path, '%(id)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
        }
    else:
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=False)
            song = info_dict.get('title', None)
            id = info_dict.get('id', None)

            if DOWNLOAD:
                if f"{id}.mp3" not in os.listdir(os.path.join(*path)):
                    ydl.download([link])

            queue = q.get(guild_id, None)
            if queue is None or not queue.playing:
                queue = Queue(voice_channel, text_channel)
                q[guild_id] = queue

                queue.songs.append(song)
                queue.ids.append(id)

                if not DOWNLOAD:
                    url = info_dict.get('url', None)
                    queue.urls.append(url)
                try:
                    voice_client = await voice_channel.connect(timeout=2.5,
                                                               reconnect=True,
                                                               self_mute=True,
                                                               self_deaf=True)
                    queue.voice_client = voice_client
                    await play_music(guild_id)

                except RuntimeError as e:
                    await interaction.edit_original_response(content='Failed to play the music!')
                    return
            else:
                queue.songs.append(song)
                queue.ids.append(id)
                if not DOWNLOAD:
                    url = info_dict.get('url', None)
                    queue.urls.append(url)

            print('Successfully Enqueued')
            await interaction.edit_original_response(
                content=f'Successfully enqueued "**{truncate(song)}**"!'
            )

    except yt_dlp.utils.DownloadError:
        await interaction.edit_original_response(
            content='Failed to retrieve information from the link!')


@tree.command(name="queue",
              description="Shows the current queue")
async def queue(interaction: discord.Interaction) -> None:
    print('Printing current queue')
    await interaction.response.send_message("Processing...")

    guild_id = interaction.guild_id
    queue = q.get(guild_id, None)
    if queue is None:
        await interaction.edit_original_response(content="There is no queue!")
    else:
        await interaction.edit_original_response(content=f"""
Currently playing: **{truncate(queue.current)}**
Coming up:
{q[guild_id].show()}
        """)


@tree.command(name="skip",
              description="Skips the current music playing")
async def skip(interaction: discord.Interaction) -> None:
    print('Skipping current song')
    await interaction.response.send_message("Processing...")

    guild_id = interaction.guild_id
    queue = q.get(guild_id, None)

    if queue is None:
        await interaction.edit_original_response(content="There is no queue!")
    else:
        if queue.voice_client is not None:
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
    print('Clearing current queue')
    await interaction.response.send_message("Processing...")

    guild_id = interaction.guild_id
    queue = q.get(guild_id, None)

    if queue is None:
        await interaction.edit_original_response(content="There is no queue!")
    else:
        if queue.voice_client is not None:
            await queue.voice_client.disconnect()
            await interaction.edit_original_response(content="Queue cleared!")

        else:
            await interaction.edit_original_response(content="Something went wrong!")


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
    print('Attempting to remove a song')
    guild_id = interaction.guild_id

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
    await interaction.edit_original_response(content=f'Successfully removed "{song}" at index **{index}**!')

client.run(TOKEN)
