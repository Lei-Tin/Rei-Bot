"""Materialize runtime secrets without putting them in container image layers."""
import os
import sys
from pathlib import Path


def write_secrets(directory, environ):
    values = {name: environ.pop(name, "") for name in
              ("DISCORD_TOKEN", "YT_COOKIES", "BILIBILI_COOKIES")}
    for name in ("DISCORD_TOKEN", "YT_COOKIES"):
        if not values[name].strip():
            raise ValueError(f"Required runtime secret missing: {name}")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, filename in (("DISCORD_TOKEN", "discord_token"),
                           ("YT_COOKIES", "cookies.txt"),
                           ("BILIBILI_COOKIES", "bilibili_cookies.txt")):
        value = values[name]
        if name == "DISCORD_TOKEN":
            value = value.strip()
        if value and not value.endswith("\n"):
            value += "\n"
        fd = os.open(directory / filename, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(value)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        write_secrets("/app/Rei", os.environ)
        Path("/tmp/reibot-ready").unlink(missing_ok=True)
    except (ValueError, OSError) as exc:
        print(f"Runtime credential setup failed ({type(exc).__name__}).", file=sys.stderr)
        sys.exit(1)
    command = sys.argv[1:] or ["python", "./Rei/rei.py"]
    os.chdir("/app")
    os.execvp(command[0], command)
