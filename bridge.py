#!/usr/bin/env python3
import hashlib
import html
import json
import os
import sqlite3
import logging
from urllib.request import Request, urlopen
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse
import re

DB_PATH = os.getenv("DB_PATH", "/data/bridge.db")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
FEED_TITLE = os.getenv("FEED_TITLE", "Angelic Angel")
FEED_LINK = os.getenv("FEED_LINK", "http://localhost:8080/rss")
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "100"))
FXTWITTER_ENABLED = os.getenv("FXTWITTER_ENABLED", "true").lower() in ("true", "1", "yes")
FXTWITTER_API_BASE = os.getenv("FXTWITTER_API_BASE", "https://api.fxtwitter.com").rstrip("/")
FXTWITTER_TIMEOUT = float(os.getenv("FXTWITTER_TIMEOUT", "5"))

def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        received_at TEXT NOT NULL,
        username TEXT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        link TEXT,
        payload TEXT NOT NULL,
        enriched INTEGER NOT NULL DEFAULT 0
    )""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_username_received_at "
        "ON events(username COLLATE NOCASE, received_at DESC)"
    )
    return db

def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

def first(payload, keys):
    for obj in walk(payload):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
    return None

def fetch_tweet(tweet_id):
    if not FXTWITTER_ENABLED or not tweet_id or not tweet_id.isdigit():
        return None
    try:
        request = Request(
            f"{FXTWITTER_API_BASE}/2/status/{tweet_id}",
            headers={"User-Agent": "angelic-rss-bridge/1.0", "Accept": "application/json"},
        )
        with urlopen(request, timeout=FXTWITTER_TIMEOUT) as response:
            result = json.load(response)
        status = result.get("status")
        if result.get("code") != 200 or not isinstance(status, dict):
            return None
        if str(status.get("id")) != tweet_id or not isinstance(status.get("text"), str):
            return None
        author = status.get("author") or {}
        username = author.get("screen_name") if isinstance(author, dict) else None
        if username and not re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
            username = None
        return {"body": status["text"], "username": username, "link": status.get("url")}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logging.warning("FxTwitter lookup failed for %s: %s", tweet_id, exc)
        return None

def normalize(payload):
    uri = payload.get("data", {}).get("uri") if isinstance(payload.get("data"), dict) else None
    match = re.match(r"^/(?:@)?([A-Za-z0-9_]{1,15})/status/\\d+(?:[/?#].*)?$", uri) if isinstance(uri, str) else None
    username = match.group(1) if match else first(payload, ("screen_name", "username"))
    title = first(payload, ("title", "screen_name", "username", "name")) or "X notification"
    body = first(payload, ("body", "text", "message", "content")) or json.dumps(payload, ensure_ascii=False)
    link = first(payload, ("url", "link", "uri", "target_url"))
    if isinstance(link, str) and link.startswith("/"):
        link = "https://x.com" + link
    tweet_id = first(payload, ("tweet_id", "status_id", "rest_id"))
    if not link and tweet_id:
        link = f"https://x.com/{username or 'i'}/status/{tweet_id}"
    stable = tweet_id or first(payload, ("id", "notification_id"))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    event_id = stable or hashlib.sha256(canonical.encode()).hexdigest()
    return event_id, username, title, body, link, canonical, tweet_id

def store(payload):
    event_id, username, title, body, link, canonical, tweet_id = normalize(payload)
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        row = db.execute("SELECT enriched FROM events WHERE id = ?", (event_id,)).fetchone()
        if row and row["enriched"]:
            return event_id, False

    details = fetch_tweet(tweet_id)
    enriched = 1 if details else 0
    if details:
        username = details["username"] or username
        body = details["body"]
        link = details["link"] or link

    with connect() as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO events"
            "(id, received_at, username, title, body, link, payload, enriched) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (event_id, now, username, title, body, link, canonical, enriched),
        )
        inserted = cursor.rowcount > 0
        if not inserted and enriched:
            db.execute(
                "UPDATE events SET username=?, body=?, link=?, enriched=1 "
                "WHERE id=? AND enriched=0",
                (username, body, link, event_id),
            )
    return event_id, inserted

