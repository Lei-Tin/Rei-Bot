"""FFmpeg playback options shared by streamed and downloaded songs."""
import config
import math


def playback_audio_options(*, download=False, gain_db=0.0):
    options = dict(config.FFMPEG_OPTIONS)
    if download:
        options.pop('before_options', None)
    if math.isfinite(gain_db):
        audio_filter = f'volume={gain_db:.6f}dB'
        options['options'] = f'{options.get("options", "")} -af {audio_filter}'.strip()
    return options
