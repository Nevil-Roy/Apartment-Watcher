#!/usr/bin/env python3
"""
Watches bauverein AG Darmstadt's Mietwohnungen (rental apartment) listings
and notifies you the moment a new one appears — address, price, rooms,
size, and a link.

Rather than rendering the page with a browser, this calls the same backend
API that the site's own map widget (a "polyestate" widget, embedded via
iframe) calls internally. This was reverse-engineered from real network
traffic on 2026-07-19 — see debug/ from earlier discovery runs if you want
to verify or re-derive it later:

    POST https://maps.polyestate.de/web/index.php/real-estate/get-marker
    Content-Type: text/plain;charset=UTF-8
    Body: {"anbieterId": "<clientId>", "apiKey": "<apiKey>", ...filters}

No browser, no Playwright, no external dependencies — just the Python
standard library. Much faster and lighter to run on a schedule than the
earlier browser-based approach.

If bauverein AG ever changes this widget/API, this script will start
failing loudly (HTTP error or empty "objekte") rather than silently
returning nothing — check the Actions log if that happens.
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

STATE_FILE = Path(__file__).parent / "state.json"
SOURCE_PAGE_URL = "https://www.bauvereinag.de/kunde-werden/mietwohnungen-suchen"

API_URL = "https://maps.polyestate.de/web/index.php/real-estate/get-marker"
CLIENT_ID = "845981"
API_KEY = "iusngpsiugnpiubnjmpynioxpgo8i4ztp987zps9etmhsz7nt4o87enDOEUZGFOZB"
WIDGET_REFERER = (
    f"https://maps.polyestate.de/widget/latest/wrapper/?clientId={CLIENT_ID}"
    f"&apiKey={API_KEY}&primaryColor=%23203C89&markerColor=%2399C21D"
    f"&controlElementColor=%23162a60&disableSearchbarShadow=true"
    f"&defaultZoom=12&defaultLat=49.85648302149247&defaultLng=8.64887380739801"
)

# Wide-open bounds so a new listing is never missed due to a filter range
# being stale — request everything in these categories, then double-check
# client-side too.
REQUEST_BODY = {
    "anbieterId": CLIENT_ID,
    "apiKey": API_KEY,
    "orderHeuristic": "SORT_ASC",
    "orderField": "gesamtpreis",
    "mieten": 1,    # rentals
    "kaufen": 0,    # exclude purchase listings
    "wohnen": 1,    # residential
    "parken": 0,    # exclude parking spaces
    "gewerbe": 0,   # exclude commercial
    "balkon": 0,
    "garten": 0,
    "kautionsfrei": 0,
    "fahrstuhl_personen": 0,
    "unterkellert_keller": 0,
    "stellplatz": 0,
    "wbs": 0,
    "preisMin": 0,
    "preisMax": 999999,
    "flaecheMin": 0,
    "flaecheMax": 9999,
    "zimmerMin": 0,
    "zimmerMax": 99,
    "etageMin": -9,
    "etageMax": 99,
    "requestSource": "MAPS",
}

# --- Notification config (GitHub Secrets / local env vars) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
CALLMEBOT_PHONE = os.environ.get("CALLMEBOT_PHONE", "")
CALLMEBOT_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return None  # None (vs {}) is how we detect "this is the first ever run"


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_listings():
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(REQUEST_BODY).encode("utf-8"),
        headers={
            "Content-Type": "text/plain;charset=UTF-8",
            "Referer": WIDGET_REFERER,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    objects = data.get("objekte", [])
    # Belt-and-braces client-side filter in case the request params above
    # don't fully restrict results server-side.
    return [
        o for o in objects
        if o.get("nutzungsart") == "WOHNEN" and o.get("vermarktungsart") == "MIETE_PACHT"
    ]


def format_listing(obj):
    address = obj.get("adresse", "Adresse unbekannt")
    district = obj.get("regionaler_zusatz")
    if district:
        address = f"{address} ({district})"

    price = obj.get("gesamtpreis")
    rooms = obj.get("anzahl_zimmer")
    size = obj.get("wohnflaeche")
    title = obj.get("objekttitel", "")
    available = obj.get("verfuegbar_ab")

    img_path = (obj.get("titelbild") or {}).get("pfad")
    anbieter_id = obj.get("anbieterId", 1)
    image_url = f"https://maps.polyestate.de/web/media/{anbieter_id}/{img_path}" if img_path else None

    lines = ["🏠 Neue Wohnung bei bauverein AG!"]
    if title:
        lines.append(title)
    lines.append(address)

    details = []
    if rooms:
        details.append(f"{rooms} Zimmer")
    if size:
        details.append(f"{size} m²")
    if details:
        lines.append(" · ".join(details))

    if price:
        lines.append(f"Gesamtmiete: {price} €")
    if available:
        lines.append(f"Verfügbar ab: {available}")
    if image_url:
        lines.append(image_url)
    lines.append(SOURCE_PAGE_URL)

    return "\n".join(lines)


def send_telegram(message):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(api_url, data=data), timeout=15)
    except Exception as e:
        print(f"[warn] Telegram send failed: {e}", file=sys.stderr)


def send_whatsapp_callmebot(message):
    if not (CALLMEBOT_PHONE and CALLMEBOT_APIKEY):
        return
    params = urllib.parse.urlencode({"phone": CALLMEBOT_PHONE, "text": message, "apikey": CALLMEBOT_APIKEY})
    api_url = f"https://api.callmebot.com/whatsapp.php?{params}"
    try:
        urllib.request.urlopen(api_url, timeout=15)
    except Exception as e:
        print(f"[warn] CallMeBot WhatsApp send failed: {e}", file=sys.stderr)


def send_email(subject, message):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASSWORD and EMAIL_TO):
        return
    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(message, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [EMAIL_TO], msg.as_string())
    except Exception as e:
        print(f"[warn] Email send failed: {e}", file=sys.stderr)


def notify(message):
    print(message)
    print("---")
    send_telegram(message)
    send_whatsapp_callmebot(message)
    send_email("🏠 Neue Wohnung bei bauverein AG", message)


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    state = load_state()
    is_first_run = state is None
    seen = set(state.get("seen_ids", [])) if state else set()

    try:
        listings = fetch_listings()
    except Exception as e:
        print(f"[error] Could not fetch listings: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[{now}] Fetched {len(listings)} current Wohnung rental listing(s).")

    if is_first_run:
        # Baseline run: record everything that currently exists, but don't
        # spam notifications for listings that were already up before you
        # started watching.
        seen = {str(o.get("id")) for o in listings if o.get("id") is not None}
        save_state({"seen_ids": list(seen), "last_run": now})
        print(
            f"[{now}] First run — recorded {len(seen)} existing listing(s) as baseline. "
            "No notifications sent for these. Future new listings will trigger a notification."
        )
        return

    new_count = 0
    for obj in listings:
        listing_id = obj.get("id")
        if listing_id is None:
            continue
        listing_id = str(listing_id)
        if listing_id in seen:
            continue
        seen.add(listing_id)
        new_count += 1
        notify(format_listing(obj))

    print(f"[{now}] {new_count} new listing(s) notified.")
    save_state({"seen_ids": list(seen), "last_run": now})


if __name__ == "__main__":
    main()