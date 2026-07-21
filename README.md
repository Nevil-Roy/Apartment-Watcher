# bauverein AG Apartment Watcher

Checks bauverein AG Darmstadt's rental listings and pings you (Telegram /
email / WhatsApp) the moment a new apartment appears — with title, address,
price, rooms, size, and a photo link.

## How it works

The site's search page (https://www.bauvereinag.de/kunde-werden/mietwohnungen-suchen)
renders listings via a third-party map widget. Rather than driving a
browser to read the rendered page, this script calls the widget's own
backend API directly:

```
POST https://maps.polyestate.de/web/index.php/real-estate/get-marker
```

This was found by capturing the widget's real network traffic (see the
`objekte` array in its response — that's every current listing, all at
once). No browser, no Playwright, zero external dependencies — just
Python's standard library. Fast and lightweight to run on a schedule.

- Each listing has a stable numeric `id` from the API — that's what's used
  to detect "new," not a text hash, so it's robust even if wording or
  ordering on the page changes.
- Only actual rental apartments are included — parking spaces (`PARKEN`)
  and purchase listings (`KAUF`) are filtered out, both in the API request
  and again client-side as a safety net.
- **First run is a baseline**: whatever's currently listed gets recorded
  silently, with no notifications — so you don't get 25+ pings at once for
  listings that were already up. Only listings that appear *after* that
  point trigger a notification.
- `state.json` (the list of listing IDs already seen) is committed back to
  the repo after each run so the next scheduled run remembers it.

If bauverein AG ever changes this widget or its API, the script will fail
with a clear error in the Actions log (rather than silently going quiet) —
if that ever happens, send me the error and we'll re-derive it.


## Test it locally first

No secrets needed to test — missing notification channels are just
silently skipped, so you'll see everything in the terminal:
```
python watch_apartments.py
```
First time you run it, expect something like:
```
[2026-07-19T13:30] Fetched 29 current Wohnung rental listing(s).
[2026-07-19T13:30] First run — recorded 29 existing listing(s) as baseline.
No notifications sent for these. Future new listings will trigger a notification.
```
That's correct — it's establishing the baseline. Run it again immediately
after and you should see `0 new listing(s)` (since nothing changed). Only
once a genuinely new apartment appears will you see a notification and the
🏠 message printed to the terminal (and sent to whichever channels you've
configured).

## One-time setup

### 1. Create a GitHub repo
The free 2,000 min/month tier easily
covers checking every 5 minutes around the clock).

### 2. Set up Telegram (recommended, easiest)
1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy
   the **bot token** it gives you.
2. Message your new bot anything (e.g. "hi") so it knows who you are.
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
   and find `"chat":{"id":123456789` — that number is your **chat ID**.
4. In your GitHub repo: **Settings → Secrets and variables → Actions → New
   repository secret**, add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

### 3. Set up email
Works with Gmail, Outlook, GMX, Web.de, or any SMTP provider. Gmail example:
1. Turn on 2-Step Verification on your Google account (required for the next step).
2. Go to https://myaccount.google.com/apppasswords and create an **App
   Password** (choose "Mail" as the app). Copy the 16-character code.
3. Add repo secrets:
   - `SMTP_HOST` = `smtp.gmail.com`
   - `SMTP_PORT` = `587`
   - `SMTP_USER` = your Gmail address
   - `SMTP_PASSWORD` = the app password from step 2 (not your normal Gmail password)
   - `EMAIL_TO` = where you want alerts sent (can be the same address)

For GMX/Web.de/Outlook, same idea — just swap `SMTP_HOST`/`SMTP_PORT` for
their SMTP settings and use your regular login (GMX/Web.de don't require
app passwords; Outlook may, depending on account settings).

### 4. (Optional) Set up WhatsApp via CallMeBot
1. Save this contact: **+34 644 59 71 66** (CallMeBot's number).
2. WhatsApp it the exact text: `I allow callmebot to send me messages`
3. You'll get an **API key** back automatically.
4. Add repo secrets:
   - `CALLMEBOT_PHONE` — your number with country code, no `+` (e.g. `4915112345678`)
   - `CALLMEBOT_APIKEY`

You don't need all three channels — the script sends to whichever secrets
you've actually set (missing ones are silently skipped). Telegram + email
is a solid combo: Telegram for instant phone alerts, email as a backup
that's easy to search later.

### 5. Push the code
```
git init
git add .
git commit -m "Apartment watcher"
git branch -M main
git remote add origin https://github.com/<you>/apartment-watcher.git
git push -u origin main
```

The workflow starts running automatically on its schedule (every 30 min by
default). You can also trigger it manually: repo → **Actions** tab →
"Watch bauverein AG apartments" → **Run workflow**.

## Changing the check frequency

Default is **every 30 minutes**. Since each check is now just one HTTP
request (no browser), you can safely go much more frequent than before —
change any time, no redeploy needed, just edit the cron line in
`.github/workflows/watch-apartments.yml`, commit, and push:
```yaml
- cron: "*/30 * * * *"   # every 30 minutes (current default)
- cron: "*/10 * * * *"   # every 10 minutes
- cron: "*/5 * * * *"    # every 5 minutes (realistic minimum for GitHub Actions)
- cron: "0 8-20 * * *"   # once an hour, 8am-8pm only
```
Cron times are in **UTC** (Germany is UTC+1 in winter, UTC+2 in summer) —
so `0 8-20 * * *` actually means 9am–9pm German winter time.

You can also trigger a check on demand any time: repo → **Actions** tab →
"Watch bauverein AG apartments" → **Run workflow**.

## Ideas to make this better

- **Restrict frequency to business hours.** Landlords almost always publish
  listings on weekdays during office hours — checking every 5–10 min from
  7am–8pm CET and hourly overnight saves your Action minutes without
  missing anything. (Even easier now that each check is a lightweight API
  call rather than a full browser launch — you could comfortably run every
  5 minutes all day if you want.)
- **Add a second data source.** bauverein AG properties sometimes also get
  cross-posted to ImmoScout24/Immowelt. Set up a saved search there too
  (filtered by landlord "bauverein AG", Darmstadt) as a backup channel.
- **Filter by your criteria.** We now have clean structured data (price,
  rooms, size, district) — easy to add a filter so you're only notified
  for listings matching your budget/room count/area, instead of every
  Wohnung that goes up.
- **Add a "still alive" ping** — e.g. once a day, send yourself a quiet
  "watcher ran fine, 0 new listings" message so silence never means "it's
  broken" vs. "nothing new."
- **Log to a spreadsheet.** Every notified listing could also be appended
  to a CSV/Google Sheet, so you build a personal history of what's come up,
  price trends, and how fast things get taken.
- **Reconsider excluded categories.** Right now parking (`PARKEN`) and
  commercial (`GEWERBE`) listings are filtered out since you're apartment
  hunting — but if you'd also want a heads-up on a cheap Stellplatz near
  you, that's a one-line change (`REQUEST_BODY["parken"] = 1`).
