# Raspberry Pi Setup Guide for Beginners

A complete step-by-step guide to get your Raspberry Pi up and running from scratch.

This guide is written for the **Raspberry Pi Zero 2 W** — the hardware used in this project — but the steps apply to any Pi model running OS Lite. Note the Zero 2 W specific differences where marked.

---

## What You'll Need

- **Raspberry Pi Zero 2 W** (recommended for this project — 512 MB RAM, low power, Wi-Fi built in)
- MicroSD card (64 GB, Class 10 or faster)
- MicroSD card reader (USB adapter)
- Power supply — **5V 2.5A micro-USB** (Pi Zero 2 W uses micro-USB, not USB-C)
- A computer (Windows, Mac, or Linux) to prepare the SD card
- Another computer or phone on the same network (to SSH in — OS Lite has no desktop)

> **Pi Zero 2 W specifics:**
> - It has **one micro-USB OTG port** for peripherals. To attach a keyboard and mouse simultaneously you need a USB OTG hub.
> - It uses a **mini-HDMI** port — bring a mini-HDMI to HDMI adapter or cable.
> - It has **512 MB RAM** — we'll configure zram and tmpfs to make the most of it.

> **Note:** Raspberry Pi OS Lite has **no graphical desktop**. You control it entirely through the command line via SSH or a connected keyboard. A monitor is optional but helpful for first-time troubleshooting.

---

## Step 1: Download Raspberry Pi Imager

1. Go to [https://www.raspberrypi.com/software/](https://www.raspberrypi.com/software/) on your computer.
2. Download **Raspberry Pi Imager** for your operating system (Windows, macOS, or Ubuntu).
3. Install and open the application.

---

## Step 2: Flash the Operating System to the SD Card

1. Insert your microSD card into the card reader, then plug it into your computer.
2. Open **Raspberry Pi Imager**.
3. Click **"Choose Device"** and select **Raspberry Pi Zero 2 W**.
4. Click **"Choose OS"**:
   - Select **Raspberry Pi OS (other)** → **Raspberry Pi OS Lite (64-bit)** — this is a minimal, headless image with no desktop environment.
   > **Important:** Use 64-bit, not 32-bit. The Pi Zero 2 W supports 64-bit and the Python packages used in this project (`google-genai`, `grpcio`) have prebuilt 64-bit ARM wheels. On 32-bit, pip falls back to compiling from source, which can take 30+ minutes on the Pi's limited hardware and may run out of memory.
5. Click **"Choose Storage"** and select your microSD card.
   > **Warning:** This will erase everything on the card. Make sure you selected the right drive.
6. Click **"Next"**.

### Optional but Recommended: Customize Settings

Before writing, click **"Edit Settings"** to pre-configure:

| Setting | What to enter |
|---|---|
| Hostname | e.g., `raspberrypi` |
| Username | Your preferred username |
| Password | A strong password |
| Wi-Fi SSID | Your Wi-Fi network name |
| Wi-Fi Password | Your Wi-Fi password |
| Locale / Timezone | Your region |

- Enable **SSH** under the **Services** tab — **this is required** for OS Lite since there is no desktop.
- Click **"Save"**, then **"Yes"** to apply the settings.

7. Click **"Yes"** to confirm writing. Wait for the process to finish (5–10 minutes).
8. Once done, safely eject the SD card from your computer.

---

## Step 3: Insert the SD Card into the Raspberry Pi

1. Locate the microSD card slot on the **underside** of the Raspberry Pi board.
2. Gently push the card in until it clicks into place.

---

## Step 4: Connect All the Cables

Connect in this order:

1. **Monitor** — plug a **mini-HDMI** cable (or adapter) into the Pi Zero 2 W and your monitor/TV.
   - Pi Zero 2 W: use the **mini-HDMI** port (adapter may be needed).
   - Pi 4/5: use the **micro-HDMI** port.
   - Pi 3: use the full-size HDMI port.
2. **Keyboard** — plug into the **micro-USB OTG port** via a USB OTG adapter. Use a USB hub if you also need a mouse.
3. **Mouse** — plug into the USB hub alongside the keyboard (if needed for initial setup only).
4. **Power supply** — plug into the **PWR IN** micro-USB port (not the USB OTG port). The Pi turns on automatically when powered.

> **Tip:** After SSH is confirmed working, you no longer need monitor, keyboard, or mouse.

---

## Step 5: First Boot

1. Power on the Pi. If a monitor is connected, you will see text-only boot messages — **there is no desktop** with OS Lite.
2. The first boot takes **1–3 minutes** as the system sets itself up.
3. Once booted, the Pi is ready to accept SSH connections. You do **not** need a monitor after this point.
4. From your computer, find the Pi's IP address (check your router's device list, or use a tool like **Advanced IP Scanner**) or try the hostname:

```bash
ping raspberrypi.local
```

---

## Step 6: Connect via SSH

Since OS Lite has no desktop, you connect over SSH from your main computer.

**Windows** (PowerShell or Command Prompt):

```bash
ssh your-username@raspberrypi.local
```

**Mac / Linux** (Terminal):

```bash
ssh your-username@raspberrypi.local
```

- Replace `your-username` with the username you set in Step 2.
- If `.local` doesn't work, use the Pi's IP address instead (e.g., `ssh pi@192.168.1.50`).
- Accept the fingerprint prompt by typing `yes` on first connection.
- Enter your password when prompted.

You are now controlling your Pi remotely from the command line.

---

## Step 7: Update the System

Keeping your Pi up to date is important for security and performance.

1. Once connected via SSH, run the following commands one at a time:

```bash
sudo apt update
```

```bash
sudo apt upgrade -y
```

3. Wait for the updates to finish. This may take several minutes.
4. Reboot when done:

```bash
sudo reboot
```

---

## Step 8: Configure the Pi with raspi-config

`raspi-config` is the main configuration tool for Raspberry Pi. Run it over SSH:

```bash
sudo raspi-config
```

Useful options for OS Lite users:

| Menu | Option | What it does |
|---|---|---|
| System Options | Hostname | Change the device name on your network |
| Interface Options | SSH | Confirm SSH is enabled |
| Interface Options | I2C / SPI | Enable hardware interfaces for sensors |
| Localisation Options | Timezone | Set your local time |
| Advanced Options | Expand Filesystem | Use the full SD card capacity |

After making changes, select **Finish** and reboot:

```bash
sudo reboot
```

Reconnect via SSH after ~30 seconds.

> **GPU Memory on Bookworm (64-bit):** The GPU Memory option was removed from `raspi-config` in Raspberry Pi OS Bookworm. Set it directly in the config file instead:
> ```bash
> sudo nano /boot/firmware/config.txt
> ```
> Add at the bottom:
> ```
> gpu_mem=16
> ```
> Save and reboot. Verify with `vcgencmd get_mem gpu` — should return `gpu=16M`. This frees ~48 MB back to the system since OS Lite has no desktop.

---

## Step 9: Protect the SD Card from Wear

SD cards degrade from repeated writes. On a headless Pi that runs 24/7, move temporary files and logs into RAM:

**Mount /tmp and /var/log as RAM disks:**

```bash
sudo nano /etc/fstab
```

Add these two lines at the bottom:

```
tmpfs /tmp      tmpfs defaults,noatime,size=64M 0 0
tmpfs /var/log  tmpfs defaults,noatime,size=32M 0 0
```

Save and exit (`Ctrl+X`, `Y`, `Enter`). These take effect on next reboot.

**Install log2ram** (buffers persistent logs in RAM, syncs to SD periodically):

```bash
echo "deb [signed-by=/usr/share/keyrings/azlux-archive-keyring.gpg] http://packages.azlux.fr/debian/ bookworm main" | sudo tee /etc/apt/sources.list.d/azlux.list
sudo wget -O /usr/share/keyrings/azlux-archive-keyring.gpg https://azlux.fr/repo.gpg
sudo apt update
sudo apt install log2ram -y
```

Reboot to apply:

```bash
sudo reboot
```

---

## Step 10: Verify zram (Compressed RAM Swap)

The Pi Zero 2 W has only 512 MB of RAM. `zram` creates a compressed swap device in RAM, preventing out-of-memory crashes without writing to the SD card.

**Raspberry Pi OS Bookworm enables zram automatically.** Do not install `zram-tools` — it conflicts with the built-in service and will fail with a "Device or resource busy" error.

Just verify zram is already active:

```bash
zramctl
swapon --show
```

You should see `/dev/zram0` listed with a size of ~463 MB and algorithm `zstd`. If it shows up, you're done — nothing else to configure.

---

## Step 11: Install Software via Command Line

OS Lite is minimal — install only what you need.

**Core tools:**

```bash
# Text editor
sudo apt install nano -y

# Python, pip, and venv
sudo apt install python3 python3-pip python3-venv -y

# Git
sudo apt install git -y

# Network utilities
sudo apt install curl wget net-tools -y
```

**Create a Python virtual environment for your project:**

```bash
mkdir ~/myapp && cd ~/myapp
python3 -m venv .venv
source .venv/bin/activate
```

Always activate the venv before installing project dependencies:

```bash
# Example: install project libraries
pip install feedparser aiohttp google-genai python-telegram-bot tenacity holidays python-dotenv
```

**Check system health:**

```bash
df -h        # disk usage
free -h      # RAM usage
uname -a     # kernel and architecture info
```

---

## Step 12: Set Up systemd for Automation

`systemd` timers are the preferred way to schedule scripts on the Pi (more reliable than raw `cron`). You'll create a `.service` file (what to run) and a `.timer` file (when to run it).

```bash
# Create a service unit
sudo nano /etc/systemd/system/myapp.service
```

```ini
[Unit]
Description=My App Script
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=your-username
WorkingDirectory=/home/your-username/myapp
ExecStart=/home/your-username/myapp/.venv/bin/python main.py
Environment=PYTHONUNBUFFERED=1
```

```bash
# Create a timer unit
sudo nano /etc/systemd/system/myapp.timer
```

```ini
[Unit]
Description=Run My App on schedule

[Timer]
OnCalendar=Mon-Fri 13:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start the timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable myapp.timer
sudo systemctl start myapp.timer
sudo systemctl list-timers   # verify it's scheduled
```

---

## Step 13: Clone and Deploy the Stock Digest App

This step clones the application from GitHub to the Pi and wires up automation. Complete Steps 1–12 first.

### 1. Clone the repository

On the Pi (via SSH):

```bash
cd ~
git clone https://github.com/sochan2k/RssFeed.git stock-digest
cd stock-digest
```

> Cloning as `stock-digest` so the paths in the systemd unit files match without modification.
For a **private repo**, save your credentials first so you're not prompted every time:

```bash
git config --global credential.helper store
git clone https://github.com/sochan2k/RssFeed.git stock-digest
# Enter your GitHub username and a Personal Access Token when prompted
```

Personal Access Tokens: GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → New token → scope: `repo`.

### 2. Create a virtual environment and install dependencies

```bash
cd ~/stock-digest
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> On the Pi Zero 2 W, `pip install` takes 2–5 minutes. If you see memory errors, confirm zram is running (`zramctl`).

### 3. Configure environment variables

```bash
cp ~/stock-digest/.env.example ~/stock-digest/.env
nano ~/stock-digest/.env
```

Fill in all four values:

```
GEMINI_API_KEY=your_gemini_api_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_IDS=123456789
ADMIN_CHAT_ID=123456789
```

Save and exit (`Ctrl+X`, `Y`, `Enter`), then restrict permissions:

```bash
chmod 600 ~/stock-digest/.env
```

> Any comments you add to `.env` must start with `#` — otherwise `python-dotenv` will fail to parse the file.

### 4. Smoke-test the app

Run the pipeline once with `--force` to bypass the trading-day check:

```bash
cd ~/stock-digest
source .venv/bin/activate
python main.py --mode scheduled --force
```

You should see `Pipeline complete.` in the logs and a digest message arrive in Telegram. If there are errors, check your `.env` values and network connection.

To test the Telegram bot (interactive commands):

```bash
python main.py --bot
```

Press `Ctrl+C` to stop it once you confirm it responds to `/start`.

### 5. Deploy with systemd

The `deploy/` folder contains ready-made unit files. Substitute your username into them first (**without** `sudo` — otherwise `$USER` resolves to `root`), then copy to systemd:

```bash
cd ~/stock-digest

# 1. Substitute USER placeholder — run WITHOUT sudo so $USER is your login name, not root
sed -i "s/USER/$USER/g" deploy/stock-digest.service
sed -i "s/USER/$USER/g" deploy/stock-digest-bot.service

# 2. Copy unit files to systemd
sudo cp deploy/stock-digest.service     /etc/systemd/system/
sudo cp deploy/stock-digest.timer       /etc/systemd/system/
sudo cp deploy/stock-digest-bot.service /etc/systemd/system/

# 3. Register the new units
sudo systemctl daemon-reload
```

Enable and start both services:

```bash
# Scheduled digest (timer fires Mon–Fri at 13:00 UTC and 22:00 UTC)
sudo systemctl enable stock-digest.timer
sudo systemctl start  stock-digest.timer

# Telegram bot (always-on, restarts automatically on failure)
sudo systemctl enable stock-digest-bot.service
sudo systemctl start  stock-digest-bot.service
```

### 6. Verify everything is running

```bash
# Confirm the timer shows two upcoming triggers
sudo systemctl list-timers stock-digest.timer

# Check the bot is active
sudo systemctl status stock-digest-bot.service

# Follow live logs
sudo journalctl -u stock-digest-bot.service -f
sudo journalctl -u stock-digest.service -f
```

The bot is live when you see `Application started` in the logs and your Pi responds to `/start` in Telegram.

### Redeploying after code changes

Push from Windows:

```powershell
git push
```

Then on the Pi:

```bash
cd ~/stock-digest
git pull
sudo systemctl restart stock-digest-bot.service
# No restart needed for the digest service — it's oneshot and re-reads code on each run
```

---

## Common Problems & Fixes

| Problem | Likely Cause | Fix |
|---|---|---|
| No display output | Wrong HDMI port or cable type | Pi Zero 2 W needs **mini-HDMI** — check you have the right adapter |
| Rainbow square on screen | Low power | Use the official micro-USB power supply (5V 2.5A) |
| Pi won't boot | Corrupt SD card | Re-flash the SD card using Raspberry Pi Imager |
| Can't find Wi-Fi | Wrong credentials | Re-check SSID and password in settings |
| Slow performance | Overheating | The Zero 2 W runs warm — add a heatsink; ensure good ventilation |
| SSH connection refused | SSH not enabled | Re-flash with SSH enabled in Imager settings |
| SSH "host key changed" warning | SD card was re-flashed — new host key | Run `ssh-keygen -R rasppi.local` on your PC, then reconnect |
| Out of memory errors | 512 MB limit hit | Confirm zram is active (`zramctl`); do not install `zram-tools` on Bookworm |
| `zramswap.service` failed | Bookworm has built-in zram; `zram-tools` conflicts | Remove with `sudo apt remove zram-tools -y`; verify with `zramctl` |

---

## Next Steps

This setup is the foundation for the **Daily US Stock News Summarizer** (see Step 13 above and `deploy/README.md` for the full deployment checklist):

- **RSS Feed Fetcher** — async `feedparser` + `aiohttp` pulling financial news
- **AI Summarizer** — Gemini API call with a filtered news digest
- **Telegram Delivery** — summary pushed to your phone via Telegram bot
- **Scheduled Automation** — systemd timer running on US trading days at ICT times

Other OS Lite project ideas:

- **Ad blocker** — install Pi-hole (`curl -sSL https://install.pi-hole.net | bash`)
- **Home automation** — install Home Assistant
- **VPN server** — install WireGuard or PiVPN

---

## Helpful Resources

- Official documentation: [https://www.raspberrypi.com/documentation/](https://www.raspberrypi.com/documentation/)
- Community forum: [https://forums.raspberrypi.com/](https://forums.raspberrypi.com/)
- Project ideas: [https://projects.raspberrypi.org/](https://projects.raspberrypi.org/)

---

*Guide written for Raspberry Pi OS Lite 64-bit (Bookworm) on Raspberry Pi Zero 2 W — May 2026*
