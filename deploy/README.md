# ReiBot deployment

Pushes to `main`, or **Actions → Build and deploy ReiBot to Azure → Run workflow**,
build and deploy the bot. After changing `YT_COOKIES`, run the workflow again;
changing a GitHub secret does not modify an already running container.

The build job has DockerHub login credentials only. It builds a code-only image,
checks that the application credential files are absent, and publishes
`hleitr/reibot:gh-RUN_ID-ATTEMPT`. The deploy job uses the exact image digest.

The deploy job uses OIDC and the repository variable `AZURE_CLIENT_ID`. The Azure
identity trusts only `repo:Lei-Tin/Rei-Bot:ref:refs/heads/main`, with a custom role
assigned only to the `reibot` Container App. It cannot delete resources or manage
role assignments. Tenant and subscription IDs are non-secret identifiers.

GitHub secrets `DISCORD_TOKEN`, `YT_COOKIES`, and optional `BILIBILI_COOKIES` are
sent directly to versioned Azure Container App secrets, never to the Docker
build. `YT_COOKIES` must contain the complete Netscape cookies.txt text including
its header. The entrypoint writes private credential files at the paths the bot
already uses, removes those variables from its environment, and executes
`python ./Rei/rei.py` from `/app`.

Deployment keeps existing resource limits, scaling and persistent mounts. It
requires Single revision mode, one replica and the migrated `reibot-payg`
storage. A short stop/start avoids two Discord bot workers during the cutover;
active playback and the in-memory queue do not survive this restart. Persistent
playlists remain mounted at `/app/Rei/Guilds`.

Deployment checks Discord readiness, the persistent mount, storage read/write,
YouTube extraction and three seconds of remote audio decoding. It then checks
replica readiness and unexpected restarts. A failed deployment restores the
previous app template and starts it. A previous version can itself have an
external authentication problem; rollback is not a guarantee that YouTube
accepts its older cookie session. Real Discord voice delivery still needs a
human playback test. Failure logs show only allowlisted stage/error categories;
they do not include raw media errors or credential contents. A readiness marker
can take up to 60 seconds to appear after Azure marks the container ready.

Old runtime secret versions are retained for rollback. Review and remove only
unreferenced `rb-gh-*` secrets periodically after old revisions are retired.
Never print cookie contents, Discord tokens, raw request payloads or detailed
Discord debug logs in workflow output. Historical DockerHub images from the
previous build process may still contain older credentials; this workflow does
not delete existing registry images or rotate the Discord token automatically.

yt-dlp and its matching default dependencies are updated to the latest stable
release on each clean CI build because YouTube extraction changes frequently.
CI prints the installed version and accepts a deployment only after the media
check passes. discord.py and curl_cffi retain the previously verified versions.
The Python base tag, OS packages and transitive dependencies can still change;
the deployed digest identifies the exact tested image. When building locally
with a persistent Docker cache, use `--no-cache` to refresh yt-dlp.
