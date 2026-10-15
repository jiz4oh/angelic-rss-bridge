#!/usr/bin/env python3
"""Periodically retry failed FxTwitter enrichments from SQLite."""
import logging
import signal
import threading
import time

import bridge

stopping = threading.Event()

def stop(_signal, _frame):
    stopping.set()

def main():
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if bridge.FXTWITTER_WORKER_INTERVAL < 1:
        raise ValueError("FXTWITTER_WORKER_INTERVAL must be positive")
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
