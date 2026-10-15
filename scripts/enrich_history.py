#!/usr/bin/env python3
"""Manually enrich old tweets using the same processing path as the retry worker."""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bridge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=bridge.DB_PATH, help="SQLite database path")
    parser.add_argument("--dry-run", action="store_true", help="Preview without API calls or writes")
    parser.add_argument("--limit", type=int, default=0, help="Maximum eligible rows (0 = all)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between rows")
    args = parser.parse_args()
    if args.limit < 0 or args.delay < 0:
        parser.error("--limit and --delay must be nonnegative")
    if not Path(args.db).is_file():
        parser.error(f"database does not exist: {args.db}")
    if not args.dry_run and not bridge.FXTWITTER_ENABLED:
        parser.error("FXTWITTER_ENABLED is false")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rows = bridge.pending_events(
        args.db, manual=True, limit=args.limit or 2**31 - 1
    )
    logging.info("Manual enrichment candidates=%d dry_run=%s", len(rows), args.dry_run)
    results = {"updated": 0, "failed": 0, "skipped": 0}
    for index, row in enumerate(rows, 1):
        tweet_id = bridge.event_tweet_id(row)
        if args.dry_run:
            logging.info("[%d/%d] id=%s tweet_id=%s candidate", index, len(rows), row["id"], tweet_id)
            continue
        status = bridge.enrich_event(row["id"], db_path=args.db, manual=True)
        results[status] += 1
        logging.info("[%d/%d] id=%s tweet_id=%s status=%s", index, len(rows), row["id"], tweet_id, status)
        if index < len(rows) and args.delay:
            time.sleep(args.delay)
    logging.info("Finished: %s", results)


if __name__ == "__main__":
    main()
