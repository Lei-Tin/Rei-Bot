# Deploying ReiBot

Push to `main` to deploy. After changing a cookie, update GitHub's `YT_COOKIES`
secret, then choose **Actions → Deploy ReiBot → Run workflow** on `main`.
Changing a GitHub secret alone does not update an existing container.

The workflow builds and pushes once, logs in to Azure, syncs runtime secrets,
and updates the existing container with the published image digest. Docker and
Azure's official Actions handle building, deployment and stop/start. A short
restart prevents two Discord workers during the update. Saved playlists remain
on Azure Files; current playback and the in-memory queue reset on deployment.

## Configuration

Azure login is already configured with OIDC. Repository variables
`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID` hold the account
identifiers. No subscription IDs need to be entered for normal deployments.
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
preserved. The deployment action sets the three bot environment variables listed
in the workflow; add any future variables there as well.

CPU, memory, scaling and storage are maintained on the existing Azure app.
The live volume `reibotfs` maps to `reibot-payg` and the new storage account
`reibotpayg20260905`. Keep this volume; the old account with a similar name was deleted.

## Checks and recovery

CI tests credential handling and log redaction. Deployment and start use the
results returned by Azure's official actions; no extra startup polling is needed.
Full YouTube/audio diagnosis is available on demand in the Azure container Console:

```sh
python /app/deploy/smoke.py https://www.youtube.com/watch?v=mYEA5A0Bjyo
```

There is no custom automatic rollback. A failed update still attempts to restart
the app and leaves the workflow failed. Revert a bad code change and push `main`
to redeploy; correct cookie problems by updating the secret and running again.
Fixed secret values apply across revisions, so reverting code does not restore
an earlier cookie. Never reactivate historical revisions pointing to the deleted
old file share.

yt-dlp and matching default/EJS dependencies update on each clean build. Deno
and the other explicitly pinned runtime packages remain configured in Dockerfile.
