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
from urllib.parse import unquote, urlparse, quote
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
        enriched INTEGER NOT NULL DEFAULT 0,
        details TEXT
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
        return {"body": status["text"], "username": username, "link": status.get("url"), "status": status}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logging.warning("FxTwitter lookup failed for %s: %s", tweet_id, exc)
        return None

def normalize(payload):
    uri = payload.get("data", {}).get("uri") if isinstance(payload.get("data"), dict) else None
    match = re.match(r"^/(?:@)?([A-Za-z0-9_]{1,15})/status/(\d+)(?:[/?#].*)?$", uri) if isinstance(uri, str) else None
    username = match.group(1) if match else first(payload, ("screen_name", "username"))
    title = first(payload, ("title", "screen_name", "username", "name")) or "X notification"
    body = first(payload, ("body", "text", "message", "content")) or json.dumps(payload, ensure_ascii=False)
    link = first(payload, ("url", "link", "uri", "target_url"))
    if isinstance(link, str) and link.startswith("/"):
        link = "https://x.com" + link
    tweet_id = first(payload, ("tweet_id", "status_id", "rest_id")) or (match.group(2) if match else None)
    if not link and tweet_id:
        link = f"https://x.com/{username or 'i'}/status/{tweet_id}"
    stable = tweet_id or first(payload, ("id", "notification_id"))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    event_id = stable or hashlib.sha256(canonical.encode()).hexdigest()
    return event_id, username, title, body, link, canonical, tweet_id

def fxtwitter_link(username, tweet_id):
    if username and tweet_id and re.fullmatch(r"[A-Za-z0-9_]{1,15}", username) and str(tweet_id).isdigit():
        return f"https://fxtwitter.com/{username}/status/{tweet_id}"
    return None

def media_html(status):
    media = status.get("media") or {}
    if not isinstance(media, dict):
        return ""
    entries = media.get("all")
    if not isinstance(entries, list):
        entries = (media.get("photos") or []) + (media.get("videos") or [])
    output = []
    seen = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "photo":
            url = item.get("url")
            if not isinstance(url, str) or urlparse(url).scheme != "https" or url in seen:
                continue
            seen.add(url)
            alt = html.escape(str(item.get("altText") or ""), quote=True)
            output.append(f'<p><img src="{html.escape(url, quote=True)}" alt="{alt}" /></p>')
        elif kind in ("video", "gif"):
            variants = item.get("formats") or []
            mp4 = [v for v in variants if isinstance(v, dict) and v.get("container") == "mp4" and isinstance(v.get("url"), str) and urlparse(v["url"]).scheme == "https"]
            mp4.sort(key=lambda v: v.get("bitrate") or 0, reverse=True)
            url = mp4[0]["url"] if mp4 else item.get("url")
            if not isinstance(url, str) or urlparse(url).scheme != "https" or not urlparse(url).path.lower().endswith(".mp4") or url in seen:
                continue
            seen.add(url)
            poster = item.get("thumbnail_url")
            poster_attr = f' poster="{html.escape(poster, quote=True)}"' if isinstance(poster, str) and urlparse(poster).scheme == "https" else ""
            output.append(f'<p><video controls{poster_attr}><source src="{html.escape(url, quote=True)}" type="video/mp4" /></video></p>')
    return "".join(output)

def description(body, details):
    content = "<p>" + html.escape(body).replace("\n", "<br />") + "</p>"
    if not details:
        return content
    status = json.loads(details)
    if not isinstance(status, dict):
        return content
    content += media_html(status)
    quoted = status.get("quote")
    if isinstance(quoted, dict) and isinstance(quoted.get("text"), str):
        author = quoted.get("author") or {}
        if not isinstance(author, dict):
            author = {}
        name = str(author.get("name") or author.get("screen_name") or "Quoted post")
        handle = author.get("screen_name")
        quote_link = fxtwitter_link(handle, quoted.get("id"))
        label = html.escape(name)
        if quote_link:
            label = f'<a href="{html.escape(quote_link, quote=True)}">{label}</a>'
        content += f"<blockquote><p><strong>{label}</strong></p><p>"
        content += html.escape(quoted["text"]).replace("\n", "<br />") + "</p></blockquote>"
    return content

def tweet_date(status, fallback):
    stamp = status.get("created_timestamp")
    if isinstance(stamp, (int, float)) and stamp > 0:
        try:
            return datetime.fromtimestamp(stamp, timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    return fallback

def hashtags(text):
    return list(dict.fromkeys(re.findall(r"(?<!\\w)#([\\w]+)", text, flags=re.UNICODE)))


def store(payload):
    event_id, username, title, body, link, canonical, tweet_id = normalize(payload)
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        row = db.execute("SELECT enriched FROM events WHERE id = ?", (event_id,)).fetchone()
        if row and row["enriched"]:
            return event_id, False

    details = fetch_tweet(tweet_id)
    enriched = 1 if details else 0
    details_json = json.dumps(details["status"], ensure_ascii=False) if details else None
    if details:
        username = details["username"] or username
        body = details["body"]
        link = details["link"] or link

    with connect() as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO events"
            "(id, received_at, username, title, body, link, payload, enriched, details) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (event_id, now, username, title, body, link, canonical, enriched, details_json),
        )
        inserted = cursor.rowcount > 0
        if not inserted and enriched:
            db.execute(
                "UPDATE events SET username=?, body=?, link=?, enriched=1, details=? "
                "WHERE id=? AND enriched=0",
                (username, body, link, details_json, event_id),
            )
    return event_id, inserted

def rss(username):
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM events WHERE username = ? COLLATE NOCASE ORDER BY received_at DESC LIMIT ?",
            (username, MAX_ITEMS),
        ).fetchall()
    items = []
    for row in rows:
        status = json.loads(row["details"]) if row["details"] else {}
        if not isinstance(status, dict):
            status = {}
        author = status.get("author") or {}
        if not isinstance(author, dict):
            author = {}
        handle = author.get("screen_name") or row["username"]
        display_name = str(author.get("name") or row["title"])
        tweet_id = status.get("id") or row["id"]
        link = fxtwitter_link(handle, tweet_id) or row["link"] or ""
        body = row["body"]
        title = f"{display_name}: {body.replace(chr(10), ' ').strip()}"
        if status.get("replying_to"):
            title = "↩️ " + title
        dt = tweet_date(status, datetime.fromisoformat(row["received_at"]))
        item = [
            "<item>",
            f'<guid isPermaLink="false">{html.escape(row["id"])}</guid>',
            f"<title>{html.escape(title[:240])}</title>",
            f"<description>{html.escape(description(body, row['details']))}</description>",
            f"<pubDate>{format_datetime(dt)}</pubDate>",
        ]
        if link:
            item.append(f"<link>{html.escape(link)}</link>")
        if handle and re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
            item.append(f"<author>{html.escape('@' + handle)}</author>")
        for tag in hashtags(body):
            item.append(f"<category>{html.escape(tag)}</category>")
        item.append("</item>")
        items.append("".join(item))
    feed_title = f"{FEED_TITLE} - @{username}"
    feed_link = f"https://fxtwitter.com/{username}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>{html.escape(feed_title)}</title>"
        f"<link>{html.escape(feed_link)}</link>"
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
            if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
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
