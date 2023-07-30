"""
The main file for the bot
"""

from config import TOKEN, MAX_SONG_NAME_LENGTH
from Queue import Queue

import discord
from discord import app_commands

import os
import yt_dlp

import asyncio

intents = discord.Intents.default()

intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Mapping from guild id to queue and other information
q = {}  # Maps from int to Queue

discord.opus.load_opus('/opt/homebrew/Cellar/opus/1.4/lib/libopus.0.dylib')
if not discord.opus.is_loaded():
    raise RuntimeError('Opus failed to load')


@client.event
async def on_ready():
    # await tree.sync(guild=TEST_GUILD)
    await tree.sync()  # Use the above line if you only want it to work in one guild
    print("Rei Bot is ready!")


async def play_song(guild_id: int) -> None:
    print('Playing a song')

    queue = q.get(guild_id, None)
    if queue is None:
        raise RuntimeError('Queue is None!')

    song = queue.songs.pop(0) if queue.songs else ''
    id = queue.ids.pop(0) if queue.ids else ''
    voice_client = queue.voice_client

    path = ['Guilds', str(guild_id), f"{id}.mp3"]

    if song == '':
        await voice_client.disconnect()
        del q[guild_id]
    else:
        queue.current = song
        await queue.text_channel.send(f'Now playing: "{song[:MAX_SONG_NAME_LENGTH]}..."')
        voice_client.play(discord.FFmpegPCMAudio(os.path.join(*path)))

        while voice_client.is_playing():
            await asyncio.sleep(1)

        await play_song(guild_id)

@tree.command(name="play",
              description="Play a music with the provided link")
              # guild=TEST_GUILD)
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

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(*path, '%(id)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=False)
            title = info_dict.get('title', None)
            id = info_dict.get('id', None)

            if f"{id}.mp3" not in os.listdir(os.path.join(*path)):
                ydl.download([link])

            queue = q.get(guild_id, None)
            if queue is None:
                queue = Queue(voice_channel, text_channel)
                q[guild_id] = queue

                queue.songs.append(title)
                queue.ids.append(id)

                try:
                    voice_client = await voice_channel.connect()
                    queue.voice_client = voice_client
                    await play_song(guild_id)

                except Exception as e:
                    print(e)
                    await interaction.edit_original_response(content='Failed to play the music!')
            else:
                queue.songs.append(title)
                queue.ids.append(id)

            print('Successfully Enqueued')
            await interaction.edit_original_response(content='Added to queue!')

    except yt_dlp.utils.DownloadError:
        await interaction.edit_original_response(
            content='Failed to retrieve information from the link!')


@tree.command(name="queue",
              description="Shows the current queue")
              # guild=TEST_GUILD)
async def queue(interaction: discord.Interaction) -> None:
    print('Printing current queue')

    guild_id = interaction.guild_id
    queue = q.get(guild_id, None)
    if queue is None:
        await interaction.response.send_message("There is no queue!")
    else:
        await interaction.response.send_message(f"""
Currently playing: {q[interaction.guild_id].current}
Current queue:
{q[interaction.guild_id].show()}
        """)


client.run(TOKEN)
