# angelic-rss-bridge

A minimal webhook-to-RSS bridge for [Angelic Angel](https://github.com/sh1ma/Angelic-Angel), intended for RSS consumers such as RSStT.

## Architecture

```text
Twitter/X -> Mozilla AutoPush -> Angelic Angel -> POST /webhook -> SQLite -> GET /rss -> RSStT -> Telegram
```

Runtime deployment uses prebuilt images from GitHub Container Registry. No local image build is required.

## Directory layout

```text
.
├── compose.yml
├── .env
└── data
    ├── angelic-angel
    │   └── angelic-angel.toml   # created by init
    └── bridge
        └── bridge.db            # created automatically
```

Both data directories are bind-mounted from the directory containing `compose.yml`. Runtime contents are ignored by Git.

## First-time setup

Create the environment file:

```sh
cp .env.example .env
```

At minimum, configure the bridge port and public feed URL:

```dotenv
BRIDGE_PORT=8080
FEED_LINK=http://YOUR_HOST:8080/rss
```

Pull the published images:

```sh
docker compose pull
```

Initialize Angelic Angel. This creates `./data/angelic-angel/angelic-angel.toml`:

```sh
docker compose run --rm angelic-angel \
  init --auth-token YOUR_AUTH_TOKEN --ct0 YOUR_CT0
```

Register the Web Push subscription and persist it in the same config file:

```sh
docker compose run --rm angelic-angel register
```

Verify the registration:

```sh
docker compose run --rm angelic-angel status
```

Then start both long-running services:

```sh
docker compose up -d
```

Check service state and logs:

```sh
docker compose ps
docker compose logs -f bridge angelic-angel
```

The RSS feed is available at the URL configured by `FEED_LINK`. Subscribe that URL in RSStT.

## Updating

Pull new images and recreate the containers:

```sh
docker compose pull
docker compose up -d
```

The bind-mounted `./data/angelic-angel` and `./data/bridge` directories remain unchanged during image updates, so normal updates do not require initialization or registration again.

## Configuration

| Variable | Example | Purpose |
| --- | --- | --- |
| `BRIDGE_PORT` | `8080` | Bridge listen port, container port, published host port, internal webhook port, and healthcheck port |
| `FEED_TITLE` | `Angelic Angel` | RSS channel title |
| `FEED_LINK` | `http://host:8080/rss` | Public RSS channel URL |
| `MAX_ITEMS` | `100` | Maximum number of RSS items returned |
| `RUST_LOG` | `info` | Angelic Angel logging level |

`BRIDGE_PORT` and `FEED_LINK` are defined in `.env`; Compose does not hard-code the bridge port.

## Endpoints

The bridge exposes these paths on `BRIDGE_PORT`:

- `POST /webhook` receives decrypted notification JSON from Angelic Angel.
- `GET /rss` and `GET /rss.xml` return RSS 2.0.
- `GET /health` checks the bridge and SQLite database.

Duplicate events are ignored. The bridge prefers tweet/status IDs as RSS GUIDs and falls back to a hash of the canonical JSON payload when no stable ID is available.

## Persistent data

- `./data/angelic-angel/angelic-angel.toml` contains X credentials and Web Push registration state. Treat it as sensitive.
- `./data/bridge/bridge.db` contains received events and RSS history.

## Image publishing

GitHub Actions publishes:

- `ghcr.io/jiz4oh/angelic-rss-bridge:latest`
- `ghcr.io/jiz4oh/angelic-angel:latest`

The bridge image is rebuilt when bridge source or its Dockerfile changes.

The Angelic Angel image is rebuilt when the tracked `upstream/Angelic-Angel` submodule pointer or `Dockerfile.angelic-angel` changes. A scheduled workflow checks upstream daily and advances the submodule pointer only when upstream has changed.
