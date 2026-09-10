# Scheduler Compose operations

`compose.yaml` builds the private scheduler directly from this repository on
the supported `python:3.12-slim-bookworm` base. It starts only
`python -m fantasy_advisor.scheduler`; the native launchd Discord gateway is a
separate runtime and must not be added to this Compose project.

## Configuration and first start

Create the persistent host directories before starting. They must be writable
by container UID/GID `999:999` (`fantasy`), preserving the live numeric
ownership contract:

```bash
mkdir -p /path/to/canonical/fantasy/data /path/to/canonical/fantasy/reports
```

Keep secrets in an external, host-readable environment file that is not in the
repository. The scheduler needs these values for scheduled Owner-DM delivery:

```dotenv
DISCORD_BOT_TOKEN=...
DISCORD_ALLOWED_USER_ID=...
OPENAI_API_KEY=...
```

Optional scheduler settings read by the application are
`CODEX_TIMEOUT_SECONDS`, `CODEX_INTERACTIVE_TIMEOUT_SECONDS`,
`LINEUP_ALERT_LEAD_MINUTES`, `DEADLINE_GUARDIAN_FINAL_LEAD_MINUTES`,
`OPENAI_WEB_MODEL`, and `OPENAI_WEB_REASONING_EFFORT`. The image fixes
`FANTASY_REPO_ROOT=/app`; do not override it.

When Compose is run from a disposable or external deployment checkout, point
the bind mounts at the canonical persistent project root and the env file at
its external absolute path:

```bash
FANTASY_HOST_ROOT=/path/to/canonical/fantasy \
FANTASY_ENV_FILE=/path/to/private/fantasy-scheduler.env \
docker compose config --quiet

FANTASY_HOST_ROOT=/path/to/canonical/fantasy \
FANTASY_ENV_FILE=/path/to/private/fantasy-scheduler.env \
FANTASY_SCHEDULER_IMAGE='gf-fantasy-scheduler:task-<immutable-id>' \
docker compose up -d --build scheduler
```

Do not copy either the environment file or the existing `data/` and `reports/`
contents into the build context. The included `.dockerignore` excludes them,
along with Git metadata and virtual environments. Compose publishes no ports.

## Verification

After the 180-second health start period, require the container health state to
be `healthy` and inspect the application-owned probe directly:

```bash
docker compose ps scheduler
docker compose exec scheduler \
  python -m fantasy_advisor.health --component scheduler
docker compose exec scheduler \
  python -m fantasy_advisor.automation --list-tasks
```

The probe is local and network-free. A running container alone is not proof
that scheduled work is healthy. The supported task-list command confirms the
scheduler registry loads without dispatching work. Host deployment verification
must also verify the unchanged native Discord gateway independently, with
exactly one Discord listener and one scheduler.

## Rollback and recovery

Before rebuilding, record the running container's exact immutable image
reference. Build the replacement under a unique task tag; building does not
stop that container:

```bash
previous_container="$(docker compose ps -q scheduler)"
previous_image="$(docker inspect --format '{{.Image}}' "$previous_container")"
export FANTASY_SCHEDULER_IMAGE='gf-fantasy-scheduler:task-<immutable-id>'
docker compose build scheduler
```

Keep the old container running until the build succeeds, then use
`docker compose up -d --no-build scheduler` and perform the verification above.
Do not prune the prior image until the replacement passes health and smoke
checks. If it fails, select the recorded prior immutable image and recreate
only the scheduler:

```bash
export FANTASY_SCHEDULER_IMAGE="$previous_image"
docker compose up -d --no-build --force-recreate scheduler
```

This rollback keeps the same `data/` and `reports/` bind mounts; repeat the
old-version health and task-list checks afterward. Do not use
`gf-fantasy-scheduler:health-a47fb0b` as a build base. Rollback runs a retained
prior image instead of layering new source on it.

The bind mounts preserve application state across image replacement, but they
are not backups. No backup system is configured by this Compose file, so full
disaster recovery remains dependent on a separately managed backup of the
canonical host data.
