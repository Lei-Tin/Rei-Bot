"""Measure real FFmpeg output rather than just checking the filter's configuration."""
import array
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import discord

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Rei'))
import config
from playback_audio import playback_audio_options


@unittest.skipUnless(shutil.which('ffmpeg'), 'Install ffmpeg to run the audio measurements')
class AudioTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def tone(self, name, amplitude, seconds=8):
        path = Path(self.folder.name) / f'{name}.wav'
        samples = array.array('h')
        for i in range(48000 * seconds):
            level = amplitude(i) if callable(amplitude) else amplitude
            sample = round(level * 32767 * math.sin(2 * math.pi * 440 * i / 48000))
            samples.extend((sample, sample))
        if sys.byteorder != 'little':
            samples.byteswap()
        with wave.open(str(path), 'wb') as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(48000)
            output.writeframes(samples.tobytes())
        return path

    def play(self, path, *, normalize=True, download=False):
        with patch.object(config, 'NORMALIZE_AUDIO', normalize):
            options = playback_audio_options(download=download)
        # Fixtures are local WAVs. HTTP reconnect flags apply only to the live input transport.
        options.pop('before_options', None)
        source = discord.FFmpegPCMAudio(str(path), stderr=subprocess.DEVNULL, **options)
        try:
            frames = []
            while data := source.read():
                frames.append(data)
            result = b''.join(frames)
            self.assertEqual(source._process.wait(timeout=10), 0)
            return result
        finally:
            source._stdout.close()
            source.cleanup()

    def measure(self, pcm):
        result = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-f', 's16le', '-ar', '48000',
            '-ac', '2', '-i', 'pipe:0', '-af', 'loudnorm=print_format=json', '-f', 'null', '-'],
            input=pcm, capture_output=True, timeout=15, check=True)
        stats = re.search(r'\{\s*"input_i".*?\}', result.stderr.decode(), re.S)
        self.assertIsNotNone(stats, result.stderr.decode())
        return json.loads(stats.group())

    def test_songs_twenty_decibels_apart_converge_near_the_target(self):
        quiet = self.tone('quiet', .04)
        loud = self.tone('loud', .4)
        original_quiet = self.measure(self.play(quiet, normalize=False))
        original_loud = self.measure(self.play(loud, normalize=False))
        self.assertAlmostEqual(float(original_loud['input_i']) - float(original_quiet['input_i']), 20, delta=.2)
        quiet_pcm, loud_pcm = self.play(quiet), self.play(loud)
        normalized_quiet, normalized_loud = self.measure(quiet_pcm), self.measure(loud_pcm)
        for stats in (normalized_quiet, normalized_loud):
            self.assertAlmostEqual(float(stats['input_i']), config.AUDIO_TARGET_LUFS, delta=1)
            self.assertLessEqual(float(stats['input_tp']), -1.3)
        self.assertAlmostEqual(float(normalized_quiet['input_i']), float(normalized_loud['input_i']), delta=.5)
        # 48 kHz, stereo, 16-bit PCM; normalization must preserve duration and framing.
        self.assertEqual(len(quiet_pcm), 8 * 48000 * 2 * 2)
        self.assertEqual(len(loud_pcm), len(quiet_pcm))

    def test_downloaded_songs_receive_the_same_volume_matching(self):
        stats = self.measure(self.play(self.tone('download', .04), download=True))
        self.assertAlmostEqual(float(stats['input_i']), config.AUDIO_TARGET_LUFS, delta=1)

    def test_silence_remains_silent(self):
        pcm = self.play(self.tone('silence', 0, seconds=2))
        self.assertTrue(pcm)
        self.assertEqual(set(pcm), {0})

    def test_short_loud_peaks_stay_below_the_ceiling(self):
        path = self.tone('transient', lambda i: .95 if 4 * 48000 <= i < 4.05 * 48000 else .02)
        original = self.measure(self.play(path, normalize=False))
        normalized = self.measure(self.play(path))
        self.assertGreater(float(original['input_tp']), -.8)
        self.assertLessEqual(float(normalized['input_tp']), -1.3)
