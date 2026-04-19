# Jay-Ticket – Ticketmaster Section Monitor

Monitors Ticketmaster for sections **A3 – A8** on event `2500647FEE7EB74F`
(Jay Chou Carnival II World Tour – Melbourne, 17 Oct 2026) and sends an
iPhone push notification via **ntfy.sh** when tickets become available.

No Ticketmaster API key required — uses the public manifest endpoint.

---

## Method 1 – GitHub Actions (every 5 minutes)

### 1. Fork or push this repo to GitHub

### 2. Set the secret
Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|------|-------|
| `NTFY_TOPIC` | your ntfy.sh topic name (e.g. `jay-tickets-alert`) |

### 3. Enable the workflow
Go to **Actions** → enable workflows if prompted. The schedule runs every 5 minutes automatically.

To test immediately: **Actions → Ticketmaster Monitor → Run workflow**.

---

## Method 2 – ASUS Router script (every 1 minute)

Requires an ASUS router running **Merlin firmware** with JFFS and SSH enabled.

### 1. SSH into your router
```sh
ssh -p 1088 AX3000@192.168.50.1
```

### 2. Create the script
```sh
nano /jffs/scripts/ticketmonitor.sh
```

Paste the following (replace `your_ntfy_topic` with your real topic):

```sh
#!/bin/sh
NTFY_TOPIC="your_ntfy_topic"
EVENT_ID="2500647FEE7EB74F"
LOG="/tmp/ticketmonitor.log"
MANIFEST_FILE="/tmp/manifest.json"

curl -s "https://pubapi.ticketmaster.com/sdk/static/manifest/v1/${EVENT_ID}" | gunzip > "$MANIFEST_FILE"

if [ ! -s "$MANIFEST_FILE" ]; then
  echo "$(date) - ERROR: failed to fetch manifest" >> "$LOG"
  exit 1
fi

FOUND=""
for PAIR in "A3:IEZQ" "A4:IE2A" "A5:IE2Q" "A6:IE3A" "A7:IE3Q" "A8:IE4A"; do
  SECTION=$(echo "$PAIR" | cut -d: -f1)
  PREFIX=$(echo "$PAIR" | cut -d: -f2)
  if grep -q "\"$PREFIX" "$MANIFEST_FILE"; then
    FOUND="$FOUND $SECTION"
  fi
done

if [ -n "$FOUND" ]; then
  FOUND=$(echo "$FOUND" | xargs)
  echo "$(date) ALERT - sections available: $FOUND" >> "$LOG"
  curl -s -d "Sections available: $FOUND" -H "Title: Jay Chou Tickets Available!" -H "Priority: urgent" -H "Tags: rotating_light,ticket" "https://ntfy.sh/${NTFY_TOPIC}"
else
  echo "$(date) - No A3-A8 sections available" >> "$LOG"
fi
```

### 3. Make it executable and schedule it
```sh
chmod +x /jffs/scripts/ticketmonitor.sh
cru a ticketmonitor "* * * * * /jffs/scripts/ticketmonitor.sh"
```

### 4. Check the log
```sh
tail -f /tmp/ticketmonitor.log
```

### 5. Test ntfy notification
```sh
curl -d "Test notification" -H "Title: Jay Chou Tickets Available!" -H "Priority: urgent" -H "Tags: rotating_light,ticket" "https://ntfy.sh/your_ntfy_topic"
```

---

## iPhone notifications (ntfy.sh)

1. Install the **ntfy** app from the App Store
2. Subscribe to your topic (e.g. `jay-tickets-alert`)
3. Notifications arrive instantly when tickets are found

---

## How it works

1. Fetches the public Ticketmaster manifest: `pubapi.ticketmaster.com/sdk/static/manifest/v1/{eventId}` — no auth required, returns all available place IDs (~2MB gzip-compressed).
2. Checks for place ID prefixes that correspond to sections A3–A8:

   | Section | Place ID prefix |
   |---------|----------------|
   | A3 | IEZQ |
   | A4 | IE2A |
   | A5 | IE2Q |
   | A6 | IE3A |
   | A7 | IE3Q |
   | A8 | IE4A |

3. Sends an urgent push notification via ntfy.sh if any target section is found.
