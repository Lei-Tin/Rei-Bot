"""Private Discord panels for browsing and editing saved playlists."""

import asyncio
import logging

import discord

from playlists import PlaylistError, PlaylistStore

logger = logging.getLogger(__name__)
SONGS_PER_PAGE = 10
PLAYLISTS_PER_PAGE = 25


class PlaylistSelect(discord.ui.Select):
    def __init__(self, editor, options, *, songs=False):
        super().__init__(placeholder='Select songs to remove or move' if songs else 'Choose a playlist',
                         options=options, min_values=0 if songs else 1,
                         max_values=len(options) if songs else 1, row=0)
        self.editor = editor
        self.songs = songs

    async def callback(self, interaction):
        async with self.editor.lock:
            if self.songs:
                self.editor.selected = [int(value) for value in self.values]
                self.editor.status = ''
            else:
                self.editor.load(self.values[0])
            await self.editor.update(interaction)


class PlaylistEditor(discord.ui.View):
    def __init__(self, store: PlaylistStore, guild_id: int, owner_id: int, extract_song,
                 *, name=None, page=0):
        super().__init__(timeout=600)
        self.store = store
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.extract_song = extract_song
        self.snapshot = None
        self.page = 0
        self.selected = []
        self.status = ''
        self.busy = False
        self.message = None
        self.lock = asyncio.Lock()
        self.load(name, page)

    def load(self, name=None, page=0):
        self.snapshot = self.store.read(self.guild_id, name) if name is not None else None
        self.page = max(0, page)
        self.selected = []
        self.status = ''

    def reload(self):
        if self.snapshot is not None:
            try:
                self.snapshot = self.store.read(self.guild_id, self.snapshot.name)
            except PlaylistError:
                self.snapshot = None
                self.page = 0
            except OSError:
                # Keep the last display available so a storage error can still be reported.
                pass
        self.selected = []

    def button(self, label, callback, *, row=1, disabled=False, style=discord.ButtonStyle.secondary):
        button = discord.ui.Button(label=label, row=row, disabled=disabled, style=style)
        button.callback = callback
        self.add_item(button)

    def render(self):
        self.clear_items()
        if self.snapshot is None:
            names = self.store.names(self.guild_id)
            pages = max(1, (len(names) + PLAYLISTS_PER_PAGE - 1) // PLAYLISTS_PER_PAGE)
            self.page = min(self.page, pages - 1)
            visible = names[self.page * PLAYLISTS_PER_PAGE:(self.page + 1) * PLAYLISTS_PER_PAGE]
            description = '\n'.join(discord.utils.escape_markdown(name) for name in visible)
            embed = discord.Embed(title='Playlists', color=discord.Color.blurple(),
                                  description=description or 'No playlists yet. Create one to get started.')
            if visible:
                self.add_item(PlaylistSelect(self, [discord.SelectOption(label=name, value=name) for name in visible]))
            self.button('New playlist', self.create_playlist, style=discord.ButtonStyle.primary)
            count = len(names)
            unit = 'playlist' if count == 1 else 'playlists'
        else:
            songs = self.snapshot.songs
            pages = max(1, (len(songs) + SONGS_PER_PAGE - 1) // SONGS_PER_PAGE)
            self.page = min(self.page, pages - 1)
            start = self.page * SONGS_PER_PAGE
            visible = list(enumerate(songs[start:start + SONGS_PER_PAGE], start=start))
            description = '\n'.join(
                f'**{i + 1}.** {discord.utils.escape_markdown(song.name[:100])}' for i, song in visible)
            embed = discord.Embed(title=f'Playlist: {self.snapshot.name}', color=discord.Color.blurple(),
                                  description=description or 'This playlist is empty. Add some songs below.')
            if visible:
                self.add_item(PlaylistSelect(self, [discord.SelectOption(
                    label=f'{i + 1}. {song.name}'.replace('\n', ' ')[:100], value=str(i),
                    default=i in self.selected) for i, song in visible], songs=True))
            self.button('Playlists', self.show_library)
            self.button('Add songs', self.add_songs, row=2, style=discord.ButtonStyle.primary)
            self.button('Remove selected', self.remove_selected, row=2, disabled=not self.selected,
                        style=discord.ButtonStyle.danger)
            self.button('Move song', self.move_song, row=2, disabled=len(self.selected) != 1)
            count = len(songs)
            unit = 'song' if count == 1 else 'songs'
        self.button('Previous', self.previous_page, disabled=self.page == 0)
        self.button('Next', self.next_page, disabled=self.page == pages - 1)
        self.button('Refresh', self.refresh)
        self.button('Close', self.close)
        if self.status:
            status = self.status[:2048]
            for offset in range(0, len(status), 1024):
                embed.add_field(name='Status' if offset == 0 else 'Status (continued)',
                                value=status[offset:offset + 1024], inline=False)
        embed.set_footer(text=f'{count} {unit} · Page {self.page + 1}/{pages} · Changes save immediately')
        if self.busy:
            for item in self.children:
                item.disabled = True
        return embed

    async def update(self, interaction):
        payload = dict(content=None, embed=self.render(), view=self, allowed_mentions=discord.AllowedMentions.none())
        if interaction.response.is_done():
            self.message = await interaction.edit_original_response(**payload)
        else:
            await interaction.response.edit_message(**payload)
            self.message = await interaction.original_response()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message('Open your own editor with /playlist.', ephemeral=True)
            return False
        if self.is_finished():
            await interaction.response.send_message('This editor expired. Open a new one with /playlist.', ephemeral=True)
            return False
        if self.busy:
            await interaction.response.send_message('Adding songs. Please wait for this to finish.', ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content='This editor expired. Open a new one with /playlist.', view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, interaction, error, item):
        async with self.lock:
            self.reload()
            if isinstance(error, PlaylistError):
                self.status = str(error)
            else:
                logger.error('Playlist editor failed', exc_info=(type(error), error, error.__traceback__))
                self.status = 'Could not update the playlist. Refresh and try again.'
            await self.update(interaction)

    async def previous_page(self, interaction):
        async with self.lock:
            self.reload()
            self.page = max(0, self.page - 1)
            self.status = ''
            await self.update(interaction)

    async def next_page(self, interaction):
        async with self.lock:
            self.reload()
            self.page += 1
            self.status = ''
            await self.update(interaction)

    async def refresh(self, interaction):
        async with self.lock:
            self.reload()
            self.status = ''
            await self.update(interaction)

    async def show_library(self, interaction):
        async with self.lock:
            self.load()
            await self.update(interaction)

    async def close(self, interaction):
        async with self.lock:
            if self.busy:
                await interaction.response.send_message('Adding songs. Please wait for this to finish.', ephemeral=True)
                return
            await interaction.response.edit_message(content='Playlist editor closed.', embed=None, view=None)
            self.stop()

    async def create_playlist(self, interaction):
        await interaction.response.send_modal(CreatePlaylistModal(self))

    async def add_songs(self, interaction):
        await interaction.response.send_modal(AddSongsModal(self))

    async def move_song(self, interaction):
        await interaction.response.send_modal(MoveSongModal(self))

    async def remove_selected(self, interaction):
        async with self.lock:
            count = len(self.selected)
            self.snapshot = self.store.remove(self.guild_id, self.snapshot.name, self.selected,
                                              revision=self.snapshot.revision)
            self.selected = []
            self.status = f'Removed {count} {"song" if count == 1 else "songs"}.'
            await self.update(interaction)


class EditorModal(discord.ui.Modal):
    def __init__(self, editor, title):
        super().__init__(title=title, timeout=300)
        self.editor = editor

    async def interaction_check(self, interaction):
        return await self.editor.interaction_check(interaction)

    async def on_error(self, interaction, error):
        await self.editor.on_error(interaction, error, None)


class CreatePlaylistModal(EditorModal):
    def __init__(self, editor):
        super().__init__(editor, 'New playlist')
        self.name_input = discord.ui.TextInput(min_length=1, max_length=100,
                                               placeholder='e.g. favorites')
        self.add_item(discord.ui.Label(text='Playlist name (letters and numbers)', component=self.name_input))

    async def on_submit(self, interaction):
        async with self.editor.lock:
            snapshot = self.editor.store.create(self.editor.guild_id, self.name_input.value.strip())
            self.editor.load(snapshot.name)
            self.editor.status = 'Playlist created. Add songs below.'
            await self.editor.update(interaction)


class AddSongsModal(EditorModal):
    def __init__(self, editor):
        super().__init__(editor, 'Add songs')
        self.name = editor.snapshot.name
        self.submitted = False
        self.urls = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=2000,
                                        placeholder='https://www.youtube.com/watch?v=...')
        self.add_item(discord.ui.Label(text='Song URLs (one per line, up to 10)', component=self.urls,
                                      description='Single videos only. A video opened in a playlist adds just that video.'))

    async def on_submit(self, interaction):
        links = [(number, line.strip()) for number, line in enumerate(self.urls.value.splitlines(), 1) if line.strip()]
        if not 1 <= len(links) <= 10:
            await interaction.response.send_message('Enter 1–10 song URLs, one per line.', ephemeral=True)
            return
        started = False
        songs, failures = [], []
        try:
            async with self.editor.lock:
                if self.submitted:
                    await interaction.response.send_message('This request was already submitted. Check the playlist.', ephemeral=True)
                    return
                if self.editor.is_finished():
                    await interaction.response.send_message('This editor expired. Open a new one with /playlist.', ephemeral=True)
                    return
                if self.editor.busy:
                    await interaction.response.send_message('Adding songs. Please wait for this to finish.', ephemeral=True)
                    return
                self.submitted = True
                self.editor.busy = True
                started = True
                await interaction.response.defer()
                self.editor.status = 'Loading songs…'
                await self.editor.update(interaction)
            for number, link in links:
                try:
                    song = await asyncio.wait_for(asyncio.to_thread(self.editor.extract_song, link), timeout=45)
                    songs.append(song)
                except asyncio.TimeoutError:
                    failures.append(f'Line {number}: Loading this song timed out. Please try again.')
                except PlaylistError as error:
                    failures.append(f'Line {number}: {error}'[:190])
                except Exception:
                    failures.append(f'Line {number}: Could not load this song. Check the URL and try again.')
            async with self.editor.lock:
                if songs:
                    snapshot = self.editor.store.append(self.editor.guild_id, self.name, songs)
                    self.editor.load(snapshot.name, (len(snapshot.songs) - 1) // SONGS_PER_PAGE)
                else:
                    self.editor.reload()
                count = len(songs)
                self.editor.status = f'Added {count} {"song" if count == 1 else "songs"}.' if count else 'No songs were added.'
                if failures:
                    self.editor.status += '\n' + '\n'.join(failures)
        except asyncio.CancelledError:
            if started:
                self.editor.status = 'Adding songs was interrupted. No songs were added.'
            raise
        finally:
            if started:
                self.editor.busy = False
                if interaction.response.is_done() and not self.editor.is_finished():
                    await self.editor.update(interaction)


class MoveSongModal(EditorModal):
    def __init__(self, editor):
        super().__init__(editor, 'Move song')
        self.name = editor.snapshot.name
        self.revision = editor.snapshot.revision
        self.index = editor.selected[0]
        self.position = discord.ui.TextInput(max_length=10, placeholder=f'1–{len(editor.snapshot.songs)}')
        self.add_item(discord.ui.Label(text='New position in the playlist', component=self.position))

    async def on_submit(self, interaction):
        try:
            destination = int(self.position.value.strip()) - 1
        except ValueError:
            raise PlaylistError('Enter a whole number for the new position.') from None
        async with self.editor.lock:
            snapshot = self.editor.store.move(self.editor.guild_id, self.name, self.index, destination,
                                               revision=self.revision)
            self.editor.load(snapshot.name, max(0, destination) // SONGS_PER_PAGE)
            self.editor.status = f'Moved the song to position {destination + 1}.'
            await self.editor.update(interaction)
