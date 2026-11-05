"""Exercise playback with real callbacks, worker threads, and isolated Discord doubles."""
import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import test_playlist_commands as command_tests
from playlists import PlaylistError, PlaylistSong


class Voice:
    def __init__(self):
        self.connected = True
        self.playing = False
        self.after = None
        self.played = []
        self.play_threads = []
        self.disconnect = AsyncMock(side_effect=self._disconnect)

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.playing

    def play(self, source, *, after):
        if self.playing:
            raise RuntimeError('Already playing audio.')
        self.played.append(source.url)
        self.play_threads.append(threading.get_ident())
        self.after = after
        self.playing = True

    def finish(self, error=None):
        self.playing = False
        callback, self.after = self.after, None
        if callback is not None:
            thread = threading.Thread(target=callback, args=(error,))
            thread.start()
            thread.join(timeout=1)
            assert not thread.is_alive()

    def stop(self):
        self.finish()

    async def _disconnect(self, **kwargs):
        self.connected = False
        self.stop()


def media_info(name):
    return dict(title=name, id=name, webpage_url=f'https://example.com/{name}', url=f'stream:{name}')


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        command_tests.PlaylistCommandTests.setUpClass()
        cls.bot = command_tests.PlaylistCommandTests.bot
        cls.media = command_tests.PlaylistCommandTests.media

    async def asyncSetUp(self):
        self.bot.q.clear()
        self.voice = Voice()
        self.listener = SimpleNamespace(id=20, bot=False)
        # Before connect(), the bot is not yet included in channel.members.
        self.channel = SimpleNamespace(members=[self.listener], connect=AsyncMock(return_value=self.voice))
        self.text = SimpleNamespace(send=AsyncMock())
        self.event = self.interaction()
        self.source_factory = patch.object(self.bot.discord, 'FFmpegPCMAudio',
            side_effect=lambda url, **kwargs: SimpleNamespace(url=url, cleanup=MagicMock()))
        self.source_factory.start()
        self.addCleanup(self.source_factory.stop)
        self.addAsyncCleanup(self.clean_queues)

    async def clean_queues(self):
        for guild_id, queue in tuple(self.bot.q.items()):
            await self.bot.close_queue(guild_id, queue)

    def interaction(self):
        return SimpleNamespace(guild_id=10, channel=self.text,
            user=SimpleNamespace(id=20, voice=SimpleNamespace(channel=self.channel)),
            response=SimpleNamespace(send_message=AsyncMock()), edit_original_response=AsyncMock())

    def queue(self, *names, pending=0, guild_id=10):
        queue = self.bot.Queue(self.channel, self.text)
        queue.voice_client = self.voice
        queue.pending_songs = pending
        self.bot.q[guild_id] = queue
        for name in names:
            self.bot.append_song(queue, media_info(name))
        return queue

    async def until(self, predicate):
        async def wait():
            while not predicate():
                await asyncio.sleep(0)
        await asyncio.wait_for(wait(), 2)

    async def test_skip_advances_once_and_duplicate_audio_callbacks_are_ignored(self):
        queue = self.queue('A', 'B', 'C')
        await self.bot.play_music(10, queue)
        old_callback = self.voice.after
        await self.bot.skip.callback(self.event)
        await self.until(lambda: queue.current == 'B')
        old_callback(None)
        await self.until(lambda: not queue.tasks)
        self.assertEqual(self.voice.played, ['stream:A', 'stream:B'])
        self.assertEqual(queue.songs, ['C'])
        self.assertEqual(queue.current, 'B')
        self.assertEqual(set(self.voice.play_threads), {threading.get_ident()})

    async def test_concurrent_start_connects_and_pops_only_once(self):
        queue = self.queue('A', 'B')
        queue.voice_client = None
        await asyncio.gather(*(self.bot.play_music(10, queue) for _ in range(5)))
        self.channel.connect.assert_awaited_once()
        self.assertEqual(self.voice.played, ['stream:A'])
        self.assertEqual(queue.songs, ['B'])

    async def test_playlist_of_77_songs_joins_with_only_the_requester_in_voice(self):
        songs = tuple(PlaylistSong(f'Song {i}', str(i), f'https://example.com/{i}') for i in range(77))
        with patch.object(self.bot.playlist_store, 'read', return_value=SimpleNamespace(songs=songs)), \
                patch.object(self.bot, 'extract_playback_song', side_effect=lambda guild, link: media_info(link.rsplit('/', 1)[1])):
            await self.bot.pl_enqueue.callback(self.event, 'Favorites', False)
            queue = self.bot.q[10]
            self.assertIn('Enqueueing 77 songs', self.event.edit_original_response.call_args.kwargs['content'])
            await self.until(lambda: not queue.tasks)
        self.channel.connect.assert_awaited_once()
        self.assertIs(self.bot.q[10], queue)
        self.assertEqual(queue.current, '0')
        self.assertEqual(self.voice.played, ['stream:0'])
        self.assertEqual(len(queue.songs), 76)
        self.assertEqual(queue.pending_songs, 0)

    async def test_play_joins_voice_when_the_requester_is_the_only_listener(self):
        with patch.object(self.bot, 'extract_playback_song', return_value=media_info('First')):
            await self.bot.play.callback(self.event, 'https://example.com/first')
        self.channel.connect.assert_awaited_once()
        self.assertEqual(self.voice.played, ['stream:First'])
        self.assertEqual(self.bot.q[10].current, 'First')

    async def test_two_bots_do_not_count_as_listeners(self):
        self.channel.members = [SimpleNamespace(bot=True), SimpleNamespace(bot=True)]
        queue = self.queue('A')
        queue.voice_client = None
        await self.bot.play_music(10, queue)
        self.channel.connect.assert_not_awaited()
        self.assertEqual(self.voice.played, [])
        self.assertNotIn(10, self.bot.q)
        self.assertIn('no listeners', self.text.send.call_args.args[0])

    async def test_listener_leaving_during_connect_does_not_start_audio(self):
        queue = self.queue('A')
        queue.voice_client = None

        async def connect(**kwargs):
            self.channel.members = [SimpleNamespace(bot=True)]
            return self.voice

        self.channel.connect.side_effect = connect
        await self.bot.play_music(10, queue)
        self.channel.connect.assert_awaited_once()
        self.assertEqual(self.voice.played, [])
        self.voice.disconnect.assert_awaited_once()
        self.assertNotIn(10, self.bot.q)
        self.assertIn('no listeners', self.text.send.call_args.args[0])

    async def test_last_listener_leaving_stops_before_the_next_track(self):
        queue = self.queue('A', 'B')
        await self.bot.play_music(10, queue)
        self.channel.members = [SimpleNamespace(bot=True)]
        self.voice.finish()
        await self.until(lambda: 10 not in self.bot.q)
        self.assertEqual(self.voice.played, ['stream:A'])
        self.voice.disconnect.assert_awaited_once()
        self.assertIn('no listeners', self.text.send.call_args.args[0])

    async def test_empty_ready_queue_waits_for_pending_song_then_resumes(self):
        queue = self.queue('A', pending=1)
        await self.bot.play_music(10, queue)
        self.voice.finish()
        await self.until(lambda: not queue.playing)
        self.assertIs(self.bot.q[10], queue)
        self.voice.disconnect.assert_not_awaited()
        with patch.object(self.bot, 'load_playback_song', AsyncMock(return_value=media_info('B'))):
            await self.bot.add_songs_to_queue(10, queue, [PlaylistSong('B', 'B', 'https://example.com/B')])
        self.assertEqual(self.voice.played, ['stream:A', 'stream:B'])
        self.assertEqual(queue.pending_songs, 0)
        self.voice.finish()
        await self.until(lambda: 10 not in self.bot.q)
        self.voice.disconnect.assert_awaited_once()

    async def test_clear_ignores_old_audio_callback_after_replacement(self):
        old = self.queue('A', 'B')
        await self.bot.play_music(10, old)
        old_callback = self.voice.after
        await self.bot.clear.callback(self.event)
        fresh = self.queue('New')
        old_callback(None)
        await asyncio.sleep(0)
        self.assertIs(self.bot.q[10], fresh)
        self.assertEqual(fresh.songs, ['New'])
        self.assertFalse(fresh.playing)
        self.assertEqual(old.pending_songs, 0)

    async def test_cancelled_loader_cannot_write_into_a_new_session(self):
        loop = asyncio.get_running_loop()
        started, completed = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        worker_threads = []

        def extract(guild_id, link):
            worker_threads.append(threading.get_ident())
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(2):
                    raise AssertionError('Test worker was never released')
                return media_info('Old')
            finally:
                loop.call_soon_threadsafe(completed.set)

        old = self.queue(pending=6)
        songs = [PlaylistSong(str(i), str(i), f'https://example.com/{i}') for i in range(6)]
        with patch.object(self.bot, 'extract_playback_song', side_effect=extract) as extraction:
            task = self.bot.track_queue_task(old, self.bot.add_songs_to_queue(10, old, songs))
            try:
                await asyncio.wait_for(started.wait(), 1)
                await self.bot.clear.callback(self.event)
                fresh = self.queue('New')
                release.set()
                await asyncio.wait_for(completed.wait(), 1)
                await asyncio.sleep(0)
                self.assertTrue(task.cancelled())
                self.assertEqual(fresh.songs, ['New'])
                self.assertEqual(fresh.pending_songs, 0)
                self.assertEqual(old.pending_songs, 0)
                self.assertFalse(old.tasks)
                extraction.assert_called_once()
                self.assertNotIn(threading.get_ident(), worker_threads)
            finally:
                release.set()

    async def test_play_extraction_leaves_loop_responsive_and_clear_cancels_result(self):
        loop = asyncio.get_running_loop()
        started, completed = asyncio.Event(), asyncio.Event()
        release = threading.Event()

        def extract(guild_id, link):
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(2):
                    raise AssertionError('Event loop blocked during extraction')
                return media_info('Old')
            finally:
                loop.call_soon_threadsafe(completed.set)

        with patch.object(self.bot, 'extract_playback_song', side_effect=extract):
            command = asyncio.create_task(self.bot.play.callback(self.event, 'https://example.com/old'))
            try:
                await asyncio.wait_for(started.wait(), 1)
                # These commands finish while yt-dlp is still waiting on its worker thread.
                await self.bot.queue.callback(self.interaction())
                await self.bot.clear.callback(self.interaction())
                await command
                fresh = self.queue('New')
                release.set()
                await asyncio.wait_for(completed.wait(), 1)
                self.assertEqual(fresh.songs, ['New'])
                self.assertIn('cleared', self.event.edit_original_response.call_args.kwargs['content'])
                self.assertEqual(self.voice.played, [])
            finally:
                release.set()
                await command

    async def test_playlist_enqueue_first_extraction_is_also_off_loop(self):
        snapshot = SimpleNamespace(songs=(PlaylistSong('First', 'first', 'https://example.com/first'),))
        with patch.object(self.bot.playlist_store, 'read', return_value=snapshot), \
                patch.object(self.bot, 'extract_playback_song', side_effect=lambda *args: media_info('First')):
            await self.bot.pl_enqueue.callback(self.event, 'test', False)
            queue = self.bot.q[10]
            await self.until(lambda: not queue.tasks)
        self.assertEqual(queue.current, 'First')
        self.assertEqual(queue.pending_songs, 0)
        self.channel.connect.assert_awaited_once()

    async def test_one_failed_and_one_timed_out_song_do_not_stop_the_playlist(self):
        queue = self.queue(pending=3)
        songs = [PlaylistSong(n, n, f'https://example.com/{n}') for n in ('A', 'B', 'C')]
        with patch.object(self.bot, 'load_playback_song', AsyncMock(side_effect=[
                PlaylistError('Unavailable'), asyncio.TimeoutError(), media_info('C')])):
            await self.bot.add_songs_to_queue(10, queue, songs)
        self.assertEqual(queue.pending_songs, 0)
        self.assertEqual(queue.current, 'C')
        failures = [call.args[0] for call in self.text.send.call_args_list if 'Failed' in call.args[0]]
        self.assertEqual(len(failures), 2)

    async def test_play_timeout_retires_empty_queue(self):
        with patch.object(self.bot, 'load_playback_song', AsyncMock(side_effect=asyncio.TimeoutError())):
            await self.bot.play.callback(self.event, 'https://example.com/slow')
        self.assertNotIn(10, self.bot.q)
        self.assertIn('timed out', self.event.edit_original_response.call_args.kwargs['content'])

    async def test_clear_interrupts_a_pending_voice_connection(self):
        queue = self.queue('A')
        queue.voice_client = None
        started = asyncio.Event()

        async def connect(**kwargs):
            started.set()
            await asyncio.Future()

        self.channel.connect.side_effect = connect
        task = self.bot.track_queue_task(queue, self.bot.play_music(10, queue))
        await started.wait()
        await asyncio.wait_for(self.bot.clear.callback(self.event), 1)
        self.assertTrue(task.cancelled())
        self.assertNotIn(10, self.bot.q)
        self.assertFalse(queue.tasks)

    async def test_another_voice_channel_cannot_enqueue_into_this_session(self):
        queue = self.queue('A')
        self.event.user.voice.channel = SimpleNamespace()
        with patch.object(self.bot, 'load_playback_song') as extraction:
            await self.bot.play.callback(self.event, 'https://example.com/B')
        extraction.assert_not_called()
        self.assertEqual(queue.songs, ['A'])
        self.assertIn('other channel', self.event.edit_original_response.call_args.kwargs['content'])

    async def test_remove_keeps_all_queue_fields_aligned_in_download_mode(self):
        queue = self.queue('A', 'B')
        with patch.object(self.bot, 'DOWNLOAD', True):
            await self.bot.remove.callback(self.event, 1)
        self.assertEqual(queue.songs, ['B'])
        self.assertEqual(queue.ids, ['B'])
        self.assertEqual(queue.urls, ['stream:B'])
        self.assertEqual(queue.youtube_urls, ['https://example.com/B'])
        self.assertEqual(queue.gains, [0.0])

    async def test_clear_during_play_connection_still_finishes_the_command_response(self):
        started = asyncio.Event()

        async def connect(**kwargs):
            started.set()
            await asyncio.Future()

        self.channel.connect.side_effect = connect
        with patch.object(self.bot, 'extract_playback_song', return_value=media_info('A')):
            task = asyncio.create_task(self.bot.play.callback(self.event, 'https://example.com/A'))
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.wait_for(self.bot.clear.callback(self.interaction()), 1)
            await task
        self.assertNotIn(10, self.bot.q)
        self.assertRegex(self.event.edit_original_response.call_args.kwargs['content'], 'stopped|cleared|disconnected')

    async def test_failed_connection_cleans_up_and_reports_the_failure(self):
        self.channel.connect.side_effect = self.bot.discord.ClientException('Connection failed')
        with patch.object(self.bot, 'extract_playback_song', return_value=media_info('A')), \
                self.assertLogs(self.bot.logger, level='ERROR'):
            await self.bot.play.callback(self.event, 'https://example.com/A')
        self.assertNotIn(10, self.bot.q)
        self.assertEqual(self.voice.played, [])
        self.assertIn('disconnected', self.event.edit_original_response.call_args.kwargs['content'])
        self.assertTrue(any('Failed to connect' in call.args[0] for call in self.text.send.call_args_list))

    async def test_manual_loader_cancellation_releases_only_its_pending_count(self):
        queue = self.queue('Playing', pending=4)
        await self.bot.play_music(10, queue)
        started = asyncio.Event()

        async def extract(*args):
            started.set()
            await asyncio.Future()

        songs = [PlaylistSong(str(i), str(i), f'https://example.com/{i}') for i in range(4)]
        with patch.object(self.bot, 'load_playback_song', side_effect=extract):
            task = self.bot.track_queue_task(queue, self.bot.add_songs_to_queue(10, queue, songs))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(queue.pending_songs, 0)
        self.assertEqual(queue.current, 'Playing')
        self.assertEqual(self.voice.played, ['stream:Playing'])
        self.assertIs(self.bot.q[10], queue)

    async def test_real_timeout_ignores_late_worker_result(self):
        loop = asyncio.get_running_loop()
        started, completed = asyncio.Event(), asyncio.Event()
        release = threading.Event()

        def extract(*args):
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(2):
                    raise AssertionError('Test worker was never released')
                return media_info('Late')
            finally:
                loop.call_soon_threadsafe(completed.set)

        with patch.object(self.bot, 'extract_playback_song', side_effect=extract), \
                patch.object(self.bot, 'SONG_LOAD_TIMEOUT', .05):
            try:
                command = asyncio.create_task(self.bot.play.callback(self.event, 'https://example.com/late'))
                await asyncio.wait_for(started.wait(), 1)
                await command
                self.assertNotIn(10, self.bot.q)
                fresh = self.queue('New')
                release.set()
                await asyncio.wait_for(completed.wait(), 1)
                await asyncio.sleep(0)
                self.assertEqual(fresh.songs, ['New'])
                self.assertEqual(fresh.pending_songs, 0)
                self.assertIn('timed out', self.event.edit_original_response.call_args.kwargs['content'])
            finally:
                release.set()

    async def test_unavailable_playlist_is_drained_and_disconnects_once(self):
        queue = self.queue(pending=2)
        songs = [PlaylistSong('Bad', 'bad', 'https://example.com/bad')] * 2
        with patch.object(self.bot, 'load_playback_song', AsyncMock(side_effect=PlaylistError('Unavailable'))):
            task = self.bot.track_queue_task(queue, self.bot.add_songs_to_queue(10, queue, songs))
            await task
        self.assertNotIn(10, self.bot.q)
        self.assertEqual(queue.pending_songs, 0)
        self.assertFalse(queue.tasks)
        self.voice.disconnect.assert_awaited_once()

    async def test_other_guild_can_start_while_first_guild_connects(self):
        first = self.queue('A')
        first.voice_client = None
        started, release = asyncio.Event(), asyncio.Event()

        async def connect(**kwargs):
            started.set()
            await release.wait()
            return self.voice

        self.channel.connect.side_effect = connect
        first_start = self.bot.track_queue_task(first, self.bot.play_music(10, first))
        await started.wait()
        other_voice = Voice()
        second = self.queue('B', guild_id=11)
        second.voice_client = other_voice
        await self.bot.play_music(11, second)
        self.assertEqual(other_voice.played, ['stream:B'])
        self.assertFalse(first_start.done())
        release.set()
        await first_start

    async def test_playback_url_normalization_rejects_collections_before_extraction(self):
        self.media.YoutubeDL.reset_mock()
        with self.assertRaises(PlaylistError):
            self.bot.extract_playback_song(10, 'https://youtube.com/playlist?list=PLtest')
        self.media.YoutubeDL.assert_not_called()

    async def test_bot_rename_does_not_prevent_disconnect_cleanup(self):
        queue = self.queue('A', pending=2)
        self.bot.client._connection.user = SimpleNamespace(id=999)
        self.addCleanup(setattr, self.bot.client._connection, 'user', None)
        member = SimpleNamespace(id=999, name='Renamed', guild=SimpleNamespace(id=10), voice=None)
        await self.bot.on_voice_state_update(member, SimpleNamespace(channel=self.channel), SimpleNamespace(channel=None))
        self.assertNotIn(10, self.bot.q)
        self.assertEqual(queue.pending_songs, 0)

    async def test_delayed_disconnect_event_preserves_reconnected_session(self):
        fresh = self.queue('New')
        self.bot.client._connection.user = SimpleNamespace(id=999)
        self.addCleanup(setattr, self.bot.client._connection, 'user', None)
        member = SimpleNamespace(id=999, guild=SimpleNamespace(id=10), voice=SimpleNamespace(channel=self.channel))
        await self.bot.on_voice_state_update(member, SimpleNamespace(channel=self.channel), SimpleNamespace(channel=None))
        self.assertIs(self.bot.q[10], fresh)
        self.assertEqual(fresh.songs, ['New'])

    async def test_clear_cancels_a_slow_playlist_read_before_it_can_start_playback(self):
        loop = asyncio.get_running_loop()
        started, completed = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        snapshot = SimpleNamespace(songs=(PlaylistSong('Old', 'old', 'https://example.com/old'),))

        def read(*args):
            loop.call_soon_threadsafe(started.set)
            try:
                if not release.wait(2):
                    raise AssertionError('Test reader was never released')
                return snapshot
            finally:
                loop.call_soon_threadsafe(completed.set)

        with patch.object(self.bot.playlist_store, 'read', side_effect=read), \
                patch.object(self.bot, 'extract_playback_song') as extraction:
            command = asyncio.create_task(self.bot.pl_enqueue.callback(self.event, 'test', False))
            try:
                await asyncio.wait_for(started.wait(), 1)
                await self.bot.clear.callback(self.interaction())
                await command
                fresh = self.queue('New')
                release.set()
                await asyncio.wait_for(completed.wait(), 1)
                self.assertEqual(fresh.songs, ['New'])
                self.assertEqual(fresh.pending_songs, 0)
                self.assertIn('cleared', self.event.edit_original_response.call_args.kwargs['content'])
                extraction.assert_not_called()
            finally:
                release.set()
                await command

    async def test_repeated_close_waits_for_the_existing_disconnect_cleanup(self):
        queue = self.queue('A')
        started, release = asyncio.Event(), asyncio.Event()

        async def disconnect(**kwargs):
            started.set()
            await release.wait()
            self.voice.connected = False

        self.voice.disconnect.side_effect = disconnect
        first = asyncio.create_task(self.bot.close_queue(10, queue))
        await started.wait()
        second = asyncio.create_task(self.bot.close_queue(10, queue))
        await asyncio.sleep(0)
        self.assertFalse(first.done())
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        self.voice.disconnect.assert_awaited_once()
        self.assertNotIn(10, self.bot.q)
        self.assertFalse(queue.tasks)

    async def test_playlist_joins_before_the_first_song_finishes_loading(self):
        songs = (PlaylistSong('First', 'first', 'https://example.com/first'),)
        started, release = asyncio.Event(), asyncio.Event()

        async def load(*args):
            started.set()
            await release.wait()
            return media_info('First')

        with patch.object(self.bot.playlist_store, 'read', return_value=SimpleNamespace(songs=songs)), \
                patch.object(self.bot, 'load_playback_song', side_effect=load):
            await self.bot.pl_enqueue.callback(self.event, 'test', False)
            queue = self.bot.q[10]
            await asyncio.wait_for(started.wait(), 1)
            await self.until(lambda: queue.voice_client is self.voice)
            self.channel.connect.assert_awaited_once()
            self.assertEqual(self.voice.played, [])
            self.assertEqual(queue.pending_songs, 1)
            release.set()
            await self.until(lambda: not queue.tasks)
        self.assertEqual(self.voice.played, ['stream:First'])

    async def test_play_starts_connection_and_extraction_concurrently(self):
        connecting, extracting = asyncio.Event(), asyncio.Event()
        allow_connection, allow_media = asyncio.Event(), asyncio.Event()

        async def connect(**kwargs):
            connecting.set()
            await allow_connection.wait()
            return self.voice

        async def load(*args):
            extracting.set()
            await allow_media.wait()
            return media_info('First')

        self.channel.connect.side_effect = connect
        with patch.object(self.bot, 'load_playback_song', side_effect=load):
            command = asyncio.create_task(self.bot.play.callback(self.event, 'https://example.com/first'))
            await asyncio.wait_for(asyncio.gather(connecting.wait(), extracting.wait()), 1)
            allow_media.set()
            await self.until(lambda: bool(self.bot.q[10].songs))
            self.assertEqual(self.voice.played, [])
            allow_connection.set()
            await asyncio.wait_for(command, 1)
        self.channel.connect.assert_awaited_once()
        self.assertEqual(self.voice.played, ['stream:First'])

    async def test_failed_media_cancels_a_still_pending_connection(self):
        connecting, cancelled = asyncio.Event(), asyncio.Event()

        async def connect(**kwargs):
            connecting.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        async def load(*args):
            await connecting.wait()
            raise PlaylistError('This song is unavailable.')

        self.channel.connect.side_effect = connect
        with patch.object(self.bot, 'load_playback_song', side_effect=load):
            await asyncio.wait_for(self.bot.play.callback(self.event, 'https://example.com/bad'), 1)
        self.assertTrue(cancelled.is_set())
        self.assertNotIn(10, self.bot.q)
        self.assertEqual(self.voice.played, [])
        self.assertIn('unavailable', self.event.edit_original_response.call_args.kwargs['content'])

    async def test_unavailable_playlist_cancels_connection_without_waiting_for_timeout(self):
        connecting, cancelled = asyncio.Event(), asyncio.Event()
        songs = (PlaylistSong('Bad', 'bad', 'https://example.com/bad'),)

        async def connect(**kwargs):
            connecting.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        async def load(*args):
            await connecting.wait()
            raise PlaylistError('Unavailable')

        self.channel.connect.side_effect = connect
        with patch.object(self.bot.playlist_store, 'read', return_value=SimpleNamespace(songs=songs)), \
                patch.object(self.bot, 'load_playback_song', side_effect=load):
            await self.bot.pl_enqueue.callback(self.event, 'test', False)
            queue = self.bot.q[10]
            await self.until(lambda: not queue.tasks)
        self.assertTrue(cancelled.is_set())
        self.assertNotIn(10, self.bot.q)
        self.assertEqual(queue.pending_songs, 0)

    async def test_two_play_requests_reuse_the_early_connection(self):
        connecting, allow_connection = asyncio.Event(), asyncio.Event()
        both_extracting = asyncio.Event()
        loads = 0

        async def connect(**kwargs):
            connecting.set()
            await allow_connection.wait()
            return self.voice

        async def load(guild_id, link):
            nonlocal loads
            loads += 1
            if loads == 2:
                both_extracting.set()
            await both_extracting.wait()
            return media_info(link.rsplit('/', 1)[1])

        self.channel.connect.side_effect = connect
        with patch.object(self.bot, 'load_playback_song', side_effect=load):
            commands = [asyncio.create_task(self.bot.play.callback(self.interaction(), f'https://example.com/{name}'))
                        for name in ('A', 'B')]
            await asyncio.wait_for(asyncio.gather(connecting.wait(), both_extracting.wait()), 1)
            allow_connection.set()
            await asyncio.wait_for(asyncio.gather(*commands), 1)
        self.channel.connect.assert_awaited_once()
        queue = self.bot.q[10]
        self.assertEqual(set([queue.current] + queue.songs), {'A', 'B'})
        self.assertEqual(len(self.voice.played), 1)
        self.assertEqual(queue.pending_songs, 0)

    async def test_clear_disconnects_the_partially_connected_voice_client(self):
        queue = self.queue(pending=1)
        queue.voice_client = None
        connecting = asyncio.Event()

        async def connect(*, cls, **kwargs):
            cls(object(), self.channel)
            connecting.set()
            await asyncio.Future()

        self.channel.connect.side_effect = connect
        with patch.object(self.bot.discord, 'VoiceClient', return_value=self.voice):
            task = self.bot.track_queue_task(queue, self.bot.prepare_voice(10, queue))
            await asyncio.wait_for(connecting.wait(), 1)
            await asyncio.wait_for(self.bot.clear.callback(self.event), 1)
        self.assertTrue(task.cancelled())
        self.voice.disconnect.assert_awaited_once_with(force=True)
        self.assertNotIn(10, self.bot.q)
        self.assertFalse(queue.tasks)

    async def test_each_song_keeps_its_own_fixed_gain_when_playback_advances(self):
        queue = self.queue('A', 'B')
        queue.gains = [-5.0, 2.0]
        with patch.object(self.bot, 'playback_audio_options', wraps=self.bot.playback_audio_options) as options:
            await self.bot.play_music(10, queue)
            self.voice.finish()
            await self.until(lambda: queue.current == 'B')
        self.assertEqual([call.kwargs['gain_db'] for call in options.call_args_list], [-5.0, 2.0])
        self.assertEqual(queue.gains, [])

    async def test_clear_cancels_loudness_preparation_before_it_can_enqueue(self):
        started = asyncio.Event()
        async def gain(*args, **kwargs):
            started.set()
            await asyncio.Future()
        info = media_info('A')
        with patch.object(self.bot, 'extract_playback_song', return_value=info), \
                patch.object(self.bot.track_normalizer, 'gain_for', side_effect=gain):
            command = asyncio.create_task(self.bot.play.callback(self.event, 'https://example.com/A'))
            await asyncio.wait_for(started.wait(), 1)
            old = self.bot.q[10]
            await asyncio.wait_for(self.bot.clear.callback(self.interaction()), 1)
            await command
        self.assertNotIn(10, self.bot.q)
        self.assertEqual(self.voice.played, [])
        self.assertEqual(old.pending_songs, 0)
        self.assertFalse(old.tasks)
