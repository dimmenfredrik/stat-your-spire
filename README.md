# STS2 Coach

A second-monitor coaching tool for **Slay the Spire 2**. It reads your finished `.run` history files (read-only) and shows what your losses have in common: leaks, missed card pairings, turning points, and a floor-by-floor run autopsy.

It never writes to the game folder and never reads runs in progress. Everything stays on your PC.

## Latest version: `sts2_coach_v3/`
Local web app, Windows, Python 3 (standard library only).

1. Download this repo (Code → Download ZIP) and unzip it.
2. Open `sts2_coach_v3/` and double-click **`START_HERE.bat`** (installs Python via winget if missing).
3. Your browser opens at http://localhost:8765. Keep the black window open; internet is needed for fonts and charts.

If your runs aren't found, use *Change folder* in the sidebar. The history folder is
`C:\Users\<you>\AppData\Roaming\SlayTheSpire2\steam\<steam id>\profile1\saves\history`.

### Pictures and descriptions (built from your own game)
Floors show small icons (fight, elite, boss, campfire, shop, event, treasure, ancient). Card, relic and enemy names link to the Slay the Spire wiki (dotted underline).

The first time you start the coach, `extract_art_from_game.py` finds your installed Slay the Spire 2 through Steam, reads it (read-only) and builds card, relic, potion and event pictures plus short descriptions into `sts2_coach_v3/art/` (about 30 seconds, one time; Pillow is installed automatically). Hover a name for a larger picture and its description. The pictures are made on each player's own PC from their own copy of the game and are never uploaded: this repo contains no game art. If the game isn't found, the coach simply works without pictures. To rebuild after a game update, delete `art/descriptions.json` and start again. Enemies have no still pictures in the game files, so they keep the small icons.

Optional `settings.json` next to `sts2_coach_v3.py` to rename a character: `{"character_names": {"Fool": "RealName"}}`.

## History
| Stage | What it was |
|---|---|
| commits 1-8 | tkinter app growing from Insights + Autopsy to Habits & Fixes, Stats, sidebar |
| final tkinter | `sts2_coach.py`, the reference original |
| `sts2_coach_v2/` | pywebview HTML UI: Decisions, Missed Pairings, floor strip, turning points, Dashboard |
| `sts2_coach_v3/` | pure local web app: match-history cards, grade tiles, Tailwind + Chart.js |

This is an unofficial fan tool, not affiliated with or endorsed by Mega Crit.

Use `git log` to walk through it. Personal paths and Steam ID were replaced with placeholders.
