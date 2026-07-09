# Running BasketBuddy on another laptop

This sets up the **backend (live pricing) + frontend (Expo app)** on a fresh
Windows laptop. Live pricing runs on this laptop; a phone connects to it.

## 1. Prerequisites (install these first)

| Need | Why | Get it |
|------|-----|--------|
| **Python 3** *(or Anaconda)* | runs the backend + scrapers | <https://www.python.org/downloads/> — tick **"Add python.exe to PATH"** |
| **Node.js** (LTS) | runs the Expo frontend | <https://nodejs.org> |
| **Expo Go** app | run the app on your phone | App Store / Play Store |

> If the laptop already has **Anaconda/Miniconda**, the setup uses it
> automatically — that's preferred. Otherwise it builds a local venv for you.

## 2. Get the project onto the laptop

Any one of these — the project already includes `backend\config.env` (your API
keys), so nothing else needs to be copied:

- **OneDrive:** sign into the same OneDrive and let the `basketBuddy` folder sync, **or**
- **Git:** `git clone <your repo url>`, **or**
- **Copy** the whole `basketBuddy` folder via USB/drive.

> ⚠️ `backend\config.env` holds live API keys and **is committed to the repo**.
> Keep the repo **private** and don't share it publicly.

## 3. One-time setup

Double-click **`setup.bat`** (in the project root), or from a terminal:

```bat
setup.bat
```

It will, into the correct Python:
1. install the backend dependencies (`requirements.txt`),
2. download the **CloakBrowser** stealth browser (~500 MB, one-time, per machine),
3. install the frontend dependencies (`npm install`),
4. confirm `config.env` is present.

First run takes a few minutes (the browser download is the slow part).

## 4. Start the app (every time)

Double-click **`localrun.bat`**, or:

```bat
localrun.bat
```

This launches:
- **Backend** → `http://localhost:8002` (this laptop)
- **Frontend** → Expo dev server (a QR code appears in the terminal)

## 5. Open it on your phone

1. Put the **phone and laptop on the same Wi‑Fi**.
2. Open **Expo Go** and **scan the QR code** from the `localrun` terminal.
3. The app auto-detects the laptop's LAN IP, so pricing requests reach the
   backend with no extra config.

> To reach the laptop from **outside** your Wi‑Fi (e.g. real users), run a free
> tunnel like **Cloudflare Tunnel** pointed at `localhost:8002` — see notes below.

## Notes & troubleshooting

- **"Most stores skipped" / only some stores priced:** the backend deps weren't
  installed into the Python that `localrun.bat` runs. Re-run `setup.bat`. (This
  happens if Anaconda is present but deps were never installed into it.)
- **Walmart/Target show no prices:** the CloakBrowser binary isn't installed on
  this machine. Run `python -m cloakbrowser install` (or re-run `setup.bat`),
  then `python -m cloakbrowser info` should say `Installed: True`.
- **Frontend won't start:** Node.js isn't installed or `npm install` didn't run.
  Install Node, then run `npm install` inside the `frontend` folder.
- **Keep the laptop awake:** for it to serve the phone continuously, disable
  sleep (Settings → Power) so the backend stays up.
- **Verify the backend alone:** `localrun.bat --backend` runs just the server.

## Always-on / serving real users (optional)

To use this laptop as a small live-pricing server for users beyond your Wi‑Fi:
- disable sleep and set the backend to auto-restart on reboot,
- expose `localhost:8002` with **Cloudflare Tunnel** (free, no port-forwarding),
- the laptop's **residential IP is an asset** — it's what keeps Walmart's
  PerimeterX from blocking you (a datacenter/cloud IP would be worse).

Capacity ceiling: a handful of people generating plans *at the same moment* is
fine; hundreds of simultaneous generations will hit your single IP's rate limit
and the laptop's RAM. Add a residential proxy (`CLOAK_PROXY`) when you outgrow it.
