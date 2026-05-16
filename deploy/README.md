# Pi Deployment Guide

Complete command sequence to get the stock-digest running on a Raspberry Pi Zero 2 W.
Assumes you have already completed Pi OS setup per `guides/raspberry-pi-setup-guide.md`.

Replace `USER` with your Pi username and `PI_HOST` with `raspberrypi.local` or the Pi's IP address throughout.

---

## Step 1 — Transfer code from Windows

Run these commands from your Windows machine (PowerShell or Git Bash):

```bash
# Copy project files; exclude the venv, local DB, and secrets
rsync -avz \
  --exclude '.venv/' \
  --exclude 'data/' \
  --exclude '.env' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  ./ USER@PI_HOST:~/stock-digest/
```

If you don't have `rsync` on Windows, use `scp -r` or push to Git and clone on the Pi.

---

## Step 2 — SSH into the Pi and set up the Python environment

```bash
ssh USER@PI_HOST

cd ~/stock-digest
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

`google-genai` and `python-telegram-bot` pull several dependencies — on the Pi Zero 2 W this takes 2–5 minutes. Watch for any build errors.

---

## Step 3 — Create the .env file on the Pi

```bash
nano ~/stock-digest/.env
```

Paste your credentials (same format as `.env.example`):

```
GEMINI_API_KEY=your_key_here
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_IDS=123456789
ADMIN_CHAT_ID=123456789
```

Restrict permissions so only your user can read it:

```bash
chmod 600 ~/stock-digest/.env
```

---

## Step 4 — Smoke test before enabling automation

```bash
cd ~/stock-digest
source .venv/bin/activate

# Run the full pipeline once and confirm a digest arrives in Telegram
python main.py --mode scheduled --force
```

Check the output for `Pipeline complete.` and verify the Telegram message arrives.

---

## Step 5 — Install systemd units

Substitute `USER` in the unit files, then copy them to systemd:

```bash
# Replace USER placeholder with your actual username in the service files
sed -i "s/USER/$USER/g" ~/stock-digest/deploy/stock-digest.service
sed -i "s/USER/$USER/g" ~/stock-digest/deploy/stock-digest-bot.service

# Copy to systemd
sudo cp ~/stock-digest/deploy/stock-digest.service     /etc/systemd/system/
sudo cp ~/stock-digest/deploy/stock-digest.timer       /etc/systemd/system/
sudo cp ~/stock-digest/deploy/stock-digest-bot.service /etc/systemd/system/

sudo systemctl daemon-reload
```

---

## Step 6 — Enable and start the services

**Scheduled digest** (timer-driven, twice daily):

```bash
sudo systemctl enable stock-digest.timer
sudo systemctl start  stock-digest.timer

# Verify next trigger times
sudo systemctl list-timers stock-digest.timer
```

Expected output shows two upcoming `NEXT` times: Mon–Fri 13:00 UTC and 22:00 UTC.

**Telegram bot** (always-on, handles /summary /status /health /breaking):

```bash
sudo systemctl enable stock-digest-bot.service
sudo systemctl start  stock-digest-bot.service

# Confirm it's running
sudo systemctl status stock-digest-bot.service
```

---

## Step 7 — Monitor logs

```bash
# Follow live logs for a manual digest run
sudo journalctl -u stock-digest.service -f

# Follow bot logs
sudo journalctl -u stock-digest-bot.service -f

# View last 50 lines from either service
sudo journalctl -u stock-digest.service -n 50
sudo journalctl -u stock-digest-bot.service -n 50
```

---

## Step 8 — Trigger a manual run without waiting for the timer

```bash
sudo systemctl start stock-digest.service
```

Then check the Telegram message and logs.

---

## Redeploying after code changes

From Windows, repeat Step 1 (rsync), then on the Pi:

```bash
# Restart the bot to pick up code changes
sudo systemctl restart stock-digest-bot.service

# No action needed for the digest service — it's oneshot and reads code on each run
```

---

## Timing reference

| Event         | ICT (UTC+7) | UTC       |
|---|---|---|
| Pre-market    | 20:00 Fri   | 13:00 Fri |
| Post-market   | 05:00 Sat   | 22:00 Fri |

The `is_trading_day()` guard in `main.py` skips US market holidays automatically even if the timer fires.

---

## Exit criteria

Phase 4 is complete when:
- [ ] `python main.py --mode scheduled --force` produces a digest on the Pi
- [ ] `systemctl list-timers` shows two upcoming `stock-digest` triggers
- [ ] `systemctl status stock-digest-bot.service` shows `active (running)`
- [ ] `/status` command in Telegram returns the last run info
- [ ] Two consecutive scheduled digests arrive without SSH intervention
