"""Sampled loudness measurements, fixed gain, and an atomic CSV cache."""
import asyncio
import csv
import hashlib
import json
import logging
import math
import os
import re
import shlex
import shutil
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

SAMPLE_COUNT = 3
SAMPLE_SECONDS = 12


@dataclass(frozen=True)
class LoudnessMeasurement:
    integrated_lufs: float
    true_peak_dbtp: float

    def __post_init__(self):
        if not (math.isfinite(self.integrated_lufs) and -99 <= self.integrated_lufs <= 0
                and math.isfinite(self.true_peak_dbtp) and -120 <= self.true_peak_dbtp <= 20):
            raise ValueError('Invalid loudness measurement')


def fixed_gain_db(measurement: LoudnessMeasurement | None, *, allow_boost=True) -> float:
    if measurement is None:
        return 0.0
    # One gain for the entire track. Leave peak headroom instead of compressing loud sections.
    gain = min(config.AUDIO_TARGET_LUFS - measurement.integrated_lufs,
               config.AUDIO_TRUE_PEAK_DBTP - measurement.true_peak_dbtp)
    # Samples can miss a louder section, so only a full measurement can justify boosting.
    return gain if allow_boost else min(gain, 0.0)


def sample_windows(duration: float) -> tuple[tuple[float, float], ...]:
    if duration <= SAMPLE_COUNT * SAMPLE_SECONDS:
        return ((0.0, duration),)
    section = duration / SAMPLE_COUNT
    return tuple(((index + 0.5) * section - SAMPLE_SECONDS / 2, SAMPLE_SECONDS)
                 for index in range(SAMPLE_COUNT))


def measurement_key(info: dict, *, download=False, sampled=False) -> str:
    identity = ['stereo48k-v1', info.get('extractor_key') or info.get('extractor'),
                info.get('id'), info.get('webpage_url'), info.get('format_id'),
                info.get('acodec'), info.get('asr'), info.get('audio_channels'),
                info.get('duration'), bool(download)]
    if sampled:
        identity.extend(('centered-samples-v1', SAMPLE_COUNT, SAMPLE_SECONDS))
    # Expiring media URLs are deliberately excluded from the identity and the CSV.
    return hashlib.sha256(json.dumps(identity, ensure_ascii=True).encode()).hexdigest()


class LoudnessCache:
    HEADER = ['key', 'source_id', 'format_id', 'integrated_lufs', 'true_peak_dbtp', 'measured_at']

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read(self) -> dict:
        try:
            with self.path.open(encoding='utf-8', newline='') as file:
                reader = csv.DictReader(file)
                if reader.fieldnames != self.HEADER:
                    logger.warning('Ignoring an invalid loudness cache header')
                    return {}
                rows = {}
                for row in reader:
                    try:
                        if None in row or not re.fullmatch(r'[a-f0-9]{64}', row['key']):
                            continue
                        LoudnessMeasurement(float(row['integrated_lufs']), float(row['true_peak_dbtp']))
                        rows[row['key']] = row
                    except (TypeError, KeyError, ValueError):
                        continue
                return rows
        except FileNotFoundError:
            return {}
        except (UnicodeError, csv.Error):
            logger.warning('Ignoring a corrupt loudness cache')
            return {}

    def get(self, key: str) -> LoudnessMeasurement | None:
        with self._lock:
            row = self._read().get(key)
            return (LoudnessMeasurement(float(row['integrated_lufs']), float(row['true_peak_dbtp']))
                    if row else None)

    def put(self, key: str, info: dict, measurement: LoudnessMeasurement) -> None:
        with self._lock:
            rows = self._read()
            rows[key] = dict(key=key, source_id=info.get('id', ''), format_id=info.get('format_id', ''),
                             integrated_lufs=measurement.integrated_lufs,
                             true_peak_dbtp=measurement.true_peak_dbtp,
                             measured_at=datetime.now(timezone.utc).isoformat())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                                 dir=self.path.parent, suffix='.tmp', delete=False) as file:
                    temporary = Path(file.name)
                    writer = csv.DictWriter(file, fieldnames=self.HEADER)
                    writer.writeheader()
                    writer.writerows(rows.values())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)


async def measure_audio(source: str, windows: tuple[tuple[float, float], ...], *,
                        download=False) -> LoudnessMeasurement | None:
    args = ['ffmpeg', '-hide_banner', '-nostdin', '-nostats', '-xerror',
            '-filter_complex_threads', '1', '-progress', 'pipe:1']
    if shutil.which('nice'):
        args = ['nice', '-n', '10', *args]
    before_input = [] if download else shlex.split(config.FFMPEG_OPTIONS.get('before_options', ''))
    for start, length in windows:
        args.extend([*before_input, '-threads', '1', '-ss', f'{start:.6f}', '-t', f'{length:.6f}', '-i', source])
    # Join decoded samples before measuring so loudness gating runs over the combined audio.
    stereo = 'aformat=sample_rates=48000:channel_layouts=stereo'
    analyzer = 'loudnorm=print_format=json'
    if len(windows) == 1:
        filters = f'[0:a:0]{stereo},{analyzer}[measured]'
    else:
        clips = [f'[{i}:a:0]{stereo},asetpts=PTS-STARTPTS[clip{i}]' for i in range(len(windows))]
        inputs = ''.join(f'[clip{i}]' for i in range(len(windows)))
        filters = ';'.join([*clips, f'{inputs}concat=n={len(windows)}:v=0:a=1,{analyzer}[measured]'])
    args.extend(['-filter_complex', filters, '-map', '[measured]', '-f', 'null', '-'])
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        progress, stderr = await asyncio.wait_for(process.communicate(), timeout=config.AUDIO_MEASUREMENT_TIMEOUT)
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()
    if process.returncode:
        raise RuntimeError('FFmpeg could not measure this track')
    # Some streams end early without an FFmpeg error. Avoid caching an incomplete sample.
    timestamps = re.findall(rb'^out_time_us=(\d+)', progress, re.MULTILINE)
    measured_seconds = int(timestamps[-1]) / 1_000_000 if timestamps else 0.0
    expected_seconds = sum(length for _, length in windows)
    if measured_seconds <= 0 or measured_seconds < expected_seconds - min(0.5, expected_seconds * 0.1):
        raise ValueError('FFmpeg did not read enough audio to measure this track')
    match = re.search(r'\{\s*"input_i".*?\}', stderr.decode(errors='replace'), re.S)
    if match is None:
        raise ValueError('FFmpeg returned no loudness measurement')
    stats = json.loads(match.group())
    try:
        return LoudnessMeasurement(float(stats['input_i']), float(stats['input_tp']))
    except ValueError:
        # Silence has no finite integrated loudness; keep it silent and do not cache invented values.
        if float(stats['input_i']) == -math.inf:
            return None
        raise


class TrackNormalizer:
    def __init__(self, cache: LoudnessCache):
        self.cache = cache
        # Keep CPU usage bounded on the existing small container and deduplicate cache misses.
        self._measurement_lock = asyncio.Lock()

    async def _lookup(self, key):
        try:
            return await asyncio.to_thread(self.cache.get, key)
        except OSError:
            logger.warning('Loudness cache is unavailable; measuring without the cache')
            return None

    async def _measurement(self, info: dict, windows, *, download=False):
        full_key = measurement_key(info, download=download)
        result = await self._lookup(full_key)
        if result is not None:
            logger.info('Using cached loudness for song %s', info.get('id'))
            return result, True
        sampled = len(windows) > 1
        key = measurement_key(info, download=download, sampled=True) if sampled else full_key
        if sampled:
            result = await self._lookup(key)
            if result is not None:
                logger.info('Using cached loudness samples for song %s', info.get('id'))
                return result, False
        async with self._measurement_lock:
            result = await self._lookup(key)
            if result is None:
                logger.info('Measuring loudness for song %s (%d excerpt%s)', info.get('id'),
                            len(windows), 's' if sampled else '')
                result = await measure_audio(info['url'], windows, download=download)
                if result is not None:
                    try:
                        await asyncio.to_thread(self.cache.put, key, info, result)
                    except OSError:
                        logger.warning('Could not persist the loudness measurement')
            return result, not sampled

    async def gain_for(self, info: dict, *, download=False) -> float:
        duration = info.get('duration')
        if (info.get('is_live')
                or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0):
            return 0.0
        try:
            result, allow_boost = await asyncio.wait_for(
                self._measurement(info, sample_windows(duration), download=download),
                timeout=config.AUDIO_MEASUREMENT_TIMEOUT)
        except Exception as error:
            # Do not log signed media URLs from FFmpeg errors, or fall back to dynamic gain.
            logger.warning('Loudness measurement unavailable (%s); keeping original gain', type(error).__name__)
            return 0.0
        return fixed_gain_db(result, allow_boost=allow_boost)
