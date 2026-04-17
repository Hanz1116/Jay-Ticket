#!/usr/bin/env python3
"""Ticketmaster section availability monitor.

Polls Ticketmaster every 5 minutes for sections A3-A8 on event
2500647FEE7EB74F and fires a desktop notification when tickets appear.
"""

import json
import logging
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ── Targets ───────────────────────────────────────────────────────────────────

EVENT_ID        = "2500647FEE7EB74F"
TARGET_SECTIONS = {"A3", "A4", "A5", "A6", "A7", "A8"}
POLL_INTERVAL   = 300  # seconds

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

def load_api_key() -> str:
    path = Path(__file__).parent / "config.json"
    if not path.exists():
        log.error(
            "config.json not found. "
            "Copy config.example.json → config.json and add your API key."
        )
        sys.exit(1)
    with open(path) as fh:
        data = json.load(fh)
    key = data.get("ticketmaster_api_key", "").strip()
    if not key:
        log.error("ticketmaster_api_key is empty in config.json")
        sys.exit(1)
    return key

# ── HTTP session ──────────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "TicketMonitor/1.0"})

DISCOVERY_URL = "https://app.ticketmaster.com/discovery/v2/events/{id}"
INVENTORY_URL = "https://app.ticketmaster.com/inventory-status/v1/availability"
SEAT_URL      = "https://services.ticketmaster.com/api/ismds/event/{id}/seat"

# ── API helpers ───────────────────────────────────────────────────────────────

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

    Primary path: ISMDS seat endpoint (section-level granularity).
    Fallback: inventory-status endpoint (event-level only).
    """
    # ── Primary: ISMDS seat endpoint (section-level) ──────────────────────
    try:
        r = SESSION.get(
            SEAT_URL.format(id=EVENT_ID),
            params={
                "apikey": api_key,
                "q":      "available",
                "show":   "places",
                "mode":   "primary",
            },
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
            log.info(
                "Event shows tickets available; "
                "section detail unavailable at this API tier – check Ticketmaster for A3-A8."
            )
            return ["(section detail unavailable – check Ticketmaster)"]
    except Exception as exc:
        log.error("Inventory-status check failed: %s", exc)

    return []

# ── Notifications ─────────────────────────────────────────────────────────────

def send_notification(title: str, body: str) -> None:
    """Send a desktop notification; falls back to terminal alert."""
    # Linux – libnotify
    try:
        subprocess.run(
            ["notify-send", "--urgency=critical", title, body],
            check=True, capture_output=True,
        )
        log.info("Desktop notification sent.")
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # macOS
    try:
        script = (
            f'display notification "{body}" '
            f'with title "{title}" '
            f'sound name "Sosumi"'
        )
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
        log.info("macOS notification sent.")
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # Last resort – terminal bell + bold ANSI text
    print(f"\a\033[1;31m*** ALERT: {title} — {body} ***\033[0m", flush=True)

# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    api_key = load_api_key()

    log.info("=" * 60)
    log.info("Ticketmaster Section Monitor")
    log.info("Event     : %s", EVENT_ID)
    log.info("Sections  : %s", ", ".join(sorted(TARGET_SECTIONS)))
    log.info("Interval  : %ds / %.0f min", POLL_INTERVAL, POLL_INTERVAL / 60)
    log.info("=" * 60)

    event_name = get_event_name(api_key)
    log.info("Monitoring : %s", event_name)

    def _shutdown(sig, _frame):
        log.info("Received signal %s – shutting down.", sig)
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
            send_notification(f"Tickets Available – {event_name}", msg)
            notified.update(found)
        elif found:
            log.info("Still available (already notified): %s", ", ".join(found))
        else:
            log.info("No target sections available.")
            if notified:
                log.info("Previously available sections may have sold out – resetting alert state.")
            notified.clear()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
