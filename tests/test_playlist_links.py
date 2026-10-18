import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Rei'))
from playlist_links import normalize_song_url
from playlists import PlaylistError
from tools.preview_playlist import PreviewApp


class PlaylistLinkTests(unittest.TestCase):
    def test_videos_inside_playlists_are_normalized_to_one_video(self):
        for url in (
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLdemo&index=4',
            'https://www.youtube.com/watch?list=RDdemo&v=dQw4w9WgXcQ&start_radio=1',
            'https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=OLAKdemo',
            'https://youtu.be/dQw4w9WgXcQ?list=PLdemo&t=30&si=tracking',
            'https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=10',
        ):
            with self.subTest(url=url):
                self.assertEqual(normalize_song_url(url), 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

    def test_short_live_and_embedded_video_links(self):
        for url in (
            'https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share',
            'https://www.youtube.com/live/dQw4w9WgXcQ?list=PLdemo',
            'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ',
        ):
            with self.subTest(url=url):
                self.assertEqual(normalize_song_url(url), 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

    def test_pure_playlists_channels_and_missing_video_ids_are_rejected(self):
        for url in (
            'https://www.youtube.com/playlist?list=PLdemo',
            'https://music.youtube.com/playlist?list=OLAKdemo',
            'https://www.youtube.com/playlist?list=PLdemo&v=dQw4w9WgXcQ',
            'https://www.youtube-nocookie.com/embed/videoseries?list=PLdemo',
            'https://www.youtube.com/watch?list=RDdemo',
            'https://www.youtube.com/watch?v=&list=PLdemo',
            'https://youtu.be/?list=PLdemo',
            'https://www.youtube.com/@artist/videos',
            'https://www.youtube.com/channel/UCdemo',
        ):
            with self.subTest(url=url), self.assertRaisesRegex(PlaylistError, 'video URL'):
                normalize_song_url(url)

    def test_malformed_urls_and_search_links_are_user_errors(self):
        for url in (
            None, '', 'not a url', 'http://[', 'https://', 'https:///watch',
            'https://example.com:bad/video', 'https://example.com:99999/video',
            'file:///tmp/video.mp3', 'ftp://example.com/video',
            'https://www.youtube.com/results?search_query=music',
            'https://www.youtube.com/watch?v=one&v=two',
            'https://example.com/\nvideo', 'https://example.com/with space',
        ):
            with self.subTest(url=url), self.assertRaises(PlaylistError):
                normalize_song_url(url)

    def test_discord_angle_brackets_and_surrounding_whitespace_are_accepted(self):
        self.assertEqual(normalize_song_url('  <https://youtu.be/dQw4w9WgXcQ?si=tracking>  '),
                         'https://www.youtube.com/watch?v=dQw4w9WgXcQ')

    def test_other_hosts_are_not_mistaken_for_youtube(self):
        for url in ('https://example.com/song?list=album&v=track',
                    'https://youtube.com.example.com/playlist?list=album'):
            self.assertEqual(normalize_song_url(url), url)

    def test_preview_uses_the_same_playlist_link_policy(self):
        with self.assertRaises(PlaylistError):
            PreviewApp.extract_song('https://www.youtube.com/playlist?list=PLdemo')
        added = PreviewApp.extract_song('https://youtu.be/dQw4w9WgXcQ?list=PLdemo')
        self.assertEqual(added.url, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')


if __name__ == '__main__':
    unittest.main()
