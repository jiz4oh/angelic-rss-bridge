# angelic-rss-bridge

A minimal webhook-to-RSS bridge for [Angelic Angel](https://github.com/sh1ma/Angelic-Angel), intended for RSS consumers such as RSStT.

## Architecture

```text
Twitter/X -> Mozilla AutoPush -> Angelic Angel -> POST /webhook -> SQLite -> RSS -> RSStT -> Telegram
```

Runtime deployment uses prebuilt images from GitHub Container Registry. No local image build is required.

## Directory layout

```text
.
├── compose.yml
├── .env
└── data
    ├── angelic-angel
    │   └── angelic-angel.toml
    └── bridge
        └── bridge.db
```

Both data directories are bind-mounted from the directory containing `compose.yml`. Runtime contents are ignored by Git.

## First-time setup

Create the environment file:

```sh
cp .env.example .env
```

Configure `.env`, then pull the published images:

```sh
docker compose pull
```

Initialize Angelic Angel:

```sh
docker compose run --rm angelic-angel \
  init --auth-token YOUR_AUTH_TOKEN --ct0 YOUR_CT0
```

Register and verify the Web Push subscription:

```sh
docker compose run --rm angelic-angel register
docker compose run --rm angelic-angel status
```

Start both services:

```sh
docker compose up -d
```

Check service state and logs:

```sh
docker compose ps
docker compose logs -f bridge angelic-angel
```

## RSS feeds

The bridge exposes account-specific feeds only:

```text
http://HOST:PORT/rss/alice
http://HOST:PORT/rss/bob
```

The leading `@` is optional and usernames are matched case-insensitively. `/rss` and `/rss.xml` are not feed endpoints. `MAX_ITEMS` limits each account feed independently.

## Tweet text enrichment

When a notification contains a tweet ID, the bridge looks up the full post text using FxTwitter's `/2/status/{id}` API before saving it. Successful responses provide the canonical author username, full text, and post URL. On API errors or unavailable posts, the original notification is saved instead. A duplicate webhook for an un-enriched post triggers another lookup; enriched posts are not fetched again. No background retry worker is included.

This version requires a fresh database schema with an `enriched` column. Existing databases are not migrated automatically.

## Updating

Pull new images and recreate the containers:

```sh
docker compose pull
docker compose up -d
```

The bind-mounted data directories remain unchanged during image updates.

## Configuration

| Variable | Example | Purpose |
| --- | --- | --- |
| `BRIDGE_PORT` | `8080` | Bridge listen port, published host port, internal webhook port, and healthcheck port |
| `FEED_TITLE` | `Angelic Angel` | Base RSS channel title; account feeds append `@username` |
| `FEED_LINK` | `http://host:8080/rss` | Base URL placed in RSS channel metadata |
| `MAX_ITEMS` | `100` | Maximum entries returned by each feed request |
| `RUST_LOG` | `info` | Angelic Angel logging level |
| `FXTWITTER_ENABLED` | `true` | Enable full-text lookup for tweet notifications |
| `FXTWITTER_API_BASE` | `https://api.fxtwitter.com` | FxTwitter API host |
| `FXTWITTER_TIMEOUT` | `5` | Lookup timeout in seconds |

## Endpoints

- `POST /webhook` receives decrypted notification JSON from Angelic Angel.
- `GET /rss/<username>` returns the RSS feed for one X account. `/rss` without a username is not a feed endpoint.
- `GET /health` checks the bridge and SQLite database.

Duplicate events are ignored. The bridge stores the extracted X username with each new event and prefers tweet/status IDs as RSS GUIDs, falling back to a hash of the canonical JSON payload when no stable ID is available.

## Persistent data

- `./data/angelic-angel/angelic-angel.toml` contains X credentials and Web Push registration state. Treat it as sensitive.
- `./data/bridge/bridge.db` contains received events and RSS history.

## Image publishing

GitHub Actions publishes:

- `ghcr.io/jiz4oh/angelic-rss-bridge:latest`
- `ghcr.io/jiz4oh/angelic-angel:latest`

The bridge image is rebuilt when bridge source or its Dockerfile changes.

The Angelic Angel image is rebuilt when the tracked `upstream/Angelic-Angel` submodule pointer or `Dockerfile.angelic-angel` changes. A scheduled workflow checks upstream daily and advances the submodule pointer only when upstream has changed.
