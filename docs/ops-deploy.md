# Ops deploy, rollback and backups

How code on `preview` reaches `ops.zil.global` (the NAS), how to undo a bad deploy, and how the
data is backed up and restored.

## Deploy

1. A push to `preview` runs **Preview CI** (`preview-ci.yml`).
2. When Preview CI is green on that commit, **build-and-push** (`build-and-push.yml`) starts
   (`workflow_run`). A red Preview CI deploys nothing. The agent lanes merge with `GITHUB_TOKEN`,
   which starts no workflow, after running the same bar themselves, so they start build-and-push
   with `workflow_dispatch` (`.github/ci/agent-lane/trigger-deploy.sh`). A manual run does the
   same; `-f all=true` rebuilds every image.
3. build-and-push builds only the images whose code changed since the last commit it published
   completely (tag `ops-deploy/built`), picked by `.github/ci/build-matrix.sh`. The backend image
   (api, worker and beat) is built only when `apps/api/` changes, so a frontend push does not
   restart the API. Each image is pushed as `:preview` and `:sha-<7 chars>`, and the image that was
   live before is kept as `:previous`.
4. Watchtower on the NAS polls every 60 s and recreates the containers whose `:preview` changed,
   one at a time. While a container boots, Caddy holds its requests (up to 60 s) instead of
   answering 502. The API boots in ~8 s (static files are collected at build).
5. Zil's `ops-deploy-check` (every 15 min) compares the `preview` tip with `ops-deploy/built` and
   the commit the API reports (`/api/zil/sync/version/`) with `ops-deploy/backend`. If either is
   behind for 45 min, cron-watchdog opens a BugReport.

Runs queue instead of cancelling each other, and each one diffs from `ops-deploy/built`, so a run
that GitHub drops from the queue or a failed image is built by the next run.

Check what is live:

```bash
gh run list -R zil-media/plane -w build-and-push -L 5
git ls-remote https://github.com/zil-media/plane.git preview 'refs/tags/ops-deploy/*'
docker buildx imagetools inspect ghcr.io/zil-media/plane-backend:preview \
  --format '{{ index .Image.Config.Labels "org.opencontainers.image.revision" }}'
```

## Rollback

One command per image. It copies `:previous` (or any `sha-<7 chars>`) onto `:preview`; Watchtower
deploys it within a minute:

```bash
gh workflow run rollback.yml -R zil-media/plane -f image=plane-backend
gh workflow run rollback.yml -R zil-media/plane -f image=plane-web -f to=sha-0f6f6e4
```

- Images: `plane-backend` (api, worker, beat), `plane-web`, `plane-space`, `plane-admin`,
  `plane-live`, `plane-proxy`, `plane-mcp`.
- Rolling back the backend also moves `ops-deploy/backend`, so ops-deploy-check does not report
  the rollback as a stuck deploy.
- The backend runs `migrate` on boot, but a rollback does not undo migrations. An older backend
  usually runs fine on a newer schema (added columns or tables). If the bad commit dropped or
  renamed a column, roll forward with a fix instead.
- The next build of that image deploys forward again. To pin the old image until a fix lands,
  do not push changes to that app.

## Backups

Nightly on the NAS (`/etc/cron.d/plane-pg-backup`, 03:15 ART):

1. `/usr/local/sbin/plane-pg-backup.sh`: `pg_dump` of the Plane database to
   `/home/Brian/backups/plane-pg-<stamp>.sql.gz`, checked (gzip valid, more than 1 MB, end
   marker), and pruned after 14 days, always keeping the last 7.
2. `/usr/local/sbin/plane-offsite-backup.sh`: encrypts that dump and a tarball of the MinIO data
   (`/home/Brian/plane-selfhost/minio`, the uploads) with AES-256 (key
   `/home/Brian/.secrets/plane-backup.key`, which also lives in the password manager, off the NAS)
   and uploads both to R2, bucket `workspace`, prefixes `plane-backups/pg/` and
   `plane-backups/minio/`, kept 30 days.

The cron line runs as `Brian`, not `root`: on TOS uid 0 is named `Brian` and `root` is an
unprivileged user (uid 9999) with no access to the Docker socket. With `root` every night failed
with "permission denied ... docker.sock" from 2026-10-19 to 2026-10-22. Any other `/etc/cron.d`
entry that needs privileges (`ip-guard`, `atop`) uses `Brian` for the same reason.

Both log to syslog with tag `plane-backup` (`grep plane-backup /var/log/messages`). Zil's
`ops-backup-check` (daily, 16:00 UTC) fails and opens a BugReport if the newest object under
either prefix is older than 26 h or smaller than 1 MB. A backup that did not run is caught as well
as one that failed.

### Restore

```bash
KEY=/home/Brian/.secrets/plane-backup.key
dec() { openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$KEY" -in "$1" -out "$2"; }

# from R2 (rclone remote R2 as used by vault-backup), or use the local copy in /home/Brian/backups
docker run --rm -v /home/Brian/vault/rclone:/config/rclone:ro -v /tmp/restore:/r rclone/rclone:1.68.2 \
  copy R2:workspace/plane-backups/pg/plane-pg-<stamp>.sql.gz.enc /r/
dec /tmp/restore/plane-pg-<stamp>.sql.gz.enc /tmp/restore/plane.sql.gz

# 1. test it in a scratch Postgres first and compare counts with live
docker run -d --name plane-restore-test -e POSTGRES_USER=plane -e POSTGRES_PASSWORD=x -e POSTGRES_DB=plane postgres:15.7-alpine
gzip -dc /tmp/restore/plane.sql.gz | docker exec -i plane-restore-test psql -q -U plane plane
docker exec plane-restore-test psql -U plane plane -tAc 'select count(*) from issues'
docker rm -f plane-restore-test

# 2. real restore: stop api, worker, beat-worker, then load into an empty plane database
#    (drop and recreate it) and start them again.

# MinIO: stop plane-minio, move /home/Brian/plane-selfhost/minio aside, then
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "file:$KEY" -in plane-minio-<stamp>.tar.gz.enc \
  | tar -xzf - -C /home/Brian/plane-selfhost
```

The `minio/minio` image is no longer published on Docker Hub. The NAS runs
`RELEASE.2025-09-07T16-13-09Z` from its local image cache, tagged `minio/minio:RELEASE.2025-09-07T16-13-09Z` with `pull_policy: never`. A copy is kept
in `/home/Brian/backups/minio-image-RELEASE.2025-09-07T16-13-09Z.tar.gz` (`docker load -i` on a new
host) until MinIO is replaced.
