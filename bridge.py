#!/usr/bin/env python3
import hashlib
import html
import json
import os
import sqlite3
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
        payload TEXT NOT NULL
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
    return event_id, username, title, body, link, canonical

def store(payload):
    event_id, username, title, body, link, canonical = normalize(payload)
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO events"
            "(id, received_at, username, title, body, link, payload) "
            "VALUES(?,?,?,?,?,?,?)",
            (event_id, now, username, title, body, link, canonical),
        )
        inserted = cursor.rowcount > 0
    return event_id, inserted

def rss(username):
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM events WHERE username = ? COLLATE NOCASE "
            "ORDER BY received_at DESC LIMIT ?",
            (username, MAX_ITEMS),
        ).fetchall()

    items = []
    for row in rows:
        dt = datetime.fromisoformat(row["received_at"])
        link = row["link"] or ""
        items.append(
            "<item>"
            f"<guid isPermaLink=\"false\">{html.escape(row['id'])}</guid>"
            f"<title>{html.escape(row['title'])}</title>"
            f"<description>{html.escape(row['body'])}</description>"
            f"<pubDate>{format_datetime(dt)}</pubDate>"
            + (f"<link>{html.escape(link)}</link>" if link else "")
            + "</item>"
        )

    feed_title = f"{FEED_TITLE} - @{username}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>{html.escape(feed_title)}</title>"
        f"<link>{html.escape(FEED_LINK)}</link>"
        "<description>Twitter/X notifications received by Angelic Angel</description>"
        + "".join(items)
        + "</channel></rss>"
    ).encode()

class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body=b"", content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/rss/") and len(path) > len("/rss/"):
            username = unquote(path[len("/rss/"):]).lstrip("@").strip()
            if not username or "/" in username:
                self.reply(404, b"not found\n")
                return
            self.reply(200, rss(username), "application/rss+xml; charset=utf-8")
        elif path == "/health":
            try:
                with connect() as db:
                    db.execute("SELECT 1").fetchone()
                self.reply(200, b"ok\n")
            except Exception as exc:
                self.reply(503, (str(exc) + "\n").encode())
        else:
            self.reply(404, b"not found\n")

    def do_POST(self):
        if urlparse(self.path).path != "/webhook":
            self.reply(404, b"not found\n")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("invalid payload size")
            payload = json.loads(self.rfile.read(length))
            event_id, inserted = store(payload)
            body = json.dumps({"id": event_id, "inserted": inserted}).encode()
            self.reply(200, body, "application/json")
        except (ValueError, json.JSONDecodeError) as exc:
            self.reply(400, (str(exc) + "\n").encode())
        except Exception as exc:
            self.reply(500, (str(exc) + "\n").encode())

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with connect():
        pass
    print(f"listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
