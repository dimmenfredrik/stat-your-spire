# Stat Your Spire

An unofficial fan tool for **Slay the Spire 2**. It reads your finished `.run` history files (read-only) and shows what your losses have in common: which enemies keep killing you and why, which cards and relics win or lose runs, what to fix next, and a floor-by-floor run autopsy.

It never writes to the game folder and never reads runs in progress. Everything stays on your PC.

## Try it in your browser (nothing to download)
**https://dimmenfredrik.github.io/stat-your-spire/**

Open the page in Chrome or Edge, press **Choose run files**, and pick your `.run` files from
`%APPDATA%\SlayTheSpire2\steam\<your steam id>\profile1\saves\history` (paste that path into the address bar of the window that opens, press Ctrl+A, then Open). You can also drag the files onto the page.

**Is it safe?** Nothing is uploaded. The page runs the same Python analysis inside your own browser, the files are only read, and the whole source is in this repo (branch `web` is exactly what the page serves; `tools/make_web.py` on branch `v4` builds it). You can check with your browser's network tab, or switch off your internet after the page has loaded and it still works.

The browser version remembers your runs in your own browser (never uploaded), so a refresh does not ask again. Card, relic and enemy pictures and exact card numbers are optional: use the card-pictures button in the sidebar and the page builds them once, right in your browser, from your own copy of the game (the game files are only read, and nothing is uploaded). It cannot refresh by itself while you play: choose the files again after a new run.

## What you get
- **Focus:** your one job for the next run, your last run, and what to watch out for.
- **Dashboard:** win rate and trends per character.
- **Enemies:** who keeps killing you and what usually goes wrong against them.
- **Cards:** which picks help or hurt.
- **Best builds:** what wins and loses for each character, winning card pairs and recent form.
- Second-monitor mode, co-op-only filter and a count-quits-as-losses switch.

## Desktop version (finds your runs by itself and refreshes automatically)
Local web app, Windows.

1. Download the `v4` branch (Code → switch to branch `v4` → Download ZIP) and unzip it.
2. Open `sts2_coach_v4/` and double-click **`START_HERE.bat`** (installs Python via winget if missing).
3. Your browser opens at http://localhost:8766. Keep the black window open; internet is needed for fonts and charts.

If your runs aren't found, use *Change folder* in the sidebar. The history folder is
`C:\Users\<you>\AppData\Roaming\SlayTheSpire2\steam\<steam id>\profile1\saves\history`.

### Pictures and descriptions (built from your own game)
The first time you start it, `extract_art_from_game.py` finds your installed Slay the Spire 2 through Steam, reads it (read-only) and builds card, relic, potion, event and enemy pictures plus short descriptions into `art/` (about a minute, one time; Pillow is installed automatically). The pictures are made on each player's own PC from their own copy of the game and are never uploaded: **this repo contains no game art**. If the game isn't found, the tool simply works without pictures.

## Older versions on `main`
`sts2_coach_v3/` is the previous web version. History: `sts2_coach.py` (the tkinter original), `sts2_coach_v2/` (pywebview), `sts2_coach_v3/` (local web app), `sts2_coach_v4/` (this version, branch `v4`).

This is an unofficial fan tool, not affiliated with or endorsed by Mega Crit.

Personal paths and Steam ID were replaced with placeholders.
