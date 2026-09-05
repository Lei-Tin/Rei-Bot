"""Run inside the deployed container. Print only non-sensitive check results."""
import copy
import os
import json
import re
from urllib.parse import quote
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "/app/Rei")


def safe_media_error(message, secret_values):
    """Redact runtime credentials and URLs before surfacing a media error."""
    variants = set()
    for value in secret_values:
        if value:
            variants.update((value, repr(value)[1:-1], json.dumps(value)[1:-1], quote(value, safe='')))
    for value in sorted(variants, key=len, reverse=True):
        message = message.replace(value, '[redacted]')
    message = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', message)
    message = re.sub(r'https?://\S+', '[url]', message)
    return ' '.join(message.split())[:600]


def main():
    import config
    import yt_dlp

    deadline = time.monotonic() + 60
    while not Path("/tmp/reibot-ready").exists() and time.monotonic() < deadline:
        time.sleep(2)
    if not Path("/tmp/reibot-ready").exists():
        raise RuntimeError("Discord gateway is not ready")
    folder = Path("/app/Rei/Guilds")
    mounts = [line.split() for line in Path("/proc/mounts").read_text().splitlines()]
    if not any(row[1] == str(folder) and row[2] == "cifs" for row in mounts):
        raise RuntimeError("Persistent Azure Files mount is missing")
    with tempfile.NamedTemporaryFile(prefix=".reibot-smoke-", dir=folder) as test:
        test.write(b"storage check"); test.flush(); os.fsync(test.fileno())
        assert Path(test.name).read_bytes() == b"storage check"
    print("REIBOT_STORAGE_OK", flush=True)

    class QuietLogger:
        def debug(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): pass

    with tempfile.TemporaryDirectory() as temporary:
        cookie = Path(temporary) / "cookies.txt"
        shutil.copyfile("/app/Rei/cookies.txt", cookie)
        options = copy.deepcopy(config.YDL_OPTS_STREAM)
        options.update(cookiefile=str(cookie), logger=QuietLogger(), quiet=True,
                       socket_timeout=15, retries=0, extractor_retries=0, cachedir=False)
        with yt_dlp.YoutubeDL(options) as downloader:
            try:
                result = downloader.extract_info(sys.argv[1], download=False)
            except yt_dlp.utils.DownloadError as exc:
                values = [c.value for c in downloader.cookiejar]
                # Include original values, even if the temporary jar was rotated.
                for name in ('cookies.txt', 'bilibili_cookies.txt'):
                    path = Path('/app/Rei') / name
                    if path.exists():
                        values.extend(row.split('\t')[-1] for row in path.read_text().splitlines()
                                      if len(row.split('\t')) == 7)
                token = Path('/app/Rei/discord_token')
                if token.exists():
                    values.append(token.read_text().strip())
                print('REIBOT_MEDIA_ERROR ' + safe_media_error(str(exc), values), flush=True)
                raise
        stream = result.get("url")
        if not stream:
            raise RuntimeError("Media extraction did not return an audio stream")
        result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", stream,
                                 "-t", "3", "-vn", "-f", "null", "-"],
                                capture_output=True, timeout=45)
        if result.returncode:
            raise RuntimeError("Remote audio decoding failed")
    print("REIBOT_SMOKE_OK", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Report a small fixed vocabulary; exception text can contain URLs or credentials.
        message = str(exc).lower()
        for phrase, marker in (("sign in to confirm", "AUTH_REQUIRED"),
                               ("cookies are no longer valid", "COOKIES_INVALID"),
                               ("requested format is not available", "FORMAT_UNAVAILABLE"),
                               ("video unavailable", "VIDEO_UNAVAILABLE"),
                               ("remote audio decoding failed", "AUDIO_DECODE_FAILED"),
                               ("discord gateway is not ready", "DISCORD_NOT_READY")):
            if phrase in message:
                print("REIBOT_DETAIL_" + marker, flush=True)
        print(f"REIBOT_SMOKE_FAILED:{type(exc).__name__}", flush=True)
        sys.exit(1)
