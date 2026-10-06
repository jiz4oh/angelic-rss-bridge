# angelic-rss-bridge

A minimal webhook-to-RSS bridge for [Angelic Angel](https://github.com/sh1ma/Angelic-Angel), intended for RSS consumers such as RSStT.

## Architecture

```text
Twitter/X -> Mozilla AutoPush -> Angelic Angel -> POST /webhook -> SQLite -> GET /rss -> RSStT -> Telegram
```

This repository tracks Angelic Angel as the `upstream/Angelic-Angel` Git submodule for image builds. Runtime deployment uses prebuilt images from GitHub Container Registry; no local build is required.

## Deploy with Docker Compose

Download or copy `compose.yml` and `.env.example` from this repository, then create your environment file:

```sh
cp .env.example .env
```

Pull the published images:

```sh
docker compose pull
```

Initialize Angelic Angel with your X cookies:

```sh
docker compose run --rm angelic-angel \
  init --auth-token YOUR_AUTH_TOKEN --ct0 YOUR_CT0
```

Register the Web Push subscription:

```sh
docker compose run --rm angelic-angel register
```

Start the bridge and listener:

```sh
docker compose up -d
```

Check service state:

```sh
docker compose ps
docker compose run --rm angelic-angel status
```

Follow logs:

```sh
docker compose logs -f bridge angelic-angel
```

The RSS feed is exposed at:

```text
http://HOST:8080/rss
```

Subscribe this URL in RSStT.

## Updating

Pull newly published images and recreate the containers:

```sh
docker compose pull
docker compose up -d
```

The `angelic-config` volume preserves Angelic Angel credentials and registration state, and `bridge-data` preserves RSS history, so normal image updates do not require reinitialization or re-registration.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BRIDGE_PORT` | `8080` | Host port for the RSS bridge |
| `FEED_TITLE` | `Angelic Angel` | RSS channel title |
| `FEED_LINK` | `http://localhost:8080/rss` | RSS channel link |
| `MAX_ITEMS` | `100` | Maximum number of RSS items returned |
| `RUST_LOG` | `info` | Angelic Angel logging level |

## Endpoints

- `POST /webhook` receives decrypted notification JSON from Angelic Angel.
- `GET /rss` and `GET /rss.xml` return RSS 2.0.
- `GET /health` checks the bridge and SQLite database.

Duplicate events are ignored. The bridge prefers tweet/status IDs as RSS GUIDs and falls back to a hash of the canonical JSON payload when no stable ID is available.

## Persistent data

Docker Compose creates two named volumes:

- `angelic-config`: stores `angelic-angel.toml`, including X credentials and Web Push registration state.
- `bridge-data`: stores the SQLite database used by the RSS bridge.

Treat `angelic-config` as sensitive.

## Image publishing

GitHub Actions publishes:

- `ghcr.io/jiz4oh/angelic-rss-bridge:latest`
- `ghcr.io/jiz4oh/angelic-angel:latest`

The bridge image is rebuilt when bridge source or its Dockerfile changes.

The Angelic Angel image is rebuilt when the tracked `upstream/Angelic-Angel` submodule pointer or `Dockerfile.angelic-angel` changes. A scheduled workflow checks the upstream `main` branch daily and advances the submodule pointer only when upstream has changed.
