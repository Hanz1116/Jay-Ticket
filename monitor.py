#!/usr/bin/env python3
"""Ticketmaster section availability monitor.

Polls Ticketmaster every 5 minutes for sections A3-A8 on event
2500647FEE7EB74F and fires a push notification to your phone via ntfy.sh.
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ── Targets ───────────────────────────────────────────────────────────────────

EVENT_ID        = "2500647FEE7EB74F"
TARGET_SECTIONS = {"A3", "A4", "A5", "A6", "A7", "A8"}
POLL_INTERVAL   = 300  # seconds (5 minutes)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load from Replit Secrets (env vars) or local config.json."""
    tm_key     = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()

    if tm_key and ntfy_topic:
        return {"ticketmaster_api_key": tm_key, "ntfy_topic": ntfy_topic}

    path = Path(__file__).parent / "config.json"
    if not path.exists():
        log.error("No secrets found. Set TICKETMASTER_API_KEY and NTFY_TOPIC in Replit Secrets.")
        sys.exit(1)
    with open(path) as fh:
        data = json.load(fh)

    tm_key     = tm_key     or data.get("ticketmaster_api_key", "").strip()
    ntfy_topic = ntfy_topic or data.get("ntfy_topic", "").strip()

    if not tm_key:
        log.error("TICKETMASTER_API_KEY is missing.")
        sys.exit(1)
    if not ntfy_topic:
        log.error("NTFY_TOPIC is missing.")
        sys.exit(1)

    return {"ticketmaster_api_key": tm_key, "ntfy_topic": ntfy_topic}

# ── HTTP session ──────────────────────────────────────────────────────────────

SESSION  = requests.Session()
SESSION.headers.update({"User-Agent": "TicketMonitor/1.0"})
SEAT_URL = "https://services.ticketmaster.com/api/ismds/event/{id}/seat"

# ── Availability check ────────────────────────────────────────────────────────

def check_available_sections(api_key: str) -> list[str]:
    """Return sorted list of target sections that currently have tickets."""
    try:
        r = SESSION.get(
            SEAT_URL.format(id=EVENT_ID),
            params={"apikey": api_key, "q": "available", "show": "places", "mode": "primary"},
            timeout=20,
        )
        if r.status_code == 200:
            places = r.json().get("places", [])
            found = {
                p.get("section", "").strip()
                for p in places
                if p.get("section", "").strip() in TARGET_SECTIONS
            }
            return sorted(found)
        if r.status_code == 401:
            log.error(
                "ISMDS returned 401 Unauthorized. "
                "Your API key may not have access to this endpoint. "
                "Double-check your key at developer.ticketmaster.com."
            )
        elif r.status_code == 404:
            log.error(
                "ISMDS returned 404 – event ID %s not found. "
                "Verify the event ID is correct and the event hasn't ended.",
                EVENT_ID,
            )
        else:
            log.warning("ISMDS returned unexpected status %s.", r.status_code)
    except requests.RequestException as exc:
        log.error("Network error checking availability: %s", exc)

    return []

# ── Phone notification via ntfy.sh ────────────────────────────────────────────

def send_phone_notification(topic: str, title: str, body: str) -> None:
    try:
        r = requests.post(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers={
                "Title":    title,
                "Priority": "urgent",
                "Tags":     "rotating_light,ticket",
            },
            timeout=10,
        )
        r.raise_for_status()
        log.info("Phone notification sent via ntfy.sh.")
    except Exception as exc:
        log.error("Failed to send ntfy notification: %s", exc)

# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    config     = load_config()
    api_key    = config["ticketmaster_api_key"]
    ntfy_topic = config["ntfy_topic"]

    log.info("=" * 60)
    log.info("Ticketmaster Section Monitor")
    log.info("Event     : %s", EVENT_ID)
    log.info("Sections  : %s", ", ".join(sorted(TARGET_SECTIONS)))
    log.info("Interval  : %ds / %.0f min", POLL_INTERVAL, POLL_INTERVAL / 60)
    log.info("ntfy topic: %s", ntfy_topic)
    log.info("=" * 60)

    def _shutdown(sig, _frame):
        log.info("Shutting down.")
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    notified: set[str] = set()

    while True:
        log.info("Checking … (%s)", datetime.now().strftime("%H:%M:%S"))

        found = check_available_sections(api_key)
        new   = [s for s in found if s not in notified]

        if new:
            msg = f"Sections available: {', '.join(found)}"
            log.info("ALERT  %s  |  %s", EVENT_ID, msg)
            send_phone_notification(
                ntfy_topic,
                "Tickets Available!",
                msg,
            )
            notified.update(found)
        elif found:
            log.info("Still available (already notified): %s", ", ".join(found))
        else:
            log.info("No target sections available.")
            if notified:
                log.info("Previously notified sections may have sold out – resetting.")
            notified.clear()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
