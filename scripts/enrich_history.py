#!/usr/bin/env python3
"""One-time backfill of unenriched X notifications using the existing FxTwitter client."""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bridge


def tweet_id_for(row):
    try:
        payload = json.loads(row["payload"])
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    # Reuse production extraction when possible; old SHA256 IDs still work.
    _, _, _, _, _, _, tweet_id = bridge.normalize(payload)
    if tweet_id and tweet_id.isdigit():
        return tweet_id
    if re.fullmatch(r"\d+", row["id"]):
        return row["id"]
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=bridge.DB_PATH, help="SQLite database path")
    parser.add_argument("--dry-run", action="store_true", help="Show candidates without API calls or writes")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N candidate rows (0 = all)")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between API requests")
    args = parser.parse_args()
    if args.limit < 0 or args.delay < 0:
        parser.error("--limit and --delay must be nonnegative")
    if not Path(args.db).is_file():
        parser.error(f"database does not exist: {args.db}")
    if not args.dry_run and not bridge.FXTWITTER_ENABLED:
        parser.error("FXTWITTER_ENABLED is false; enable it for backfill")

    db = sqlite3.connect(f"file:{Path(args.db).resolve()}?mode={'ro' if args.dry_run else 'rw'}", uri=True)
    db.row_factory = sqlite3.Row
    try:
        candidates = db.execute(
            "SELECT id, username, payload FROM events WHERE enriched = 0 ORDER BY received_at"
        ).fetchall()
        eligible = [(row, tweet_id_for(row)) for row in candidates]
        eligible = [(row, tweet_id) for row, tweet_id in eligible if tweet_id]
        if args.limit:
            eligible = eligible[:args.limit]
        print(f"unenriched={len(candidates)} eligible={len(eligible)} dry_run={args.dry_run}", flush=True)

        succeeded = failed = 0
        for index, (row, tweet_id) in enumerate(eligible, 1):
            if args.dry_run:
                print(f"[{index}/{len(eligible)}] id={row['id']} tweet_id={tweet_id} candidate")
                continue
            details = bridge.fetch_tweet(tweet_id)
            if not details:
                failed += 1
                print(f"[{index}/{len(eligible)}] tweet_id={tweet_id} lookup failed", flush=True)
            else:
                with db:
                    changed = db.execute(
                        """UPDATE events SET
                            username = COALESCE(?, username),
                            body = ?, link = COALESCE(?, link),
                            enriched = 1, details = ?
                           WHERE id = ? AND enriched = 0""",
                        (
                            details["username"],
                            details["body"],
                            details["link"],
                            json.dumps(details["status"], ensure_ascii=False),
                            row["id"],
                        ),
                    ).rowcount
                succeeded += changed
                print(f"[{index}/{len(eligible)}] tweet_id={tweet_id} enriched={bool(changed)}", flush=True)
            if index < len(eligible) and args.delay:
                time.sleep(args.delay)
        print(f"finished: updated={succeeded} failed={failed}; rerun to retry failures", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
