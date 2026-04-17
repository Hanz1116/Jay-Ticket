# Jay-Ticket – Ticketmaster Section Monitor

Polls Ticketmaster every 5 minutes and fires a desktop notification when
sections **A3 – A8** become available for event `2500647FEE7EB74F`.

## Setup

### 1. Get a Ticketmaster API key
Register for free at <https://developer.ticketmaster.com/> → **My Apps** → create an app → copy the **Consumer Key**.

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure
```bash
cp config.example.json config.json
# edit config.json and paste your API key
```

### 4. Run
```bash
python monitor.py
```

The script logs to both stdout and `monitor.log`.  
Press **Ctrl-C** to stop.

## Desktop notifications

| Platform | Requirement |
|----------|-------------|
| Linux    | `libnotify-bin` (`sudo apt install libnotify-bin`) |
| macOS    | Built-in via `osascript` |

If neither is available the alert prints in bold red to the terminal.

## How it works

1. **ISMDS seat endpoint** – queries Ticketmaster's internal inventory API for
   available seats and extracts section names, checking for A3-A8.
2. **Inventory-status fallback** – if the above endpoint is unavailable, falls
   back to the event-level availability status and advises manual section check.
3. Notifications are deduplicated: you get one alert per section per
   availability window (resets when sections sell back out).
