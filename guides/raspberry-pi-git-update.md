# Updating the Pi app via Git

Step-by-step for pulling a new release onto an **existing** `stock-digest`
deployment on a Raspberry Pi Zero 2 W using Git.

The app runs from `~/stock-digest` under two systemd units:
- `stock-digest-bot.service` — always-on Telegram command handler
- `stock-digest.timer` / `stock-digest.service` — scheduled digest (oneshot)

Your `.env` and `data/` (the dedup DB) are **gitignored**, so Git never
overwrites them — but we back them up first anyway.

Replace `USER` with your Pi username and `PI_HOST` with `raspberrypi.local`
(or the Pi's IP) throughout.

> **Note on first-time conversion:** earlier deploys used the zip/scp method
> in `deploy/README.md`, so `~/stock-digest` may not be a Git repo yet. Step 3
> covers both cases. After the first conversion, future updates are one-liners
> (see the end of this guide).

---

## Step 0 — (Recommended) Merge the PR first

Merge the release PR into `master` on GitHub, then pull `master` on the Pi.
To test before merging, skip this and check out the feature branch directly
(both paths shown in Step 3).

## Step 1 — SSH in and ensure Git is installed

```bash
ssh USER@PI_HOST
sudo apt update && sudo apt install -y git
git --version
```

## Step 2 — Back up secrets + database

```bash
cd ~/stock-digest
cp .env ~/env.backup
cp -r data ~/data.backup 2>/dev/null || echo "no data/ dir yet — fine"
```

## Step 3 — Put the app under Git

Check whether it is already a Git repo:

```bash
cd ~/stock-digest
git status 2>/dev/null && echo "ALREADY A GIT REPO -> Case A" || echo "NOT a git repo -> Case B"
```

### Case A — already a Git repo

```bash
cd ~/stock-digest
git fetch origin

# If you merged the PR into master:
git checkout master
git pull origin master

# OR, to test the branch without merging:
# git checkout <feature-branch>
# git pull origin <feature-branch>
```

> If `git pull` complains about local changes to tracked files, run
> `git stash` first (your untracked `.env`/`data/` are unaffected), then pull.

### Case B — NOT a Git repo (zip/scp deploy) — clone fresh and migrate

Keeps the running app untouched until the new copy is ready.

```bash
cd ~
git clone https://github.com/sochan2k/RssFeed.git stock-digest-new
# To test a branch instead of master:
# git clone -b <feature-branch> https://github.com/sochan2k/RssFeed.git stock-digest-new

# Carry over secrets and the dedup DB
cp ~/stock-digest/.env ~/stock-digest-new/.env
cp -r ~/stock-digest/data ~/stock-digest-new/data 2>/dev/null || true

# Swap old -> new (keep the old as a backup)
mv ~/stock-digest ~/stock-digest-old
mv ~/stock-digest-new ~/stock-digest
```

## Step 4 — Refresh the Python environment

The venv lives at `~/stock-digest/.venv`.

```bash
cd ~/stock-digest
# Case B only: python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> A release that adds no new dependencies makes this a fast no-op in Case A.
> In Case B a full reinstall on the Pi Zero 2 W can take 2–5 minutes.

## Step 5 — Smoke test before trusting automation

```bash
cd ~/stock-digest
source .venv/bin/activate
python main.py --mode scheduled --force
```

Confirm the digest arrives in Telegram and the log shows `Pipeline complete`.

## Step 6 — Restart services

```bash
# Always-on bot must be restarted to load new code
sudo systemctl restart stock-digest-bot.service
sudo systemctl status  stock-digest-bot.service   # expect: active (running)

# The scheduled service is oneshot — it reads fresh code on every timer fire.
sudo systemctl list-timers stock-digest.timer
```

> If you cloned to a path other than `~/stock-digest`, re-run the systemd-unit
> install from `deploy/README.md` Step 5. Same path = no unit changes needed.

## Step 7 — Verify end to end

In Telegram: `/help`, `/status`, `/summary`. Confirm output and the BotFather
command menu render as expected (the menu can take a minute to refresh).

## Step 8 — Clean up

```bash
rm ~/env.backup
rm -rf ~/data.backup ~/stock-digest-old
```

---

## Rollback

- **Case A:** `cd ~/stock-digest && git reset --hard HEAD@{1}` (or
  `git checkout <previous-commit>`), then
  `sudo systemctl restart stock-digest-bot.service`.
- **Case B:**
  `mv ~/stock-digest ~/stock-digest-broken && mv ~/stock-digest-old ~/stock-digest`,
  then `sudo systemctl restart stock-digest-bot.service`.

---

## Future updates (one-liner)

Once the app is a Git checkout:

```bash
cd ~/stock-digest && git pull && sudo systemctl restart stock-digest-bot.service
```
