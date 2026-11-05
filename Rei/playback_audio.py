"""FFmpeg playback options shared by streamed and downloaded songs."""
import config
import math
import discord


class BufferedPCMSource(discord.AudioSource):
    """Keep the frame checked before playback so the introduction is not discarded."""
    def __init__(self, original, first_frame):
        self.original = original
        self.first_frame = first_frame

    def read(self):
        if self.first_frame is not None:
            frame, self.first_frame = self.first_frame, None
            return frame
        return self.original.read()

    def cleanup(self):
        self.original.cleanup()

    @property
    def _current_error(self):
        return getattr(self.original, '_current_error', None)


def playback_audio_options(*, download=False, gain_db=0.0):
    options = dict(config.FFMPEG_OPTIONS)
    if download:
        options.pop('before_options', None)
    if config.NORMALIZE_AUDIO and math.isfinite(gain_db):
        audio_filter = f'volume={gain_db:.6f}dB'
        options['options'] = f'{options.get("options", "")} -af {audio_filter}'.strip()
    return options
