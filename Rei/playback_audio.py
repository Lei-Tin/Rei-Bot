"""FFmpeg playback options shared by streamed and downloaded songs."""
import config


def playback_audio_options(*, download=False):
    options = dict(config.FFMPEG_OPTIONS)
    if download:
        options.pop('before_options', None)
    if config.NORMALIZE_AUDIO:
        # Single-pass mode works while streaming; leave headroom and retain a broad loudness range.
        # discord.py explicitly requests 48 kHz stereo PCM after this filter.
        audio_filter = f'loudnorm=I={config.AUDIO_TARGET_LUFS}:TP=-1.5:LRA=11:linear=false'
        options['options'] = f'{options.get("options", "")} -af {audio_filter}'.strip()
    return options
