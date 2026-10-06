# angelic-rss-bridge

A minimal webhook-to-RSS bridge for [Angelic Angel](https://github.com/sh1ma/Angelic-Angel), intended for RSS consumers such as RSStT.

## Architecture

```text
Twitter/X -> Mozilla AutoPush -> Angelic Angel -> POST /webhook -> SQLite -> GET /rss -> RSStT -> Telegram
```

This repository does not fork or modify Angelic Angel. It tracks Angelic Angel as the `upstream/Angelic-Angel` Git submodule and runs the bridge beside it.

The submodule is checked for upstream changes daily. When upstream changes, GitHub Actions advances the submodule pointer and publishes a new Angelic Angel container image.

## Quick start

Copy the environment file:

```sh
cp .env.example .env
```

Build the images:

```sh
git submodule update --init --recursive
docker compose build
```

Initialize Angelic Angel with your X cookies:

```sh
docker compose run --rm angelic-angel init --auth-token YOUR_AUTH_TOKEN --ct0 YOUR_CT0
```

Register the Web Push subscription:

```sh
docker compose run --rm angelic-angel register
```

Start both services:

```sh
docker compose up -d
```

Check status and logs:

```sh
docker compose run --rm angelic-angel status
docker compose logs -f angelic-angel bridge
```

The RSS feed is available at:

```text
http://HOST:8080/rss
```

Subscribe that URL in RSStT.

## Endpoints

- `POST /webhook` accepts the decrypted JSON payload forwarded by Angelic Angel.
- `GET /rss` and `GET /rss.xml` return RSS 2.0.
- `GET /health` checks the bridge and SQLite database.

Webhook responses contain the derived event ID and whether the event was newly inserted. Duplicate events are ignored.

## Payload handling

Angelic Angel currently forwards the decrypted X notification JSON without defining a stable payload schema. The bridge therefore stores the complete original JSON and extracts common fields recursively for RSS presentation.

It prefers tweet/status IDs for stable RSS GUIDs. If none exists, it hashes the canonical JSON payload. This keeps ingestion lossless even when X changes notification fields.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BRIDGE_PORT` | `8080` | Host port for the bridge |
| `FEED_TITLE` | `Angelic Angel` | RSS channel title |
| `FEED_LINK` | `http://localhost:8080/rss` | RSS channel link |
| `MAX_ITEMS` | `100` | Maximum items returned in the feed |
| `ANGELIC_ANGEL_REF` | `main` | Upstream Angelic Angel branch/tag to build |
| `RUST_LOG` | `info` | Angelic Angel logging level |

## Upstream synchronization and container images

`upstream/Angelic-Angel` is a Git submodule tracking the upstream `main` branch.

The `sync upstream` workflow runs daily and can also be started manually. It updates and commits the submodule pointer only when upstream has changed.

The `build and publish` workflow publishes images to GitHub Container Registry:

- `ghcr.io/jiz4oh/angelic-rss-bridge:latest` is rebuilt when bridge source or its Dockerfile changes.
- `ghcr.io/jiz4oh/angelic-angel:latest` is rebuilt when the Angelic Angel submodule pointer or its Dockerfile changes.
- Bridge builds also receive a Git commit SHA tag.
- Angelic Angel builds also receive the tracked upstream commit SHA tag.

Both build jobs use GitHub Actions BuildKit cache. A manual workflow dispatch can force either image to rebuild independently.

To update the submodule manually:

```sh
git submodule update --init --remote upstream/Angelic-Angel
git add upstream/Angelic-Angel
git commit -m "chore: sync Angelic Angel upstream"
```

## Data

Two named volumes are used:

- `angelic-config` contains `angelic-angel.toml`, including X credentials and Web Push registration state.
- `bridge-data` contains the SQLite database.

Treat `angelic-config` as sensitive and do not publish or commit its contents.
