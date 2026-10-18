import asyncio
import csv
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Rei'))
from playlists import PlaylistError, PlaylistSong, PlaylistStore
from playlist_links import PLAYLIST_LINK_MESSAGE, normalize_song_url
from playlist_ui import AddSongsModal, CreatePlaylistModal, MoveSongModal, PlaylistEditor, PlaylistSelect


def song(number):
    return PlaylistSong(f'Song {number}', str(number), f'https://example.com/{number}')


def interaction(user_id=20, guild_id=10):
    message = SimpleNamespace(edit=AsyncMock())
    response = SimpleNamespace(is_done=MagicMock(return_value=False), send_message=AsyncMock(),
                               edit_message=AsyncMock(), send_modal=AsyncMock())

    async def defer():
        response.is_done.return_value = True

    response.defer = AsyncMock(side_effect=defer)
    return SimpleNamespace(user=SimpleNamespace(id=user_id), guild_id=guild_id, response=response,
                           original_response=AsyncMock(return_value=message),
                           edit_original_response=AsyncMock(return_value=message))


class PlaylistStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = PlaylistStore(Path(self.folder.name))

    def test_reads_existing_csv_and_round_trips_unicode_quotes_and_newlines(self):
        path = Path(self.folder.name, '10', 'playlists', 'favorites.csv')
        path.parent.mkdir(parents=True)
        original = PlaylistSong('歌曲, "live"\nversion', 'abc', 'https://example.com/a')
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['name', 'id', 'orig_url'])
            writer.writerow([original.name, original.id, original.url])
        self.assertEqual(self.store.read(10, 'favorites').songs, (original,))
        self.store.append(10, 'favorites', [song(2)])
        self.assertEqual(self.store.read(10, 'favorites').songs, (original, song(2)))

    def test_names_are_sorted_and_guilds_are_isolated(self):
        for name in ('Zulu', 'alpha', '空白'):
            self.store.create(10, name)
        self.store.create(11, 'other')
        self.assertEqual(self.store.names(10), ['alpha', 'Zulu', '空白'])
        self.assertEqual(self.store.names(99), [])
        for name in ('../escape', '', 'a' * 101, 'two words'):
            with self.subTest(name=name), self.assertRaises(PlaylistError):
                self.store.create(10, name)

    def test_bulk_remove_keeps_an_empty_playlist_and_header(self):
        current = self.store.append(10, 'test', [song(1), song(2), song(3)], create=True)
        current = self.store.remove(10, 'test', [0, 2], revision=current.revision)
        self.assertEqual(current.songs, (song(2),))
        current = self.store.remove(10, 'test', [0], revision=current.revision)
        self.assertEqual(current.songs, ())
        self.assertIn('test', self.store.names(10))
        self.assertEqual(self.store.read(10, 'test'), current)

    def test_invalid_indices_and_stale_edit_leave_data_unchanged(self):
        old = self.store.append(10, 'test', [song(1), song(2)], create=True)
        current = self.store.append(10, 'test', [song(3)])
        for operation in (
            lambda: self.store.remove(10, 'test', [-1]),
            lambda: self.store.remove(10, 'test', [3]),
            lambda: self.store.remove(10, 'test', [], revision=current.revision),
            lambda: self.store.remove(10, 'test', [0], revision=old.revision),
            lambda: self.store.move(10, 'test', 0, 1, revision=old.revision),
        ):
            with self.assertRaises(PlaylistError):
                operation()
            self.assertEqual(self.store.read(10, 'test'), current)

    def test_move_uses_final_position_and_preserves_duplicates(self):
        current = self.store.append(10, 'test', [song(1), song(2), song(1)], create=True)
        current = self.store.move(10, 'test', 0, 2, revision=current.revision)
        self.assertEqual(current.songs, (song(2), song(1), song(1)))
        current = self.store.move(10, 'test', 2, 0, revision=current.revision)
        self.assertEqual(current.songs, (song(1), song(2), song(1)))

    def test_concurrent_appends_do_not_overwrite_each_other(self):
        self.store.create(10, 'test')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: self.store.append(10, 'test', [song(i)]), range(20)))
        self.assertEqual({s.id for s in self.store.read(10, 'test').songs}, {str(i) for i in range(20)})

    def test_failed_atomic_replace_preserves_original_and_cleans_temporary_file(self):
        original = self.store.append(10, 'test', [song(1)], create=True)
        with patch('playlists.os.replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.store.append(10, 'test', [song(2)])
        self.assertEqual(self.store.read(10, 'test'), original)
        self.assertEqual(list(Path(self.folder.name).rglob('*.tmp')), [])

    def test_invalid_csv_is_reported_without_overwriting_it(self):
        self.store.create(10, 'test')
        path = Path(self.folder.name, '10', 'playlists', 'test.csv')
        path.write_text('broken,header\na,b,c\n')
        with self.assertRaises(PlaylistError):
            self.store.append(10, 'test', [song(1)])
        self.assertEqual(path.read_text(), 'broken,header\na,b,c\n')


class PlaylistEditorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = PlaylistStore(Path(self.folder.name))
        self.store.append(10, 'test', [song(i) for i in range(23)], create=True)
        self.view = PlaylistEditor(self.store, 10, 20, lambda link: song(link), name='test')
        self.addCleanup(self.view.stop)

    async def test_song_pagination_and_component_payload_fit_discord_limits(self):
        embed = self.view.render()
        select = next(item for item in self.view.children if isinstance(item, PlaylistSelect))
        self.assertEqual([option.value for option in select.options], [str(i) for i in range(10)])
        self.assertIn('Page 1/3', embed.footer.text)
        await self.view.next_page(interaction())
        self.assertEqual(self.view.page, 1)
        self.view.page = 2
        self.view.selected = [22]
        embed = self.view.render()
        select = next(item for item in self.view.children if isinstance(item, PlaylistSelect))
        self.assertEqual([option.value for option in select.options], ['20', '21', '22'])
        self.assertTrue(select.options[-1].default)
        self.assertEqual(select.max_values, 3)
        self.assertLessEqual(len(embed.description), 4096)
        for row in self.view.to_components():
            self.assertLessEqual(len(row['components']), 5)
        self.assertLessEqual(len(self.view.to_components()), 5)

    async def test_library_paginates_more_than_25_playlists(self):
        for i in range(30):
            self.store.create(10, f'list{i:02}')
        self.view.load()
        self.view.render()
        select = next(item for item in self.view.children if isinstance(item, PlaylistSelect))
        self.assertEqual(len(select.options), 25)
        await self.view.next_page(interaction())
        select = next(item for item in self.view.children if isinstance(item, PlaylistSelect))
        self.assertEqual(len(select.options), 6)
        select._values = ['test']
        await select.callback(interaction())
        self.assertEqual(self.view.snapshot.name, 'test')
        self.assertEqual(self.view.page, 0)

    async def test_select_and_remove_on_last_page_clamps_page(self):
        self.view.page = 2
        self.view.render()
        select = next(item for item in self.view.children if isinstance(item, PlaylistSelect))
        select._values = ['20', '21', '22']
        await select.callback(interaction())
        self.assertEqual(self.view.selected, [20, 21, 22])
        await self.view.remove_selected(interaction())
        self.assertEqual(len(self.store.read(10, 'test').songs), 20)
        self.assertEqual(self.view.page, 1)
        self.assertEqual(self.view.selected, [])

    async def test_stale_delete_refreshes_instead_of_deleting_the_wrong_song(self):
        self.view.selected = [0]
        updated = self.store.remove(10, 'test', [0])
        event = interaction()
        with self.assertRaises(PlaylistError) as raised:
            await self.view.remove_selected(event)
        await self.view.on_error(event, raised.exception, None)
        self.assertEqual(self.store.read(10, 'test'), updated)
        self.assertEqual(self.view.snapshot, updated)
        self.assertEqual(self.view.selected, [])
        self.assertIn('changed', self.view.status)

    async def test_create_empty_playlist_and_add_multiple_urls_with_partial_failure(self):
        modal = CreatePlaylistModal(self.view)
        modal.name_input._value = 'newlist'
        await modal.on_submit(interaction())
        self.assertEqual(self.view.snapshot.songs, ())

        def extract(link):
            if link == 'bad':
                raise PlaylistError('That link is unavailable.')
            return song(link)

        self.view.extract_song = extract
        modal = AddSongsModal(self.view)
        modal.urls._value = 'one\n\nbad\ntwo'
        event = interaction()
        await modal.on_submit(event)
        self.assertEqual(self.store.read(10, 'newlist').songs, (song('one'), song('two')))
        self.assertIn('Line 3:', self.view.status)
        self.assertFalse(self.view.busy)
        event.response.defer.assert_awaited_once()
        self.assertFalse(any(item.disabled for item in self.view.children if isinstance(item, PlaylistSelect)))

    async def test_add_keeps_concurrent_external_additions(self):
        def extract(link):
            self.store.append(10, 'test', [song('external')])
            return song('new')

        self.view.extract_song = extract
        modal = AddSongsModal(self.view)
        modal.urls._value = 'new'
        await modal.on_submit(interaction())
        self.assertEqual(self.store.read(10, 'test').songs[-2:], (song('external'), song('new')))

    async def test_add_failure_restores_enabled_controls(self):
        modal = AddSongsModal(self.view)
        modal.urls._value = 'new'
        event = interaction()
        with patch.object(self.store, 'append', side_effect=PlaylistError('Playlist is unavailable.')):
            with self.assertRaises(PlaylistError) as raised:
                await modal.on_submit(event)
        await modal.on_error(event, raised.exception)
        self.assertFalse(self.view.busy)
        add = next(item for item in self.view.children if getattr(item, 'label', '') == 'Add songs')
        self.assertFalse(add.disabled)

    async def test_slow_extraction_keeps_event_loop_responsive_and_blocks_overlapping_edits(self):
        started, release = threading.Event(), threading.Event()

        def extract(link):
            started.set()
            release.wait(timeout=2)
            return song('new')

        self.view.extract_song = extract
        modal = AddSongsModal(self.view)
        modal.urls._value = 'new'
        task = asyncio.create_task(modal.on_submit(interaction()))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            self.assertTrue(self.view.busy)
            self.assertFalse(await self.view.interaction_check(interaction()))
        finally:
            release.set()
            await task
        self.assertFalse(self.view.busy)

    async def test_move_modal_uses_captured_song_and_final_position(self):
        self.view.selected = [22]
        modal = MoveSongModal(self.view)
        modal.position._value = '1'
        await modal.on_submit(interaction())
        self.assertEqual(self.store.read(10, 'test').songs[0], song(22))
        self.assertEqual(self.view.page, 0)

    async def test_add_rejects_more_than_ten_urls(self):
        modal = AddSongsModal(self.view)
        modal.urls._value = '\n'.join(['url'] * 11)
        event = interaction()
        await modal.on_submit(event)
        event.response.send_message.assert_awaited_once()
        self.assertEqual(len(self.store.read(10, 'test').songs), 23)

    async def test_other_users_other_guilds_and_expired_editors_are_rejected(self):
        for event in (interaction(user_id=21), interaction(guild_id=11)):
            self.assertFalse(await self.view.interaction_check(event))
            self.assertTrue(event.response.send_message.call_args.kwargs['ephemeral'])
        self.view.stop()
        modal = CreatePlaylistModal(self.view)
        self.assertFalse(await modal.interaction_check(interaction()))

    async def test_timeout_disables_controls_and_close_removes_them(self):
        original = self.store.read(10, 'test')
        self.view.render()
        self.view.message = SimpleNamespace(edit=AsyncMock())
        await self.view.on_timeout()
        self.assertTrue(all(item.disabled for item in self.view.children))
        self.view.message.edit.assert_awaited_once()
        event = interaction()
        await self.view.close(event)
        self.assertIsNone(event.response.edit_message.call_args.kwargs['view'])
        self.assertTrue(self.view.is_finished())
        self.assertEqual(self.store.read(10, 'test'), original)

    async def test_playlist_and_invalid_links_do_not_block_valid_links_or_further_additions(self):
        self.view.extract_song = lambda link: PlaylistSong('New song', 'new', normalize_song_url(link))
        modal = AddSongsModal(self.view)
        modal.urls._value = ('https://www.youtube.com/playlist?list=PLdemo\n'
                             'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLdemo\n'
                             'not a link')
        await modal.on_submit(interaction())
        songs = self.store.read(10, 'test').songs
        self.assertEqual(len(songs), 24)
        self.assertEqual(songs[-1].url, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        self.assertIn('Line 1:', self.view.status)
        self.assertIn('Line 3:', self.view.status)
        second = AddSongsModal(self.view)
        second.urls._value = 'https://youtu.be/aqz-KE-bpKQ'
        await second.on_submit(interaction())
        self.assertEqual(len(self.store.read(10, 'test').songs), 25)

    async def test_all_ten_failed_links_are_reported_without_changing_playlist(self):
        original = self.store.read(10, 'test')

        def fail(link):
            raise PlaylistError(PLAYLIST_LINK_MESSAGE)

        self.view.extract_song = fail
        modal = AddSongsModal(self.view)
        modal.urls._value = '\n'.join(['https://www.youtube.com/playlist?list=PLdemo'] * 10)
        await modal.on_submit(interaction())
        self.assertEqual(self.store.read(10, 'test'), original)
        self.assertFalse(self.view.busy)
        embed = self.view.render()
        displayed = ''.join(field.value for field in embed.fields)
        self.assertIn('No songs were added.', displayed)
        for line in range(1, 11):
            self.assertIn(f'Line {line}:', displayed)
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
        self.assertLessEqual(len(embed), 6000)

    async def test_timed_out_extraction_cannot_add_a_song_when_the_thread_finishes_later(self):
        original = self.store.read(10, 'test')
        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        def extract(link):
            started.set()
            release.wait(timeout=3)
            finished.set()
            return song('late')

        actual_wait_for = asyncio.wait_for

        async def short_wait(awaitable, timeout):
            task = asyncio.create_task(awaitable)
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            return await actual_wait_for(task, timeout=0.01)

        self.view.extract_song = extract
        modal = AddSongsModal(self.view)
        modal.urls._value = 'https://example.com/slow'
        try:
            with patch('playlist_ui.asyncio.wait_for', new=short_wait):
                await modal.on_submit(interaction())
            self.assertIn('timed out', self.view.status)
            self.assertFalse(self.view.busy)
        finally:
            release.set()
        self.assertTrue(await asyncio.to_thread(finished.wait, 1))
        self.assertEqual(self.store.read(10, 'test'), original)
        self.assertFalse(next(item for item in self.view.children if getattr(item, 'label', '') == 'Add songs').disabled)

    async def test_duplicate_and_overlapping_submissions_do_not_add_twice(self):
        started, release = threading.Event(), threading.Event()

        def extract(link):
            started.set()
            release.wait(timeout=3)
            return song('once')

        self.view.extract_song = extract
        modal = AddSongsModal(self.view)
        modal.urls._value = 'https://example.com/song'
        overlapping = AddSongsModal(self.view)
        overlapping.urls._value = modal.urls.value
        task = asyncio.create_task(modal.on_submit(interaction()))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            duplicate_event = interaction()
            await modal.on_submit(duplicate_event)
            self.assertIn('already submitted', duplicate_event.response.send_message.call_args.args[0])
            overlap_event = interaction()
            await overlapping.on_submit(overlap_event)
            self.assertIn('Please wait', overlap_event.response.send_message.call_args.args[0])
            close_event = interaction()
            await self.view.close(close_event)
            self.assertFalse(self.view.is_finished())
        finally:
            release.set()
            await task
        self.assertEqual(self.store.read(10, 'test').songs.count(song('once')), 1)
        await modal.on_submit(interaction())
        self.assertEqual(self.store.read(10, 'test').songs.count(song('once')), 1)

    async def test_cancelled_add_restores_controls_without_saving_partial_results(self):
        started, release = threading.Event(), threading.Event()

        def extract(link):
            started.set()
            release.wait(timeout=3)
            return song('cancelled')

        original = self.store.read(10, 'test')
        self.view.extract_song = extract
        modal = AddSongsModal(self.view)
        modal.urls._value = 'https://example.com/song'
        task = asyncio.create_task(modal.on_submit(interaction()))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        self.assertFalse(self.view.busy)
        self.assertEqual(self.store.read(10, 'test'), original)
        self.assertFalse(next(item for item in self.view.children if getattr(item, 'label', '') == 'Add songs').disabled)

    async def test_failed_discord_acknowledgement_does_not_leave_editor_busy(self):
        original = self.store.read(10, 'test')
        modal = AddSongsModal(self.view)
        modal.urls._value = 'https://example.com/song'
        event = interaction()
        event.response.defer.side_effect = RuntimeError('Discord unavailable')
        with self.assertRaises(RuntimeError):
            await modal.on_submit(event)
        self.assertFalse(self.view.busy)
        self.assertEqual(self.store.read(10, 'test'), original)

    async def test_submitting_a_modal_after_close_does_not_save_any_songs(self):
        original = self.store.read(10, 'test')
        modal = AddSongsModal(self.view)
        modal.urls._value = 'https://example.com/song'
        await self.view.close(interaction())
        event = interaction()
        await modal.on_submit(event)
        self.assertIn('expired', event.response.send_message.call_args.args[0])
        self.assertEqual(self.store.read(10, 'test'), original)


if __name__ == '__main__':
    unittest.main()
