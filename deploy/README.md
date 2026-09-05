# ReiBot deployment

Pushes to `main`, or **Actions → Build and deploy ReiBot to Azure → Run workflow**,
build and deploy the bot. After changing `YT_COOKIES`, run the workflow again;
changing a GitHub secret does not modify an already running container.

The workflow uses maintained vendor Actions for the general deployment work:

- `docker/setup-buildx-action`, `docker/login-action`, and
  `docker/build-push-action` build, check, and publish the code-only image.
  The publish step reuses the verified build's local BuildKit cache.
- `azure/login` authenticates CLI and PowerShell through OIDC.
- `azure/powershell` runs `Stop-AzContainerApp` / `Start-AzContainerApp`,
  including Azure's built-in asynchronous operation waiting.
- `azure/container-apps-deploy-action` applies the deployment configuration
  and also restores the previous template if deployment or verification fails.

The build job has DockerHub credentials only. Application credentials are
available only in the deploy job. Images are tagged
`hleitr/reibot:gh-RUN_ID-ATTEMPT`; deployment uses the exact published digest.

OIDC uses the repository variable `AZURE_CLIENT_ID`. The Azure
identity trusts only `repo:Lei-Tin/Rei-Bot:ref:refs/heads/main`, with a custom role
assigned only to the `reibot` Container App. It cannot delete resources or manage
role assignments. Tenant and subscription IDs are non-secret identifiers.

GitHub secrets `DISCORD_TOKEN`, `YT_COOKIES`, and optional `BILIBILI_COOKIES` are
sent directly to versioned Azure Container App secrets, never to the Docker
build. `YT_COOKIES` must contain the complete Netscape cookies.txt text including
its header. The entrypoint writes private credential files at the paths the bot
already uses, removes those variables from its environment, and executes
`python ./Rei/rei.py` from `/app`.

`prepare.py` only prepares private configuration files for the official action;
it does not orchestrate deployment. JSON is used as valid YAML so multiline
cookies are escaped correctly without shell interpolation. Files live in the
runner's temporary directory with permissions 0600, are never uploaded as
artifacts, and are removed in an `always()` cleanup step. Existing registry
secrets are preserved. The rollback file contains the previous image and secret
references, not secret values.

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
human playback test. `verify.sh` uses Azure CLI's resource waiter and the standard `script` terminal
utility instead of a custom polling / PTY implementation. Logs show check
markers and redacted media/CLI diagnostics, never credential contents. A readiness marker
can take up to 60 seconds to appear after Azure marks the container ready.

The volume named `reibotfs` is still required: it maps to environment storage
`reibot-payg` and the new account `reibotpayg20260905`. Its name is not the old
storage account. Never delete this live volume or roll back to a historical
template using the removed old share.

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
