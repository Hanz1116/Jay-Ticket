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
    """Load from environment variables (Replit Secrets) or config.json."""
    # Replit Secrets show up as environment variables
    tm_key     = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()

    if tm_key and ntfy_topic:
        return {"ticketmaster_api_key": tm_key, "ntfy_topic": ntfy_topic}

    # Fallback: local config.json
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

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "TicketMonitor/1.0"})

DISCOVERY_URL = "https://app.ticketmaster.com/discovery/v2/events/{id}"
INVENTORY_URL = "https://app.ticketmaster.com/inventory-status/v1/availability"
SEAT_URL      = "https://services.ticketmaster.com/api/ismds/event/{id}/seat"

# ── Ticketmaster helpers ──────────────────────────────────────────────────────

def get_event_name(api_key: str) -> str:
    try:
        r = SESSION.get(
            DISCOVERY_URL.format(id=EVENT_ID),
            params={"apikey": api_key},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("name", "Unknown Event")
    except Exception as exc:
        log.warning("Could not fetch event name: %s", exc)
        return "Unknown Event"


def check_available_sections(api_key: str) -> list[str]:
    """Return sorted list of target sections that currently have tickets.

    Primary:  ISMDS seat endpoint (section-level granularity).
    Fallback: inventory-status endpoint (event-level only).
    """
    # ── Primary: ISMDS seat endpoint ─────────────────────────────────────
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
        log.debug("ISMDS returned %s – trying inventory-status fallback", r.status_code)
    except requests.RequestException as exc:
        log.debug("ISMDS request error: %s – trying fallback", exc)

    # ── Fallback: inventory-status (event-level) ──────────────────────────
    try:
        r = SESSION.get(
            INVENTORY_URL,
            params={"events": EVENT_ID, "apikey": api_key},
            timeout=15,
        )
        r.raise_for_status()
        avail = (
            r.json()
            .get("_embedded", {})
            .get("availability", [{}])[0]
            .get("availability", {})
        )
        if avail.get("status") == "available":
            log.info("Event shows tickets available (section detail unavailable at this API tier).")
            return ["(section detail unavailable – check Ticketmaster)"]
    except Exception as exc:
        log.error("Inventory-status check failed: %s", exc)

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

    event_name = get_event_name(api_key)
    log.info("Monitoring : %s", event_name)

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
            log.info("ALERT  %s  |  %s", event_name, msg)
            send_phone_notification(
                ntfy_topic,
                f"Tickets Available – {event_name}",
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
