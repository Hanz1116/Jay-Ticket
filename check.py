#!/usr/bin/env python3
"""Single-run availability check — called by GitHub Actions every 5 minutes."""

import logging
import os
import sys

import requests

EVENT_ID        = "2500647FEE7EB74F"
TARGET_SECTIONS = {"A3", "A4", "A5", "A6", "A7", "A8"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

SEAT_URL = "https://services.ticketmaster.com/api/ismds/event/{id}/seat"


def check_available_sections(api_key: str) -> list[str]:
    try:
        r = requests.get(
            SEAT_URL.format(id=EVENT_ID),
            params={"apikey": api_key, "q": "available", "show": "places", "mode": "primary"},
            headers={"User-Agent": "TicketMonitor/1.0"},
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
            log.error("401 Unauthorized — check your TICKETMASTER_API_KEY secret.")
        elif r.status_code == 404:
            log.error("404 — event ID %s not found.", EVENT_ID)
        else:
            log.warning("Unexpected status %s.", r.status_code)
    except requests.RequestException as exc:
        log.error("Network error: %s", exc)
    return []


def send_phone_notification(topic: str, title: str, body: str) -> None:
    try:
        r = requests.post(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "urgent", "Tags": "rotating_light,ticket"},
            timeout=10,
        )
        r.raise_for_status()
        log.info("Phone notification sent.")
    except Exception as exc:
        log.error("ntfy failed: %s", exc)


def main() -> None:
    api_key    = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()

    if not api_key or not ntfy_topic:
        log.error("TICKETMASTER_API_KEY and NTFY_TOPIC must be set as GitHub Secrets.")
        sys.exit(1)

    log.info("Checking event %s for sections %s …", EVENT_ID, ", ".join(sorted(TARGET_SECTIONS)))

    found = check_available_sections(api_key)

    if found:
        msg = f"Sections available: {', '.join(found)}"
        log.info("ALERT — %s", msg)
        send_phone_notification(ntfy_topic, "Tickets Available!", msg)
    else:
        log.info("No target sections available.")


if __name__ == "__main__":
    main()
