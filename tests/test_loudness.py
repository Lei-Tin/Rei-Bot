import asyncio
import csv
import math
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Rei'))
import config
from loudness import LoudnessCache, LoudnessMeasurement, TrackNormalizer, fixed_gain_db, measure_audio, measurement_key


def track(**changes):
    return dict(dict(id='song', extractor_key='Youtube', webpage_url='https://youtube.com/watch?v=song',
                     url='https://media.example/audio?signature=one', format_id='251', acodec='opus',
                     asr=48000, audio_channels=2, duration=180), **changes)


class LoudnessCacheTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'Guilds' / 'audio_loudness.csv'
        self.cache = LoudnessCache(self.path)
        self.info = track()
        self.key = measurement_key(self.info)
        self.measurement = LoudnessMeasurement(-20, -4)

    def test_measurement_survives_restart_without_storing_signed_media_urls(self):
        self.cache.put(self.key, self.info, self.measurement)
        restarted = LoudnessCache(self.path)
        self.assertEqual(restarted.get(self.key), self.measurement)
        text = self.path.read_text()
        self.assertNotIn('signature', text)
        self.assertNotIn('https://', text)
        self.assertIn('song,251', text)
        self.assertIn('measured_at', text)

    def test_identity_survives_expiring_urls_but_changes_for_other_audio(self):
        self.assertEqual(self.key, measurement_key(track(url='https://other.example/audio?token=two')))
        for info in (track(id='different'), track(format_id='140'), track(duration=181), track(acodec='aac')):
            self.assertNotEqual(self.key, measurement_key(info))
        self.assertNotEqual(self.key, measurement_key(self.info, download=True))

    def test_corrupt_rows_do_not_discard_other_valid_measurements(self):
        self.cache.put(self.key, self.info, self.measurement)
        with self.path.open('a') as file:
            file.write('bad,row\n')
            file.write('a' * 64 + ',bad,251,nan,0,today\n')
            file.write('b' * 64 + ',bad,251,-20,-4,today,extra\n')
        self.assertEqual(self.cache.get(self.key), self.measurement)
        self.assertIsNone(self.cache.get('a' * 64))
        self.assertIsNone(self.cache.get('b' * 64))

    def test_invalid_header_is_rebuilt_after_a_valid_measurement(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('unrelated,columns\n')
        with self.assertLogs('loudness', level='WARNING'):
            self.assertIsNone(self.cache.get(self.key))
            self.cache.put(self.key, self.info, self.measurement)
        self.assertEqual(self.cache.get(self.key), self.measurement)

    def test_parallel_writes_preserve_every_row(self):
        def write(i):
            info = track(id=f'song{i}')
            self.cache.put(measurement_key(info), info, self.measurement)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(write, range(20)))
        with self.path.open() as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 20)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_failed_atomic_write_keeps_the_previous_cache(self):
        self.cache.put(self.key, self.info, self.measurement)
        original = self.path.read_bytes()
        with patch('loudness.os.replace', side_effect=OSError('unavailable')), self.assertRaises(OSError):
            self.cache.put(self.key, self.info, LoudnessMeasurement(-12, -2))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_gain_is_constant_and_limited_by_peak_headroom(self):
        self.assertAlmostEqual(fixed_gain_db(LoudnessMeasurement(-10.95, -.5)), -5.05)
        self.assertAlmostEqual(fixed_gain_db(LoudnessMeasurement(-28, -3)), 1.5)
        self.assertEqual(fixed_gain_db(None), 0)
        for values in ((math.nan, 0), (-20, math.inf), (5, -2)):
            with self.assertRaises(ValueError):
                LoudnessMeasurement(*values)


class TrackNormalizerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.cache = LoudnessCache(Path(self.folder.name) / 'audio_loudness.csv')
        self.normalizer = TrackNormalizer(self.cache)
        self.info = track()
        self.measurement = LoudnessMeasurement(-20, -8)

    async def test_cache_hit_after_restart_skips_ffmpeg_and_reuses_raw_measurements(self):
        with patch('loudness.measure_audio', AsyncMock(return_value=self.measurement)) as measure:
            self.assertEqual(await self.normalizer.gain_for(self.info), 4)
            fresh = TrackNormalizer(LoudnessCache(self.cache.path))
            with patch.object(config, 'AUDIO_TARGET_LUFS', -18):
                self.assertEqual(await fresh.gain_for(track(url='https://new.example/expired')), 2)
        measure.assert_awaited_once()

    async def test_concurrent_cache_misses_measure_only_once(self):
        async def measured(*args, **kwargs):
            await asyncio.sleep(0)
            return self.measurement
        with patch('loudness.measure_audio', AsyncMock(side_effect=measured)) as measure:
            results = await asyncio.gather(*(self.normalizer.gain_for(self.info) for _ in range(6)))
        self.assertEqual(results, [4] * 6)
        measure.assert_awaited_once()

    async def test_failed_measurement_uses_original_gain_and_is_not_cached(self):
        with patch('loudness.measure_audio', AsyncMock(side_effect=RuntimeError('signed URL secret'))) as measure, \
                self.assertLogs('loudness', level='WARNING') as logs:
            self.assertEqual(await self.normalizer.gain_for(self.info), 0)
        self.assertNotIn('signed URL secret', '\n'.join(logs.output))
        self.assertFalse(self.cache.path.exists())
        with patch('loudness.measure_audio', AsyncMock(return_value=self.measurement)):
            self.assertEqual(await self.normalizer.gain_for(self.info), 4)

    async def test_cache_write_failure_still_uses_the_measured_gain(self):
        with patch('loudness.measure_audio', AsyncMock(return_value=self.measurement)), \
                patch.object(self.cache, 'put', side_effect=OSError()), self.assertLogs('loudness', level='WARNING'):
            self.assertEqual(await self.normalizer.gain_for(self.info), 4)

    async def test_unavailable_cache_does_not_block_measurement_or_playback(self):
        with patch('loudness.measure_audio', AsyncMock(return_value=self.measurement)), \
                patch.object(self.cache, 'get', side_effect=OSError()), \
                patch.object(self.cache, 'put', side_effect=OSError()), self.assertLogs('loudness', level='WARNING'):
            self.assertEqual(await self.normalizer.gain_for(self.info), 4)

    async def test_live_unknown_duration_and_disabled_normalization_do_not_scan(self):
        with patch('loudness.measure_audio', AsyncMock()) as measure:
            for info in (track(is_live=True), track(duration=None), track(duration=math.inf)):
                self.assertEqual(await self.normalizer.gain_for(info), 0)
            with patch.object(config, 'NORMALIZE_AUDIO', False):
                self.assertEqual(await self.normalizer.gain_for(self.info), 0)
        measure.assert_not_called()
        self.assertFalse(self.cache.path.exists())

    async def test_cancelling_a_measurement_does_not_cache_or_keep_the_lock(self):
        started = asyncio.Event()
        async def measured(*args, **kwargs):
            started.set()
            await asyncio.Future()
        with patch('loudness.measure_audio', side_effect=measured):
            task = asyncio.create_task(self.normalizer.gain_for(self.info))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertFalse(self.cache.path.exists())
        with patch('loudness.measure_audio', AsyncMock(return_value=self.measurement)):
            self.assertEqual(await self.normalizer.gain_for(self.info), 4)

    async def test_timeout_uses_original_gain_without_caching(self):
        async def measured(*args, **kwargs):
            await asyncio.Future()
        with patch('loudness.measure_audio', side_effect=measured), \
                patch.object(config, 'AUDIO_MEASUREMENT_TIMEOUT', .02), self.assertLogs('loudness', level='WARNING'):
            self.assertEqual(await self.normalizer.gain_for(self.info), 0)
        self.assertFalse(self.cache.path.exists())

    async def test_cancellation_kills_and_reaps_the_ffmpeg_process(self):
        started = asyncio.Event()
        process = SimpleNamespace(returncode=None)
        calls = 0
        async def communicate():
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await asyncio.Future()
            process.returncode = -9
            return b'', b''
        process.communicate = AsyncMock(side_effect=communicate)
        process.kill = MagicMock()
        with patch('loudness.asyncio.create_subprocess_exec', AsyncMock(return_value=process)):
            task = asyncio.create_task(measure_audio('https://example.com/audio'))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        process.kill.assert_called_once()
        self.assertEqual(calls, 2)
        self.assertEqual(process.returncode, -9)
