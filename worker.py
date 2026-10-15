#!/usr/bin/env python3
"""Periodically retry failed FxTwitter enrichments from SQLite."""
import json
import logging
import signal
import threading
import time

import bridge

stopping = threading.Event()

def stop(_signal, _frame):
    stopping.set()

def schedule_legacy():
    # Seed pre-worker unenriched rows once. Exhausted rows (retry_count=3)
    # remain untouched on subsequent worker restarts.
    with bridge.connect() as db:
        rows = db.execute(
            "SELECT id, payload FROM events WHERE enriched=0 AND retry_count=0 AND next_retry_at IS NULL"
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
                tweet_id = bridge.normalize(payload)[-1] if isinstance(payload, dict) else None
            except (ValueError, TypeError, AttributeError):
                tweet_id = None
            if tweet_id and tweet_id.isdigit():
                db.execute(
                    "UPDATE events SET next_retry_at=? WHERE id=? AND enriched=0 AND retry_count=0 AND next_retry_at IS NULL",
                    (bridge.next_retry_at(0), row["id"]),
                )

def main():
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if bridge.FXTWITTER_WORKER_INTERVAL < 1:
        raise ValueError("FXTWITTER_WORKER_INTERVAL must be positive")
    schedule_legacy()
    while not stopping.is_set():
        try:
            completed = bridge.retry_pending()
            if completed:
                logging.info("Enriched %s pending tweets", completed)
        except Exception:
            logging.exception("Retry worker error")
        stopping.wait(bridge.FXTWITTER_WORKER_INTERVAL)

if __name__ == "__main__":
    main()
