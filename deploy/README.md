# Pi Deployment Guide

Complete command sequence to get the stock-digest running on a Raspberry Pi Zero 2 W.
Assumes you have already completed Pi OS setup per `guides/raspberry-pi-setup-guide.md`.

Replace `USER` with your Pi username and `PI_HOST` with `raspberrypi.local` or the Pi's IP address throughout.

---

## Step 1 — Transfer code from Windows

Choose **one** of the following options to copy the files to your Raspberry Pi:

### Option A — The Zip + SCP Method (Recommended, No Git/Rsync needed)
This is the easiest and cleanest way to transfer files from Windows using native PowerShell, as it bundles everything into a single compressed file and avoids copying heavy temporary or environment folders.

1. **On Windows (PowerShell):** Open PowerShell in your project folder (`RssFeed/`) and run:
   ```powershell
   # Create a zip of only the required project files
   Compress-Archive -Path .\main.py, .\requirements.txt, .\src, .\deploy, .\guides, .\.env.example -DestinationPath .\stock-digest.zip -Force

   # Transfer the zip to your Pi (replace USER and PI_HOST with your Pi details)
   scp .\stock-digest.zip USER@PI_HOST:~/

   # Clean up the zip file from your Windows folder
   Remove-Item .\stock-digest.zip
   ```

2. **On the Pi (via SSH):** Extract the project files:
   ```bash
   # Ensure unzip is installed
   sudo apt update && sudo apt install unzip -y

   # Create the target directory and extract the files
   mkdir -p ~/stock-digest
   unzip ~/stock-digest.zip -d ~/stock-digest

   # Clean up the zip file on the Pi
   rm ~/stock-digest.zip
   ```

---

### Option B — Rsync (Fastest for subsequent updates, requires Git Bash or WSL)
If you have Git Bash, WSL, or Rsync on Windows, you can sync files directly:

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

---

### Option C — Graphical SFTP Client (FileZilla or WinSCP)
If you prefer a visual interface, you can drag and drop:

1. Download and open **WinSCP** or **FileZilla**.
2. Connect to your Pi:
   - **Protocol**: SFTP
   - **Host Name**: `raspberrypi.local` (or the Pi's IP address)
   - **Port**: `22`
   - **Username / Password**: Your Pi credentials
3. Navigate to `/home/USERNAME/` on the Pi (right pane) and create a directory named `stock-digest`.
4. In the Windows pane (left), select and drag **only** the following files/folders to the Pi:
   - `src/`
   - `deploy/`
   - `guides/`
   - `main.py`
   - `requirements.txt`
   - `.env.example`
   *(Do NOT drag `.git/`, `.venv/`, `data/`, `__pycache__/`, or `.env` to prevent workspace corruption or credential leakage)*

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

Paste your credentials (same format as `.env.example`).

> [!IMPORTANT]
> - Ensure your `TELEGRAM_CHAT_IDS` is completely correct (double check the length).
> - Any notes you add manually to this file **must** begin with a `#` (e.g., `# To change the time`). Otherwise, `python-dotenv` will fail to parse the file.

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
# 1. Replace USER placeholder with your actual username (Do NOT run this with sudo, or $USER becomes root!)
sed -i "s/USER/$USER/g" ~/stock-digest/deploy/stock-digest.service
sed -i "s/USER/$USER/g" ~/stock-digest/deploy/stock-digest-bot.service

# 2. Copy to systemd
sudo cp ~/stock-digest/deploy/stock-digest.service     /etc/systemd/system/
sudo cp ~/stock-digest/deploy/stock-digest.timer       /etc/systemd/system/
sudo cp ~/stock-digest/deploy/stock-digest-bot.service /etc/systemd/system/

# 3. Force systemd to register the new services (Fixes "Unit not found" errors)
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
