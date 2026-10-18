import asyncio
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Rei'))
from playlists import PlaylistError, PlaylistSong, PlaylistStore


class MediaError(Exception):
    pass


class PlaylistCommandTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Load real Discord command registration without credentials, audio, or media requests.
        cls.media = SimpleNamespace(YoutubeDL=MagicMock(), utils=SimpleNamespace(
            YoutubeDLError=MediaError, DownloadError=MediaError, ExtractorError=MediaError))
        original_isfile = os.path.isfile

        def without_credentials(path):
            return False if str(path).endswith('/discord_token') else original_isfile(path)

        path = Path(__file__).resolve().parents[1] / 'Rei' / 'rei.py'
        with patch.dict(sys.modules, {'yt_dlp': cls.media}), \
                patch('platform.system', return_value='Windows'), \
                patch('os.path.isfile', side_effect=without_credentials), \
                patch('discord.client._log.warning'):
            spec = importlib.util.spec_from_file_location('rei_playlist_test', path)
            cls.bot = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.bot)

    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.bot.playlist_store = PlaylistStore(Path(self.folder.name))
        self.bot.q.clear()
        self.song = PlaylistSong('First song', 'first', 'https://example.com/first')
        self.bot.playlist_store.append(10, 'test', [self.song], create=True)
        self.event = SimpleNamespace(guild_id=10, user=SimpleNamespace(id=20),
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
            original_response=AsyncMock(), edit_original_response=AsyncMock())
        self.media.YoutubeDL.reset_mock()
        extractor = self.media.YoutubeDL.return_value.__enter__.return_value
        extractor.extract_info.side_effect = None
        extractor.process_video_result.side_effect = lambda info, **kwargs: info

    async def test_registered_editor_is_guild_only_with_optional_autocompleted_name(self):
        payload = self.bot.playlist.to_dict(self.bot.tree)
        self.assertFalse(payload['dm_permission'])
        self.assertFalse(payload['options'][0]['required'])
        self.assertTrue(payload['options'][0]['autocomplete'])

    async def test_playlist_and_legacy_view_commands_open_private_interactive_panels(self):
        for command, args in ((self.bot.playlist, ()), (self.bot.pl_show, ()), (self.bot.pl_view, ('test',))):
            with self.subTest(command=command.name):
                await command.callback(self.event, *args)
                kwargs = self.event.response.send_message.call_args.kwargs
                self.assertTrue(kwargs['ephemeral'])
                self.assertIsNotNone(kwargs['embed'])
                self.assertTrue(kwargs['view'].children)
                kwargs['view'].stop()

    async def test_legacy_remove_zero_preserves_csv_header_and_song(self):
        original = self.bot.playlist_store.read(10, 'test')
        await self.bot.pl_remove.callback(self.event, 'test', 0)
        self.assertEqual(self.bot.playlist_store.read(10, 'test'), original)
        self.assertIn('invalid', self.event.response.send_message.call_args.args[0])

    async def test_legacy_remove_keeps_empty_playlist_and_enqueue_reports_it(self):
        await self.bot.pl_remove.callback(self.event, 'test', 1)
        self.assertEqual(self.bot.playlist_store.read(10, 'test').songs, ())
        self.event.user.voice = SimpleNamespace(channel=SimpleNamespace())
        self.event.channel = SimpleNamespace()
        await self.bot.pl_enqueue.callback(self.event, 'test', False)
        self.assertIn('empty', self.event.edit_original_response.call_args.kwargs['content'])
        self.media.YoutubeDL.assert_not_called()

    async def test_legacy_add_appends_through_the_shared_store(self):
        added = PlaylistSong('New song', 'new', 'https://example.com/new')
        with patch.object(self.bot, 'extract_playlist_song', return_value=added):
            await self.bot.pl_add.callback(self.event, 'test', added.url)
        self.assertEqual(self.bot.playlist_store.read(10, 'test').songs, (self.song, added))
        self.event.response.defer.assert_awaited_once_with(thinking=True)

    async def test_autocomplete_is_filtered_and_capped_at_25(self):
        for i in range(30):
            self.bot.playlist_store.create(10, f'list{i:02}')
        choices = await self.bot.playlist_names(self.event, 'LIST')
        self.assertEqual(len(choices), 25)
        self.assertTrue(all(choice.value.startswith('list') for choice in choices))

    async def test_extract_rejects_invalid_urls_and_playlist_results(self):
        for link in ('not a link', 'file:///tmp/local', 'https://example.com/?search_query=test', 'http://['):
            with self.subTest(link=link), self.assertRaises(PlaylistError):
                self.bot.extract_playlist_song(link)
        extractor = self.media.YoutubeDL.return_value.__enter__.return_value.extract_info
        extractor.return_value = {'entries': []}
        with self.assertRaises(PlaylistError):
            self.bot.extract_playlist_song('https://example.com/playlist')
        extractor.return_value = dict(title='Title', id='video', webpage_url='https://example.com/watch')
        self.assertEqual(self.bot.extract_playlist_song('https://example.com/watch'),
                         PlaylistSong('Title', 'video', 'https://example.com/watch'))

    async def test_now_playing_still_suppresses_embed_and_counts_pending_songs(self):
        queue = SimpleNamespace(songs=['next'], pending_songs=2, text_channel=SimpleNamespace(send=AsyncMock()))
        await self.bot.announce_now_playing(queue, 'Song', 'https://example.com/watch')
        self.assertTrue(queue.text_channel.send.call_args.kwargs['suppress_embeds'])
        self.assertTrue(queue.text_channel.send.call_args.args[0].endswith('\n3 songs remaining'))

    async def test_known_playlist_links_are_rejected_before_any_media_request(self):
        for link in ('https://www.youtube.com/playlist?list=PLdemo',
                     'https://music.youtube.com/watch?list=RDdemo',
                     'https://www.youtube.com/@artist/videos'):
            with self.subTest(link=link), self.assertRaises(PlaylistError):
                self.bot.extract_playlist_song(link)
        self.media.YoutubeDL.assert_not_called()

    async def test_video_in_playlist_extracts_and_saves_only_the_canonical_video(self):
        extractor = self.media.YoutubeDL.return_value.__enter__.return_value
        extractor.extract_info.return_value = dict(title='Title', id='dQw4w9WgXcQ',
            webpage_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLdemo')
        result = self.bot.extract_playlist_song('https://youtu.be/dQw4w9WgXcQ?list=PLdemo&index=5')
        self.assertEqual(result.url, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        extractor.extract_info.assert_called_once_with(result.url, download=False, process=False, ie_key=None)
        extractor.process_video_result.assert_called_once()

    async def test_collection_results_are_rejected_without_iterating_entries(self):
        extractor = self.media.YoutubeDL.return_value.__enter__.return_value

        def entries():
            raise AssertionError('Playlist entries must never be expanded')
            yield

        for result in ({'_type': 'playlist', 'entries': entries()},
                       {'_type': 'multi_video'}, {'_type': 'compat_list'}, {'entries': None}):
            with self.subTest(result_type=result.get('_type')), self.assertRaises(PlaylistError):
                extractor.extract_info.return_value = result
                self.bot.extract_playlist_song('https://example.com/collection')
        extractor.process_video_result.assert_not_called()

    async def test_redirect_to_a_known_playlist_is_rejected_before_following_it(self):
        extractor = self.media.YoutubeDL.return_value.__enter__.return_value
        extractor.extract_info.return_value = dict(_type='url', url='https://www.youtube.com/playlist?list=PLdemo')
        with self.assertRaises(PlaylistError):
            self.bot.extract_playlist_song('https://example.com/share')
        extractor.extract_info.assert_called_once()
        extractor.process_video_result.assert_not_called()

    async def test_redirected_collection_is_rejected_and_single_video_redirect_is_accepted(self):
        extractor = self.media.YoutubeDL.return_value.__enter__.return_value
        extractor.extract_info.side_effect = [
            dict(_type='url_transparent', url='https://example.com/collection'),
            dict(_type='playlist', entries=[]),
        ]
        with self.assertRaises(PlaylistError):
            self.bot.extract_playlist_song('https://example.com/share')
        extractor.process_video_result.assert_not_called()
        extractor.extract_info.reset_mock()
        extractor.extract_info.side_effect = [
            dict(_type='url', url='https://youtu.be/dQw4w9WgXcQ?list=PLdemo', ie_key='Youtube'),
            dict(title='Title', id='dQw4w9WgXcQ'),
        ]
        result = self.bot.extract_playlist_song('https://example.com/share')
        self.assertEqual(result.url, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        self.assertEqual(extractor.extract_info.call_args.kwargs['ie_key'], 'Youtube')

    async def test_redirect_loops_and_excessive_redirects_have_finite_work(self):
        extractor = self.media.YoutubeDL.return_value.__enter__.return_value
        extractor.extract_info.return_value = dict(_type='url', url='https://example.com/share')
        with self.assertRaisesRegex(PlaylistError, 'loop'):
            self.bot.extract_playlist_song('https://example.com/share')
        extractor.extract_info.assert_called_once()
        extractor.extract_info.reset_mock()
        extractor.extract_info.side_effect = [dict(_type='url', url=f'https://example.com/{i}') for i in range(5)]
        with self.assertRaisesRegex(PlaylistError, 'too many'):
            self.bot.extract_playlist_song('https://example.com/share')
        self.assertEqual(extractor.extract_info.call_count, 5)

    async def test_missing_or_malformed_extractor_data_becomes_a_user_error(self):
        extractor = self.media.YoutubeDL.return_value.__enter__.return_value
        for result in (None, [], 'invalid', {}, {'_type': 'unknown'},
                       {'title': 'Title'}, {'id': 'id'}, {'title': 123, 'id': 'id'},
                       {'title': '  ', 'id': 'id'}, {'title': 'Title', 'id': 'id', 'webpage_url': 'bad'}):
            with self.subTest(result=result), self.assertRaises(PlaylistError):
                extractor.extract_info.return_value = result
                self.bot.extract_playlist_song('https://example.com/video')

    async def test_media_and_format_failures_never_write_partial_songs(self):
        original = self.bot.playlist_store.read(10, 'test')
        extractor = self.media.YoutubeDL.return_value.__enter__.return_value
        for error in (MediaError('private implementation detail'), OSError('connection failed')):
            with self.subTest(error=type(error).__name__):
                extractor.extract_info.side_effect = error
                await self.bot.pl_add.callback(self.event, 'test', 'https://example.com/video')
                self.assertEqual(self.bot.playlist_store.read(10, 'test'), original)
                message = self.event.edit_original_response.call_args.kwargs['content']
                self.assertIn('Could not load', message)
                self.assertNotIn('private implementation detail', message)
        extractor.extract_info.side_effect = None
        extractor.extract_info.return_value = dict(title='Title', id='video')
        extractor.process_video_result.side_effect = MediaError('No audio formats')
        await self.bot.pl_add.callback(self.event, 'test', 'https://example.com/video')
        self.assertEqual(self.bot.playlist_store.read(10, 'test'), original)

    async def test_legacy_add_timeout_is_reported_without_writing_anything(self):
        async def timed_out(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError

        original = self.bot.playlist_store.read(10, 'test')
        with patch.object(self.bot.asyncio, 'wait_for', new=timed_out):
            await self.bot.pl_add.callback(self.event, 'test', 'https://example.com/video')
        self.assertEqual(self.bot.playlist_store.read(10, 'test'), original)
        self.assertIn('timed out', self.event.edit_original_response.call_args.kwargs['content'])


if __name__ == '__main__':
    unittest.main()
