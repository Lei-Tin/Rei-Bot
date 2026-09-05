# Deploying ReiBot

Push to `main` to deploy. After changing a cookie, update GitHub's `YT_COOKIES`
secret, then choose **Actions → Deploy ReiBot → Run workflow** on `main`.
Changing a GitHub secret alone does not update an existing container.

The workflow builds and pushes `hleitr/reibot:latest`, logs in to Azure, syncs
runtime secrets, then restarts the current ready revision so Azure pulls `latest`.
It does not create a new revision for each release. Saved playlists remain on
Azure Files; current playback and the in-memory queue reset on restart.

## Configuration

Azure login is already configured with OIDC. Repository variables
`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID` hold the account
identifiers. No subscription IDs need to be entered for normal deployments.
The workflow requires `containerApps/revisions/restart/action` on this app.
The existing OIDC identity has app-scoped deployment rights plus the single
`managedEnvironments/join/action` permission on the existing ReiBot environment,
as required by Azure CLI updates. It has no resource-group-wide management role.

GitHub secrets:

- `DOCKERHUB_USERNAME` and `DOCKERHUB_PASSWORD`: image publishing.
- `DISCORD_TOKEN`: bot login.
- `YT_COOKIES`: complete Netscape cookies.txt text, including its header.
- `BILIBILI_COOKIES`: optional; defaults to an empty Netscape cookie file.

Application credentials are passed only to Azure runtime secrets, never to the
Docker build. The entrypoint writes private credential files and starts the bot.
Fixed Azure secret names are updated in place. Existing registry credentials are
preserved. Azure's existing container configuration references `discord-token`,
`youtube-cookies`, and `bilibili-cookies` from the corresponding environment
variables `DISCORD_TOKEN`, `YT_COOKIES`, and `BILIBILI_COOKIES`.

The Azure container image must remain
`registry.hub.docker.com/hleitr/reibot:latest`. This is configured once on the app;
the workflow only restarts it. Changing it to a fixed digest would prevent a
restart from picking up newly published images.

CPU, memory, scaling and storage are maintained on the existing Azure app.
The live volume `reibotfs` maps to `reibot-payg` and the new storage account
`reibotpayg20260905`. Keep this volume; the old account with a similar name was deleted.

## Checks and recovery

CI tests credential handling and log redaction. The restart step uses the result
returned by Azure CLI; no extra startup polling is added.
Full YouTube/audio diagnosis is available on demand in the Azure container Console:

```sh
python /app/deploy/smoke.py https://www.youtube.com/watch?v=mYEA5A0Bjyo
```

There is no custom automatic rollback. Build or secret synchronization failures
skip the restart; a restart error leaves the workflow failed. Revert a bad code
change and push `main` to rebuild `latest` and restart; correct cookie problems
by updating the secret and running again. A revision restart can also pull a
previously published `latest`, so releases are tracked through GitHub build logs
and image digests rather than distinct Azure revisions.
Fixed secret values apply across revisions, so reverting code does not restore
an earlier cookie. Never reactivate historical revisions pointing to the deleted
old file share.

yt-dlp and matching default/EJS dependencies update on each clean build. Deno
and the other explicitly pinned runtime packages remain configured in Dockerfile.
