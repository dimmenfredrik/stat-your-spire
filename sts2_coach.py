#!/usr/bin/env python3
"""
sts2_coach.py - Slay the Spire 2 second-monitor coaching tool.

Reads the plain-JSON .run files from your STS2 history folder. Pick a character
in the sidebar (or "All characters") and switch between:
  * Habits & Fixes - the habits that show up in your losses, ranked, with what to do
  * Stats          - records, pick rates, fight speed, leaks, nemeses, card insights
  * Run Autopsy    - floor-by-floor review of any run with automatic callouts

Standard library only (tkinter). Run with:  python sts2_coach.py
Optional:  python sts2_coach.py "D:\\path\\to\\history"
"""

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, ttk

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
DEFAULT_HISTORY_DIR = (
    r"C:\Users\YOU\AppData\Roaming\SlayTheSpire2\steam"
    r"\YOUR_STEAM_ID\profile1\saves\history"
)
POLL_MS = 3000                 # how often to check the folder for new .run files
GOLD_LEAK_THRESHOLD = 150      # "died with >150 unspent gold"
MIN_OFFERED = 8                # Card Pick Impact: only cards offered at least this often
BLOAT_DECK = 28                # a final deck this size or larger counts as "bloated"
LEAN_DECK = 24                 # a final deck this size or smaller counts as "lean"
MIN_PARTNER_RUNS = 4           # synergy partners need this many shared decks
TEMPO_FIGHTS = 4               # hallway fights measured after a pick
SLOW_TURNS_BY_ACT = {1: 3.5, 2: 4.0, 3: 4.5}   # avg turns per normal fight
SLOW_FIGHT_TURNS = 5           # a single hallway fight taking this many turns is "slow"
BIG_HIT_FRACTION = 0.30        # a fight costing >=30% of max HP is a "big hit"
ACT_ORDER = ["ACT.OVERGROWTH", "ACT.UNDERDOCKS", "ACT.HIVE", "ACT.GLORY"]
COMBAT_TYPES = ("monster", "elite", "boss")

# Colours - deep teal theme (one ground, raised panels, mint accent for actions/selection)
BG = "#04211f"          # page ground
SIDEBAR = BG            # one background everywhere
CARD = "#0f3531"        # raised panels
CARD_HI = "#174641"     # hover / selected / nested surface
BORDER = "#24544f"      # tracks and hairlines
FG = "#fcfbfc"          # primary text
DIM = "#c9d6d3"         # secondary text
FAINT = "#9db8b3"       # labels, captions
ACCENT = "#3fe0c5"      # buttons + selected state only
ACCENT_HOVER = "#7bebd8"
ON_ACCENT = "#040404"
GOOD = "#9be37c"
BAD = "#ff7b7b"
WARN = "#ffc266"
INFO = "#86c8ff"
FOCUS_BG = "#0c3c37"
DANGER_BG = "#3a2026"
PANEL = CARD
SEL = CARD_HI
CHAR_COLORS = {
    "Ironclad": "#ff7b7b", "Silent": "#9be37c", "Defect": "#86c8ff",
    "Regent": "#ffc266", "Necrobinder": "#d3a6ff", "Fool": "#ff9fd0",
}
FALLBACK_COLORS = ["#7fdbca", "#f78c6c", "#82aaff", "#c3e88d", "#ffcb6b"]
# Fonts: Host Grotesk is embedded below (FONT_DATA) and loaded privately at start-up.
# If that fails, Segoe UI is used.
UI_FONT = "Segoe UI"
UI_FONT_SEMI = "Segoe UI Semibold"
DISPLAY_FONT = ("Segoe UI", "bold")
MONO_FONT = "Consolas"


def disp(size):
    """Display (heading) font at a size: Host Grotesk ExtraBold, or bold Segoe UI as fallback."""
    if isinstance(DISPLAY_FONT, tuple):
        return (DISPLAY_FONT[0], size, DISPLAY_FONT[1])
    return (DISPLAY_FONT, size)


def install_fonts():
    """Write the embedded Host Grotesk weights to disk and register them for this process only."""
    import base64
    import tempfile
    try:
        if sys.platform.startswith("win"):
            base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
            folder = os.path.join(base, "sts2_coach", "fonts")
        elif sys.platform.startswith("linux"):
            folder = os.path.join(os.path.expanduser("~"), ".local", "share", "fonts", "sts2_coach")
        else:
            return False
        os.makedirs(folder, exist_ok=True)
        paths = []
        for fam, chunks in FONT_DATA.items():
            data = base64.b64decode("".join(chunks))
            path = os.path.join(folder, fam.replace(" ", "") + ".ttf")
            if not os.path.exists(path) or os.path.getsize(path) != len(data):
                with open(path, "wb") as fh:
                    fh.write(data)
            paths.append(path)
        if sys.platform.startswith("win"):
            import ctypes
            for p in paths:
                ctypes.windll.gdi32.AddFontResourceExW(p, 0x10, 0)   # FR_PRIVATE
        else:
            import subprocess
            subprocess.run(["fc-cache", "-f", folder], capture_output=True, timeout=20)
        return True
    except Exception:
        return False


def pick_fonts(root):
    """After Tk starts, switch to Host Grotesk if it registered."""
    global UI_FONT, UI_FONT_SEMI, DISPLAY_FONT
    from tkinter import font as tkfont
    fams = set(tkfont.families(root))
    if "STS2 Host Grotesk" in fams:
        UI_FONT = "STS2 Host Grotesk"
        UI_FONT_SEMI = "STS2 Host Grotesk SemiBold" if "STS2 Host Grotesk SemiBold" in fams else UI_FONT
        DISPLAY_FONT = ("STS2 Host Grotesk ExtraBold" if "STS2 Host Grotesk ExtraBold" in fams
                        else (UI_FONT, "bold"))
    elif "Segoe UI" not in fams:
        UI_FONT, UI_FONT_SEMI, DISPLAY_FONT = "TkDefaultFont", "TkDefaultFont", ("TkDefaultFont", "bold")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def pretty(id_str):
    """'ENCOUNTER.KNIGHTS_ELITE' -> 'Knights Elite', 'CARD.HEAVY_SHOT' -> 'Heavy Shot'."""
    if not id_str or id_str == "NONE.NONE":
        return ""
    s = str(id_str).split(".", 1)[-1]
    return s.replace("_", " ").title()


def pretty_encounter(id_str):
    s = pretty(id_str)
    for suffix, tag in ((" Weak", " (weak)"), (" Normal", ""), (" Elite", " (elite)"),
                        (" Boss", " (BOSS)")):
        if s.endswith(suffix):
            return s[: -len(suffix)] + tag
    return s


def pretty_act(act_id):
    return pretty(act_id) or "?"


def pretty_event_choice(choice):
    """Turn event title keys into 'Sunken Statue: Dive Into Water'."""
    title = (choice or {}).get("title") or {}
    key = title.get("key", "")
    table = title.get("table", "")
    if not key:
        return ""
    parts = key.split(".")
    if table == "events" and "options" in parts:
        ev = parts[0]
        i = parts.index("options")
        opt = parts[i + 1] if i + 1 < len(parts) else ""
        return f"{pretty('X.' + ev)}: {pretty('X.' + opt)}"
    return pretty("X." + parts[0])


def avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def steam_id_from_path(path):
    m = re.search(r"(\d{17})", path or "")
    return int(m.group(1)) if m else None


def guess_history_dir():
    if os.path.isdir(DEFAULT_HISTORY_DIR):
        return DEFAULT_HISTORY_DIR
    appdata = os.environ.get("APPDATA")
    if appdata:
        root = os.path.join(appdata, "SlayTheSpire2", "steam")
        if os.path.isdir(root):
            for sid in sorted(os.listdir(root)):
                cand = os.path.join(root, sid, "profile1", "saves", "history")
                if os.path.isdir(cand):
                    return cand
    return DEFAULT_HISTORY_DIR


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def pick_player(run, steam_id):
    """Return the player dict + id that represents *you* (handles co-op runs)."""
    players = run.get("players") or []
    if not players:
        return {}, None
    if len(players) == 1:
        return players[0], players[0].get("id")
    for p in players:
        if steam_id is not None and p.get("id") == steam_id:
            return p, p.get("id")
    return players[0], players[0].get("id")


def my_stats(floor, pid):
    stats = floor.get("player_stats") or []
    for s in stats:
        if s.get("player_id") == pid:
            return s
    return stats[0] if stats else {}


def parse_run(path, steam_id=None):
    with open(path, "r", encoding="utf-8") as f:
        run = json.load(f)

    player, pid = pick_player(run, steam_id)
    acts = run.get("acts") or []
    win = bool(run.get("win"))
    abandoned = bool(run.get("was_abandoned"))

    floors = []
    held_potions = []   # reconstructed potion belt
    floor_no = 0
    for act_idx, act_floors in enumerate(run.get("map_point_history") or []):
        act_id = acts[act_idx] if act_idx < len(acts) else f"ACT.{act_idx + 1}"
        for fl in act_floors or []:
            floor_no += 1
            s = my_stats(fl, pid)
            rooms = fl.get("rooms") or []
            combat_rooms = [r for r in rooms if r.get("room_type") in COMBAT_TYPES]
            room_type = (combat_rooms[0].get("room_type") if combat_rooms
                         else (rooms[0].get("room_type") if rooms else fl.get("map_point_type")))
            encounter = combat_rooms[0].get("model_id") if combat_rooms else None
            label_parts = []
            for r in rooms:
                mid = r.get("model_id")
                if mid:
                    label_parts.append(pretty_encounter(mid) if mid.startswith("ENCOUNTER")
                                       else pretty(mid))
            label = " / ".join(dict.fromkeys(label_parts)) or pretty("X." + (fl.get("map_point_type") or ""))

            picked = [c.get("choice") for c in s.get("potion_choices") or [] if c.get("was_picked")]
            bought = list(s.get("bought_potions") or [])
            used = list(s.get("potion_used") or [])
            discarded = list(s.get("potion_discarded") or [])
            held_potions += picked + bought
            for p in used + discarded:
                if p in held_potions:
                    held_potions.remove(p)

            card_choices = [(pretty((c.get("card") or {}).get("id")), bool(c.get("was_picked")))
                            for c in s.get("card_choices") or []]
            offered_ids = {(c.get("card") or {}).get("id") for c in s.get("card_choices") or []}
            other_gained = [pretty(c.get("id")) for c in s.get("cards_gained") or []
                            if c.get("id") not in offered_ids]

            floors.append({
                "floor": floor_no,
                "act": act_idx + 1,
                "act_id": act_id,
                "map_type": fl.get("map_point_type"),
                "room_type": room_type,
                "is_combat": bool(combat_rooms),
                "encounter": encounter,
                "is_weak": bool(encounter and encounter.endswith("_WEAK")),
                "label": label,
                "turns": sum(int(r.get("turns_taken") or 0) for r in combat_rooms),
                "damage": int(s.get("damage_taken") or 0),
                "healed": int(s.get("hp_healed") or 0),
                "hp": s.get("current_hp"),
                "max_hp": s.get("max_hp"),
                "max_hp_delta": int(s.get("max_hp_gained") or 0) - int(s.get("max_hp_lost") or 0),
                "gold": s.get("current_gold"),
                "gold_gained": int(s.get("gold_gained") or 0),
                "gold_spent": int(s.get("gold_spent") or 0),
                "gold_lost": int(s.get("gold_lost") or 0) + int(s.get("gold_stolen") or 0),
                "card_choices": card_choices,
                "cards_other": other_gained,
                "potions_picked": [pretty(p) for p in picked + bought],
                "potions_skipped": [pretty(c.get("choice")) for c in s.get("potion_choices") or []
                                    if not c.get("was_picked")],
                "potions_used": [pretty(p) for p in used],
                "potions_discarded": [pretty(p) for p in discarded],
                "events": [e for e in (pretty_event_choice(c) for c in s.get("event_choices") or []) if e],
                "rest": [pretty("X." + r) for r in s.get("rest_site_choices") or []],
                "relics": [pretty(r.get("choice")) for r in s.get("relic_choices") or [] if r.get("was_picked")]
                          + [pretty(r) for r in s.get("bought_relics") or []],
                "removed": [pretty(c.get("id")) for c in s.get("cards_removed") or []],
                "upgraded": [pretty(c) for c in s.get("upgraded_cards") or []],
                "bought_cards": [pretty(c) for c in s.get("bought_colorless") or []],
            })

    # Deck size at the end of Act 2 (only if the run reached Act 3): final-deck cards added by then,
    # plus cards added by then that were removed later.
    deck_act2 = None
    act2_floors = [f["floor"] for f in floors if f["act"] == 2]
    if act2_floors and any(f["act"] >= 3 for f in floors):
        edge = max(act2_floors)
        removed_raw = []
        fno = 0
        for act_floors in run.get("map_point_history") or []:
            for fl in act_floors or []:
                fno += 1
                for c in my_stats(fl, pid).get("cards_removed") or []:
                    removed_raw.append((c.get("floor_added_to_deck") or 0, fno))
        deck_act2 = (sum(1 for c in player.get("deck") or [] if (c.get("floor_added_to_deck") or 0) <= edge)
                     + sum(1 for added, rf in removed_raw if added <= edge < rf))

    final_potions = [pretty(p.get("id")) for p in player.get("potions") or []]
    # On death the game clears the belt, so fall back to the reconstruction.
    unused_potions = final_potions or [pretty(p) for p in held_potions]

    killer_enc = run.get("killed_by_encounter")
    killer_evt = run.get("killed_by_event")
    killer = pretty_encounter(killer_enc) or pretty(killer_evt)
    last = floors[-1] if floors else {}
    died_hp0 = bool(last) and last.get("hp") == 0

    if win:
        result = "WIN"
    elif abandoned:
        result = "ABANDONED"
    else:
        result = "LOSS"

    return {
        "path": path,
        "file": os.path.basename(path),
        "start": int(run.get("start_time") or 0),
        "run_time": int(run.get("run_time") or 0),
        "ascension": run.get("ascension", 0),
        "mode": run.get("game_mode", "?"),
        "build": run.get("build_id", ""),
        "character": pretty(player.get("character")) or "?",
        "multiplayer": len(run.get("players") or []) > 1,
        "acts": acts,
        "win": win,
        "abandoned": abandoned,
        "result": result,
        "killer": killer,
        "killer_id": (killer_enc if killer_enc and killer_enc != "NONE.NONE" else killer_evt) or "",
        "died_hp0": died_hp0,
        "floors": floors,
        "final_floor": floors[-1]["floor"] if floors else 0,
        "final_act": floors[-1]["act"] if floors else 0,
        "final_gold": last.get("gold") or 0,
        "unused_potions": unused_potions,
        "deck_size": len(player.get("deck") or []),
        "deck_added": [pretty(c.get("id")) for c in player.get("deck") or []
                       if (c.get("floor_added_to_deck") or 0) > 1],
        "removals": sum(len(f["removed"]) for f in floors),
        "deck_act2": deck_act2,
        "relic_count": len(player.get("relics") or []),
    }


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
def is_loss(r, include_abandoned):
    if r["win"]:
        return False
    if r["abandoned"]:
        # Only count abandons that look like real deaths/give-ups, not floor-1 resets
        return include_abandoned and r["final_floor"] > 1
    return True


def aggregate(runs, include_abandoned):
    out = {}
    wins = [r for r in runs if r["win"]]
    losses = [r for r in runs if is_loss(r, include_abandoned)]
    abandoned = [r for r in runs if r["abandoned"]]
    out["wins"], out["losses"], out["abandoned"] = wins, losses, abandoned
    decided = wins + losses
    out["deck_all"] = avg([r["deck_size"] for r in decided])
    out["deck_win"] = avg([r["deck_size"] for r in wins])
    out["deck_loss"] = avg([r["deck_size"] for r in losses])

    # Card pick vs skip, by act number
    picks = defaultdict(lambda: [0, 0, set()])   # act -> [offers, picked, act names]
    for r in runs:
        for f in r["floors"]:
            if f["card_choices"] and f["map_type"] != "shop":
                picks[f["act"]][0] += 1
                picks[f["act"]][1] += any(p for _, p in f["card_choices"])
                picks[f["act"]][2].add(pretty_act(f["act_id"]))
    out["picks"] = picks

    # Fights by act id and room type
    fights = defaultdict(lambda: defaultdict(list))   # act_id -> room_type -> [(turns, dmg)]
    act_num = {}
    for r in runs:
        for f in r["floors"]:
            if f["is_combat"]:
                fights[f["act_id"]][f["room_type"]].append((f["turns"], f["damage"]))
                act_num[f["act_id"]] = f["act"]
    out["fights"], out["act_num"] = fights, act_num

    # Leaks among losses
    gold_leak = [r for r in losses if r["final_gold"] > GOLD_LEAK_THRESHOLD]
    pot_leak = [r for r in losses if r["unused_potions"]]
    any_leak = [r for r in losses if r in gold_leak or r in pot_leak]
    out["gold_leak"], out["pot_leak"], out["any_leak"] = gold_leak, pot_leak, any_leak
    out["avg_gold_at_death"] = avg([r["final_gold"] for r in losses])

    out["nemesis"] = Counter(r["killer"] for r in losses if r["killer"]).most_common(12)
    out["death_act"] = Counter(r["final_act"] for r in losses)
    out["death_room"] = Counter(r["floors"][-1]["room_type"] for r in losses if r["floors"])

    chars = defaultdict(lambda: [0, 0])
    for r in decided:
        chars[r["character"]][0 if r["win"] else 1] += 1
    out["chars"] = chars
    return out


def autopsy_callouts(r):
    """Return a list of (severity, text) coaching callouts for a single run."""
    calls = []
    fl = r["floors"]
    if not fl:
        return [("info", "No floors recorded (run abandoned immediately).")]
    lost = not r["win"]
    died = "Gave up" if r["abandoned"] else "Died"

    if lost and r["final_gold"] > GOLD_LEAK_THRESHOLD:
        calls.append(("bad", f"{died} with {r['final_gold']} unspent gold - that's a shop removal, "
                             f"a relic or 2-3 cards you never converted into power."))
    if lost and r["unused_potions"]:
        calls.append(("bad", f"{died} holding potion(s): {', '.join(r['unused_potions'])}. "
                             f"Potions are free HP - use them in the fight that kills you (or earlier)."))

    # Slow Act-1 hallway fights
    slow_a1 = [f for f in fl if f["act"] == 1 and f["room_type"] == "monster"
               and f["turns"] >= SLOW_FIGHT_TURNS]
    slow_weak = [f for f in slow_a1 if f["is_weak"]]
    if len(slow_weak) >= 2:
        calls.append(("warn", f"Took {SLOW_FIGHT_TURNS}+ turns on {len(slow_weak)} weak Act 1 fights - "
                              f"draft more frontloaded damage early."))
    elif len(slow_a1) >= 3:
        calls.append(("warn", f"{len(slow_a1)} Act 1 hallway fights lasted {SLOW_FIGHT_TURNS}+ turns - "
                              f"your early deck lacks damage."))
    for act in (1, 2, 3):
        hall = [f["turns"] for f in fl if f["act"] == act and f["room_type"] == "monster"]
        if len(hall) >= 3 and avg(hall) > SLOW_TURNS_BY_ACT[act]:
            calls.append(("warn", f"Act {act} hallway fights averaged {avg(hall):.1f} turns "
                                  f"(target <= {SLOW_TURNS_BY_ACT[act]})."))

    # Big HP hits
    big = [f for f in fl if f["room_type"] in ("monster", "elite") and f["max_hp"]
           and f["damage"] >= BIG_HIT_FRACTION * f["max_hp"] and f is not fl[-1]]
    if big:
        worst = max(big, key=lambda f: f["damage"])
        calls.append(("warn", f"{len(big)} hallway/elite fight(s) cost 30%+ of max HP. Worst: floor {worst['floor']} "
                              f"{worst['label']} (-{worst['damage']} HP in {worst['turns']} turns)."))

    # Entering the fatal fight
    if lost and r["floors"][-1]["is_combat"] and len(fl) >= 2:
        prev = fl[-2]
        last = fl[-1]
        if prev.get("hp") and prev.get("max_hp"):
            ratio = prev["hp"] / prev["max_hp"]
            if ratio < 0.5:
                calls.append(("bad", f"Walked into the fatal {last['room_type']} ({last['label']}) at "
                                     f"{prev['hp']}/{prev['max_hp']} HP ({ratio:.0%})."))
        # Smithed instead of resting shortly before dying?
        for f in fl[-4:-1]:
            if "Smith" in f["rest"] and f["hp"] and f["max_hp"] and f["hp"] / f["max_hp"] < 0.5:
                calls.append(("warn", f"Upgraded at the floor {f['floor']} campfire with "
                                      f"{f['hp']}/{f['max_hp']} HP, then died {last['floor'] - f['floor']} "
                                      f"floor(s) later - rest when below ~50%."))
                break

    # Card reward behaviour
    a1_offers = [f for f in fl if f["act"] == 1 and f["card_choices"] and f["map_type"] != "shop"]
    a1_skips = [f for f in a1_offers if not any(p for _, p in f["card_choices"])]
    if len(a1_skips) >= 3:
        calls.append(("warn", f"Skipped {len(a1_skips)}/{len(a1_offers)} Act 1 card rewards - early Act 1 "
                              f"usually wants damage/power picks, not a thin deck."))

    # Gold management per act
    for act in sorted({f["act"] for f in fl}):
        act_fl = [f for f in fl if f["act"] == act]
        peak = max((f["gold"] or 0) for f in act_fl)
        shops = [f for f in act_fl if f["map_type"] == "shop"]
        if peak >= 300 and not shops:
            calls.append(("info", f"Peaked at {peak} gold in Act {act} without visiting a shop."))

    if lost and r["killer"]:
        calls.append(("info", f"Killed by {r['killer']} on floor {r['final_floor']} (Act {r['final_act']}) "
                              f"with a {r['deck_size']}-card deck."))
    if r["win"]:
        calls.insert(0, ("good", f"Victory! {r['deck_size']}-card deck, {r['relic_count']} relics, "
                                 f"{r['run_time'] // 60} min."))
    if not calls:
        calls.append(("good", "No obvious leaks in this run."))
    return calls



# --------------------------------------------------------------------------
# Habit detection - what keeps ruining your runs, and what to do about it
# --------------------------------------------------------------------------
def _hall_turns(r, act):
    t = [f["turns"] for f in r["floors"] if f["act"] == act and f["room_type"] == "monster"]
    return avg(t) if len(t) >= 3 else None


def _fatal_entry_hp(r):
    fl = r["floors"]
    if len(fl) < 2 or not fl[-1]["is_combat"]:
        return None
    prev = fl[-2]
    if prev.get("hp") is None or not prev.get("max_hp"):
        return None
    return prev["hp"] / prev["max_hp"]


def _low_hp_smiths(r):
    return sum(1 for f in r["floors"] if "Smith" in f["rest"] and f["hp"] is not None
               and f["max_hp"] and f["hp"] / f["max_hp"] < 0.5)


def _act1_skips(r):
    return sum(1 for f in r["floors"] if f["act"] == 1 and f["card_choices"]
               and f["map_type"] != "shop" and not any(p for _, p in f["card_choices"]))


def _hallway_big_hits(r):
    return sum(1 for f in r["floors"][:-1] if f["room_type"] == "monster" and f["max_hp"]
               and f["damage"] >= 0.25 * f["max_hp"])


def _hoarded_without_shop(r):
    worst = 0
    for act in {f["act"] for f in r["floors"]}:
        act_fl = [f for f in r["floors"] if f["act"] == act]
        if not any(f["map_type"] == "shop" for f in act_fl):
            worst = max(worst, max((f["gold"] or 0) for f in act_fl))
    return worst


# Each habit:
#   kind "death": only meaningful for runs you lost (state at death)
#   kind "run":   compared between wins and losses
#   metric(run, ctx) -> number or None (None = not applicable to this run)
#   bad(value, ctx)  -> True when the habit is present
HABITS = [
    dict(id="potions", kind="death", title="Dying with potions on the belt",
         metric=lambda r, c: len(r["unused_potions"]),
         bad=lambda v, c: v >= 1, unit="potions held at death", fmt="{:.1f}",
         why="Every potion you die with is HP, damage or block you paid for and never used.",
         fix=["When a fight is going badly (you'll lose 50%+ HP), drink immediately - don't wait for 'the right moment'.",
              "Treat elites and bosses as potion fights by default.",
              "Keep one slot free so you never skip a potion reward because the belt is full."]),
    dict(id="gold", kind="death", title="Dying with unspent gold",
         metric=lambda r, c: r["final_gold"],
         bad=lambda v, c: v > GOLD_LEAK_THRESHOLD, unit="gold at death", fmt="{:.0f}",
         why="Gold is worth nothing on the death screen. 150+ gold is a card removal plus a key card or relic.",
         fix=["Path through a shop at least once per act, especially when you're above ~200 gold.",
              "Buy card removal first, then the single strongest card/relic for your deck's weakness.",
              "Before an act boss, ask: 'what could I buy that wins this fight?'"]),
    dict(id="lowhp_fatal", kind="death", title="Walking into the fatal fight at low HP",
         metric=lambda r, c: (None if _fatal_entry_hp(r) is None else 100 * _fatal_entry_hp(r)),
         bad=lambda v, c: v < 50, unit="HP entering the fight that killed you", fmt="{:.0f}%",
         why="Most deaths aren't the fight's fault - you arrived without the HP buffer to survive a bad draw.",
         fix=["Below ~50% HP, path toward rest sites and events instead of hallway fights and elites.",
              "Rest (don't upgrade) at the campfire before an elite or the boss when you're under half HP.",
              "Use potions in the fight *before* the dangerous one if it keeps your HP up."]),
    dict(id="elite_death", kind="death", title="Losing runs to elites",
         metric=lambda r, c: 1 if r["floors"] and r["floors"][-1]["room_type"] == "elite" else 0,
         bad=lambda v, c: v == 1, unit="share of deaths to elites", fmt="{:.0%}",
         why="Elites are optional. Dying to one usually means it was taken too greedily.",
         fix=["Only take an elite when you're above ~60-70% HP and your deck can deal big damage quickly.",
              "In Act 1, take at most 1-2 elites unless your deck is clearly ahead.",
              "Learn the elite's pattern (check the Nemesis list in Stats) and save a potion for it."]),
    dict(id="slow_a1", kind="run", title="Slow Act 1 fights (not enough early damage)",
         metric=lambda r, c: _hall_turns(r, 1),
         bad=lambda v, c: v > SLOW_TURNS_BY_ACT[1], unit="avg turns per Act 1 hallway fight", fmt="{:.2f}",
         why="Every extra turn in Act 1 is another enemy attack. Slow fights add up to the HP you're missing later.",
         fix=["Prioritise frontloaded damage and AoE in your first 3-4 card rewards.",
              "Upgrade your best damage card at the first campfire if you're healthy.",
              "Don't take slow scaling/powers in Act 1 until you can kill hallway fights in ~3 turns."]),
    dict(id="slow_a2", kind="run", title="Deck not scaling into Act 2",
         metric=lambda r, c: _hall_turns(r, 2),
         bad=lambda v, c: v > SLOW_TURNS_BY_ACT[2], unit="avg turns per Act 2 hallway fight", fmt="{:.2f}",
         why="Act 2 enemies outscale a deck that still relies on starter Strikes.",
         fix=["By the end of Act 1, look for AoE plus one scaling engine (strength, powers, or your character's scaling).",
              "Remove Strikes at shops so your good damage cards come up more often.",
              "Spend upgrades on cards that multiply damage, not on Defends."]),
    dict(id="skip_a1", kind="run", title="Skipping too many Act 1 card rewards",
         metric=lambda r, c: _act1_skips(r),
         bad=lambda v, c: v >= 3, unit="Act 1 card rewards skipped", fmt="{:.1f}",
         why="Early on your deck is mostly starter cards. Skipping keeps it weak exactly when it needs power.",
         fix=["In Act 1, take the best damage card offered unless it's actively bad.",
              "Start skipping once your deck has a clear plan (usually mid-Act 2).",
              "If unsure between two cards, take the one that kills a hallway fight faster."]),
    dict(id="big_hits", kind="run", title="Bleeding HP in hallway fights",
         metric=lambda r, c: _hallway_big_hits(r),
         bad=lambda v, c: v >= 2, unit="hallway fights costing 25%+ max HP", fmt="{:.1f}",
         why="Normal fights should cost chip damage. Big hits there leave you too low for elites and bosses.",
         fix=["Pick up at least 2-3 good block/Weak cards by mid-Act 1.",
              "Against multi-hit or multiple enemies, block first and kill the biggest threat.",
              "Use a potion in a hallway fight that's spiralling - that's cheaper than the HP."]),
    dict(id="smith_low", kind="run", title="Upgrading at the campfire while low on HP",
         metric=lambda r, c: _low_hp_smiths(r),
         bad=lambda v, c: v >= 1, unit="upgrades taken below 50% HP", fmt="{:.1f}",
         why="An upgrade doesn't matter if the next elite or boss kills you.",
         fix=["Rule of thumb: below 50% HP with an elite/boss ahead, rest.",
              "Upgrade only when healthy or when the next floors are safe (shop, event, treasure)."]),
    dict(id="no_removal", kind="run", title="Never removing cards",
         metric=lambda r, c: (r["removals"] if r["final_floor"] >= 20 else None),
         bad=lambda v, c: v == 0, unit="cards removed per run", fmt="{:.1f}",
         why="Starter Strikes and Defends dilute your draws. Removal is often the best thing a shop sells.",
         fix=["Buy a removal at every shop you can afford it - Strikes first.",
              "Take removal options from events when they're offered."]),
    dict(id="bloat", kind="run", title="Bloated deck",
         metric=lambda r, c: r["deck_size"],
         bad=lambda v, c: v > c["bloat"], unit="cards in final deck", fmt="{:.1f}",
         why="Every card you add makes it less likely you draw your best ones.",
         fix=["After Act 1, only take cards that fix a real weakness (AoE, block, scaling, draw).",
              "Skipping a card reward is fine once the deck has a plan."]),
    dict(id="hoard_noshop", kind="run", title="Hoarding gold and not visiting shops",
         metric=lambda r, c: _hoarded_without_shop(r),
         bad=lambda v, c: v >= 300, unit="peak gold in an act with no shop", fmt="{:.0f}",
         why="Gold is only strong once it's spent. 300+ gold unused for a whole act is a lot of lost power.",
         fix=["When you hit ~250 gold, plan your path through a shop.",
              "Don't save gold for 'later' unless you know a shop is coming."]),
]


def habit_report(runs, include_abandoned):
    """Analyse a set of runs; return ranked habits plus 'under control' ones."""
    wins = [r for r in runs if r["win"]]
    losses = [r for r in runs if is_loss(r, include_abandoned)]
    win_decks = [r["deck_size"] for r in wins]
    ctx = {"bloat": max(28, round(avg(win_decks) + 6)) if win_decks else 30}
    out, fine = [], []
    for h in HABITS:
        def vals(rs):
            res = []
            for r in rs:
                v = h["metric"](r, ctx)
                if v is not None:
                    res.append((r, v, bool(h["bad"](v, ctx))))
            return res
        lv = vals(losses)
        if len(lv) < 2:
            continue
        loss_hits = sum(1 for _, _, b in lv if b)
        loss_rate = pct(loss_hits, len(lv))
        item = dict(h=h, loss_n=len(lv), loss_hits=loss_hits, loss_rate=loss_rate,
                    loss_avg=avg([v for _, v, _ in lv]), examples=[r for r, _, b in lv if b])
        if h["kind"] == "run":
            wv = vals(wins)
            win_hits = sum(1 for _, _, b in wv if b)
            item.update(win_n=len(wv), win_hits=win_hits,
                        win_rate=pct(win_hits, len(wv)) if wv else None,
                        win_avg=avg([v for _, v, _ in wv]) if wv else None)
            with_h = loss_hits + win_hits
            without_h = (len(lv) - loss_hits) + (len(wv) - win_hits)
            item["wr_with"] = pct(win_hits, with_h) if with_h else None
            item["wr_without"] = pct(len(wv) - win_hits, without_h) if without_h else None
            if len(wv) >= 2:
                danger = loss_rate - item["win_rate"] * 0.8
            else:
                danger = loss_rate * 0.6
        else:
            danger = loss_rate * 0.8
        item["danger"] = danger
        item["sev"] = "high" if danger >= 40 else "med" if danger >= 20 else "low"
        if loss_hits >= 2 and loss_rate >= 20 and danger >= 10:
            out.append(item)
        elif loss_rate < 15:
            fine.append(item)
    out.sort(key=lambda i: -i["danger"])
    return out, fine, wins, losses


def card_insights(runs, include_abandoned):
    """Win rate of non-starter cards that ended up in your final deck."""
    stat = defaultdict(lambda: [0, 0])     # card -> [wins, decided]
    for r in runs:
        if not (r["win"] or is_loss(r, include_abandoned)):
            continue
        for card in set(r["deck_added"]):
            stat[card][1] += 1
            stat[card][0] += r["win"]
    rows = [(c, w, n) for c, (w, n) in stat.items()]
    best = sorted([x for x in rows if x[2] >= 2 and x[1] >= 1], key=lambda x: (-x[1] / x[2], -x[2]))[:8]
    worst = sorted([x for x in rows if x[2] >= 3 and x[1] == 0], key=lambda x: -x[2])[:8]
    return best, worst


def act_baselines(runs):
    """Average turns per hallway (monster) fight, per act id, for the given runs."""
    per = defaultdict(list)
    for r in runs:
        for f in r["floors"]:
            if f["room_type"] == "monster" and f["is_combat"]:
                per[f["act_id"]].append(f["turns"])
    return {k: avg(v) for k, v in per.items()}


def card_pick_impact(runs, include_abandoned, min_offered=MIN_OFFERED, act_ids=None):
    """Per-card draft impact using card_choices, turns_taken, cards_removed and final deck size.

    Only finished runs (wins + losses) are used, so every number can be tied to a result.
    """
    decided = [r for r in runs if r["win"] or is_loss(r, include_abandoned)]
    base = act_baselines(runs)
    st = defaultdict(lambda: dict(offered=0, picks=0, np=0, wp=0, ns=0, ws=0, decks=[],
                                  loss_decks=[], tempo=[], removed=0))
    for r in decided:
        fl = r["floors"]
        offered_here, first_pick = set(), {}
        for i, f in enumerate(fl):
            if not f["card_choices"] or f["map_type"] == "shop":
                continue
            if act_ids and f["act_id"] not in act_ids:
                continue
            for name, picked in f["card_choices"]:
                s = st[name]
                s["offered"] += 1
                offered_here.add(name)
                if not picked:
                    continue
                s["picks"] += 1
                first_pick.setdefault(name, i)
                nxt = [g for g in fl[i + 1:] if g["room_type"] == "monster" and g["is_combat"]][:TEMPO_FIGHTS]
                if nxt:
                    s["tempo"].append(avg([g["turns"] - base.get(g["act_id"], g["turns"]) for g in nxt]))
        for name in offered_here:
            s = st[name]
            if name in first_pick:
                s["np"] += 1
                s["wp"] += r["win"]
                s["decks"].append(r["deck_size"])
                if not r["win"]:
                    s["loss_decks"].append(r["deck_size"])
                # Buyer's remorse: removed later in the same run (capped by times picked)
                picks_in_run = sum(1 for f in fl for n, p in f["card_choices"]
                                   if p and n == name and f["map_type"] != "shop"
                                   and (not act_ids or f["act_id"] in act_ids))
                removed = sum(g["removed"].count(name) for g in fl[first_pick[name] + 1:])
                s["removed"] += min(removed, picks_in_run)
            else:
                s["ns"] += 1
                s["ws"] += r["win"]

    losing_decks = [r["deck_size"] for r in decided if not r["win"]]
    bloat_base = (sum(1 for d in losing_decks if d >= BLOAT_DECK) / len(losing_decks)) if losing_decks else 0
    all_tempo = [t for s in st.values() for t in s["tempo"]]
    tempo_base = avg(all_tempo) if all_tempo else 0.0
    rows = []
    for name, s in st.items():
        if s["offered"] < min_offered:
            continue
        wr_p = pct(s["wp"], s["np"]) if s["np"] else None
        wr_s = pct(s["ws"], s["ns"]) if s["ns"] else None
        bloated = [d for d in s["loss_decks"] if d >= BLOAT_DECK]
        rows.append(dict(
            card=name, offered=s["offered"], picks=s["picks"], pick_pct=pct(s["picks"], s["offered"]),
            np=s["np"], ns=s["ns"], wr_p=wr_p, wr_s=wr_s,
            delta=(wr_p - wr_s) if wr_p is not None and wr_s is not None else None,
            deck=avg(s["decks"]) if s["decks"] else None,
            bloat=(len(s["loss_decks"]) >= 4 and len(bloated) / len(s["loss_decks"]) >= 0.6
                   and len(bloated) / len(s["loss_decks"]) >= bloat_base + 0.15),
            bloat_n=len(bloated), loss_n=len(s["loss_decks"]),
            tempo=avg(s["tempo"]) if s["tempo"] else None, tempo_n=len(s["tempo"]),
            removed=s["removed"],
        ))
    # Rank by lift shrunk toward 0 for small samples, so 1-pick flukes don't top the table
    for x in rows:
        n = min(x["np"], x["ns"])
        x["score"] = x["delta"] * n / (n + 4) if x["delta"] is not None else None
    rows.sort(key=lambda x: (x["score"] is not None, x["score"] or 0, x["offered"]), reverse=True)
    deltas = [(x["delta"], min(x["np"], x["ns"])) for x in rows if x["delta"] is not None]
    lift_base = (sum(d * n for d, n in deltas) / sum(n for _, n in deltas)) if deltas and sum(n for _, n in deltas) else 0.0
    meta = dict(base=base, bloat_base=bloat_base, tempo_base=tempo_base, lift_base=lift_base)
    return rows, meta


GAMEPLAN_RUNS = 20             # Next Run Gameplan looks at this many recent runs (unless a filter is on)
GAMEPLAN_MIN_PICKS = 5         # Draft Watchlist needs this many picks per card
SLOW_A1_GAMEPLAN = 3.8         # Act 1 hallway turns that count as "slow" for the gameplan


def _act2_rewards(r):
    rw = [f for f in r["floors"] if f["act"] == 2 and f["card_choices"] and f["map_type"] != "shop"]
    skipped = sum(1 for f in rw if not any(p for _, p in f["card_choices"]))
    return len(rw), skipped


def gameplan_fixes(runs, include_abandoned):
    """Score each candidate leak on the given runs; return the two biggest with a last-5 check.

    Each check gives, per finished run, True (handled well), False (leaked) or None (not applicable).
    """
    decided = [r for r in sorted(runs, key=lambda r: r["start"], reverse=True)
               if r["win"] or is_loss(r, include_abandoned)]

    def a1_avg(r):
        t = [f["turns"] for f in r["floors"] if f["act"] == 1 and f["room_type"] == "monster"]
        return avg(t) if len(t) >= 3 else None

    checks = [
        dict(id="gold", title="Spend your gold",
             check=lambda r: True if r["win"] else r["final_gold"] <= GOLD_LEAK_THRESHOLD,
             detail=lambda bad, rs: (f"Died with {GOLD_LEAK_THRESHOLD}+ gold in {len(bad)}/{len(rs)} losses "
                                     f"(avg {avg([r['final_gold'] for r in bad]):.0f})."),
             target=f"Arrive at every boss and elite with ≤{GOLD_LEAK_THRESHOLD} gold: removal first, then one key card/relic.",
             ok_word="spent gold well", scope="losses"),
        dict(id="potions", title="Drink your potions",
             check=lambda r: True if r["win"] else not r["unused_potions"],
             detail=lambda bad, rs: (f"Died holding potions in {len(bad)}/{len(rs)} losses "
                                     f"({', '.join(sorted({p for r in bad for p in r['unused_potions']})[:3])})."),
             target="Use a potion the moment a fight will cost 40%+ HP - never die with a full belt.",
             ok_word="used their potions", scope="losses"),
        dict(id="slow_a1", title="Kill Act 1 hallways faster",
             check=lambda r: None if a1_avg(r) is None else a1_avg(r) <= SLOW_A1_GAMEPLAN,
             detail=lambda bad, rs: (f"{len(bad)}/{len(rs)} runs averaged >{SLOW_A1_GAMEPLAN} turns per Act 1 "
                                     f"hallway fight (worst {max(a1_avg(r) for r in bad):.1f})."),
             target=f"Take frontloaded damage with your first 3 card rewards; aim for ≤{SLOW_A1_GAMEPLAN} turns per hallway.",
             ok_word="had fast Act 1 fights", scope="runs"),
        dict(id="a2_skip", title="Skip more in Act 2",
             check=lambda r: (None if _act2_rewards(r)[0] < 3 else _act2_rewards(r)[1] >= 1),
             detail=lambda bad, rs: (f"Took a card from every Act 2 reward in {len(bad)}/{len(rs)} runs "
                                     f"that saw 3+ Act 2 rewards."),
             target="In Act 2, skip at least 1-2 rewards that don't add AoE, scaling or block.",
             ok_word="skipped in Act 2", scope="runs"),
        dict(id="lowhp", title="Don't enter fights low",
             check=lambda r: (True if r["win"] else (None if _fatal_entry_hp(r) is None else _fatal_entry_hp(r) >= 0.5)),
             detail=lambda bad, rs: (f"Entered the fight that killed you below 50% HP in {len(bad)}/{len(rs)} losses."),
             target="Below 50% HP: rest at campfires and path around elites until you're healthy.",
             ok_word="stayed healthy", scope="losses"),
    ]
    out = []
    for c in checks:
        res = [(r, c["check"](r)) for r in decided]
        rel = [(r, v) for r, v in res if v is not None and (c["scope"] == "runs" or not r["win"])]
        if len(rel) < 3:
            continue
        bad = [r for r, v in rel if v is False]
        rate = pct(len(bad), len(rel))
        if not bad or rate < 25:
            continue
        last5 = [v for _, v in res if v is not None][:5]
        out.append(dict(id=c["id"], title=c["title"], rate=rate, detail=c["detail"](bad, [r for r, _ in rel]),
                        target=c["target"], last5=last5, ok_word=c["ok_word"]))
    out.sort(key=lambda x: -x["rate"])
    return out[:2], len(decided)


def draft_watchlist(runs, include_abandoned, min_picks=GAMEPLAN_MIN_PICKS):
    rows, _ = card_pick_impact(runs, include_abandoned, min_offered=1)
    ok = [x for x in rows if x["delta"] is not None and x["np"] >= min_picks and x["ns"] >= 1]
    if not ok:
        return None, None, 0
    best = max(ok, key=lambda x: (x["delta"], x["np"]))
    trap = min(ok, key=lambda x: (x["delta"], -x["np"]))
    if best["delta"] <= 0:
        best = None
    if trap["delta"] >= 0 or (best and trap["card"] == best["card"]):
        trap = None
    return best, trap, len(ok)


def card_detail(runs, include_abandoned, card):
    """Synergy breakdown for one card: deck-size split, co-picked partners, act-drafted split."""
    decided = [r for r in runs if r["win"] or is_loss(r, include_abandoned)]
    with_card = [r for r in decided if card in r["deck_added"]]

    def wr(rs):
        return (pct(sum(r["win"] for r in rs), len(rs)), len(rs)) if rs else (None, 0)

    out = {"overall": wr(with_card)}
    # 1. deck size - only runs that reached Act 3, so short early deaths (small decks) don't fake a
    #    "lean decks lose" result
    late = [r for r in with_card if r.get("deck_act2") is not None]
    out["late_n"] = len(late)
    out["lean"] = wr([r for r in late if r["deck_act2"] <= LEAN_DECK])
    out["mid"] = wr([r for r in late if LEAN_DECK < r["deck_act2"] < BLOAT_DECK])
    out["bloated"] = wr([r for r in late if r["deck_act2"] >= BLOAT_DECK])
    out["deck_avg_win"] = avg([r["deck_act2"] for r in late if r["win"]]) if any(r["win"] for r in late) else None
    out["deck_avg_loss"] = avg([r["deck_act2"] for r in late if not r["win"]]) if any(not r["win"] for r in late) else None

    # 2. partners
    base, n_base = out["overall"]
    partners = []
    if with_card:
        cand = Counter(p for r in with_card for p in set(r["deck_added"]) if p != card)
        for p, n in cand.items():
            if n < MIN_PARTNER_RUNS:
                continue
            both = [r for r in with_card if p in r["deck_added"]]
            without = [r for r in with_card if p not in r["deck_added"]]
            w_both, _ = wr(both)
            w_wo, n_wo = wr(without)
            partners.append(dict(card=p, n=n, wr=w_both, delta=w_both - base, wr_without=w_wo, n_without=n_wo))
    partners.sort(key=lambda x: (-x["delta"], -x["n"]))
    out["best"] = [x for x in partners if x["delta"] > 0][:3]
    out["worst"] = sorted([x for x in partners if x["delta"] < 0], key=lambda x: (x["delta"], -x["n"]))[:3]
    out["partner_pool"] = len(partners)

    # 3. act drafted (first time it was picked from a card reward)
    a1, a23 = [], []
    for r in decided:
        if r.get("deck_act2") is None:      # same checkpoint: only runs that reached Act 3
            continue
        first = next((f for f in r["floors"] if f["map_type"] != "shop"
                      and any(p and n == card for n, p in f["card_choices"])), None)
        if first:
            (a1 if first["act"] == 1 else a23).append(r)
    out["act1"], out["act23"] = wr(a1), wr(a23)
    return out


def reward_stats(runs, include_abandoned, act_ids=None):
    """Card-reward take/skip rates, overall and split by won vs lost runs."""
    tot = taken = 0
    split = {True: [0, 0], False: [0, 0]}     # win? -> [rewards, skipped]
    for r in runs:
        decided = r["win"] or is_loss(r, include_abandoned)
        for f in r["floors"]:
            if not f["card_choices"] or f["map_type"] == "shop":
                continue
            if act_ids and f["act_id"] not in act_ids:
                continue
            took = any(p for _, p in f["card_choices"])
            tot += 1
            taken += took
            if decided:
                split[r["win"]][0] += 1
                split[r["win"]][1] += not took
    return dict(rewards=tot, pick=pct(taken, tot),
                skip_win=pct(split[True][1], split[True][0]) if split[True][0] >= 5 else None,
                skip_loss=pct(split[False][1], split[False][0]) if split[False][0] >= 5 else None)


def char_color(name, _cache={}):
    if name in CHAR_COLORS:
        return CHAR_COLORS[name]
    if name not in _cache:
        _cache[name] = FALLBACK_COLORS[len(_cache) % len(FALLBACK_COLORS)]
    return _cache[name]


# --------------------------------------------------------------------------
# Small modern widgets
# --------------------------------------------------------------------------
def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a rounded rectangle on a canvas (soft corners)."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, splinesteps=12, **kw)


class PillButton(tk.Canvas):
    """Rounded button. primary=True uses the mint accent fill (the main action)."""

    def __init__(self, parent, text, command, primary=False, bg=None):
        from tkinter import font as tkfont
        self._font = tkfont.Font(family=UI_FONT_SEMI, size=10)
        w = self._font.measure(text) + 32
        h = self._font.metrics("linespace") + 16
        super().__init__(parent, width=w, height=h, bg=bg or parent.cget("bg"), highlightthickness=0,
                         cursor="hand2", takefocus=1)
        self.primary = primary
        self.command = command
        self.colors = ((ACCENT, ACCENT_HOVER, ON_ACCENT) if primary else (CARD_HI, BORDER, FG))
        self.shape = rounded_rect(self, 1, 1, w - 1, h - 1, 8, fill=self.colors[0],
                                  outline=self.colors[0])
        self.label = self.create_text(w / 2, h / 2, text=text, fill=self.colors[2], font=self._font)
        self.bind("<Enter>", lambda e: self._paint(self.colors[1]))
        self.bind("<Leave>", lambda e: self._paint(self.colors[0]))
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Return>", lambda e: self.command())
        self.bind("<space>", lambda e: self.command())
        self.bind("<FocusIn>", lambda e: self.itemconfigure(self.shape, outline=FG, width=2))
        self.bind("<FocusOut>", lambda e: self.itemconfigure(self.shape, outline=self.colors[0], width=1))

    def _paint(self, fill):
        self.itemconfigure(self.shape, fill=fill)


class ScrollFrame(tk.Frame):
    """A vertically scrolling frame (mouse wheel works while hovering)."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                 style="Modern.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.bind_all("<Button-4>", self._wheel, add="+")
        self.bind_all("<Button-5>", self._wheel, add="+")

    def _wheel(self, e):
        w = self.winfo_containing(e.x_root, e.y_root)
        while w is not None and w is not self:
            w = w.master
        if w is None or not self.winfo_ismapped():
            return
        if getattr(e, "num", None) == 4:
            step = -3
        elif getattr(e, "num", None) == 5:
            step = 3
        else:
            step = int(-e.delta / 40) or (-1 if e.delta > 0 else 1)
        self.canvas.yview_scroll(step, "units")

    def clear(self):
        for c in self.inner.winfo_children():
            c.destroy()
        self.canvas.yview_moveto(0)


def wrap_label(parent, text, size=10, fg=FG, bg=CARD, weight="normal", pad=0, font=None, **kw):
    lbl = tk.Label(parent, text=text, fg=fg, bg=bg, justify="left", anchor="w",
                   font=font or (UI_FONT_SEMI if weight == "bold" else UI_FONT, size), **kw)
    lbl.bind("<Configure>", lambda e: lbl.configure(wraplength=max(100, e.width - pad)))
    return lbl


def text_widget(parent):
    frame = tk.Frame(parent, bg=CARD)
    txt = tk.Text(frame, bg=CARD, fg=FG, insertbackground=FG, relief="flat", wrap="word",
                  font=(MONO_FONT, 10), padx=18, pady=14, borderwidth=0,
                  highlightthickness=0, cursor="arrow", spacing1=1, spacing3=1)
    sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview, style="Modern.Vertical.TScrollbar")
    txt.configure(yscrollcommand=sb.set)
    txt.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    tags = {
        "h1": dict(font=disp(18), foreground=FG, spacing1=2, spacing3=6),
        "h2": dict(font=disp(13), foreground=FG, spacing1=16, spacing3=6),
        "dim": dict(foreground=DIM), "faint": dict(foreground=FAINT),
        "good": dict(foreground=GOOD), "bad": dict(foreground=BAD),
        "warn": dict(foreground=WARN), "info": dict(foreground=INFO),
        "bold": dict(font=(MONO_FONT, 10, "bold")),
        "picked": dict(foreground=GOOD, font=(MONO_FONT, 10, "bold")),
        "skipped": dict(foreground=FAINT, overstrike=True),
        "floorhead": dict(font=(MONO_FONT, 10, "bold"), foreground=DIM),
        "combat": dict(foreground="#ffb3b3"),
        "elite": dict(foreground=WARN, font=(MONO_FONT, 10, "bold")),
        "boss": dict(foreground=BAD, font=(MONO_FONT, 10, "bold")),
        "callout": dict(lmargin1=4, lmargin2=28, spacing1=3, spacing3=3, font=(UI_FONT, 10)),
        "actbar": dict(background=CARD_HI, foreground=FG, font=(UI_FONT_SEMI, 11),
                       spacing1=12, spacing3=6, lmargin1=4),
        "ui": dict(font=(UI_FONT, 10)),
        "detail": dict(lmargin2=110),
    }
    for tag, opts in tags.items():
        txt.tag_configure(tag, **opts)
    txt.configure(state="disabled")
    return frame, txt


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
ALL = "All characters"
VIEWS = ("Habits & Fixes", "Draft Guide", "Overview", "Card Table", "Run Autopsy")


class CoachApp(tk.Tk):
    def __init__(self, history_dir):
        install_fonts()
        super().__init__()
        pick_fonts(self)
        self.title("STS2 Coach")
        self.geometry("1480x940")
        self.minsize(1100, 700)
        self.configure(bg=BG)
        self.history_dir = tk.StringVar(value=history_dir)
        self.auto_refresh = tk.BooleanVar(value=True)
        self.include_abandoned = tk.BooleanVar(value=False)
        self.include_multi = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="")
        self.cache = {}
        self.all_runs = []
        self.runs = []
        self.character = ALL
        self.view = VIEWS[0]
        self.selected_file = None
        self._last_seen = set()
        self.asc_filter = tk.StringVar(value="All")
        self.range_filter = "All runs"
        self.current_build = ""
        self.expanded = set()          # habit ids whose WHAT TO DO is open
        self._auto_expand = True
        self.min_picks = tk.IntVar(value=8)
        self.killer_filter = None

        self._style()
        self._build()
        self.reload(force=True)
        self.after(POLL_MS, self._poll)

    # ----- styling ------------------------------------------------------
    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=FG, font=(UI_FONT, 10))
        st.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=FG,
                     rowheight=30, borderwidth=0, relief="flat", font=(UI_FONT, 10))
        st.configure("Treeview.Heading", background=CARD, foreground=DIM, relief="flat",
                     borderwidth=0, font=(UI_FONT_SEMI, 9), padding=(6, 6))
        st.map("Treeview.Heading", background=[("active", CARD)])
        st.map("Treeview", background=[("selected", CARD_HI)], foreground=[("selected", FG)])
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Modern.Vertical.TScrollbar", background=BORDER, troughcolor=CARD,
                     bordercolor=CARD, arrowcolor=CARD, lightcolor=BORDER, darkcolor=BORDER,
                     gripcount=0, arrowsize=0, width=8)
        st.map("Modern.Vertical.TScrollbar", background=[("active", FAINT)])
        st.configure("TEntry", fieldbackground=CARD, foreground=FG, insertcolor=FG,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=6)
        st.configure("Filter.TCombobox", fieldbackground=CARD, background=CARD, foreground=FG,
                     arrowcolor=DIM, bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD, padding=(8, 4))
        st.map("Filter.TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", CARD)], selectforeground=[("readonly", FG)],
               background=[("active", CARD_HI)])
        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", CARD_HI)
        self.option_add("*TCombobox*Listbox.font", (UI_FONT, 10))
        st.configure("TCheckbutton", background=SIDEBAR, foreground=DIM, font=(UI_FONT, 9),
                     indicatorbackground=CARD, indicatorforeground=ACCENT, focuscolor=SIDEBAR)
        st.map("TCheckbutton", background=[("active", SIDEBAR)], foreground=[("active", FG)],
               indicatorbackground=[("selected", CARD_HI)])

    # ----- layout --------------------------------------------------------
    def _build(self):
        # Brand row ---------------------------------------------------------
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=24, pady=(18, 0))
        mark = tk.Canvas(top, width=34, height=34, bg=BG, highlightthickness=0)
        mark.pack(side="left")
        rounded_rect(mark, 1, 1, 33, 33, 8, fill=ACCENT, outline="")
        mark.create_text(17, 17, text="S2", fill=ON_ACCENT, font=disp(12))
        tk.Label(top, text="STS2 Coach", bg=BG, fg=FG, font=disp(19)).pack(side="left", padx=(12, 0))
        tk.Label(top, text="Slay the Spire 2 run analysis", bg=BG, fg=FAINT,
                 font=(UI_FONT, 10)).pack(side="left", padx=(14, 0), pady=(5, 0))
        PillButton(top, "Refresh", lambda: self.reload(force=True), primary=True).pack(side="right")
        PillButton(top, "Change folder", self._settings).pack(side="right", padx=(0, 10))
        tk.Label(top, textvariable=self.status, bg=BG, fg=FAINT, font=(UI_FONT, 9),
                 justify="right", anchor="e").pack(side="right", padx=(0, 18))

        # Full-width navigation ---------------------------------------------
        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=24, pady=(20, 0))
        self.tab_widgets = {}
        for v in VIEWS:
            f = tk.Frame(nav, bg=BG, cursor="hand2")
            f.pack(side="left", padx=(0, 30))
            lbl = tk.Label(f, text=v, bg=BG, fg=DIM, font=(UI_FONT_SEMI, 12), cursor="hand2")
            lbl.pack(pady=(0, 7))
            bar = tk.Frame(f, bg=BG, height=3)
            bar.pack(fill="x")
            for w in (f, lbl):
                w.bind("<Button-1>", lambda e, v=v: self.set_view(v))
                w.bind("<Enter>", lambda e, l=lbl, v=v: l.configure(fg=FG))
                w.bind("<Leave>", lambda e, l=lbl, v=v: l.configure(fg=FG if self.view == v else DIM))
            self.tab_widgets[v] = (lbl, bar)

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(22, 22))

        # Sidebar: characters + options -------------------------------------
        self.sidebar = tk.Frame(body, bg=SIDEBAR, width=236)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Label(self.sidebar, text="CHARACTERS", bg=SIDEBAR, fg=FAINT,
                 font=(UI_FONT_SEMI, 8)).pack(anchor="w", padx=2, pady=(2, 8))
        self.char_list = tk.Frame(self.sidebar, bg=SIDEBAR)
        self.char_list.pack(fill="x")

        bottom = tk.Frame(self.sidebar, bg=SIDEBAR)
        bottom.pack(side="bottom", fill="x", pady=(16, 0))
        tk.Label(bottom, text="OPTIONS", bg=SIDEBAR, fg=FAINT,
                 font=(UI_FONT_SEMI, 8)).pack(anchor="w", padx=2, pady=(0, 6))
        ttk.Checkbutton(bottom, text="Count quits as losses", variable=self.include_abandoned,
                        command=self.refresh_views).pack(anchor="w", pady=2)
        ttk.Checkbutton(bottom, text="Include co-op runs", variable=self.include_multi,
                        command=self.reload).pack(anchor="w", pady=2)
        ttk.Checkbutton(bottom, text="Auto-refresh on new runs", variable=self.auto_refresh).pack(anchor="w", pady=2)

        # Main area ---------------------------------------------------------
        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True, padx=(28, 0))

        header = tk.Frame(main, bg=BG)
        header.pack(fill="x", pady=(0, 10))
        self.title_dot = tk.Label(header, text="●", bg=BG, fg=ACCENT, font=(UI_FONT, 18))
        self.title_dot.pack(side="left", pady=(4, 0))
        self.title_lbl = tk.Label(header, text=ALL, bg=BG, fg=FG, font=disp(28))
        self.title_lbl.pack(side="left", padx=(8, 0))
        self.subtitle_lbl = tk.Label(header, text="", bg=BG, fg=DIM, font=(UI_FONT, 10))
        self.subtitle_lbl.pack(side="left", padx=16, pady=(10, 0))

        fbar = tk.Frame(main, bg=BG)
        fbar.pack(fill="x", pady=(0, 14))
        tk.Label(fbar, text="ASCENSION", bg=BG, fg=FAINT, font=(UI_FONT_SEMI, 8)).pack(side="left", padx=(0, 8))
        self.asc_box = ttk.Combobox(fbar, textvariable=self.asc_filter, width=7, state="readonly",
                                    values=["All"], style="Filter.TCombobox")
        self.asc_box.pack(side="left")
        self.asc_box.bind("<<ComboboxSelected>>", lambda e: (self.asc_box.selection_clear(), self._filters_changed()))
        tk.Label(fbar, text="RUNS", bg=BG, fg=FAINT, font=(UI_FONT_SEMI, 8)).pack(side="left", padx=(24, 8))
        self.range_pills = {}
        pills = tk.Frame(fbar, bg=CARD)
        pills.pack(side="left")
        for opt in ("All runs", "Last 30", "Last 50", "Current build"):
            p = tk.Label(pills, text=opt, bg=CARD, fg=DIM, font=(UI_FONT_SEMI, 9), padx=12, pady=5, cursor="hand2")
            p.pack(side="left", padx=1, pady=1)
            p.bind("<Button-1>", lambda e, o=opt: self._set_range(o))
            self.range_pills[opt] = p
        self.build_lbl = tk.Label(fbar, text="", bg=BG, fg=FAINT, font=(UI_FONT, 9))
        self.build_lbl.pack(side="left", padx=12)

        self.cards_row = tk.Frame(main, bg=BG)
        self.cards_row.pack(fill="x", pady=(0, 22))

        self.content = tk.Frame(main, bg=BG)
        self.content.pack(fill="both", expand=True)

        # View: habits
        self.habits_view = ScrollFrame(self.content)
        # View: stats
        self._build_stats()
        # View: autopsy
        self.autopsy_view = tk.Frame(self.content, bg=BG)
        self.killer_bar = tk.Frame(self.autopsy_view, bg=BG)
        pane = tk.PanedWindow(self.autopsy_view, orient="horizontal", bg=BG, sashwidth=10,
                              borderwidth=0, sashrelief="flat")
        pane.pack(fill="both", expand=True)
        left = tk.Frame(pane, bg=CARD)
        cols = ("date", "char", "asc", "result", "floor", "killer")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for c, w, t in (("date", 100, "DATE"), ("char", 92, "CHARACTER"), ("asc", 40, "ASC"),
                        ("result", 74, "RESULT"), ("floor", 52, "FLOOR"), ("killer", 150, "KILLED BY")):
            self.tree.heading(c, text=t, anchor="w" if c in ("date", "char", "killer") else "center")
            self.tree.column(c, width=w, minwidth=36,
                             anchor="w" if c in ("date", "char", "killer") else "center",
                             stretch=(c == "killer"))
        self.tree.tag_configure("WIN", foreground=GOOD)
        self.tree.tag_configure("LOSS", foreground=FG)
        self.tree.tag_configure("ABANDONED", foreground=FAINT)
        tsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview, style="Modern.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        tsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        right, self.autopsy_txt = text_widget(pane)
        pane.add(left, minsize=340, width=450)
        pane.add(right, minsize=420)

        self.set_view(self.view)

    def _flat_button(self, parent, text, cmd, bg=CARD, fg=FG):
        b = tk.Label(parent, text=text, bg=CARD_HI, fg=fg, font=(UI_FONT_SEMI, 9),
                     padx=12, pady=5, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        b.bind("<Enter>", lambda e: b.configure(bg=BORDER))
        b.bind("<Leave>", lambda e: b.configure(bg=CARD_HI))
        return b

    def _settings(self):
        win = tk.Toplevel(self)
        win.title("History folder")
        win.configure(bg=BG)
        win.transient(self)
        tk.Label(win, text="Folder with your .run files", bg=BG, fg=FG,
                 font=(UI_FONT_SEMI, 11)).pack(anchor="w", padx=18, pady=(16, 6))
        var = tk.StringVar(value=self.history_dir.get())
        ttk.Entry(win, textvariable=var, width=90).pack(fill="x", padx=18)
        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=18, pady=14)

        def browse():
            d = filedialog.askdirectory(initialdir=var.get() or os.path.expanduser("~"), parent=win)
            if d:
                var.set(os.path.normpath(d))

        def save():
            self.history_dir.set(var.get())
            self.cache.clear()
            win.destroy()
            self.reload(force=True)

        self._flat_button(row, "Browse...", browse).pack(side="left")
        self._flat_button(row, "Save", save, fg=ACCENT).pack(side="right")

    # ----- sidebar + header ----------------------------------------------
    def _render_sidebar(self):
        for c in self.char_list.winfo_children():
            c.destroy()
        inc = self.include_abandoned.get()
        groups = defaultdict(list)
        for r in self.all_runs:
            groups[r["character"]].append(r)
        entries = [(ALL, self._scope(self.all_runs))] + sorted(
            ((k, self._scope(v)) for k, v in groups.items()), key=lambda kv: -len(kv[1]))
        for name, rs in entries:
            w = sum(1 for r in rs if r["win"])
            l = sum(1 for r in rs if is_loss(r, inc))
            sel = name == self.character
            bg = CARD_HI if sel else SIDEBAR
            row = tk.Frame(self.char_list, bg=bg, cursor="hand2")
            row.pack(fill="x", pady=1)
            tk.Frame(row, bg=(char_color(name) if name != ALL else ACCENT) if sel else bg,
                     width=3).pack(side="left", fill="y")
            dot = tk.Label(row, text="●", bg=bg, fg=char_color(name) if name != ALL else FG,
                           font=(UI_FONT, 11))
            dot.pack(side="left", padx=(10, 6), pady=8)
            nm = tk.Label(row, text=name, bg=bg, fg=FG if sel else "#c3c8d4",
                          font=(UI_FONT_SEMI if sel else UI_FONT, 10))
            nm.pack(side="left")
            rec = tk.Label(row, text=f"{w}-{l}  {pct(w, w + l):.0f}%", bg=bg,
                           fg=GOOD if pct(w, w + l) >= 25 else DIM, font=(UI_FONT, 9))
            rec.pack(side="right", padx=12)
            widgets = (row, dot, nm, rec)
            for wd in widgets:
                wd.bind("<Button-1>", lambda e, n=name: self.set_character(n))
                if not sel:
                    wd.bind("<Enter>", lambda e, ws=widgets: [x.configure(bg=CARD) for x in ws])
                    wd.bind("<Leave>", lambda e, ws=widgets: [x.configure(bg=SIDEBAR) for x in ws])

    def _stat_card(self, parent, value, caption, color=FG):
        f = tk.Frame(parent, bg=CARD, padx=20, pady=14)
        f.pack(side="left", padx=(0, 12), fill="y")
        tk.Label(f, text=value, bg=CARD, fg=color, font=disp(20)).pack(anchor="w")
        tk.Label(f, text=caption, bg=CARD, fg=DIM, font=(UI_FONT, 9)).pack(anchor="w")

    def _render_header(self):
        name = self.character
        self.title_lbl.configure(text=name)
        self.title_dot.configure(fg=char_color(name) if name != ALL else ACCENT)
        for c in self.cards_row.winfo_children():
            c.destroy()
        inc = self.include_abandoned.get()
        rs = self.runs
        wins = [r for r in rs if r["win"]]
        losses = [r for r in rs if is_loss(r, inc)]
        decided = wins + losses
        filt = []
        if self.asc_filter.get() != "All":
            filt.append(self.asc_filter.get())
        if self.range_filter != "All runs":
            filt.append(self.range_filter.lower())
        self.subtitle_lbl.configure(text=f"{len(rs)} runs  ·  {len([r for r in rs if r['abandoned']])} abandoned"
                                         + (f"  ·  filtered: {', '.join(filt)}" if filt else ""))
        wr = pct(len(wins), len(decided))
        self._stat_card(self.cards_row, f"{wr:.0f}%", "Win rate", GOOD if wr >= 25 else WARN if wr >= 10 else BAD)
        self._stat_card(self.cards_row, f"{len(wins)}–{len(losses)}", "Wins – Losses")
        self._stat_card(self.cards_row, f"{avg([r['final_floor'] for r in losses]):.0f}" if losses else "-",
                        "Avg floor reached in losses")
        self._stat_card(self.cards_row, f"{avg([r['deck_size'] for r in decided]):.0f}" if decided else "-",
                        "Avg final deck size")
        asc = max((r["ascension"] for r in wins), default=None)
        self._stat_card(self.cards_row, f"A{asc}" if asc is not None else "-", "Highest ascension won")
        recent = sorted(decided, key=lambda r: r["start"], reverse=True)[:10]
        if recent:
            f = tk.Frame(self.cards_row, bg=CARD, padx=18, pady=12)
            f.pack(side="left", fill="y")
            strip = tk.Frame(f, bg=CARD)
            strip.pack(anchor="w", pady=(6, 4))
            for r in reversed(recent):
                tk.Frame(strip, bg=GOOD if r["win"] else BAD, width=14, height=14).pack(side="left", padx=2)
            tk.Label(f, text="Last 10 results (oldest → newest)", bg=CARD, fg=DIM,
                     font=(UI_FONT, 9)).pack(anchor="w", pady=(4, 0))

    # ----- navigation ----------------------------------------------------
    def set_character(self, name):
        self.character = name
        self.selected_file = None
        self.killer_filter = None
        self._apply_filter()
        self.refresh_views()

    def set_view(self, view):
        self.view = view
        for v, (lbl, bar) in self.tab_widgets.items():
            on = v == view
            lbl.configure(fg=FG if on else DIM)
            bar.configure(bg=ACCENT if on else BG)
        for w in (self.habits_view, self.stats_view, self.autopsy_view):
            w.pack_forget()
        if view in self.STATS_TABS:
            self.stats_view.pack(fill="both", expand=True)
            self._set_stats_tab(view)
        else:
            {"Habits & Fixes": self.habits_view, "Run Autopsy": self.autopsy_view}[view].pack(
                fill="both", expand=True)

    # ----- data ----------------------------------------------------------
    def _scan(self):
        found = {}
        try:
            with os.scandir(self.history_dir.get()) as it:
                for e in it:
                    if e.is_file() and e.name.endswith(".run"):
                        found[e.path] = e.stat().st_mtime
        except OSError:
            return None
        return found

    def _load_changed(self, found):
        changed = False
        sid = steam_id_from_path(self.history_dir.get())
        for p, mt in found.items():
            if p not in self.cache or self.cache[p][0] != mt:
                try:
                    run = parse_run(p, sid)
                except (OSError, ValueError, KeyError, TypeError, IndexError):
                    run, mt = None, -1          # half-written file: retry next poll
                self.cache[p] = (mt, run)
                changed = True
        for p in list(self.cache):
            if p not in found:
                del self.cache[p]
                changed = True
        return changed

    def _poll(self):
        if self.auto_refresh.get():
            found = self._scan()
            if found is not None and self._load_changed(found):
                new = [p for p in found if p not in self._last_seen]
                self.reload()
                if new:
                    newest = max(new, key=lambda p: found[p])
                    run = next((r for r in self.runs if r["path"] == newest), None)
                    if run:
                        self.selected_file = run["file"]
                        self._render_list()
                        self.status.set(self.status.get() + f"\nNew run: {run['character']} - {run['result']}")
        self.after(POLL_MS, self._poll)

    def reload(self, force=False):
        found = self._scan()
        if force:
            self.cache.clear()
        if found is None:
            self.status.set("Folder not found - click 'Change folder...'")
            self.all_runs = []
        else:
            self._load_changed(found)
            self._last_seen = set(found)
            runs = [r for _, r in self.cache.values() if r and r["floors"]]
            if not self.include_multi.get():
                runs = [r for r in runs if not r["multiplayer"]]
            self.all_runs = runs
            newest = max(runs, key=lambda r: r["start"], default=None)
            self.current_build = newest["build"] if newest else ""
            self.status.set(f"{len(runs)} runs loaded · updated {time.strftime('%H:%M:%S')}")
        if self.character != ALL and not any(r["character"] == self.character for r in self.all_runs):
            self.character = ALL
        self._apply_filter()
        self.refresh_views()

    def _scope(self, rs):
        """Apply the header filters (ascension, run range / build) to a list of runs."""
        asc = self.asc_filter.get()
        if asc != "All":
            n = int(asc.strip("A+"))
            rs = [r for r in rs if (r["ascension"] >= n if asc.endswith("+") else r["ascension"] == n)]
        if self.range_filter == "Current build":
            rs = [r for r in rs if r["build"] == self.current_build]
        rs = sorted(rs, key=lambda r: r["start"], reverse=True)
        if self.range_filter.startswith("Last "):
            rs = rs[: int(self.range_filter.split()[1])]
        return rs

    def _apply_filter(self):
        rs = self.all_runs if self.character == ALL else [r for r in self.all_runs if r["character"] == self.character]
        self.runs = self._scope(rs)

    def _set_range(self, opt):
        self.range_filter = opt
        self._filters_changed()

    def _filters_changed(self):
        self._apply_filter()
        self.refresh_views()

    def _render_filters(self):
        ascs = sorted({r["ascension"] for r in self.all_runs})
        vals = ["All"] + [f"A{a}" for a in ascs] + [f"A{a}+" for a in ascs if a > 0]
        self.asc_box["values"] = vals
        if self.asc_filter.get() not in vals:
            self.asc_filter.set("All")
        for opt, p in self.range_pills.items():
            on = opt == self.range_filter
            p.configure(bg=CARD_HI if on else CARD, fg=ACCENT if on else DIM)
        self.build_lbl.configure(text=f"current build {self.current_build}" if self.current_build else "")

    def refresh_views(self):
        self._render_filters()
        self._render_sidebar()
        self._render_header()
        self._render_habits()
        self._render_stats()
        self._render_list()

    # ----- Habits & Fixes view -------------------------------------------
    def _render_habits(self):
        sf = self.habits_view
        sf.clear()
        inner = sf.inner
        inc = self.include_abandoned.get()
        habits, fine, wins, losses = habit_report(self.runs, inc)
        who = "this character" if self.character != ALL else "all characters"

        self._gameplan_card(inner)

        if len(losses) < 2:
            box = tk.Frame(inner, bg=CARD, padx=22, pady=20)
            box.pack(fill="x", pady=(0, 12))
            wrap_label(box, "Not enough losses yet to find patterns.", 13, weight="bold").pack(fill="x")
            wrap_label(box, f"Play a few more runs with {who} and this page will rank the habits that "
                            f"keep ending your runs.", 10, fg=DIM).pack(fill="x", pady=(4, 0))
            return

        wrap_label(inner, f"Run-killing habits  ·  based on {len(losses)} losses and {len(wins)} wins",
                   12, bg=BG, weight="bold").pack(fill="x", pady=(2, 2))
        wrap_label(inner, "Ranked by how much more often they show up in your losses than in your wins.",
                   9, bg=BG, fg=DIM).pack(fill="x", pady=(0, 10))

        if not habits:
            box = tk.Frame(inner, bg=CARD, padx=22, pady=18)
            box.pack(fill="x", pady=(0, 12))
            wrap_label(box, "No recurring run-killing habit found. Nice!", 12, weight="bold", fg=GOOD).pack(fill="x")

        if self._auto_expand and habits:
            self.expanded.add(habits[0]["h"]["id"])
            self._auto_expand = False
        for i, it in enumerate(habits, 1):
            self._habit_card(inner, i, it)

        if fine:
            wrap_label(inner, "Under control", 12, bg=BG, weight="bold").pack(fill="x", pady=(16, 6))
            chips = tk.Frame(inner, bg=BG)
            chips.pack(fill="x")
            for j, it in enumerate(fine):
                c = tk.Frame(chips, bg=CARD, padx=12, pady=7)
                c.grid(row=j // 3, column=j % 3, sticky="ew", padx=(0, 8), pady=4)
                tk.Label(c, text="✓  " + it["h"]["title"], bg=CARD, fg=GOOD,
                         font=(UI_FONT, 9), anchor="w").pack(anchor="w")
            for col in range(3):
                chips.grid_columnconfigure(col, weight=1)

    def _gameplan_card(self, parent):
        """Compact 'Next Run Gameplan': 2 priority fixes with a last-5 check + 1 best / 1 trap card."""
        inc = self.include_abandoned.get()
        filtered = self.asc_filter.get() != "All" or self.range_filter != "All runs"
        scope = self.runs if filtered else self.runs[:GAMEPLAN_RUNS]
        fixes, n_dec = gameplan_fixes(scope, inc)
        who = self.character if self.character != ALL else "all"
        scope_txt = (f"current filter · {n_dec} finished runs" if filtered
                     else f"last {min(GAMEPLAN_RUNS, len(self.runs))} {who} runs · {n_dec} finished")

        card = tk.Frame(parent, bg=FOCUS_BG)
        card.pack(fill="x", pady=(0, 18))
        tk.Frame(card, bg=ACCENT, height=3).pack(fill="x")
        body = tk.Frame(card, bg=FOCUS_BG, padx=20, pady=14)
        body.pack(fill="x")
        head = tk.Frame(body, bg=FOCUS_BG)
        head.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="Next Run Gameplan", bg=FOCUS_BG, fg=FG, font=disp(15)).pack(side="left")
        tk.Label(head, text=scope_txt, bg=FOCUS_BG, fg=FAINT, font=(UI_FONT, 9)).pack(side="left", padx=12, pady=(4, 0))

        grid = tk.Frame(body, bg=FOCUS_BG)
        grid.pack(fill="x")
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1, uniform="gp")

        # Priority fixes
        for i in range(2):
            cell = tk.Frame(grid, bg=CARD, padx=14, pady=12)
            cell.grid(row=0, column=i, sticky="nsew", padx=(0, 10))
            if i >= len(fixes):
                tk.Label(cell, text=f"PRIORITY {i + 1}", bg=CARD, fg=FAINT, font=(UI_FONT_SEMI, 8)).pack(anchor="w")
                wrap_label(cell, "No other leak above 25% in these runs - keep it up." if fixes or n_dec >= 3
                           else "Not enough finished runs yet.", 10, fg=GOOD if n_dec >= 3 else DIM).pack(fill="x", pady=(4, 0))
                continue
            f = fixes[i]
            top = tk.Frame(cell, bg=CARD)
            top.pack(fill="x")
            tk.Label(top, text=f"PRIORITY {i + 1}", bg=CARD, fg=ACCENT, font=(UI_FONT_SEMI, 8)).pack(side="left")
            tk.Label(top, text=f"{f['rate']:.0f}% leak", bg=CARD, fg=BAD, font=(UI_FONT_SEMI, 8)).pack(side="right")
            tk.Label(cell, text=f["title"], bg=CARD, fg=FG, font=disp(13)).pack(anchor="w", pady=(2, 2))
            wrap_label(cell, f["detail"], 9, fg=DIM).pack(fill="x")
            wrap_label(cell, "Target: " + f["target"], 9, fg=FG).pack(fill="x", pady=(4, 6))
            chk = tk.Frame(cell, bg=CARD)
            chk.pack(fill="x")
            dots = tk.Frame(chk, bg=CARD)
            dots.pack(side="left")
            for v in reversed(f["last5"]):        # oldest -> newest
                tk.Frame(dots, bg=GOOD if v else BAD, width=10, height=10).pack(side="left", padx=1)
            ok_n = sum(1 for v in f["last5"] if v)
            tk.Label(chk, text=f"  {ok_n}/{len(f['last5'])} recent runs {f['ok_word']}", bg=CARD,
                     fg=GOOD if ok_n >= 4 else WARN if ok_n >= 2 else BAD, font=(UI_FONT, 9)).pack(side="left")

        # Draft watchlist (from the Card Table data, current filters)
        cell = tk.Frame(grid, bg=CARD, padx=14, pady=12)
        cell.grid(row=0, column=2, sticky="nsew")
        tk.Label(cell, text=f"DRAFT WATCHLIST  ·  {GAMEPLAN_MIN_PICKS}+ picks", bg=CARD, fg=ACCENT,
                 font=(UI_FONT_SEMI, 8)).pack(anchor="w")
        if self.character == ALL:
            wrap_label(cell, "Pick a character in the sidebar to see which cards to look for and avoid.",
                       10, fg=DIM).pack(fill="x", pady=(4, 0))
            return
        best, trap, n_ok = draft_watchlist(self.runs, inc)
        if not best and not trap:
            wrap_label(cell, f"No card has {GAMEPLAN_MIN_PICKS}+ picks with these filters yet.", 10,
                       fg=DIM).pack(fill="x", pady=(4, 0))
            return
        for label, x, col in (("LOOK FOR", best, GOOD), ("AVOID", trap, BAD)):
            row = tk.Frame(cell, bg=CARD_HI, padx=10, pady=7, cursor="hand2" if x else "")
            row.pack(fill="x", pady=(6, 0))
            top = tk.Frame(row, bg=CARD_HI)
            top.pack(fill="x")
            tk.Label(top, text=label, bg=CARD_HI, fg=col, font=(UI_FONT_SEMI, 8)).pack(side="left")
            if not x:
                tk.Label(row, text="nothing clear yet", bg=CARD_HI, fg=FAINT, font=(UI_FONT, 9)).pack(anchor="w")
                continue
            tk.Label(top, text=f"{x['delta']:+.0f}", bg=CARD_HI, fg=col, font=disp(12)).pack(side="right")
            tk.Label(row, text=x["card"], bg=CARD_HI, fg=FG, font=(UI_FONT_SEMI, 11)).pack(anchor="w")
            tk.Label(row, text=f"win {x['wr_p']:.0f}% taken · {x['wr_s']:.0f}% skipped · {x['np']} picks",
                     bg=CARD_HI, fg=DIM, font=(UI_FONT, 8)).pack(anchor="w")
            for wdg in [row] + list(row.winfo_children()) + list(top.winfo_children()):
                wdg.bind("<Button-1>", lambda e, c=x["card"]: self.open_card(c))

    def open_card(self, card):
        """Jump to the Card Table with this card selected (biome reset to all acts)."""
        self.biome = "All acts"
        self.detail_card = card
        self.set_view("Card Table")

    def _habit_card(self, parent, rank, it):
        h = it["h"]
        color = {"high": BAD, "med": WARN, "low": INFO}[it["sev"]]
        label = {"high": "MAJOR LEAK", "med": "LEAK", "low": "MINOR"}[it["sev"]]
        outer = tk.Frame(parent, bg=CARD)
        outer.pack(fill="x", pady=(0, 12))
        tk.Frame(outer, bg=color, width=4).pack(side="left", fill="y")
        body = tk.Frame(outer, bg=CARD, padx=20, pady=16)
        body.pack(side="left", fill="both", expand=True)

        top = tk.Frame(body, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text=f"{rank}", bg=CARD, fg=FAINT, font=disp(18)).pack(side="left", padx=(0, 12))
        tk.Label(top, text=h["title"], bg=CARD, fg=FG, font=disp(14)).pack(side="left")
        tk.Label(top, text=f" {label} ", bg=color, fg=BG, font=(UI_FONT_SEMI, 8)).pack(side="right")

        # frequency bars
        bars = tk.Frame(body, bg=CARD)
        bars.pack(fill="x", pady=(10, 4))
        self._bar(bars, "In your losses", it["loss_rate"], color,
                  f"{it['loss_hits']}/{it['loss_n']}")
        if h["kind"] == "run" and it.get("win_n"):
            self._bar(bars, "In your wins", it["win_rate"], GOOD, f"{it['win_hits']}/{it['win_n']}")

        # numbers
        fmt = h["fmt"]
        if h["id"] == "elite_death":
            nums = f"{it['loss_rate']:.0f}% of your losses ended at an elite."
        else:
            nums = f"Your average: {fmt.format(it['loss_avg'])} {h['unit']} in losses"
            if h["kind"] == "run" and it.get("win_avg") is not None and it.get("win_n"):
                nums += f"  vs  {fmt.format(it['win_avg'])} in wins"
            nums += "."
        if h["kind"] == "run" and it.get("wr_with") is not None and it.get("wr_without") is not None \
                and it.get("win_n"):
            nums += f"  Win rate with this habit {it['wr_with']:.0f}%, without {it['wr_without']:.0f}%."
        wrap_label(body, nums, 10, fg=INFO).pack(fill="x", pady=(6, 2))
        wrap_label(body, h["why"], 10, fg=DIM).pack(fill="x", pady=(2, 6))

        hid = h["id"]
        toggle = tk.Label(body, bg=CARD, fg=ACCENT, font=(UI_FONT_SEMI, 8), cursor="hand2")
        toggle.pack(anchor="w")
        tips = tk.Frame(body, bg=CARD)

        def show(open_):
            toggle.configure(text=("▾  WHAT TO DO" if open_ else f"▸  WHAT TO DO  ({len(h['fix'])} tips)"))
            if open_:
                tips.pack(fill="x", after=toggle, pady=(2, 0))
            else:
                tips.pack_forget()

        def flip(_e=None):
            if hid in self.expanded:
                self.expanded.discard(hid)
            else:
                self.expanded.add(hid)
            show(hid in self.expanded)

        toggle.bind("<Button-1>", flip)
        show(hid in self.expanded)
        for tip in h["fix"]:
            row = tk.Frame(tips, bg=CARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text="→", bg=CARD, fg=FAINT, font=(UI_FONT_SEMI, 10)).pack(side="left", anchor="n")
            wrap_label(row, tip, 10, pad=10).pack(side="left", fill="x", expand=True, padx=(8, 0))

        ex = sorted(it["examples"], key=lambda r: r["start"], reverse=True)[:4]
        if ex:
            exr = tk.Frame(body, bg=CARD)
            exr.pack(fill="x", pady=(10, 0))
            tk.Label(exr, text="Recent examples:", bg=CARD, fg=FAINT, font=(UI_FONT, 9)).pack(side="left")
            for r in ex:
                d = datetime.fromtimestamp(r["start"]).strftime("%d %b") if r["start"] else "?"
                txt = f"{d} · {r['character']} · F{r['final_floor']}"
                lk = tk.Label(exr, text=txt, bg=CARD_HI, fg=INFO, font=(UI_FONT, 9), padx=8, pady=2,
                              cursor="hand2")
                lk.pack(side="left", padx=(8, 0))
                lk.bind("<Button-1>", lambda e, f=r["file"]: self.open_autopsy(f))

    def _bar(self, parent, label, value, color, count):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, bg=CARD, fg=DIM, font=(UI_FONT, 9), width=14, anchor="w").pack(side="left")
        track = tk.Frame(row, bg=BORDER, height=8, width=260)
        track.pack(side="left", padx=(4, 10))
        track.pack_propagate(False)
        fill_w = max(2, int(260 * (value or 0) / 100))
        tk.Frame(track, bg=color, height=8, width=fill_w).place(x=0, y=0)
        tk.Label(row, text=f"{(value or 0):.0f}%  ({count})", bg=CARD, fg=FG, font=(UI_FONT, 9)).pack(side="left")

    def open_autopsy(self, fname):
        self.killer_filter = None
        self.selected_file = fname
        self.set_view("Run Autopsy")
        self._render_list()

    # ----- Stats view ----------------------------------------------------
    STATS_TABS = ("Draft Guide", "Overview", "Card Table")

    def _build_stats(self):
        self.stats_view = tk.Frame(self.content, bg=BG)
        self.stats_tab = "Draft Guide"
        self.biome = "All acts"
        self.min_picks_scope = {"all": 8, "biome": 3}
        self.table_sort = ("score", True)
        self._stats_job = None

        bar = tk.Frame(self.stats_view, bg=BG)
        bar.pack(fill="x", pady=(0, 12))
        seg = tk.Frame(bar, bg=CARD)      # sub-tabs now live in the main navigation (kept for state)
        self.stats_tab_btns = {}
        for name in self.STATS_TABS:
            b = tk.Label(seg, text=name, bg=CARD, fg=DIM, font=(UI_FONT_SEMI, 9), padx=14, pady=6, cursor="hand2")
            b.pack(side="left", padx=1, pady=1)
            b.bind("<Button-1>", lambda e, n=name: self._set_stats_tab(n))
            self.stats_tab_btns[name] = b

        right = tk.Frame(bar, bg=BG)
        right.pack(side="left")
        self.stats_right = right
        self.min_val_lbl = tk.Label(right, text="", bg=BG, fg=ACCENT, font=(UI_FONT_SEMI, 10), width=3)
        self.min_val_lbl.pack(side="right")
        self.slider_var = tk.IntVar(value=8)
        self.min_scale = tk.Scale(right, from_=3, to=25, orient="horizontal", variable=self.slider_var,
                                  showvalue=False, length=150, bg=ACCENT, troughcolor=BORDER,
                                  activebackground=ACCENT_HOVER, highlightthickness=0, borderwidth=0,
                                  sliderrelief="flat", sliderlength=14, width=8, cursor="hand2")
        self.min_scale.pack(side="right", padx=6)
        tk.Label(right, text="MIN PICKS", bg=BG, fg=FAINT, font=(UI_FONT_SEMI, 8)).pack(side="right", padx=(18, 0))
        self.slider_var.trace_add("write", self._on_slider)

        self.biome_bar = tk.Frame(right, bg=CARD)
        self.biome_bar.pack(side="right")
        self.biome_btns = {}

        body = tk.Frame(self.stats_view, bg=BG)
        body.pack(fill="both", expand=True)
        self.guide_sf = ScrollFrame(body)
        self.overview_sf = ScrollFrame(body)
        self.table_frame = tk.Frame(body, bg=BG)
        tpane = tk.PanedWindow(self.table_frame, orient="horizontal", bg=BG, sashwidth=10,
                               borderwidth=0, sashrelief="flat")
        tpane.pack(fill="both", expand=True)
        tleft = tk.Frame(tpane, bg=CARD)
        self.detail_sf = ScrollFrame(tpane, bg=CARD)
        tpane.add(tleft, minsize=520, stretch="always")
        tpane.add(self.detail_sf, minsize=340, width=390, stretch="never")
        self.detail_card = None
        cols = [("card", "CARD", 128, "w"), ("verdict", "VERDICT", 72, "w"), ("offered", "OFFERS", 56, "center"),
                ("pick", "PICK%", 50, "center"), ("wrp", "WIN TAKEN", 80, "center"),
                ("wrs", "WIN SKIP", 80, "center"), ("lift", "LIFT", 44, "center"),
                ("deck", "DECK", 46, "center"), ("tempo", "TEMPO", 54, "center"),
                ("removed", "REM", 40, "center"), ("flags", "NOTES", 90, "w")]
        self.card_tree = ttk.Treeview(tleft, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, title, wdt, anc in cols:
            self.card_tree.heading(key, text=title, anchor=anc, command=lambda k=key: self._sort_table(k))
            self.card_tree.column(key, width=wdt, minwidth=36, anchor=anc, stretch=key in ("card", "flags"))
        self.card_tree.tag_configure("TAKE", foreground=GOOD)
        self.card_tree.tag_configure("SKIP", foreground=BAD)
        self.card_tree.tag_configure("OK", foreground=FG)
        self.card_tree.tag_configure("LOW", foreground=FAINT)
        tsb = ttk.Scrollbar(tleft, orient="vertical", command=self.card_tree.yview,
                            style="Modern.Vertical.TScrollbar")
        self.card_tree.configure(yscrollcommand=tsb.set)
        self.card_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        tsb.pack(side="right", fill="y")
        self.card_tree.bind("<<TreeviewSelect>>", self._on_card_select)
        self._set_stats_tab(self.stats_tab, render=False)
        self.stats_bar = bar

    def _scope_key(self):
        return "all" if self.biome == "All acts" else "biome"

    def _set_stats_tab(self, name, render=True):
        self.stats_tab = name
        for n, b in self.stats_tab_btns.items():
            b.configure(bg=CARD_HI if n == name else CARD, fg=ACCENT if n == name else DIM)
        bar = getattr(self, "stats_bar", None)
        if name == "Overview":
            self.stats_right.pack_forget()
            if bar is not None:
                bar.pack_forget()
        else:
            if bar is not None and not bar.winfo_ismapped():
                bar.pack(fill="x", pady=(0, 14), before=bar.master.winfo_children()[1])
            if not self.stats_right.winfo_ismapped():
                self.stats_right.pack(side="left")
        for w in (self.guide_sf, self.overview_sf, self.table_frame):
            w.pack_forget()
        {"Draft Guide": self.guide_sf, "Overview": self.overview_sf,
         "Card Table": self.table_frame}[name].pack(fill="both", expand=True)
        if render:
            self._render_stats()

    def _set_biome(self, biome):
        self.biome = biome
        self.slider_var.set(self.min_picks_scope[self._scope_key()])
        self._render_stats()

    def _on_slider(self, *_):
        self.min_picks_scope[self._scope_key()] = self.slider_var.get()
        self.min_val_lbl.configure(text=str(self.slider_var.get()))
        if self._stats_job:
            self.after_cancel(self._stats_job)
        self._stats_job = self.after(120, self._render_stats)

    def _render_biome_bar(self):
        for c in self.biome_bar.winfo_children():
            c.destroy()
        present = {f["act_id"] for r in self.runs for f in r["floors"]}
        opts = ["All acts"] + [a for a in ACT_ORDER if a in present] + sorted(present - set(ACT_ORDER))
        if self.biome not in ["All acts"] + [pretty_act(a) for a in opts[1:]]:
            self.biome = "All acts"
        for a in opts:
            name = a if a == "All acts" else pretty_act(a)
            on = name == self.biome
            b = tk.Label(self.biome_bar, text=name, bg=CARD_HI if on else CARD, fg=ACCENT if on else DIM,
                         font=(UI_FONT_SEMI, 9), padx=11, pady=6, cursor="hand2")
            b.pack(side="left", padx=1, pady=1)
            b.bind("<Button-1>", lambda e, n=name: self._set_biome(n))
        self.min_val_lbl.configure(text=str(self.slider_var.get()))

    def _biome_act_ids(self):
        if self.biome == "All acts":
            return None
        return {a for r in self.runs for f in r["floors"] for a in [f["act_id"]] if pretty_act(a) == self.biome}

    def _render_stats(self):
        self._stats_job = None
        self._render_biome_bar()
        if self.stats_tab == "Draft Guide":
            self._render_guide()
        elif self.stats_tab == "Overview":
            self._render_overview()
        else:
            self._render_card_table()

    # -- shared helpers for the stats sub-views
    def _panel(self, parent, title, subtitle=None, accent=None):
        outer = tk.Frame(parent, bg=CARD)
        if accent:
            tk.Frame(outer, bg=accent, height=3).pack(fill="x")
        inner = tk.Frame(outer, bg=CARD, padx=18, pady=14)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=title, bg=CARD, fg=accent or FG, font=(UI_FONT_SEMI, 11)).pack(anchor="w")
        if subtitle:
            wrap_label(inner, subtitle, 9, fg=FAINT).pack(fill="x", pady=(1, 0))
        body = tk.Frame(inner, bg=CARD)
        body.pack(fill="both", expand=True, pady=(10, 0))
        return outer, body

    def _guide_rows(self):
        inc = self.include_abandoned.get()
        act_ids = self._biome_act_ids()
        rows, meta = card_pick_impact(self.runs, inc, min_offered=1, act_ids=act_ids)
        n = self.slider_var.get()
        ok = [x for x in rows if x["delta"] is not None and x["np"] >= n]
        wsum = sum(min(x["np"], x["ns"]) for x in ok)
        base = sum(x["delta"] * min(x["np"], x["ns"]) for x in ok) / wsum if wsum else 0.0
        tb = meta["tempo_base"]
        for x in rows:
            x["rel"] = (x["delta"] - base) if x["delta"] is not None else None
            k = min(x["np"], x["ns"])
            x["score"] = x["rel"] * k / (k + 4) if x["rel"] is not None else None
            x["trel"] = (x["tempo"] - tb) if x["tempo"] is not None else None
            if x["delta"] is None or x["np"] < n:
                x["verdict"] = "LOW"
            elif x["score"] >= 4:
                x["verdict"] = "TAKE"
            elif x["score"] <= -4:
                x["verdict"] = "SKIP"
            else:
                x["verdict"] = "OK"
            notes = []
            if x["trel"] is not None and x["tempo_n"] >= 3:
                if x["trel"] <= -0.4:
                    notes.append(("faster fights", GOOD))
                elif x["trel"] >= 0.4:
                    notes.append(("slower fights", WARN))
            if x["bloat"]:
                notes.append(("bloated losses", BAD))
            if x["removed"] >= 2 or (x["picks"] and x["removed"] and x["removed"] / x["picks"] >= 0.3):
                notes.append(("often removed", WARN))
            x["notes"] = notes
        return rows, meta, base

    # -- Draft Guide
    def _render_guide(self):
        sf = self.guide_sf
        sf.clear()
        inner = sf.inner
        if not self.runs:
            wrap_label(inner, "No runs with the current filters.", 12, bg=BG, fg=DIM).pack(fill="x")
            return
        inc = self.include_abandoned.get()
        rows, meta, base = self._guide_rows()
        tk.Label(inner, text=("Draft guide - all acts" if self.biome == "All acts" else f"Draft guide - {self.biome}"),
                 bg=BG, fg=FG, font=disp(16)).pack(anchor="w", pady=(0, 8))
        n = self.slider_var.get()
        rs = reward_stats(self.runs, inc, self._biome_act_ids())

        # Summary strip
        strip = tk.Frame(inner, bg=BG)
        strip.pack(fill="x", pady=(0, 12))
        where = "across all acts" if self.biome == "All acts" else f"in {self.biome}"
        self._mini_stat(strip, f"{rs['rewards']}", f"card rewards {where}")
        self._mini_stat(strip, f"{rs['pick']:.0f}%", "of rewards you take a card")
        if rs["skip_win"] is not None and rs["skip_loss"] is not None:
            diff = rs["skip_loss"] - rs["skip_win"]
            col = WARN if abs(diff) >= 8 else FG
            self._mini_stat(strip, f"{rs['skip_win']:.0f}% / {rs['skip_loss']:.0f}%",
                            "skip rate in wins / losses", col)
        bases = meta["base"]
        ids = self._biome_act_ids()
        if ids:
            bt = [bases[a] for a in ids if a in bases]
            if bt:
                self._mini_stat(strip, f"{avg(bt):.2f}", "avg turns per hallway fight here")

        if rs["skip_win"] is not None and rs["skip_loss"] is not None and abs(rs["skip_loss"] - rs["skip_win"]) >= 8:
            more = "more" if rs["skip_loss"] > rs["skip_win"] else "fewer"
            tip = ("You skip more rewards in runs you lose - in this part of the run, taking a playable card "
                   "beats skipping." if more == "more" else
                   "You take more cards in runs you lose - be pickier here and skip cards that don't fix a "
                   "real weakness.")
            ban = tk.Frame(inner, bg=FOCUS_BG, padx=16, pady=10)
            ban.pack(fill="x", pady=(0, 12))
            wrap_label(ban, "💡 " + tip, 10, bg=FOCUS_BG, fg=FG).pack(fill="x")

        take = sorted([x for x in rows if x["verdict"] == "TAKE"], key=lambda x: -x["score"])
        skip = sorted([x for x in rows if x["verdict"] == "SKIP"], key=lambda x: x["score"])
        okay = sorted([x for x in rows if x["verdict"] == "OK"], key=lambda x: -x["np"])

        cols = tk.Frame(inner, bg=BG)
        cols.pack(fill="both", expand=True)
        for i in range(3):
            cols.grid_columnconfigure(i, weight=1, uniform="cols")
        spec = [("TAKE", "Cards that lift your win rate", GOOD, take),
                ("FINE EITHER WAY", "No clear effect yet", DIM, okay),
                ("SKIP", "Cards your losing runs are full of", BAD, skip)]
        for i, (title, sub, color, items) in enumerate(spec):
            outer, body = self._panel(cols, f"{title}  ·  {len(items)}", sub, accent=color)
            outer.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
            if not items:
                wrap_label(body, f"No cards here with {n}+ picks.\nTry lowering MIN PICKS.", 9, fg=FAINT).pack(fill="x")
            for x in items[:12]:
                self._card_tile(body, x, color)
            if len(items) > 12:
                tk.Label(body, text=f"+{len(items) - 12} more in Card Table", bg=CARD, fg=FAINT,
                         font=(UI_FONT, 9)).pack(anchor="w", pady=(6, 0))

        low = len([x for x in rows if x["verdict"] == "LOW"])
        wrap_label(inner, f"Lift = your win rate when you took the card minus when you skipped it, compared with "
                          f"your typical card here ({base:+.0f}). Cards need {n}+ picks to be rated "
                          f"({low} cards have too few). The dots show confidence: ●○○ few picks, ●●● many. "
                          f"Results, not card quality - small samples are hints, not rules.",
                   9, bg=BG, fg=FAINT).pack(fill="x", pady=(14, 0))

    def _mini_stat(self, parent, value, caption, color=FG):
        f = tk.Frame(parent, bg=CARD, padx=16, pady=10)
        f.pack(side="left", padx=(0, 10))
        tk.Label(f, text=value, bg=CARD, fg=color, font=(UI_FONT_SEMI, 14)).pack(anchor="w")
        tk.Label(f, text=caption, bg=CARD, fg=DIM, font=(UI_FONT, 9)).pack(anchor="w")

    def _card_tile(self, parent, x, color):
        tile = tk.Frame(parent, bg=CARD_HI, padx=12, pady=8)
        tile.pack(fill="x", pady=3)
        top = tk.Frame(tile, bg=CARD_HI)
        top.pack(fill="x")
        tk.Label(top, text=x["card"], bg=CARD_HI, fg=FG, font=(UI_FONT_SEMI, 10)).pack(side="left")
        tk.Label(top, text=f"{x['delta']:+.0f}", bg=CARD_HI, fg=color if color != DIM else FG,
                 font=(UI_FONT_SEMI, 12)).pack(side="right")
        conf = "●●●" if x["np"] >= 8 else "●●○" if x["np"] >= 5 else "●○○"
        mid = tk.Frame(tile, bg=CARD_HI)
        mid.pack(fill="x")
        tk.Label(mid, text=f"win {x['wr_p']:.0f}% taken · {x['wr_s']:.0f}% skipped · {x['np']} picks",
                 bg=CARD_HI, fg=DIM, font=(UI_FONT, 9)).pack(side="left")
        tk.Label(mid, text=conf, bg=CARD_HI, fg=FAINT, font=(UI_FONT, 8)).pack(side="right")
        if x["notes"]:
            nr = tk.Frame(tile, bg=CARD_HI)
            nr.pack(fill="x", pady=(4, 0))
            for text, col in x["notes"]:
                tk.Label(nr, text=text, bg=CARD, fg=col, font=(UI_FONT, 8), padx=6, pady=1).pack(side="left", padx=(0, 4))

    # -- Overview
    def _render_overview(self):
        sf = self.overview_sf
        sf.clear()
        inner = sf.inner
        runs = self.runs
        if not runs:
            wrap_label(inner, "No runs with the current filters.", 12, bg=BG, fg=DIM).pack(fill="x")
            return
        inc = self.include_abandoned.get()
        a = aggregate(runs, inc)
        nw, nl = len(a["wins"]), len(a["losses"])
        grid = tk.Frame(inner, bg=BG)
        grid.pack(fill="both", expand=True)
        grid.grid_columnconfigure(0, weight=1, uniform="ov")
        grid.grid_columnconfigure(1, weight=1, uniform="ov")

        def place(panel, r, c, span=1):
            panel.grid(row=r, column=c, columnspan=span, sticky="nsew",
                       padx=(0 if c == 0 else 6, 0 if c + span >= 2 else 6), pady=(0, 12))

        # Fight speed table (full width)
        p, b = self._panel(grid, "Fight speed by biome",
                           "Average turns and damage per fight (red = slower than target). Win % = finished runs "
                           "that went through that biome - for Act 1 that's the biome you started in.")
        place(p, 0, 0, 2)
        heads = ["Biome", "Hallway turns", "Hallway dmg", "Elite turns", "Elite dmg", "Boss turns", "Boss dmg",
                 "Fights", "Win %"]
        decided = [r for r in runs if r["win"] or is_loss(r, inc)]
        for j, h in enumerate(heads):
            tk.Label(b, text=h.upper(), bg=CARD, fg=FAINT, font=(UI_FONT_SEMI, 8)).grid(
                row=0, column=j, sticky="w", padx=(0, 22), pady=(0, 4))
        order = sorted(a["fights"], key=lambda k: (ACT_ORDER.index(k) if k in ACT_ORDER else 99, k))
        for i, act_id in enumerate(order, 1):
            num = a["act_num"].get(act_id, 0)
            fd = a["fights"][act_id]
            tk.Label(b, text=f"Act {num} · {pretty_act(act_id)}", bg=CARD, fg=FG,
                     font=(UI_FONT_SEMI, 10)).grid(row=i, column=0, sticky="w", padx=(0, 22), pady=3)
            col = 1
            for rt in COMBAT_TYPES:
                data = fd.get(rt, [])
                if data:
                    t = avg([d[0] for d in data])
                    lim = SLOW_TURNS_BY_ACT.get(num)
                    tc = (BAD if lim and t > lim else GOOD) if rt == "monster" else FG
                    tk.Label(b, text=f"{t:.2f}", bg=CARD, fg=tc, font=(UI_FONT, 10)).grid(row=i, column=col, sticky="w")
                    tk.Label(b, text=f"{avg([d[1] for d in data]):.1f}", bg=CARD, fg=DIM,
                             font=(UI_FONT, 10)).grid(row=i, column=col + 1, sticky="w")
                else:
                    tk.Label(b, text="-", bg=CARD, fg=FAINT).grid(row=i, column=col, sticky="w")
                col += 2
            tk.Label(b, text=str(sum(len(v) for v in fd.values())), bg=CARD, fg=DIM,
                     font=(UI_FONT, 10)).grid(row=i, column=7, sticky="w", padx=(0, 22))
            visited = [r for r in decided if any(f["act_id"] == act_id for f in r["floors"])]
            if visited:
                wins_here = sum(r["win"] for r in visited)
                w_pct = pct(wins_here, len(visited))
                overall = pct(len(a["wins"]), len(decided)) if decided else 0
                wc = GOOD if w_pct >= overall + 5 else BAD if w_pct <= overall - 5 else FG
                cell = tk.Frame(b, bg=CARD)
                cell.grid(row=i, column=8, sticky="w")
                tk.Label(cell, text=f"{w_pct:.0f}%", bg=CARD, fg=wc, font=(UI_FONT_SEMI, 10)).pack(side="left")
                tk.Label(cell, text=f" ({wins_here}/{len(visited)})", bg=CARD, fg=FAINT,
                         font=(UI_FONT, 9)).pack(side="left")
            else:
                tk.Label(b, text="-", bg=CARD, fg=FAINT).grid(row=i, column=8, sticky="w")

        # Card rewards by biome
        p, b = self._panel(grid, "Card rewards by biome", "How often you take a card, and skip rate in wins vs losses.")
        place(p, 1, 0)
        for j, h in enumerate(["Biome", "Rewards", "Take %", "Skip in wins", "Skip in losses"]):
            tk.Label(b, text=h.upper(), bg=CARD, fg=FAINT, font=(UI_FONT_SEMI, 8)).grid(
                row=0, column=j, sticky="w", padx=(0, 18), pady=(0, 4))
        acts_present = sorted({f["act_id"] for r in runs for f in r["floors"]},
                              key=lambda k: ACT_ORDER.index(k) if k in ACT_ORDER else 99)
        for i, act_id in enumerate(acts_present, 1):
            st = reward_stats(runs, inc, {act_id})
            if not st["rewards"]:
                continue
            vals = [pretty_act(act_id), str(st["rewards"]), f"{st['pick']:.0f}%",
                    "-" if st["skip_win"] is None else f"{st['skip_win']:.0f}%",
                    "-" if st["skip_loss"] is None else f"{st['skip_loss']:.0f}%"]
            for j, v in enumerate(vals):
                fg = FG if j == 0 else DIM
                if j == 4 and st["skip_win"] is not None and st["skip_loss"] is not None \
                        and abs(st["skip_loss"] - st["skip_win"]) >= 8:
                    fg = WARN
                tk.Label(b, text=v, bg=CARD, fg=fg, font=(UI_FONT_SEMI if j == 0 else UI_FONT, 10)).grid(
                    row=i, column=j, sticky="w", padx=(0, 18), pady=2)

        # Leaks
        p, b = self._panel(grid, "Leaks at death", f"Based on {nl} losses.")
        place(p, 1, 1)
        if nl:
            for label, n_, color in ((f"Gold >{GOLD_LEAK_THRESHOLD}", len(a["gold_leak"]), WARN),
                                     ("Unused potions", len(a["pot_leak"]), WARN),
                                     ("Either leak", len(a["any_leak"]), BAD)):
                self._bar(b, label, pct(n_, nl), color, f"{n_}/{nl}")
            tk.Label(b, text=f"Average gold at death: {a['avg_gold_at_death']:.0f}", bg=CARD, fg=DIM,
                     font=(UI_FONT, 9)).pack(anchor="w", pady=(8, 0))
            pots = Counter(p_ for r in a["pot_leak"] for p_ in r["unused_potions"]).most_common(4)
            if pots:
                wrap_label(b, "Often held at death: " + ", ".join(f"{p_} ×{k}" for p_, k in pots),
                           9, fg=FAINT).pack(fill="x")
        else:
            tk.Label(b, text="No losses here.", bg=CARD, fg=GOOD).pack(anchor="w")

        # Nemesis
        p, b = self._panel(grid, "Nemesis list", "What ends your runs.")
        place(p, 2, 0)
        if a["nemesis"]:
            top = a["nemesis"][0][1]
            for name, k in a["nemesis"][:8]:
                row = tk.Frame(b, bg=CARD, cursor="hand2")
                row.pack(fill="x", pady=1)
                nm = tk.Label(row, text=name, bg=CARD, fg=FG, font=(UI_FONT, 10), width=26, anchor="w",
                              cursor="hand2")
                nm.pack(side="left", padx=(4, 0), pady=1)
                track = tk.Frame(row, bg=CARD, width=180, height=10)
                track.pack(side="left", padx=6)
                track.pack_propagate(False)
                tk.Frame(track, bg=BAD, width=max(4, int(180 * k / top)), height=10).place(x=0, y=0)
                cnt = tk.Label(row, text=str(k), bg=CARD, fg=DIM, font=(UI_FONT, 9))
                cnt.pack(side="left")
                arrow = tk.Label(row, text="view runs →", bg=CARD, fg=CARD, font=(UI_FONT, 8))
                arrow.pack(side="right", padx=6)
                parts = (row, nm, cnt, arrow, track)
                for wdg in parts:
                    wdg.bind("<Button-1>", lambda e, n=name: self.show_killer_runs(n))
                    wdg.bind("<Enter>", lambda e, ps=parts, ar=arrow: (
                        [x.configure(bg=CARD_HI) for x in ps], ar.configure(fg=INFO)))
                    wdg.bind("<Leave>", lambda e, ps=parts, ar=arrow: (
                        [x.configure(bg=CARD) for x in ps], ar.configure(fg=CARD)))
            tk.Label(b, text="Click an enemy to see the runs it ended.", bg=CARD, fg=FAINT,
                     font=(UI_FONT, 8)).pack(anchor="w", pady=(6, 0))
            wrap_label(b, "By act: " + "  ·  ".join(f"Act {k}: {v}" for k, v in sorted(a["death_act"].items()))
                       + "      By room: " + "  ·  ".join(f"{k} {v}" for k, v in a["death_room"].most_common()),
                       9, fg=FAINT).pack(fill="x", pady=(8, 0))
        else:
            tk.Label(b, text="Nothing has killed you here yet.", bg=CARD, fg=GOOD).pack(anchor="w")

        # Record
        p, b = self._panel(grid, "Record")
        place(p, 2, 1)
        lines = [(f"{nw} wins  ·  {nl} losses  ·  {len(a['abandoned'])} quit", FG),
                 (f"Win rate {pct(nw, nw + nl):.1f}%", GOOD if pct(nw, nw + nl) >= 25 else WARN),
                 (f"Avg final deck: {a['deck_win']:.1f} in wins  ·  {a['deck_loss']:.1f} in losses", DIM)]
        asc = Counter(r["ascension"] for r in a["wins"])
        if asc:
            lines.append(("Wins by ascension: " + "  ·  ".join(f"A{k} ×{v}" for k, v in sorted(asc.items())), DIM))
        if self.character == ALL and a["chars"]:
            lines.append(("By character: " + "  ·  ".join(
                f"{c} {v[0]}-{v[1]}" for c, v in sorted(a["chars"].items(), key=lambda kv: -sum(kv[1]))), DIM))
        for text, col in lines:
            wrap_label(b, text, 10, fg=col).pack(fill="x", pady=1)

    # -- Card table
    def _render_card_table(self):
        rows, meta, base = self._guide_rows()
        rank = {"TAKE": 0, "OK": 1, "SKIP": 2, "LOW": 3}
        key, desc = self.table_sort
        getters = {
            "card": lambda x: x["card"], "verdict": lambda x: rank[x["verdict"]],
            "offered": lambda x: x["offered"], "pick": lambda x: x["pick_pct"],
            "wrp": lambda x: x["wr_p"] if x["wr_p"] is not None else -1,
            "wrs": lambda x: x["wr_s"] if x["wr_s"] is not None else -1,
            "lift": lambda x: x["delta"] if x["delta"] is not None else -999,
            "deck": lambda x: x["deck"] or 0, "tempo": lambda x: x["tempo"] if x["tempo"] is not None else 99,
            "removed": lambda x: x["removed"], "flags": lambda x: len(x["notes"]),
            "score": lambda x: (x["score"] if x["score"] is not None and x["verdict"] != "LOW" else -999),
        }
        rows = [x for x in rows if x["offered"] >= 3]
        rows.sort(key=getters[key], reverse=desc)
        self.card_tree.delete(*self.card_tree.get_children())
        label = {"TAKE": "✔ Take", "SKIP": "✖ Skip", "OK": "Either", "LOW": "few picks"}
        for x in rows:
            self.card_tree.insert("", "end", iid=x["card"], tags=(x["verdict"],), values=(
                x["card"], label[x["verdict"]], x["offered"], f"{x['pick_pct']:.0f}%",
                "-" if x["wr_p"] is None else f"{x['wr_p']:.0f}% ({x['np']})",
                "-" if x["wr_s"] is None else f"{x['wr_s']:.0f}% ({x['ns']})",
                "-" if x["delta"] is None else f"{x['delta']:+.0f}",
                "-" if x["deck"] is None else f"{x['deck']:.1f}",
                "-" if x["tempo"] is None else f"{x['tempo']:+.2f}",
                x["removed"], ", ".join(t for t, _ in x["notes"])))
        if self.detail_card and self.card_tree.exists(self.detail_card):
            self.card_tree.selection_set(self.detail_card)
            self.card_tree.see(self.detail_card)
        self._render_card_detail()

    def _on_card_select(self, _e=None):
        sel = self.card_tree.selection()
        if sel and sel[0] != self.detail_card:
            self.detail_card = sel[0]
            self._render_card_detail()

    def _wr_row(self, parent, label, value, n, color, note=""):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, bg=CARD, fg=DIM, font=(UI_FONT, 9), width=15, anchor="w").pack(side="left")
        track = tk.Frame(row, bg=BORDER, width=90, height=8)
        track.pack(side="left", padx=(2, 10))
        track.pack_propagate(False)
        if value is not None:
            tk.Frame(track, bg=color, width=max(3, int(90 * value / 100)), height=8).place(x=0, y=0)
        txt = "no runs" if value is None else f"{value:.0f}%  ({n})"
        tk.Label(row, text=txt, bg=CARD, fg=FG if value is not None else FAINT, font=(UI_FONT, 9)).pack(side="left")
        if note:
            tk.Label(row, text=note, bg=CARD, fg=FAINT, font=(UI_FONT, 8)).pack(side="left", padx=6)

    def _render_card_detail(self):
        sf = self.detail_sf
        sf.clear()
        b = tk.Frame(sf.inner, bg=CARD, padx=18, pady=16)
        b.pack(fill="both", expand=True)
        if self.character == ALL:
            tk.Label(b, text="Card detail", bg=CARD, fg=FG, font=(UI_FONT_SEMI, 13)).pack(anchor="w")
            wrap_label(b, "Pick a single character in the sidebar, then click a card to see its synergy "
                          "breakdown (cards behave very differently across characters).", 10, fg=DIM).pack(fill="x", pady=(6, 0))
            return
        card = self.detail_card
        if not card:
            tk.Label(b, text="Card detail", bg=CARD, fg=FG, font=(UI_FONT_SEMI, 13)).pack(anchor="w")
            wrap_label(b, "Click any card in the table to see whether it wins on its own, needs partners, "
                          "or only works in a lean deck.", 10, fg=DIM).pack(fill="x", pady=(6, 0))
            return
        inc = self.include_abandoned.get()
        d = card_detail(self.runs, inc, card)
        ov, n_ov = d["overall"]
        tk.Label(b, text=card, bg=CARD, fg=FG, font=disp(17)).pack(anchor="w")
        if ov is None:
            wrap_label(b, "This card never made it into a finished deck with the current filters "
                          "(it may have been removed, or only appears in quit runs).", 10, fg=DIM).pack(fill="x", pady=(6, 0))
            return
        wrap_label(b, f"In {n_ov} finished deck{'s' if n_ov != 1 else ''} · win rate {ov:.0f}%  "
                      f"(all biomes, current filters)", 10, fg=DIM).pack(fill="x", pady=(2, 10))

        def section(title, sub):
            tk.Frame(b, bg=BORDER, height=1).pack(fill="x", pady=(10, 8))
            tk.Label(b, text=title, bg=CARD, fg=ACCENT, font=(UI_FONT_SEMI, 9)).pack(anchor="w")
            wrap_label(b, sub, 8, fg=FAINT).pack(fill="x", pady=(0, 4))

        # 1. Deck size
        section("WIN RATE BY DECK SIZE", f"Deck size at the end of Act 2, in the {d['late_n']} runs with this card "
                                         f"that reached Act 3 - same checkpoint for every run, so early deaths "
                                         f"don't skew it.")
        lean, n_l = d["lean"]
        mid, n_m = d["mid"]
        blo, n_b = d["bloated"]
        self._wr_row(b, f"Lean (≤{LEAN_DECK})", lean, n_l, GOOD)
        self._wr_row(b, f"Middle ({LEAN_DECK + 1}-{BLOAT_DECK - 1})", mid, n_m, INFO)
        self._wr_row(b, f"Bloated ({BLOAT_DECK}+)", blo, n_b, BAD)
        if lean is not None and blo is not None and n_l >= 2 and n_b >= 2:
            diff = lean - blo
            if diff >= 15:
                msg, col = (f"Works much better when you stay disciplined: +{diff:.0f} pts in lean decks. "
                            f"Skip more cards after taking it."), GOOD
            elif diff <= -15:
                msg, col = (f"Wins more in big decks ({-diff:.0f} pts) - likely needs support cards or "
                            f"a long game to come online."), INFO
            else:
                msg, col = "Deck size doesn't change much for this card.", DIM
            wrap_label(b, msg, 9, fg=col).pack(fill="x", pady=(4, 0))
        elif d["deck_avg_win"] is not None and d["deck_avg_loss"] is not None:
            wrap_label(b, f"Avg deck at end of Act 2: {d['deck_avg_win']:.1f} in wins vs {d['deck_avg_loss']:.1f} in losses.",
                       9, fg=DIM).pack(fill="x", pady=(4, 0))

        # 2. Partners
        section("BEST & WORST CO-PICKED PARTNERS",
                f"Cards also in the deck in {MIN_PARTNER_RUNS}+ runs, vs this card's {ov:.0f}% baseline.")
        if not d["partner_pool"]:
            wrap_label(b, f"No partner appears in {MIN_PARTNER_RUNS}+ decks with this card yet.", 9,
                       fg=FAINT).pack(fill="x")
        for title, items, col in (("Synergy enablers", d["best"], GOOD), ("Anti-synergy / clutter", d["worst"], BAD)):
            tk.Label(b, text=title, bg=CARD, fg=col, font=(UI_FONT_SEMI, 9)).pack(anchor="w", pady=(6, 2))
            if not items:
                tk.Label(b, text="none found", bg=CARD, fg=FAINT, font=(UI_FONT, 9)).pack(anchor="w")
            for x in items:
                row = tk.Frame(b, bg=CARD_HI, padx=10, pady=5)
                row.pack(fill="x", pady=2)
                top = tk.Frame(row, bg=CARD_HI)
                top.pack(fill="x")
                tk.Label(top, text=x["card"], bg=CARD_HI, fg=FG, font=(UI_FONT_SEMI, 10)).pack(side="left")
                tk.Label(top, text=f"{x['delta']:+.0f}", bg=CARD_HI, fg=col, font=(UI_FONT_SEMI, 11)).pack(side="right")
                wo = "" if x["wr_without"] is None else f"  ·  {x['wr_without']:.0f}% without it"
                tk.Label(row, text=f"{x['wr']:.0f}% win together ({x['n']} runs){wo}", bg=CARD_HI, fg=DIM,
                         font=(UI_FONT, 8)).pack(anchor="w")

        # 3. Act drafted
        section("ACT DRAFTED", "Win rate by the act you first took it from a card reward - runs that reached "
                               "Act 3 only, so Act 1 picks aren't punished for early deaths.")
        a1, n1 = d["act1"]
        a23, n23 = d["act23"]
        self._wr_row(b, "Drafted in Act 1", a1, n1, INFO)
        self._wr_row(b, "Drafted in Act 2/3", a23, n23, ACCENT)
        if a1 is not None and a23 is not None and n1 >= 2 and n23 >= 2 and abs(a1 - a23) >= 15:
            if a23 > a1:
                msg = (f"Better as a later pick (+{a23 - a1:.0f} pts in Act 2/3) - in Act 1 prefer frontloaded "
                       f"damage and take this once the deck can survive.")
            else:
                msg = f"Better as an early pick (+{a1 - a23:.0f} pts in Act 1) - it helps most while the deck is weak."
            wrap_label(b, msg, 9, fg=GOOD).pack(fill="x", pady=(4, 0))

        wrap_label(b, "Small samples: runs that last longer collect more cards, so treat these as hints.",
                   8, fg=FAINT).pack(fill="x", pady=(14, 0))

    def _sort_table(self, key):
        cur, desc = self.table_sort
        self.table_sort = (key, not desc if cur == key else key not in ("card", "verdict", "tempo"))
        self._render_card_table()

    # ----- Autopsy view --------------------------------------------------
    def show_killer_runs(self, killer):
        """Jump to Run Autopsy showing only the losses this encounter caused."""
        self.killer_filter = killer
        self.selected_file = None
        self.set_view("Run Autopsy")
        self._render_list()

    def clear_killer_filter(self):
        self.killer_filter = None
        self.selected_file = None
        self._render_list()

    def _list_runs(self):
        if not self.killer_filter:
            return self.runs
        inc = self.include_abandoned.get()
        return [r for r in self.runs if is_loss(r, inc) and r["killer"] == self.killer_filter]

    def _render_killer_bar(self, n):
        for c in self.killer_bar.winfo_children():
            c.destroy()
        if not self.killer_filter:
            self.killer_bar.pack_forget()
            return
        if not self.killer_bar.winfo_ismapped():
            self.killer_bar.pack(fill="x", pady=(0, 10), before=self.killer_bar.master.winfo_children()[1])
        chip = tk.Frame(self.killer_bar, bg=DANGER_BG, padx=12, pady=6)
        chip.pack(side="left")
        tk.Label(chip, text="☠", bg=DANGER_BG, fg=BAD, font=(UI_FONT, 11)).pack(side="left")
        tk.Label(chip, text=f"  Runs ended by {self.killer_filter}", bg=DANGER_BG, fg=FG,
                 font=(UI_FONT_SEMI, 10)).pack(side="left")
        tk.Label(chip, text=f"   {n} run{'s' if n != 1 else ''}", bg=DANGER_BG, fg=DIM,
                 font=(UI_FONT, 9)).pack(side="left")
        x = tk.Label(chip, text="   ✕ clear", bg=DANGER_BG, fg=INFO, font=(UI_FONT_SEMI, 9), cursor="hand2")
        x.pack(side="left")
        x.bind("<Button-1>", lambda e: self.clear_killer_filter())

    def _render_list(self):
        keep = self.selected_file
        cols = ("date", "char", "asc", "result", "floor", "killer")
        self.tree.configure(displaycolumns=cols if self.character == ALL
                            else tuple(c for c in cols if c != "char"))
        self.tree.delete(*self.tree.get_children())
        shown = self._list_runs()
        self._render_killer_bar(len(shown))
        for r in shown:
            date = datetime.fromtimestamp(r["start"]).strftime("%d %b %H:%M") if r["start"] else "?"
            char = r["character"] + (" (co-op)" if r["multiplayer"] else "")
            res = {"WIN": "✔ Win", "LOSS": "✖ Loss", "ABANDONED": "– Quit"}[r["result"]]
            self.tree.insert("", "end", iid=r["file"], tags=(r["result"],),
                             values=(date, char, r["ascension"], res, r["final_floor"],
                                     "" if r["win"] else r["killer"]))
        target = keep if keep and self.tree.exists(keep) else (shown[0]["file"] if shown else None)
        if target:
            self.tree.selection_set(target)
            self.tree.see(target)
            self.selected_file = target
            self._render_autopsy(next((r for r in shown if r["file"] == target), None))
        else:
            self._render_autopsy(None)

    def _on_select(self, _evt=None):
        sel = self.tree.selection()
        if not sel or sel[0] == self.selected_file and _evt is None:
            return
        self.selected_file = sel[0]
        self._render_autopsy(next((r for r in self.runs if r["file"] == sel[0]), None))

    def _render_autopsy(self, r):
        t = self.autopsy_txt
        t.configure(state="normal")
        t.delete("1.0", "end")
        w = lambda s, *tags: t.insert("end", s, tags)
        if not r:
            w("Select a run on the left.\n", "dim")
            t.configure(state="disabled")
            return

        res_tag = {"WIN": "good", "LOSS": "bad"}.get(r["result"], "dim")
        date = datetime.fromtimestamp(r["start"]).strftime("%a %d %b %Y, %H:%M") if r["start"] else "?"
        w(f"{r['character']}  ", "h1"); w({"WIN": "Victory", "LOSS": "Defeat", "ABANDONED": "Abandoned"}[r["result"]] + "\n", "h1", res_tag)
        w(f"{date}  ·  A{r['ascension']}  ·  {r['mode']}  ·  {r['run_time'] // 60}m {r['run_time'] % 60:02d}s  ·  "
          f"floor {r['final_floor']}  ·  {r['deck_size']} cards  ·  {r['relic_count']} relics\n", "dim", "ui")

        w("Coach's callouts\n", "h2")
        icon = {"bad": "✖", "warn": "▲", "info": "•", "good": "✔"}
        for sev, text in autopsy_callouts(r):
            w(f"{icon.get(sev, '•')}   ", sev, "callout"); w(text + "\n", "callout")

        w("\nFloor by floor\n", "h2")
        w(f"{'#':>3}  {'Room / Enemy':<26}{'Turns':>5}  {'HP ±':<9}{'HP':>7}  {'Gold':>5} {'(±)':<8}\n", "faint")
        cur_act = None
        for f in r["floors"]:
            if f["act"] != cur_act:
                cur_act = f["act"]
                w(f" Act {f['act']} · {pretty_act(f['act_id'])}\n", "actbar")
            rt = f["room_type"]
            row_tag = {"elite": "elite", "boss": "boss"}.get(rt, "combat" if f["is_combat"] else "")
            w(f"{f['floor']:>3}  ", "floorhead")
            w(f"{f['label'][:25]:<26}", row_tag)
            slow = f["is_combat"] and rt == "monster" and f["turns"] >= SLOW_FIGHT_TURNS
            w(f"{(str(f['turns']) if f['is_combat'] else '-'):>5}", "bad" if slow else "")
            hpc = " ".join(x for x in (f"-{f['damage']}" if f["damage"] else "",
                                       f"+{f['healed']}" if f["healed"] else "") if x) or "0"
            big = f["max_hp"] and f["damage"] >= BIG_HIT_FRACTION * f["max_hp"]
            w(f"  {hpc:<9}", "bad" if big else "warn" if f["damage"] else "good" if f["healed"] else "faint")
            hp = f"{f['hp']}/{f['max_hp']}" if f["hp"] is not None else "?"
            w(f"{hp:>7}", "bad" if f["hp"] == 0 else "")
            gd = " ".join(x for x in (f"+{f['gold_gained']}" if f["gold_gained"] else "",
                                      f"-{f['gold_spent']}" if f["gold_spent"] else "",
                                      f"-{f['gold_lost']}!" if f["gold_lost"] else "") if x)
            w(f"  {f['gold'] if f['gold'] is not None else '?':>5} ")
            w(f"{gd:<8}\n", "faint")

            pad = "       "
            if f["card_choices"] and f["map_type"] == "shop":
                gained = set(f["cards_other"]) | set(f["bought_cards"])
                w(pad + "Shop:  ", "faint", "detail")
                for i, (name, picked) in enumerate(f["card_choices"]):
                    if i:
                        w("  ")
                    bought = picked or name in gained
                    w(("$ " if bought else "") + name, "picked" if bought else "faint", "detail")
                w("\n")
            elif f["card_choices"]:
                w(pad + "Cards: ", "faint", "detail")
                for i, (name, picked) in enumerate(f["card_choices"]):
                    if i:
                        w("  ")
                    w(("✔ " if picked else "") + name, "picked" if picked else "skipped", "detail")
                if not any(p for _, p in f["card_choices"]):
                    w("   (skipped)", "warn")
                w("\n")
            extras = []
            if f["cards_other"]:
                extras.append((("Bought: " if f["map_type"] == "shop" else "+ Cards: ")
                               + ", ".join(f["cards_other"]), "info"))
            if f["bought_cards"]:
                extras.append(("Bought: " + ", ".join(f["bought_cards"]), "info"))
            if f["relics"]:
                extras.append(("Relic: " + ", ".join(f["relics"]), "good"))
            if f["potions_picked"]:
                extras.append(("Potion +: " + ", ".join(f["potions_picked"]), "info"))
            if f["potions_used"]:
                extras.append(("Potion used: " + ", ".join(f["potions_used"]), "good"))
            if f["potions_discarded"]:
                extras.append(("Discarded: " + ", ".join(f["potions_discarded"]), "warn"))
            if f["events"]:
                extras.append(("Event: " + "; ".join(f["events"]), "dim"))
            if f["rest"]:
                low = "Smith" in f["rest"] and f["hp"] and f["max_hp"] and f["hp"] / f["max_hp"] < 0.5
                extras.append(("Campfire: " + ", ".join(f["rest"]) + ("  ← upgraded while low" if low else ""),
                               "warn" if low else "dim"))
            if f["upgraded"]:
                extras.append(("Upgraded: " + ", ".join(f["upgraded"]), "faint"))
            if f["removed"]:
                extras.append(("Removed: " + ", ".join(f["removed"]), "good"))
            if f["max_hp_delta"]:
                extras.append((f"Max HP {f['max_hp_delta']:+d}", "good" if f["max_hp_delta"] > 0 else "bad"))
            for text, tag in extras:
                w(pad + text + "\n", tag, "detail")

        if not r["win"] and r["floors"]:
            w("\n")
            w(f"  ☠  Run ended on floor {r['final_floor']}"
              + (f" to {r['killer']}" if r["killer"] else "")
              + f" with {r['final_gold']} gold"
              + (f" and {', '.join(r['unused_potions'])} unused" if r["unused_potions"] else "")
              + ".\n", "bad")
        t.configure(state="disabled")


# --------------------------------------------------------------------------
# Embedded fonts: Host Grotesk (c) 2023 The Host Grotesk Project Authors
# (https://github.com/Element-Type/HostGrotesk), SIL Open Font License 1.1
# (https://openfontlicense.org). Static 400/600/800 instances, subset to Latin,
# renamed "STS2 Host Grotesk*" so they never clash with an installed copy.
# --------------------------------------------------------------------------
FONT_DATA = {
    'STS2 Host Grotesk': (
        'AAEAAAAQAQAABAAAR0RFRgLQAsUAACxoAAAAfEdQT1Ps6uCDAAAs5AAAHpZHU1VCiPOV7gAAS3wAAAD+T1MvMmdMAngAAAGIAAAA'
        'YFNUQVTne8soAABMfAAAAEhjbWFwtaK0YwAAA9wAAAEuZ2FzcAAAABAAACxgAAAACGdseWZ5pq3+AAAGEAAAIaRoZWFkKS1cowAA'
        'AQwAAAA2aGhlYQcbBrQAAAFEAAAAJGhtdHgJdBbTAAAB6AAAAfRsb2NhI2Iq7AAABRQAAAD8bWF4cACJAJoAAAFoAAAAIG5hbWXk'
        'LGSsAAAntAAABIxwb3N0/58AMgAALEAAAAAgcHJlcGgGjIUAAAUMAAAABwABAAAAAQDFZA1PjV8PPPUAAwPoAAAAAN/XrBoAAAAA'
        '5x1sAf9a/xgDxwPIAAAABgACAAAAAAAAAAEAAAP3/sUAAAP0/1r/lgPHA+gAAAAAAAAAAAAAAAAAAAB9AAEAAAB9AEwABQBMAAQA'
        'AQAAAAAAAAAAAAAAAAACAAEABAIuAZAABQAAAooCWAAAAEsCigJYAAABXgAyASoAAAILBQQDBAIAAgOAAAADAAAAYgAAAAAAAAAA'
        'TE1OVADAACAiZQP3/sUAAAPRAXQAAAABAAAAAAHwArwAAAAgAAMCgAAeAqIAHwJVAEUCwQAiAq0ARQIbAD0CCwBFAt0AIgKjAEUA'
        '6gBIAZEAGgJ2AEUCCQBFA1cARQKzAEgC+AAiAk0ARQMVACICgABFAl8AIQJLACkCegA3AsYAKAP0AC0CfQAzAoIAKAIeAC4CKwAj'
        'AloAOAIkAB8CWgAfAi0AIAFOABUCbAAgAjkAOQDUADQAz//NAhIAOQDUAD0DgwA+AjkAPAJAACACWgA4AloAHwF9ADwB7wAeAWMA'
        'CwIaADUCKAAkAyYAKwI2ADECTgAqAdEAJwKiAB8DiAAfAxMAIwIrACMDhAAgAjcAHAAA/1oAAP+WAAD/lgImABYCIgAVAooAMAKK'
        'AE4CigBRAooANQKKAB0CigBHAooAOAKKAEwCigBCAooAPwEzAAAA4AAzAN4AJQDgADMA3gAlAjUAMAEUAE0B9AAbAOAANQFfADUB'
        'zgAuAyAAKQHWABoB1gAaAeoAEgKzAFIDVwA9Ap8APgGBAEIBgQAdAYEALAGBADEBgQBbAYEARwG2ADABtgAxAQoAMwEKADQBWwA+'
        'AMgAOQN+AE0CwwAuAOoASAKKADQCigAIAooAMgJOAEQCTgBEAk4AZgJOAEQCTgB6Ak4AbQJOAEQCTgBDAk4ARAJOAEICTgBcA1sA'
        'OAKjAEACowBAAZAAXwAAAAIAAAADAAAAFAADAAEAAAAUAAQBGgAAADAAIAAEABAALwA5AEAAWgBgAHoAfgCjALEAtwDGANgA5gD4'
        'IBQgGSAdICIgJiCsIZAhkiJl//8AAAAgADAAOgBBAFsAYQB7AKMAsQC3AMUA1wDlAPggEyAYIBwgIiAmIKwhkCGSImT//wAAABAA'
        'AP/AAAD/ugAA/8r/xf+b/3AAAP9T/0LgRuBM4EbgMeAp38De697oAAAAAQAwAAAATAAAAFYAAABeAAAAAAAAAAAAXAAAAAAAAAAA'
        'AAAAAAAAAAAAAAAAAEoAAABKAFAAZgBVAGsAeQBpAGcAXABdAFQAbgBMAFgASwBWAE0ATgBzAHEAcgBRAGgAYABXAGEAeABbAHwA'
        'XgBqAF8AdwBwADcAdQB0AAC4Af+FsASNAAAAACcAQgB6AKgAywDhAPUBKAFCAU4BYwF+AY0BrgHEAfYCGQJcAowC1ALlAwYDGgM5'
        'A1cDbgOEA80EAwQxBGcEnwS8BQYFJgU4BVUFcgV+BbEF0QYDBjkGcAaJBs4G7gcOByAHQAdXB3sHkQedB8AH+wgHCGwIpwi0CNkI'
        '/gkmCTIJXgl6CbAJ8goSCkkKkQqjCvELOQs5C0QLWwtnC3MLiQucC9QL6gwGDCgMSQxYDGcMbwx7DIcMkwy0DNUNFw1ZDWoNew2P'
        'DaINrw28Dc8N3A5CDnwOiQ7YDxEPTA9fD2wPhA+XD6oPvg/YD/MQDhA0EEUQnxC0EMkQ0gAFAB4AAAJiArwAAwAGAAkADAAPAABz'
        'ESERJSEDBxMDAREDJxMhHgJE/gUBu9312toB4NAb0/5aArz9RDIBEu0BDgEP/e8CAv8AIAEFAAACAB8AAAKDArwABwALAABzATMB'
        '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'
        'gQF//kz++AAAAQAuAAAB8AK8AAkAAHM1ASE1IRUBIRUuAVb+rwG6/qkBWkcCKE1H/dhNAAACACP/9AIOAfwAJgAzAABXIiYmNTQ2'
        'MzIWFzU0JiMiBgcjPgIzMhYVFRQWFjMzFSMiJicGBicyNjY3JiYjIgYVFBbaPFIpdV8qRBZDOC5DCFoGPVw0amsJFhMHEzE+CxdR'
        'MSw/JAIXQiFEPTcMKUUnUVUMCBZAQSYtNUYib1yVJCIITiAwJzVJLEgoBws1KCMuAAIAOP/0AjsC0AASACIAAEUiJicVIxEzETY2'
        'MzIWFhUUBgYnMjY2NTQmJiMiBgYVFBYWAUU9XBpaWhhYREluPj5uVjFLKytLMTBLKipLDDEsUQLQ/s8kOUR2S0t1Q04uUjY2Ui4u'
        'UjY2Ui4AAAEAH//0Af0B/AAdAABFIiYmNTQ2NjMyFhcjJiYjIgYGFRQWFjMyNjczBgYBGUdxQkJxR1p5EV0KSzIpSSwsSSkySwpd'
        'EHoMQnVNTnRCXU4sMipRPDtSKjEtTF8AAgAf//QCIgLQABIAIgAARSImJjU0NjYzMhYXETMRIzUGBicyNjY1NCYmIyIGBhUUFhYB'
        'FUpuPj5vST1dGVpaGFc4MUoqKkoxMEwqKkwMRHZLS3VDMSwBMf0wUSQ5Ti5SNjZSLi5RNzZSLgAAAQAg//QCAgH8ACUAAEUiJiY1'
        'NDY2MzIWFhUUFAchNSEmJiMiBgYVFRQWFjMyNjczDgIBFkhvPz5wSUlpOQH+YgFGA1M+KkgrLEgpMkQQWQ08WwxBdE5PdUFBaj8K'
        'Fw1CQUolSTYbO1AoLigtSioAAAIAFQAAASMC0AAMABAAAHMRNDY2MzMVIyIGFREDNSEVXhw/NDYmKhujAQ4CRzc7F00ZKv3AAaRM'
        'TAACACD/GAIyAfwAIgAyAABFIiYmJzMWFjMyNjY1NQ4CIyImJjU0NjYzMhYXNTMRFAYGAzI2NjU0JiYjIgYGFRQWFgEwQWxJClkO'
        'Wz0wTC0QNUkwRnJCQnJGQWMaWkN1UjJOLCxOMjFOLS1O6C1VPTI/KVE7RxsxH0R1Skt0QzooVv4uUnU/AS0uUjU2US0tUTY0Uy4A'
        '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'
        'ADsAAHMBMwEDIiYmNTQ2NjMyFhYVFAYGJzI2NTQmIyIGFRQWASImJjU0NjYzMhYWFRQGBicyNjU0JiMiBhUUFrQBlln+azUtSior'
        'Si0uSCsrSS4jMzIjIzQ0Ac0tSiorSS4tSSoqSi0iNDIjIzQzArz9RAF0KU00NEwpKUw0NE0pRDMzMzMzMzMz/jwpTTM1TCkpTDUz'
        'TSlEMzI0MzM0MjMAAAEAQAB0AmMCSAAIAABlJzchNSEnNxcBeTKR/mgBmJEy6nQzk0iTM+oAAAEAQAB0AmMCSAAIAABlJzcXByEV'
        'IRcBKurqMpEBmP5okXTq6jOTSJMA//8AXwItARsC5gQHADsBBQAAAAAAFAD2AAEAAAAAAQAABgAAAAMAAQQJAAAAugAGAAMAAQQJ'
        'AAEAIgDAAAMAAQQJAAIADgDiAAMAAQQJAAMAQADwAAMAAQQJAAQAIgDAAAMAAQQJAAUAGgEwAAMAAQQJAAYALgFKAAMAAQQJAAgA'
        'GAF4AAMAAQQJAAkAIgGQAAMAAQQJAAsALAGyAAMAAQQJAAwAKAHeAAMAAQQJAA0BIgIGAAMAAQQJAA4ANgMoAAMAAQQJABAAIgDA'
        'AAMAAQQJABEADgDiAAMAAQQJABkAFgNeAAMAAQQJAQAADAN0AAMAAQQJARYADAOAAAMAAQQJARcACgOMV2VpZ2h0AEMAbwBwAHkA'
        'cgBpAGcAaAB0ACAAMgAwADIAMwAgAFQAaABlACAASABvAHMAdAAgAEcAcgBvAHQAZQBzAGsAIABQAHIAbwBqAGUAYwB0ACAAQQB1'
        'AHQAaABvAHIAcwAgACgAaAB0AHQAcABzADoALwAvAGcAaQB0AGgAdQBiAC4AYwBvAG0ALwBFAGwAZQBtAGUAbgB0AC0AVAB5AHAA'
        'ZQAvAEgAbwBzAHQARwByAG8AdABlAHMAawApAFMAVABTADIAIABIAG8AcwB0ACAARwByAG8AdABlAHMAawBSAGUAZwB1AGwAYQBy'
        'AFMAVABTADIASABvAHMAdABHAHIAbwB0AGUAcwBrAC0AUgBlAGcAdQBsAGEAcgA7AG0AbwBkAGkAZgBpAGUAZABWAGUAcgBzAGkA'
        'bwBuACAAMQAuADAAMAAzAFMAVABTADIASABvAHMAdABHAHIAbwB0AGUAcwBrAC0AUgBlAGcAdQBsAGEAcgBFAGwAZQBtAGUAbgB0'
        'ACAAVAB5AHAAZQBEAG8BHwB1AGsAYQBuACAASwBhAHIAYQBwATEAbgBhAHIAaAB0AHQAcABzADoALwAvAGUAbABlAG0AZQBuAHQA'
        'dAB5AHAAZQAuAGMAbwBoAHQAdABwAHMAOgAvAC8AZABvAHUAZwBoAGsAYQBuAC4AYwBvAG0AVABoAGkAcwAgAEYAbwBuAHQAIABT'
        'AG8AZgB0AHcAYQByAGUAIABpAHMAIABsAGkAYwBlAG4AcwBlAGQAIAB1AG4AZABlAHIAIAB0AGgAZQAgAFMASQBMACAATwBwAGUA'
        'bgAgAEYAbwBuAHQAIABMAGkAYwBlAG4AcwBlACwAIABWAGUAcgBzAGkAbwBuACAAMQAuADEALgAgAFQAaABpAHMAIABsAGkAYwBl'
        'AG4AcwBlACAAaQBzACAAYQB2AGEAaQBsAGEAYgBsAGUAIAB3AGkAdABoACAAYQAgAEYAQQBRACAAYQB0ADoAIABoAHQAdABwAHMA'
        'OgAvAC8AbwBwAGUAbgBmAG8AbgB0AGwAaQBjAGUAbgBzAGUALgBvAHIAZwBoAHQAdABwAHMAOgAvAC8AbwBwAGUAbgBmAG8AbgB0'
        'AGwAaQBjAGUAbgBzAGUALgBvAHIAZwBIAG8AcwB0AEcAcgBvAHQAZQBzAGsAVwBlAGkAZwBoAHQASQB0AGEAbABpAGMAUgBvAG0A'
        'YQBuAAMAAAAAAAD/nAAyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAB//8ADwABAAAADAAAAAAAAAACABIAAQABAAEAAwAFAAEABwAH'
        'AAEACQAMAAEADgAPAAEAEQAVAAEAFwAXAAEAGQAbAAEAHQAfAAEAIQAmAAEAKAApAAEALAAvAAEAMQAxAAEAMwA1AAEANwA5AAEA'
        'PwA/AAIAaQBpAAEAawBrAAEAAQAAAAoAJAA0AAJERkxUAA5sYXRuAA4ABAAAAAD//wABAAAAAWtlcm4ACAAAAAIAAQAAAAIABh0g'
        'AAIACAACAAoREAABAKoABAAAAFAKbADSAQQC2gqeAU4CBALMAkYCbAKeAswCzALaAyQDzgQYBEIEgATKBOwFygYYBsIHEArqCEIH'
        'JgdICwQHWgfICCgH2gfsCCIIKAgoCEIIQgh8CIYItAjuCQQJDgmECbYKFApOCmwKngq0CuoLBAs6DCILXAvOC/gMIgyQDOoNbA2i'
        'DdwORg7gD2oPag9qD3QP7g/8D+4P/A/uD/wQBhCEAAIABgABAAgAAAAKACIACAAkADoAIQBLAFQAOABWAGEAQgBoAGkATgAMABb/'
        '5QAY/+oAMP/gADL/5QA3//sAOv/7AFD/9gBR//QAVP/vAFb/0gBX/9IAW//gABIAFv/SABj/1wAw/+oAMv/qADf/9AA6/+8AS//v'
        'AEz/7wBN//QATv/0AE//7wBQ//QAUf/xAFT/6gBW/7QAV//IAFv/vgBp//YALQAB/7kAA//gAAf/4AAK/74AD//gABH/4AAT/+8A'
        'G//VAB3/yAAe/8gAH//IACD/7wAh/9IAJ//cACj/3AAp/8gAKv/cACv/yAAs/+EALf/XAC7/5QAv/+AAMP/IADH/wwAy/7QAM/+0'
        'ADT/3AA1/7kANv94ADf/4QA4/9UAOf/VADr/zQA+/+8AP//vAEv/5QBM/+UATf/0AE7/9ABP/9sAUP/2AFb/qgBb/4wAaP/qAGn/'
        '7wAQABb/3AAY/9IAMP/0ADL/4QA6/+8AS//gAEz/4ABN//QATv/0AE//4ABQ//QAUf/0AFT/5QBW/74AV//IAFv/qgAJADD/8QAy'
        '//QAOv/xAEv/9ABM//QAT//0AFD/9ABW/+AAW//cAAwAFv/gADD/qgA3//QAOv/0AFH/6gBS/+AAU//gAFT/7wBX/+AAW//0AGj/'
        '8QBp/9sACwAW/4wAMP+cADL/9AA3/+UAUf/SAFL/4ABT/9wAVP+0AFf/qgBo//YAaf/vAAMAMP/xADL/+wA6//sAEgAW/8gAGP/W'
        'ADD/5QAy/9wAN//0ADr/5QBL/9wATP/cAE3/8QBO//EAT//cAFD/6gBR/+AAVP/lAFb/uQBX/74AW/++AGn/8QAqAAH/qgAD//QA'
        'B//0AAr/oAAP//QAEf/0ABP/9AAU/+AAFv/cABf/3AAY/9sAGf/GABr/6gAb/9YAHf/cAB7/3AAf/9wAIf/SACn/3AAr/9wALf/g'
        'AC//9gAw//YAMf/2ADL/8QAz/+oANP/vADX/qgA2/1YAN//0ADj/1gA5/9YAOv/IAEv/lgBM/5YAT/+WAFD/9ABW/3gAV//cAFv/'
        'jABo/90Aaf/lABIAFv/IABj/1gAw/+UAMv/cADf/9AA6/+UASwAOAEz/3ABN//EATv/xAE//3ABQ/+oAUf/gAFT/5QBW/7kAV/++'
        'AFv/vgBp//EACgAW/8gAMP/vADL/7wA6//YAUf/2AFT/9gBW//YAV//cAFv/9gBp//YADwAW/9MAGP/bADD/2wAy/9wAN//0ADr/'
        '7wBL//YATP/2AE//8QBQ//EAVP/0AFb/4ABX/+AAW//cAGn/8QASACr/oQAw/5YAMv+RADf/yAA6/4wAS//IAEz/yABN/+oATv/q'
        'AE//yABR//sAUv/gAFP/3ABU//YAVv+0AFv/yABo/9EAaf/qAAgAMP/0ADL/6gA6//YAS//0AEz/9ABP//QAVv/gAFv/0gA3AAH/'
        'jAAD/8gAB//IAAr/lgAP/8gAEf/IABP/2wAY/+oAG/+bAB3/oAAe/6AAH/+gACD/4AAh/5YAI//gACT/9gAn/8gAKP/IACn/oAAq'
        '/8gAK/+gACz/yAAt/6oALv/gAC//yAAw/8gAMf/IADL/vgAz/7QANP++ADX/jAA2/1oAN/++ADj/mwA5/5sAOv+bAD7/4AA//+AA'
        'S/++AEz/vgBN/+AATv/gAE//vgBQ//QAUf/0AFL/3ABT/9IAVP/0AFb/cgBY/9wAWf/cAFr/3ABb/6oAaP++AGn/1gATACr/yAAw'
        '/9IAMv/IADf/2AA6/7QAS//IAEz/yABN/+AATv/gAE//yABQ//QAUf/qAFL/4ABT/9wAVP/0AFb/lgBb/8gAaP/XAGn/2wAqAAP/'
        'zAAH/8wAD//MABH/zAAT/9sAFv/qABv/4AAd/9cAHv/XAB//1wAg/+8AIf/gACf/9AAo//QAKf/XACr/9AAr/9cALf/lAC7/6wAv'
        '/+AAMP+0ADH/tAAy//QAM/+0ADf/9AA4/+AAOf/gADr/9AA+/+8AP//vAFH/6gBS/9wAU//SAFT/5QBW//YAV//0AFj/3ABZ/9wA'
        'Wv/cAFv/9ABo//QAaf/qABMAKv+0ADD/vgAy/7QAN//DADr/jABL/74ATP++AE3/3ABO/9wAT/++AFD/9ABR/+AAUv/SAFP/uQBU'
        '/+oAVv+MAFv/tABo/6oAaf/IAAUAMP/cADL/6gA3//EAU//qAFv/9AAIADD/5QAy/9sAOv/2AFH/6gBU/9wAVv/gAFf/qgBb/9wA'
        'BAAb//YAM//2ADj/9gA5//YAGwAb/+cAHf/qAB7/6gAf/+oAIf/lACn/6gAr/+oALf/vADD/9AAx//EAMv/0ADP/9AA4/+cAOf/n'
        'ADr/6gBL/9wATP/cAE//3ABQ//QAUf/2AFL/9gBUABQAVv/gAFf/8QBb/8gAaP/2AGn/6gAEAFD/+wBR/+oAV//SAGn/8QAEAEv/'
        '8QBQ//YAV//2AGn/9gANADD/5QA6//YASwAeAEwAHgBNABQATgAUAE8AFABR//EAUv/0AFP/3ABU/+oAV/++AGn/6gABAGn/9gAG'
        'ADD/2wAy//QAUf/qAFT/4ABX/7QAaf/2AA4AMP/bADL/3AA6//sAS//0AEz/9ABP//QAUP/xAFH/3ABU/9IAVv/cAFf/oABb/9wA'
        'aP/2AGn/+wACACQAMgBX/9IACwAw//EAMv/vADr/5QBL/9wATP/cAE//3ABW/6oAV//IAFv/yABo//QAaf/qAA4AMP/WADL/2wBL'
        '//sATP/7AE//+wBQ/+8AUf/bAFP/9gBU/9wAVv/XAFf/lgBb/8gAaP/7AGn/9gAFADL/9ABTAA8AVv/2AFf/3ABo/+cAAgBX/9IA'
        'W//0AB0AG//bAB3/2wAe/9sAH//bACH/1gAkAAUAKf/bACv/2wAt/+AAMv/xADP/6gA0//EAOP/bADn/2wA6/9wAS//XAEz/1wBP'
        '/9cAUP/xAFL/9ABT//QAVv+RAFf/3ABb/9IAXf/gAF//4ABh/+AAaP/vAGn/1gAMADr/4ABL/9wATP/cAE//3ABQ//YAUv/xAFP/'
        '8QBW/6AAV//gAFv/0gBo/+oAaf/gABcAG//lAB3/4QAe/+EAH//hACH/6gAp/+EAK//hAC3/8QAuAAUAMP/xADH/9gA4/+UAOf/l'
        'ADr/9ABS/+oAU//qAFb/9gBX/9wAXf/2AF//9gBh//YAaP/7AGn/5QAOACr/7wAw/+kAOv/WAEv/tABM/7QAT/+0AFD/9gBS/+oA'
        'U//qAFb/eABX/9wAW/+CAGj/2wBp/8gABwAw//YATwAKAFD/9gBX/8gAW//0AGj/+wBp//EADAAW/4wAMP+qADf/9gBR/9IAUv/g'
        'AFP/4ABU/5YAV/+CAFz/9gBe//YAYP/2AGn/6gAFADD/4AAy//EAOv/0AFf/8QBp//EADQAW/+AAGP/qADD/9AAy/+oAN//0ADr/'
        '9ABR//QAVP/0AFb/yABX//QAW//SAGj/9gBp//QABgAw/6oAUf/lAFP/8QBU/9wAV/+WAFv/9AANADD/3AAy/9wAS//2AEz/9gBQ'
        '/+8AUf/IAFL/9gBT//YAVP/SAFb/0gBX/6oAW//IAGn/+wAIADD/6gAy/+oAS//vAEz/7wBP/+8AVv/SAFf/0gBb/+oAHAAD/9wA'
        'B//cAA//3AAR/9wAE//xABT/yAAV//QAFv++ABf/yAAZ/74AG//xAB3/9AAe//QAH//0ACD/4AAkADIAKf/0ACv/9AAt//YALv/q'
        'ADD/1wAx/9wAM//qADQACgA4//EAOf/xAD7/4AA//+AACgAD//EAB//xAA//8QAR//EAFP/qABb/4AAX/+AAGf/cACQAHgAuAAoA'
        'CgAD//EAB//xAA//8QAR//EAFP/qABb/4AAX/+AAGf/cACQAKAAuAAoAGwAD/9wAB//cAA//3AAR/9wAE//xABT/yAAV//QAFv++'
        'ABf/yAAZ/74AG//xAB3/9AAe//QAH//0ACD/4AAkABQAKf/0ACv/9AAt//YALv/qADD/1wAx/9wAM//qADj/8QA5//EAPv/gAD//'
        '4AAWAAP/6gAH/+oAD//qABH/6gAT//sAFv/0ABf/9AAZ//QAG//2AB3/+wAe//sAH//7ACD/9gAp//sAK//7ADD/8QAx//YAM//0'
        'ADj/9gA5//YAPv/2AD//9gAgAAH/uQAD//YAB//2AAr/yAAP//YAEf/2ABP/9gAU//YAFv/0ABf/9AAY/+oAGf/gABr/9gAb/+8A'
        'Hf/qAB7/6gAf/+oAIAAUACH/4AAkABQAKf/qACv/6gAt//QALgAZADX/uQA2/6AAN//qADj/7wA5/+8AOv/0AD4AFAA/ABQADQAB'
        '/+AAFP/gABb/3AAX/+AAGP/cABn/vgAkABQALgAKADD/9AAx//EAMv/qADX/4AA2/9IADgAB/+AAFP/cABb/0gAX/9wAGP/SABn/'
        'uQAa/+oALf/2AC4ACgAw//QAMf/xADL/6gA1/+AANv/IABoAA//lAAf/5QAK/9IAD//lABH/5QAT//QAFP/2ABb/9AAX//QAGP/l'
        'ABn/6gAb/9wAHf/bAB7/2wAf/9sAIf++ACQADwAp/9sAK//bAC3/wwAuABQANv9kADf/4AA4/9wAOf/cADr/4AAmAAH/ggAD/80A'
        'B//NAAr/vgAP/80AEf/NABP/3AAY//YAGv/0ABv/lgAd/6AAHv+gAB//oAAg/+oAIf+MACT/9gAn/9IAKP/SACn/oAAq/9IAK/+g'
        'ACz/3AAt/5EALv/IAC//3AAw/9wAMf/gADL/3AAz/9wANP/IADX/ggA2/24AN//IADj/lgA5/5YAOv+gAD7/6gA//+oAIgAD/80A'
        'B//NAA//zQAR/80AE//SABT/tAAV/+AAFv94ABf/mwAY/+oAGf+CABr/9AAb/9IAHf/cAB7/3AAf/9wAIP/gACH/9AAkAB4AKf/c'
        'ACv/3AAt/+AALv++AC//9AAw/5EAMf+gADL/9gA0//QAN//qADj/0gA5/9IAOv/2AD7/4AA//+AAAgAW/9wAGP/cAB4AA/++AAf/'
        'vgAP/74AEf++ABP/3AAU/8gAFf/SABb/qgAX/8gAGP/0ABn/tAAa//QAG//cAB3/3AAe/9wAH//cACD/3AAkACgAKf/cACv/3AAt'
        '/9IALv/gAC//6gAw/9IAMf/SADf/9AA4/9wAOf/cAD7/3AA//9wAAwAw/+AAMv/2ADr/6gACAAH/9gA1//YAHwAB/+oAA//2AAf/'
        '9gAK//YAD//2ABH/9gAT//YAFP/NABb/xAAX/84AGP/lABn/pgAb//YAHf/2AB7/9gAf//YAIf/2ACn/9gAr//YALf/2AC4ACgAw'
        '/+8AMf/sADL/5QAz/+8ANP/2ADX/6gA2/9wAN//0ADj/9gA5//YAIAAD//EAB//xAA//8QAR//EAE//7ABT/0gAW/8gAF//gABj/'
        '9AAZ/74AGv/vABv/9AAd//EAHv/xAB//8QAh//YAJAAKACf/9gAo//YAKf/xACr/9gAr//EALf/xAC8ACgAw//QAMf/2ADL/6gAz'
        '/+oANv/0ADf/9AA4//QAOf/0AAIJ/gAEAAAKYgs2ACkAHwAAAAAAAP/2AAAAAAAA//YAAAAA/9wAAAAAAAD/4v/bAAAAAAAAAAD/'
        '9AAA/9IAAP/xAAAAAAAAAAAAAAAAAAD/8QAA/+D/1gAAAAD/9gAA/77/3P/x/9EAAP/v/+D/yP/b/+UAAP/7/+oAAAAAAAD/rwAA'
        '/9wAAAAA/80AAP/q//T/9AAAAAAAAP/7AAAAAP/b//YAAAAA//H/4AAAAAD/9AAA//EAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
        'AP/2AAAAAAAAAAAAAAAA/9YAAAAAAAD/9v/gAAAAAAAAAAD/+f/2/9IAAAAAAAAAAAAAAAAAAAAAAAD/7//W/+8AAP/qAAD/8QAA'
        '/4z/pv/0/6oAAP/n/77/qgAA/+oAAP/WAAAAAAAA//QAAAAA/6r/tP+0AAAAAP/2AAD/8f/vAAAAAAAAAAAAAP/qAAAAAAAA//H/'
        '9AAAAAD/8QAAAAD/9gAAAAAAAP/IAAAAAAAAAAAAAAAA//sAAAAAAAAAAAAAAAAAAAAA/8gAAAAAAAAAAP/bAAAAAAAAAAr/7wAA'
        '/9z/9AAAAAAAAP/qAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/9AAAAAAAAAAAAAAA'
        'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP/xAAAAAAAA//sAAAAAAAD/8QAAAAAAAP/0AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
        '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'
        'AAAAABYAAAAWAAAAFgAcAB0AHAAdABsAGwACAAgAAQAIAAEALgAEAAAAEgBQAHYAhACEAIoAmACyALwAxgDcAQoBIAEuAS4BLgEu'
        'ATQBNAACAAUASwBPAAAAUQBUAAUAVgBXAAkAWwBbAAsAYgBnAAwACQBR/+AAVP/gAFf/3ABi/+AAY//2AGT/4ABl//YAZv/gAGf/'
        '4AADAFH/4ABU/+AAV//cAAEAV//qAAMAUf/gAFT/6gBX/+AABgBL/8gATP/SAE//0gBW/6oAV//0AFv/oAACAFb/4ABX/+AAAgBW'
        '/9IAV//SAAUAS//gAE//6gBW/4IAV//0AFv/vgALAEv/3ABM/9wATf/qAE7/6gBP/+AAUf/gAFL/4ABT/9IAVP/0AFb/UABb/1oA'
        'BQBR/+AAUv/gAFP/0gBU/4IAV/9QAAMAUf/gAFT/yABX/1oAAQBL/+oAAQBL//QAAAABAAAACgAmAEAAAkRGTFQADmxhdG4ADgAE'
        'AAAAAP//AAIAAAABAAJjYWx0AA5saWdhABQAAAABAAAAAAABAAIAAwAIAHwAlgAGAAAABAAOACIAOABOAAMAAQBcAAEAeAABAFwA'
        'AQAAAAEAAwACAEIASAABAGQAAQBCAAEAAAABAAMAAQAyAAEATgACACwAMgABAAAAAQADAAIAFgAcAAEAOAABABwAAQAAAAEAAQAB'
        'AEoAAgABAEAASQAAAAEAAAABAAgAAgAKAAIAcABwAAEAAgAYADIABAAIAAEACAABABoAAQAIAAIABgAMAD4AAgAjAD8AAgAmAAEA'
        'AQAgAAAAAQABAAgAAgAAABQAAgAAACQAAndnaHQBAAAAaXRhbAEWAAEABAAUAAMAAAACAAIBkAAAArwAAAADAAEAAgEXAAAAAAAB'
        'AAA='
    ),
    'STS2 Host Grotesk SemiBold': (
        'AAEAAAAQAQAABAAAR0RFRgLQAsUAACy8AAAAfEdQT1Ps6uCDAAAtOAAAHpZHU1VCiPOV7gAAS9AAAAD+T1MvMmdMAngAAAGIAAAA'
        'YFNUQVTlg8wyAABM0AAAAERjbWFwtaK0YwAAA9wAAAEuZ2FzcAAAABAAACy0AAAACGdseWYugtWdAAAGEAAAIZJoZWFkKTNcqAAA'
        'AQwAAAA2aGhlYQchBq4AAAFEAAAAJGhtdHgJdBHmAAAB6AAAAfRsb2NhIe4pcgAABRQAAAD8bWF4cACJAJoAAAFoAAAAIG5hbWWJ'
        'qkjIAAAnpAAABO5wb3N0/58AMgAALJQAAAAgcHJlcGgGjIUAAAUMAAAABwABAAAAAQDFthlAn18PPPUAAwPoAAAAAN/XrBoAAAAA'
        '5x1sAf9R/xgD1gPNAAAABgACAAAAAAAAAAEAAAP3/sUAAAP0/1H/kAPWA+gAAAAAAAAAAAAAAAAAAAB9AAEAAAB9AEwABQBMAAQA'
        'AQAAAAAAAAAAAAAAAAACAAEABAIuAZAABQAAAooCWAAAAEsCigJYAAABXgAyASoAAAILBQQDBAIAAgOAAAADAAAAYgAAAAAAAAAA'
        'TE1OVADAACAiZQP3/sUAAAPRAXQAAAABAAAAAAHwArwAAAAgAAMCgAAeAqIADgJVADgCwQAfAq0AOAIbADUCCwA4At0AHwKjADgA'
        '6gA5AZEAEQJ2ADgCCQA4A1cAOAKzADkC+AAfAk0AOAMVAB8CgAA4Al8AGwJLABwCegArAsYAGQP0AB4CfQAaAoIAGQIeACYCKwAh'
        'AloALQIkABgCWgAYAi0AGQFOAAwCbAAeAjkALADUAC4Az//DAhIALADUAC4DgwAuAjkALQJAABkCWgAtAloAGAF9AC0B7wATAWMA'
        'BgIaACUCKAAVAyYAFwI2ABoCTgAaAdEAHgKiAA4DiAAOAxMAIQIrACEDhAAYAjcAFQAA/1EAAP+QAAD/kAImAA4CIgAMAooAKAKK'
        'AEcCigBLAooALgKKAB8CigA/AooALwKKAD0CigA3AooANgEzAAAA4AAkAN4AFwDgACQA3gAXAjUAIwEUAD0B9AAVAOAAKQFfACoB'
        'zgAsAyAAHAHWAAwB1gAMAeoAEgKzAE0DVwAyAp8AMQGBADEBgQAVAYEAIwGBACgBgQBGAYEAOAG2AB4BtgAeAQoAJQEKACcBWwAr'
        'AMgALwN+ADgCwwApAOoAOQKKADACigAEAooAMgJOAEQCTgBEAk4AXQJOAEQCTgB5Ak4AaAJOAEQCTgBDAk4ARAJOAC0CTgBUA1sA'
        'IgKjADYCowA2AZAAWAAAAAIAAAADAAAAFAADAAEAAAAUAAQBGgAAADAAIAAEABAALwA5AEAAWgBgAHoAfgCjALEAtwDGANgA5gD4'
        'IBQgGSAdICIgJiCsIZAhkiJl//8AAAAgADAAOgBBAFsAYQB7AKMAsQC3AMUA1wDlAPggEyAYIBwgIiAmIKwhkCGSImT//wAAABAA'
        'AP/AAAD/ugAA/8r/xf+b/3AAAP9T/0LgRuBM4EbgMeAp38De697oAAAAAQAwAAAATAAAAFYAAABeAAAAAAAAAAAAXAAAAAAAAAAA'
        'AAAAAAAAAAAAAAAAAEoAAABKAFAAZgBVAGsAeQBpAGcAXABdAFQAbgBMAFgASwBWAE0ATgBzAHEAcgBRAGgAYABXAGEAeABbAHwA'
        'XgBqAF8AdwBwADcAdQB0AAC4Af+FsASNAAAAACcAQgB6AKgAywDhAPUBKAFCAU4BYwF9AYwBqwHBAfMCFgJaAooC0gLjAwQDGAM3'
        'A1UDawOBA8oEAAQuBGQEnAS5BQMFIwU1BVIFbgV6Ba0FzQX/BjUGbAaFBsoG6QcJBxsHOgdRB3UHigeWB7gH8wf/CGQInwisCNEI'
        '9gkeCSoJVglyCagJ6goKCkEKiQqbCukLMQsxCzwLUwtfC2sLgQuUC8wL4gv+DB4MQAxPDF4MZgxyDH4MigyrDMwNDg1QDWENcg2G'
        'DZoNpw20DccN1A46DnQOgQ7QDwgPQw9WD2MPew+OD6EPtQ/PD+oQBRArEDwQlhCrEMAQyQAFAB4AAAJiArwAAwAGAAkADAAPAABz'
        'ESERJSEDBxMDAREDJxMhHgJE/gUBu9312toB4NAb0/5aArz9RDIBEu0BDgEP/e8CAv8AIAEFAAACAA4AAAKUArwABwALAABzATMB'
        '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'
        'FhYVFAYGJzI2NTQmIyIGFRQWASImJjU0NjYzMhYWFRQGBicyNjU0JiMiBhUUFqsBjHX+dFQwTC4uTTAvTSwsTTAfKysfHiwrAeMw'
        'TC4uTS8xTC0uTDEgKyogHiwrArz9RAFoKk82OE8qKk84Nk8qVC8sLy8vLywv/jgqTzc2TyoqTzY3TypULy0uLi4uLS8AAAEANgBo'
        'Am0CVAAIAABlJzchNSEnNxcBdj6F/nkBh4U+92hAiFyIQPYAAAEANgBoAm0CVAAIAABlJzcXByEVIRcBLff3PoUBh/55hWj29kCI'
        'XIgA//8AWAIsAScC7AQHADsBBwAAAAAAAAAWAQ4AAQAAAAABAAAGAAAAAQAAAAABEAAIAAYAAwABBAkAAAC6AA4AAwABBAkAAQA0'
        'AMgAAwABBAkAAgAOAPwAAwABBAkAAwBQAQoAAwABBAkABAA0AMgAAwABBAkABQAaAVoAAwABBAkABgA+AXQAAwABBAkACAAYAbIA'
        'AwABBAkACQAiAcoAAwABBAkACwAsAewAAwABBAkADAAoAhgAAwABBAkADQEiAkAAAwABBAkADgA2A2IAAwABBAkAEAA0AMgAAwAB'
        'BAkAEQAOAPwAAwABBAkAGQAWA5gAAwABBAkBAAAMA64AAwABBAkBEAAQA7oAAwABBAkBFgAMA8oAAwABBAkBFwAKA9ZXZWlnaHRT'
        'ZW1pQm9sZABDAG8AcAB5AHIAaQBnAGgAdAAgADIAMAAyADMAIABUAGgAZQAgAEgAbwBzAHQAIABHAHIAbwB0AGUAcwBrACAAUABy'
        'AG8AagBlAGMAdAAgAEEAdQB0AGgAbwByAHMAIAAoAGgAdAB0AHAAcwA6AC8ALwBnAGkAdABoAHUAYgAuAGMAbwBtAC8ARQBsAGUA'
        'bQBlAG4AdAAtAFQAeQBwAGUALwBIAG8AcwB0AEcAcgBvAHQAZQBzAGsAKQBTAFQAUwAyACAASABvAHMAdAAgAEcAcgBvAHQAZQBz'
        'AGsAIABTAGUAbQBpAEIAbwBsAGQAUgBlAGcAdQBsAGEAcgBTAFQAUwAyAEgAbwBzAHQARwByAG8AdABlAHMAawBTAGUAbQBpAEIA'
        'bwBsAGQALQBSAGUAZwB1AGwAYQByADsAbQBvAGQAaQBmAGkAZQBkAFYAZQByAHMAaQBvAG4AIAAxAC4AMAAwADMAUwBUAFMAMgBI'
        'AG8AcwB0AEcAcgBvAHQAZQBzAGsAUwBlAG0AaQBCAG8AbABkAC0AUgBlAGcAdQBsAGEAcgBFAGwAZQBtAGUAbgB0ACAAVAB5AHAA'
        'ZQBEAG8BHwB1AGsAYQBuACAASwBhAHIAYQBwATEAbgBhAHIAaAB0AHQAcABzADoALwAvAGUAbABlAG0AZQBuAHQAdAB5AHAAZQAu'
        'AGMAbwBoAHQAdABwAHMAOgAvAC8AZABvAHUAZwBoAGsAYQBuAC4AYwBvAG0AVABoAGkAcwAgAEYAbwBuAHQAIABTAG8AZgB0AHcA'
        'YQByAGUAIABpAHMAIABsAGkAYwBlAG4AcwBlAGQAIAB1AG4AZABlAHIAIAB0AGgAZQAgAFMASQBMACAATwBwAGUAbgAgAEYAbwBu'
        'AHQAIABMAGkAYwBlAG4AcwBlACwAIABWAGUAcgBzAGkAbwBuACAAMQAuADEALgAgAFQAaABpAHMAIABsAGkAYwBlAG4AcwBlACAA'
        'aQBzACAAYQB2AGEAaQBsAGEAYgBsAGUAIAB3AGkAdABoACAAYQAgAEYAQQBRACAAYQB0ADoAIABoAHQAdABwAHMAOgAvAC8AbwBw'
        'AGUAbgBmAG8AbgB0AGwAaQBjAGUAbgBzAGUALgBvAHIAZwBoAHQAdABwAHMAOgAvAC8AbwBwAGUAbgBmAG8AbgB0AGwAaQBjAGUA'
        'bgBzAGUALgBvAHIAZwBIAG8AcwB0AEcAcgBvAHQAZQBzAGsAVwBlAGkAZwBoAHQAUwBlAG0AaQBCAG8AbABkAEkAdABhAGwAaQBj'
        'AFIAbwBtAGEAbgAAAAMAAAAAAAD/nAAyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAB//8ADwABAAAADAAAAAAAAAACABIAAQABAAEA'
        'AwAFAAEABwAHAAEACQAMAAEADgAPAAEAEQAVAAEAFwAXAAEAGQAbAAEAHQAfAAEAIQAmAAEAKAApAAEALAAvAAEAMQAxAAEAMwA1'
        'AAEANwA5AAEAPwA/AAIAaQBpAAEAawBrAAEAAQAAAAoAJAA0AAJERkxUAA5sYXRuAA4ABAAAAAD//wABAAAAAWtlcm4ACAAAAAIA'
        'AQAAAAIABh0gAAIACAACAAoREAABAKoABAAAAFAKbADSAQQC2gqeAU4CBALMAkYCbAKeAswCzALaAyQDzgQYBEIEgATKBOwFygYY'
        'BsIHEArqCEIHJgdICwQHWgfICCgH2gfsCCIIKAgoCEIIQgh8CIYItAjuCQQJDgmECbYKFApOCmwKngq0CuoLBAs6DCILXAvOC/gM'
        'IgyQDOoNbA2iDdwORg7gD2oPag9qD3QP7g/8D+4P/A/uD/wQBhCEAAIABgABAAgAAAAKACIACAAkADoAIQBLAFQAOABWAGEAQgBo'
        'AGkATgAMABb/5QAY/+oAMP/gADL/5QA3//sAOv/7AFD/9gBR//QAVP/vAFb/0gBX/9IAW//gABIAFv/SABj/1wAw/+oAMv/qADf/'
        '9AA6/+8AS//vAEz/7wBN//QATv/0AE//7wBQ//QAUf/xAFT/6gBW/7QAV//IAFv/vgBp//YALQAB/7kAA//gAAf/4AAK/74AD//g'
        'ABH/4AAT/+8AG//VAB3/yAAe/8gAH//IACD/7wAh/9IAJ//cACj/3AAp/8gAKv/cACv/yAAs/+EALf/XAC7/5QAv/+AAMP/IADH/'
        'wwAy/7QAM/+0ADT/3AA1/7kANv94ADf/4QA4/9UAOf/VADr/zQA+/+8AP//vAEv/5QBM/+UATf/0AE7/9ABP/9sAUP/2AFb/qgBb'
        '/4wAaP/qAGn/7wAQABb/3AAY/9IAMP/0ADL/4QA6/+8AS//gAEz/4ABN//QATv/0AE//4ABQ//QAUf/0AFT/5QBW/74AV//IAFv/'
        'qgAJADD/8QAy//QAOv/xAEv/9ABM//QAT//0AFD/9ABW/+AAW//cAAwAFv/gADD/qgA3//QAOv/0AFH/6gBS/+AAU//gAFT/7wBX'
        '/+AAW//0AGj/8QBp/9sACwAW/4wAMP+cADL/9AA3/+UAUf/SAFL/4ABT/9wAVP+0AFf/qgBo//YAaf/vAAMAMP/xADL/+wA6//sA'
        'EgAW/8gAGP/WADD/5QAy/9wAN//0ADr/5QBL/9wATP/cAE3/8QBO//EAT//cAFD/6gBR/+AAVP/lAFb/uQBX/74AW/++AGn/8QAq'
        'AAH/qgAD//QAB//0AAr/oAAP//QAEf/0ABP/9AAU/+AAFv/cABf/3AAY/9sAGf/GABr/6gAb/9YAHf/cAB7/3AAf/9wAIf/SACn/'
        '3AAr/9wALf/gAC//9gAw//YAMf/2ADL/8QAz/+oANP/vADX/qgA2/1YAN//0ADj/1gA5/9YAOv/IAEv/lgBM/5YAT/+WAFD/9ABW'
        '/3gAV//cAFv/jABo/90Aaf/lABIAFv/IABj/1gAw/+UAMv/cADf/9AA6/+UASwAOAEz/3ABN//EATv/xAE//3ABQ/+oAUf/gAFT/'
        '5QBW/7kAV/++AFv/vgBp//EACgAW/8gAMP/vADL/7wA6//YAUf/2AFT/9gBW//YAV//cAFv/9gBp//YADwAW/9MAGP/bADD/2wAy'
        '/9wAN//0ADr/7wBL//YATP/2AE//8QBQ//EAVP/0AFb/4ABX/+AAW//cAGn/8QASACr/oQAw/5YAMv+RADf/yAA6/4wAS//IAEz/'
        'yABN/+oATv/qAE//yABR//sAUv/gAFP/3ABU//YAVv+0AFv/yABo/9EAaf/qAAgAMP/0ADL/6gA6//YAS//0AEz/9ABP//QAVv/g'
        'AFv/0gA3AAH/jAAD/8gAB//IAAr/lgAP/8gAEf/IABP/2wAY/+oAG/+bAB3/oAAe/6AAH/+gACD/4AAh/5YAI//gACT/9gAn/8gA'
        'KP/IACn/oAAq/8gAK/+gACz/yAAt/6oALv/gAC//yAAw/8gAMf/IADL/vgAz/7QANP++ADX/jAA2/1oAN/++ADj/mwA5/5sAOv+b'
        'AD7/4AA//+AAS/++AEz/vgBN/+AATv/gAE//vgBQ//QAUf/0AFL/3ABT/9IAVP/0AFb/cgBY/9wAWf/cAFr/3ABb/6oAaP++AGn/'
        '1gATACr/yAAw/9IAMv/IADf/2AA6/7QAS//IAEz/yABN/+AATv/gAE//yABQ//QAUf/qAFL/4ABT/9wAVP/0AFb/lgBb/8gAaP/X'
        'AGn/2wAqAAP/zAAH/8wAD//MABH/zAAT/9sAFv/qABv/4AAd/9cAHv/XAB//1wAg/+8AIf/gACf/9AAo//QAKf/XACr/9AAr/9cA'
        'Lf/lAC7/6wAv/+AAMP+0ADH/tAAy//QAM/+0ADf/9AA4/+AAOf/gADr/9AA+/+8AP//vAFH/6gBS/9wAU//SAFT/5QBW//YAV//0'
        'AFj/3ABZ/9wAWv/cAFv/9ABo//QAaf/qABMAKv+0ADD/vgAy/7QAN//DADr/jABL/74ATP++AE3/3ABO/9wAT/++AFD/9ABR/+AA'
        'Uv/SAFP/uQBU/+oAVv+MAFv/tABo/6oAaf/IAAUAMP/cADL/6gA3//EAU//qAFv/9AAIADD/5QAy/9sAOv/2AFH/6gBU/9wAVv/g'
        'AFf/qgBb/9wABAAb//YAM//2ADj/9gA5//YAGwAb/+cAHf/qAB7/6gAf/+oAIf/lACn/6gAr/+oALf/vADD/9AAx//EAMv/0ADP/'
        '9AA4/+cAOf/nADr/6gBL/9wATP/cAE//3ABQ//QAUf/2AFL/9gBUABQAVv/gAFf/8QBb/8gAaP/2AGn/6gAEAFD/+wBR/+oAV//S'
        'AGn/8QAEAEv/8QBQ//YAV//2AGn/9gANADD/5QA6//YASwAeAEwAHgBNABQATgAUAE8AFABR//EAUv/0AFP/3ABU/+oAV/++AGn/'
        '6gABAGn/9gAGADD/2wAy//QAUf/qAFT/4ABX/7QAaf/2AA4AMP/bADL/3AA6//sAS//0AEz/9ABP//QAUP/xAFH/3ABU/9IAVv/c'
        'AFf/oABb/9wAaP/2AGn/+wACACQAMgBX/9IACwAw//EAMv/vADr/5QBL/9wATP/cAE//3ABW/6oAV//IAFv/yABo//QAaf/qAA4A'
        'MP/WADL/2wBL//sATP/7AE//+wBQ/+8AUf/bAFP/9gBU/9wAVv/XAFf/lgBb/8gAaP/7AGn/9gAFADL/9ABTAA8AVv/2AFf/3ABo'
        '/+cAAgBX/9IAW//0AB0AG//bAB3/2wAe/9sAH//bACH/1gAkAAUAKf/bACv/2wAt/+AAMv/xADP/6gA0//EAOP/bADn/2wA6/9wA'
        'S//XAEz/1wBP/9cAUP/xAFL/9ABT//QAVv+RAFf/3ABb/9IAXf/gAF//4ABh/+AAaP/vAGn/1gAMADr/4ABL/9wATP/cAE//3ABQ'
        '//YAUv/xAFP/8QBW/6AAV//gAFv/0gBo/+oAaf/gABcAG//lAB3/4QAe/+EAH//hACH/6gAp/+EAK//hAC3/8QAuAAUAMP/xADH/'
        '9gA4/+UAOf/lADr/9ABS/+oAU//qAFb/9gBX/9wAXf/2AF//9gBh//YAaP/7AGn/5QAOACr/7wAw/+kAOv/WAEv/tABM/7QAT/+0'
        'AFD/9gBS/+oAU//qAFb/eABX/9wAW/+CAGj/2wBp/8gABwAw//YATwAKAFD/9gBX/8gAW//0AGj/+wBp//EADAAW/4wAMP+qADf/'
        '9gBR/9IAUv/gAFP/4ABU/5YAV/+CAFz/9gBe//YAYP/2AGn/6gAFADD/4AAy//EAOv/0AFf/8QBp//EADQAW/+AAGP/qADD/9AAy'
        '/+oAN//0ADr/9ABR//QAVP/0AFb/yABX//QAW//SAGj/9gBp//QABgAw/6oAUf/lAFP/8QBU/9wAV/+WAFv/9AANADD/3AAy/9wA'
        'S//2AEz/9gBQ/+8AUf/IAFL/9gBT//YAVP/SAFb/0gBX/6oAW//IAGn/+wAIADD/6gAy/+oAS//vAEz/7wBP/+8AVv/SAFf/0gBb'
        '/+oAHAAD/9wAB//cAA//3AAR/9wAE//xABT/yAAV//QAFv++ABf/yAAZ/74AG//xAB3/9AAe//QAH//0ACD/4AAkADIAKf/0ACv/'
        '9AAt//YALv/qADD/1wAx/9wAM//qADQACgA4//EAOf/xAD7/4AA//+AACgAD//EAB//xAA//8QAR//EAFP/qABb/4AAX/+AAGf/c'
        'ACQAHgAuAAoACgAD//EAB//xAA//8QAR//EAFP/qABb/4AAX/+AAGf/cACQAKAAuAAoAGwAD/9wAB//cAA//3AAR/9wAE//xABT/'
        'yAAV//QAFv++ABf/yAAZ/74AG//xAB3/9AAe//QAH//0ACD/4AAkABQAKf/0ACv/9AAt//YALv/qADD/1wAx/9wAM//qADj/8QA5'
        '//EAPv/gAD//4AAWAAP/6gAH/+oAD//qABH/6gAT//sAFv/0ABf/9AAZ//QAG//2AB3/+wAe//sAH//7ACD/9gAp//sAK//7ADD/'
        '8QAx//YAM//0ADj/9gA5//YAPv/2AD//9gAgAAH/uQAD//YAB//2AAr/yAAP//YAEf/2ABP/9gAU//YAFv/0ABf/9AAY/+oAGf/g'
        'ABr/9gAb/+8AHf/qAB7/6gAf/+oAIAAUACH/4AAkABQAKf/qACv/6gAt//QALgAZADX/uQA2/6AAN//qADj/7wA5/+8AOv/0AD4A'
        'FAA/ABQADQAB/+AAFP/gABb/3AAX/+AAGP/cABn/vgAkABQALgAKADD/9AAx//EAMv/qADX/4AA2/9IADgAB/+AAFP/cABb/0gAX'
        '/9wAGP/SABn/uQAa/+oALf/2AC4ACgAw//QAMf/xADL/6gA1/+AANv/IABoAA//lAAf/5QAK/9IAD//lABH/5QAT//QAFP/2ABb/'
        '9AAX//QAGP/lABn/6gAb/9wAHf/bAB7/2wAf/9sAIf++ACQADwAp/9sAK//bAC3/wwAuABQANv9kADf/4AA4/9wAOf/cADr/4AAm'
        'AAH/ggAD/80AB//NAAr/vgAP/80AEf/NABP/3AAY//YAGv/0ABv/lgAd/6AAHv+gAB//oAAg/+oAIf+MACT/9gAn/9IAKP/SACn/'
        'oAAq/9IAK/+gACz/3AAt/5EALv/IAC//3AAw/9wAMf/gADL/3AAz/9wANP/IADX/ggA2/24AN//IADj/lgA5/5YAOv+gAD7/6gA/'
        '/+oAIgAD/80AB//NAA//zQAR/80AE//SABT/tAAV/+AAFv94ABf/mwAY/+oAGf+CABr/9AAb/9IAHf/cAB7/3AAf/9wAIP/gACH/'
        '9AAkAB4AKf/cACv/3AAt/+AALv++AC//9AAw/5EAMf+gADL/9gA0//QAN//qADj/0gA5/9IAOv/2AD7/4AA//+AAAgAW/9wAGP/c'
        'AB4AA/++AAf/vgAP/74AEf++ABP/3AAU/8gAFf/SABb/qgAX/8gAGP/0ABn/tAAa//QAG//cAB3/3AAe/9wAH//cACD/3AAkACgA'
        'Kf/cACv/3AAt/9IALv/gAC//6gAw/9IAMf/SADf/9AA4/9wAOf/cAD7/3AA//9wAAwAw/+AAMv/2ADr/6gACAAH/9gA1//YAHwAB'
        '/+oAA//2AAf/9gAK//YAD//2ABH/9gAT//YAFP/NABb/xAAX/84AGP/lABn/pgAb//YAHf/2AB7/9gAf//YAIf/2ACn/9gAr//YA'
        'Lf/2AC4ACgAw/+8AMf/sADL/5QAz/+8ANP/2ADX/6gA2/9wAN//0ADj/9gA5//YAIAAD//EAB//xAA//8QAR//EAE//7ABT/0gAW'
        '/8gAF//gABj/9AAZ/74AGv/vABv/9AAd//EAHv/xAB//8QAh//YAJAAKACf/9gAo//YAKf/xACr/9gAr//EALf/xAC8ACgAw//QA'
        'Mf/2ADL/6gAz/+oANv/0ADf/9AA4//QAOf/0AAIJ/gAEAAAKYgs2ACkAHwAAAAAAAP/2AAAAAAAA//YAAAAA/9wAAAAAAAD/4v/b'
        'AAAAAAAAAAD/9AAA/9IAAP/xAAAAAAAAAAAAAAAAAAD/8QAA/+D/1gAAAAD/9gAA/77/3P/x/9EAAP/v/+D/yP/b/+UAAP/7/+oA'
        'AAAAAAD/rwAA/9wAAAAA/80AAP/q//T/9AAAAAAAAP/7AAAAAP/b//YAAAAA//H/4AAAAAD/9AAA//EAAAAAAAAAAAAAAAAAAAAA'
        'AAAAAAAAAAAAAP/2AAAAAAAAAAAAAAAA/9YAAAAAAAD/9v/gAAAAAAAAAAD/+f/2/9IAAAAAAAAAAAAAAAAAAAAAAAD/7//W/+8A'
        'AP/qAAD/8QAA/4z/pv/0/6oAAP/n/77/qgAA/+oAAP/WAAAAAAAA//QAAAAA/6r/tP+0AAAAAP/2AAD/8f/vAAAAAAAAAAAAAP/q'
        'AAAAAAAA//H/9AAAAAD/8QAAAAD/9gAAAAAAAP/IAAAAAAAAAAAAAAAA//sAAAAAAAAAAAAAAAAAAAAA/8gAAAAAAAAAAP/bAAAA'
        'AAAAAAr/7wAA/9z/9AAAAAAAAP/qAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/9AAA'
        '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'
        'DwAAAAoAFQAEABkAAAADAAMAAAAAAAAAAAAYABgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
        'AAAAFwAXABcAAAAAABYAAAAWAAAAFgAcAB0AHAAdABsAGwACAAgAAQAIAAEALgAEAAAAEgBQAHYAhACEAIoAmACyALwAxgDcAQoB'
        'IAEuAS4BLgEuATQBNAACAAUASwBPAAAAUQBUAAUAVgBXAAkAWwBbAAsAYgBnAAwACQBR/+AAVP/gAFf/3ABi/+AAY//2AGT/4ABl'
        '//YAZv/gAGf/4AADAFH/4ABU/+AAV//cAAEAV//qAAMAUf/gAFT/6gBX/+AABgBL/8gATP/SAE//0gBW/6oAV//0AFv/oAACAFb/'
        '4ABX/+AAAgBW/9IAV//SAAUAS//gAE//6gBW/4IAV//0AFv/vgALAEv/3ABM/9wATf/qAE7/6gBP/+AAUf/gAFL/4ABT/9IAVP/0'
        'AFb/UABb/1oABQBR/+AAUv/gAFP/0gBU/4IAV/9QAAMAUf/gAFT/yABX/1oAAQBL/+oAAQBL//QAAAABAAAACgAmAEAAAkRGTFQA'
        'DmxhdG4ADgAEAAAAAP//AAIAAAABAAJjYWx0AA5saWdhABQAAAABAAAAAAABAAIAAwAIAHwAlgAGAAAABAAOACIAOABOAAMAAQBc'
        'AAEAeAABAFwAAQAAAAEAAwACAEIASAABAGQAAQBCAAEAAAABAAMAAQAyAAEATgACACwAMgABAAAAAQADAAIAFgAcAAEAOAABABwA'
        'AQAAAAEAAQABAEoAAgABAEAASQAAAAEAAAABAAgAAgAKAAIAcABwAAEAAgAYADIABAAIAAEACAABABoAAQAIAAIABgAMAD4AAgAj'
        'AD8AAgAmAAEAAQAgAAAAAQABAAgAAgAAABQAAgAAACQAAndnaHQBAAAAaXRhbAEWAAEABAAQAAEAAAAAARACWAAAAAMAAQACARcA'
        'AAAAAAEAAA=='
    ),
    'STS2 Host Grotesk ExtraBold': (
        'AAEAAAAQAQAABAAAR0RFRgLQAsUAACy8AAAAfEdQT1Ps6uCDAAAtOAAAHpZHU1VCiPOV7gAAS9AAAAD+T1MvMmdMAngAAAGIAAAA'
        'YFNUQVTmS8w2AABM0AAAAERjbWFwtaK0YwAAA9wAAAEuZ2FzcAAAABAAACy0AAAACGdseWZ4IAYuAAAGEAAAIYpoZWFkKTZcrAAA'
        'AQwAAAA2aGhlYQckBqoAAAFEAAAAJGhtdHgJcw6SAAAB6AAAAfRsb2NhIRUolgAABRQAAAD8bWF4cACJAJoAAAFoAAAAIG5hbWU/'
        '7WgjAAAnnAAABPdwb3N0/58AMgAALJQAAAAgcHJlcGgGjIUAAAUMAAAABwABAAAAAQDFtnCpJl8PPPUAAwPoAAAAAN/XrBoAAAAA'
        '5x1sAf9K/xgD4APRAAAABgACAAAAAAAAAAEAAAP3/sUAAAP0/0r/jAPgA+gAAAAAAAAAAAAAAAAAAAB9AAEAAAB9AEwABQBMAAQA'
        'AQAAAAAAAAAAAAAAAAACAAEABAIuAZAABQAAAooCWAAAAEsCigJYAAABXgAyASoAAAILBQQDBAIAAgOAAAADAAAAYgAAAAAAAAAA'
        'TE1OVADAACAiZQP3/sUAAAPRAXQAAAABAAAAAAHwArwAAAAgAAMCgAAeAqIAAgJVAC8CwQAcAq0ALwIbAC8CCwAvAt0AHAKjAC8A'
        '6gAvAZEADAJ2AC8CCQAvA1cALwKzAC8C+AAcAk0ALwMVABwCgAAvAl8AGAJLABQCegAjAsYADwP0ABQCfQAKAoIADgIeACACKwAf'
        'AloAJgIkABMCWgATAi0AFQFOAAYCbAAdAjkAJADUACQAz/+8AhIAJADUACQDgwAkAjkAJAJAABUCWgAmAloAEwF9ACQB7wAMAWMA'
        'AwIaABoCKAAKAyYACgI2AAsCTgAQAdEAGAKiAAIDiAACAxMAHwIrAB8DhAATAjcAEQAA/0oAAP+MAAD/jAIlAAkCIgAGAooAIgKK'
        'AEMCigBGAooAKgKKACACigA5AooAKQKKADMCigAwAooAMAEzAAAA4AAaAN4ADQDgABoA3gANAjUAGgEUADMB9AAQAOAAIQFfACMB'
        'zgArAyAAEwHWAAMB1gADAeoAEgKzAEkDVwArAp8AKAGBACYBgQAQAYEAHAGBACEBgQA5AYEALgG2ABIBtgASAQoAHAEKAB8BWwAe'
        'AMgAKAN+ACkCwwAlAOoALwKKAC4CigACAooAMgJOAEQCTgBEAk4AWAJOAEQCTgB4Ak4AZAJOAEQCTgBEAk4ARAJOAB8CTgBOA1sA'
        'FAKjADACowAwAZAAUgAAAAIAAAADAAAAFAADAAEAAAAUAAQBGgAAADAAIAAEABAALwA5AEAAWgBgAHoAfgCjALEAtwDGANgA5gD4'
        'IBQgGSAdICIgJiCsIZAhkiJl//8AAAAgADAAOgBBAFsAYQB7AKMAsQC3AMUA1wDlAPggEyAYIBwgIiAmIKwhkCGSImT//wAAABAA'
        'AP/AAAD/ugAA/8r/xf+b/3AAAP9T/0LgRuBM4EbgMeAp38De697oAAAAAQAwAAAATAAAAFYAAABeAAAAAAAAAAAAXAAAAAAAAAAA'
        'AAAAAAAAAAAAAAAAAEoAAABKAFAAZgBVAGsAeQBpAGcAXABdAFQAbgBMAFgASwBWAE0ATgBzAHEAcgBRAGgAYABXAGEAeABbAHwA'
        'XgBqAF8AdwBwADcAdQB0AAC4Af+FsASNAAAAACcAQgB6AKgAywDhAPQBJgFAAUwBYQF7AYoBqQG/AfECFAJYAogC0ALhAwIDFQM0'
        'A1IDZwN9A8YD/AQqBGAEmAS1BP8FHwUxBU4FagV2BakFyQX7BjEGaAaBBsYG5QcFBxcHNwdOB3IHhgeSB7QH7wf7CGAImwioCM0I'
        '8gkaCSYJUgluCaQJ5goGCj0KhQqXCuULLQstCzgLTwtbC2cLfQuQC8gL3gv6DBoMPAxLDFoMYgxuDHoMhgynDMgNCg1MDV0Nbg2C'
        'DZYNow2wDcMN0A42DnAOfQ7MDwQPPw9SD18Pdw+KD50PsQ/LD+YQARAnEDgQkhCnELwQxQAFAB4AAAJiArwAAwAGAAkADAAPAABz'
        'ESERJSEDBxMDAREDJxMhHgJE/gUBu9312toB4NAb0/5aArz9RDIBEu0BDgEP/e8CAv8AIAEFAAACAAIAAAKgArwABwALAABzEzMB'
        'IwMzAyc3IRcC/58BAJTYOdgdJQFoJQK8/UQCcP2QnW1tAAADAC8AAAJDArwAEwAcACUAAHMRITIWFhUUBgYHNx4CFRQGBiMnMzI2'
        'NTQmIyM1MzI2NTQmIyMvASNJZDQuSy0QMEsrNmdKoYs1Ojw1iYAzNjU1fwK8LVE2NUgmBAsBME4uOFcwcjAuLTRoLysqLwAAAQAc'
        '//QCqALIAB0AAEUiJiY1NDY2MzIWFyMmJiMiBgYVFBYWMzI2NzMGBgFxaplSUplqgKQTmgxRQj5YLy9YPkJQDJoTowxbo2trpFyA'
        'dDg9OWpJSWk5OTVvfQACAC8AAAKMArwACgAVAABzETMyFhYVFAYGIyczMjY2NTQmJiMjL/Z7n01Nn3tqYlVhKiphVWICvFedamme'
        'V3g3Z0hIaDcAAQAvAAAB/gK8AAsAAHMRIRUhFSEVIRUhFS8Bz/69ASX+2wFDArxxsW28cQABAC8AAAH6ArwACQAAcxEhFSEVMxUj'
        'ES8By/7B//8CvHG1bv7YAAEAHP/0AsgCyAAhAABFIiYmNTQ2NjMyFhcjJiYjIgYGFRQWFjMyNjUjNSEVFAYGAYZzolVVnm19oxic'
        'EE4+Q14xM2JIU2C+AUxUkQxZoWtspl13aS0yOmtKSWg3W1FoPXCXTAADAC8AAAJ0ArwAAwAHAAsAAGERMxEhETMRAzUhFQHojP27'
        'jBIBVgK8/UQCvP1EAS1xcQAAAQAvAAAAuwK8AAMAAHMRMxEvjAK8/UQAAQAMAAABawK8AAsAAHM1MzI2NREzERQGIwyEKySMdmV9'
        'MysB4f4fanEAAQAvAAACaQK8AAsAAHMRMxETMwEBIwMHFS+M+qz+/wEJq8JBArz+7wER/uv+WQE7RvUAAAEALwAAAe0CvAAFAABz'
        'ETMRIRUvjAEyArz9sW0AAAEALwAAAygCvAAPAABzETMTBxMzESMRFwMjAzcRL6jzO/KnjC/ncOgvArz9tggCUv1EAlAj/dMCLSP9'
        'sAAAAQAvAAAChAK8AAkAAHMRMwERMxEjAREvjAE9jIz+wwK8/iUB2/1EAdn+JwACABz/9ALcAsgADwAfAABFIiYmNTQ2NjMyFhYV'
        'FAYGJzI2NjU0JiYjIgYGFRQWFgF8aJ9ZWZ9oaZ5ZWZ5oQF00NF1AQF40NF4MXKNra6NcXKNra6NcfjlqSUlqOTlqSUlqOQAAAgAv'
        'AAACNQK8AAwAFQAAcxEhMhYWFRQGBiMjEREzMjY1NCYjIy8BC1VvNzVvV392Pjg4PnYCvDljPjljPf73AXo4MDE3AAMAHP/0AxYC'
        'yAAPAB8AKwAARSImJjU0NjYzMhYWFRQGBicyNjY1NCYmIyIGBhUUFhYFIiYnAzcXFhYzMxUBfGifWVmfaGmeWVmeaEBdNDRdQEBe'
        'NDReAYEZGA39XdoKDBI0DFyja2ujXFyja2ujXH45aklJajk5aklJajlyCg8BG0r1CgZ5AAACAC8AAAJfArwAFQAeAABzESEyFhYV'
        'FAYHFhYXFyMnLgIjIxERMzI2NTQmIyMvASlVbzcqIyYpAgiJCwIXMCmelD44OD6UArw5Yz4wUR0aUjWjoyMtFv73AXo4MDE3AAAB'
        'ABj/9AI5AsgAMQAARSIuAiczHgIzMjY2NTQmJycmJjU0NjYzMhYWFyMuAiMiBgYVFBYXFxYWFRQOAgE1MGBRNgaACTNEICU5ISA3'
        'cVliQnBER3FHB4IHKDYbGTknKTJoWWgtS1wMGztfQzM3FhgqGh0uChURa0lCXTIwZVAtLxIQJiIcLAkTEF1cNFA3HQABABQAAAI3'
        'ArwABwAAcxEjNSEVIxHgzAIjywJLcXH9tQAAAQAj//QCVwK8ABMAAEUiJiY1ETMRFBYzMjY1ETMRFAYGATpOfkuMS0NDS4xNggw+'
        'fl8Brf5STE1NTAGu/lNffj4AAQAPAAACtwK8AAYAAGEDMxMTMwMBDf6Vv8CU/gK8/dMCLf1EAAABABQAAAPgArwADwAAcwMzEyMT'
        'MxMjEzMDIwMzA8u3lYkmopqeJomXvKeQGJQCvP2QAnD9jwJx/UQCJP3cAAMACgAAAnMCvAADAAcACwAAYQEzASETFwMTJxMzAdH+'
        'OaIBx/2a81GlzlCknwK8/UQBh2z+5QE4bAEYAAEADgAAAnQCvAAJAABzNQMzEyMTMwMV++2fqCWnne30Acj+oAFg/jj0AAEAIAAA'
        'Af4CvAAJAABzNQEhNSEVASEVIAE8/sYB2/7CAT9rAd10a/4jdAAAAgAf//QCIAH8ACYAMwAAVyImJjU0NjMyFhc1NCYjIgYHIz4C'
        'MzIWFRUUFhYzMxUjIiYnBgYnMjY2NyYmIyIGFRQW0TdQK29aKz0TOSweMAeDBjteOXCBCRQQBB82SBEaUhQdKRwHFDUbHywmDChE'
        'KU1VDAYYMSwYIDVKJ2liZyYlCnUbJyIsahktHAYLHx0YHwACACb/9AJHAtAAEgAiAABFIiYnFSMRMxE2NjMyFhYVFAYGJzI2NjU0'
        'JiYjIgYGFRQWFgFUN1EajIwYTT1FbkBAbmYnPSIiPScnPCIiPAwoJEAC0P7cIDBEdktKdkN6JD4nKD8kJD4oKD4kAAABABP/9AIQ'
        'AfwAHQAARSImJjU0NjYzMhYXIyYmIyIGBhUUFhYzMjY3MwYGARlNdkNDdk1ghBOUCTYlITYfHzYhJTYJlBKFDEN1TEx1Q2VZICYi'
        'PiwrQCIlIlZoAAIAE//0AjQC0AASACIAAEUiJiY1NDY2MzIWFxEzESM1BgYnMjY2NTQmJiMiBgYVFBYWAQdFb0BAb0U3URmMjBdN'
        'HSc8IiI8JyY9IiI9DER3Skt1QygkASD9MEQgMHokPycoPiQkPSgoPyQAAAEAFf/0AhYB/AAlAABFIiYmNTQ2NjMyFhYVFBQHITUh'
        'JiYjIgYGFRUUFhYzMjY3Mw4CARpNdkJBdk5KckAC/mUBDwM9LSI5IR83JCMwDY8OQ2EMQXNLTXhEQG9HChkNVCw1Hj0vHSY5Hx8Z'
        'ME0tAAACAAYAAAEyAtAADAAQAABzETQ2NjMzFSMiBhURAzUhFUkhSz4/IyMXzwEsAipJRxZ3FiH93gF7dXUAAgAd/xgCRwH8ACIA'
        'MgAARSImJiczFhYzMjY2NTUOAiMiJiY1NDY2MzIWFzUzERQGBgMyNjY1NCYmIyIGBhUUFhYBOz91UgiLCEcxIzwkDy4/KUdxQUFx'
        'RzdVGYxKelApPCIiPCkoPSIiPegpWkgmLB07LjwXJhdDdEhIc0MsIUH+L1d1OwFgJDwlJjwjIzsmJT0kAAEAJAAAAhUC0AATAABz'
        'ETMRNjYzMhYVESMRNCYjIgYVESSMGFU3XWSLMDUzQgLQ/tcnLndw/usBCD1BRz//AAACACQAAACwAsEAAwAHAABzETMRAzUzFSSM'
        'hoIB8P4QAj+CggAC/7z/JACrAsEADAAQAABHNTMyNjURMxEUBgYjEzUzFUQxIBKMJEg2F4LcdxEdAif900BFGgMbgoIAAwAkAAAC'
        'IALQAAMABwALAAB3JxMzAREzETMnNwGpRPSj/iiMxbtUARKHUAEZ/hAC0P0w81P+ugABACQAAACwAtAAAwAAcxEzESSMAtD9MAAB'
        'ACQAAANfAfwAIgAAcxEzFTY2MzIWFzY2MzIWFREjETQmIyIGFREjETQmIyIGFREkjBhNMjhRGBxaN2Nniy4yMTuLMDIwOwHwOyEm'
        'LCooLndw/usBCD1BRz//AAEIPUFHP/8AAAABACQAAAIVAfwAEwAAcxEzFTY2MzIWFREjETQmIyIGFREkjBhTOF5kjDE1MkEB8Ekn'
        'Lndw/usBCD1BRz//AAAAAgAV//QCKwH8AA8AHwAARSImJjU0NjYzMhYWFRQGBicyNjY1NCYmIyIGBhUUFhYBIEt5R0d6Skt5R0d5'
        'SyI4ISI3ISI4IiE4DEJ2TE11QkJ1TUx2QnkfPi4uPh8fPS8uPh8AAAIAJv8kAkcB/AASACIAAFcRMxU2NjMyFhYVFAYGIyImJxET'
        'MjY2NTQmJiMiBgYVFBYWJowYTT1FbkBAbkU3URqBJz0iIj0nJzwiIjzcAsxEIDBEdktKdkMoJP7kAUokPicoPyQkPigoPiQAAAIA'
        'E/8kAjQB/AASACIAAEURBgYjIiYmNTQ2NjMyFhc1MxEBMjY2NTQmJiMiBgYVFBYWAagXTT1Fb0BAb0U3URmM/vMnPCIiPCcmPSIi'
        'PdwBICAwRHdKS3VDKCRA/TQBSiQ/Jyg+JCQ9KCg/JAAAAQAkAAABYwH1AA4AAHMRMxU2NjMzFSMiBgYVFSSMFDwmPUslLhUB8Esl'
        'K3wmSzbSAAABAAz/9AHSAfwALwAAVyImJzMWFjMyNjU0JicmJicuAjU0NjMyFhcjJiYjIgYVFBceAhceAxUUBgb4ZIAIjwc2JSkr'
        'ICcOMQ8qRShkYWJxB4cDMB8mJj4JISMKHjktGjJhDF5MHSMdFREVBAIIAwglPSxDXFZMGxwaEx8LAQUFAgQTIDQmMkwqAAABAAMA'
        'AAFeAngAFQAAcyImJjU1IzUzNTMVMxUjFRQWFjMzFfc0RyRVVYx6egobFzsYRUHddYiIdcwXGAl3AAEAGv/0AfYB8AATAABXIiY1'
        'ETMRFBYzMjY1ETMRIzUGBtJWYosuLjI3jIwWSwx3cAEV/vg9QUc/AQD+EEcmLQABAAoAAAIeAfAABgAAcwMzExMzA7+1k3h3krUB'
        '8P6UAWz+EAABAAoAAAMcAfAADwAAcwMzEycTMxMHEzMDIwMzA5ySimIicZtyI2KLkpF6J3kB8P5fAQGg/mABAaH+EAGs/lQAAQAL'
        'AAACKwHwAAsAAHM3JzMXNzMHFyMnBwu3t5d6eZa3t5Z5evj4qKj4+KioAAEAEP8kAksB8AATAABXNTMyNjY3NwcDMxMTMwEOAyMc'
        'bA8UEgonBtiYhImW/vkQGBkiGtxuBxYYVjwCD/6uAVL9pSQtFwkAAAEAGAAAAbQB8AAJAABzNRMjNSEVAyEVGPf0AZT7AQBwAQx0'
        'cP70dP//AAIAAAKgA9EGJgABAAAABwA9AVEAAAACAAIAAANrArwADgASAABzASEVIRUzFSMVIRUhEQEnNyEVAgF1AfT+9uzsAQr+'
        'av7FCDoBTAK8b7NrwG8CUv2uhWtrAAMAH//0AvcCyAAPABMAIwAARSImJjU0NjYzMhYWFRQGBiUBMwE3MjY2NTQmJiMiBgYVFBYW'
        'AX9on1lZn2hpnllZnv44AlSD/azdQF00NF1AQF40NF4MXKNra6NcXKNra6NcDAK8/URyOWpJSWo5OWpJSWo5AP//AB//9AIgAwUG'
        'JgAbAAAABwA8ARAAAAADABP/9ANrAfwAMwA/AEcAAFciJiY1NDYzMzU0JiMiBgcjPgIzMhYXNjYzMhYWFRQGByEeAjMyNjczDgIj'
        'IiYnBgYnMjY2NzUjIgYVFBYlMyYmIyIGBtlAWC5nbYQ2JiI1BogFPmQ+O1seIFozSXFBAQL+kwMgMx4nMwyMDUNjPkFrIh5fNyAw'
        'IQZrKy0tAS7gBDwsGzEhDClFKURZCS8rIR81UCwjICAjQHBIChgOIjEbKB00UjE0Lis3bB0yHgchGRsfyC80FiwAAwAR//QCJgH8'
        'AA8AEwAjAABFIiYmNTQ2NjMyFhYVFAYGJQEzATcyNjY1NCYmIyIGBhUUFhYBG0d0RER0SEhzRER0/q4Bq2r+Vp8iOCIiNyIhOSIi'
        'OAxCdkxNdUJCdU1MdkIMAfD+EGAiRDIzQyIiQzMyRCIAAAH/SgIrACcC8QADAABDJzMXO3uDWgIrxsYAAv+MAiAAdAMFAAsAFwAA'
        'USImNTQ2MzIWFRQGJzI2NTQmIyIGFRQWL0VFLzBERDAUGhoUExsbAiA+NTU9PTU1PkMaFhYZGRYWGgAC/4wC7AB0A9EACwAXAABR'
        'IiY1NDYzMhYVFAYnMjY1NCYjIgYVFBYvRUUvMEREMBQaGhQTGxsC7D41NT09NTU+QxoWFhkZFhYaAAIACQAAAgEC0AAWABoAAHMR'
        'IzUzNTQ2NjMzFSMiBhUVIREjESMREzUzFUxDQyFLPj8jIxcBGIyMfK0Be3U6SUcWdxYhMv4QAXv+hQI0nJz//wAGAAAB/gLQBCYA'
        'IAAAAAcAJgFOAAAAAgAi//QCaALIAA8AGwAARSImJjU0NjYzMhYWFRQGBicyNjU0JiMiBhUUFgFFW4NFRYNbXIJFRYJcUEdHUE9I'
        'SAxao21to1pao21to1p+d3V1d3d1dXcAAAIAQwAAAl8CvAAKAA4AAGURIzU3NjY1NTMRBTUhFQENsYcTF4z+qgIcMwHJZgoCFBMn'
        '/XczcnIAAQBGAAACTALIACQAAHM1NDY2Nzc2NjU0JiYjIgYGFSM+AjMyFhYVFAYHBw4CFSEVRjFgRRY/TBgxJiY4HYcCSHdHTms4'
        'XW8oLTUWAXM4V25IHgodOS4ZLBwfNCFPaDM3XjpGdzUTFSkqGnIAAQAq//QCVALIAC4AAEUiJiYnMxQWFjMyNjU0JiYjIzUzMjY1'
        'NCYjIgYHIz4CMzIWFhUUBgcWFhUUBgYBRU1/TQKJI0ItQEUoSDA6OjtTQDU6QQOJA0N1TFJxOksyQVA/eAwyZk8gNB46KyIuGHMr'
        'LSYrOCdDXzMzVjM9UA4LWkQ6YDoAAgAgAAACUwK8AAoAEAAAYTUhNQEzETMVIxUnERcBJyEBev6mAUqPWlp6Iv7sFwE/fHAB0P46'
        'eny3AaoK/mo1AAEAOf/0Al0CvAAjAABFIiYmJzMWFjMyNjY1NCYjIgYHIxMhFSEHJzY2MzIWFhUUBgYBUFV6QwWICU0yKz8iS0Er'
        'ShB/PQGo/sAoDBdUQ1FvOUV5DDdfPSg0Ij0nOEckHQGNe8knGihEbT5Kc0EAAgAp//QCWgLIACAAMAAARSIuAjU0NjYzMhYWFyMm'
        'JiMiBhcnPgIzMhYWFRQGBicyNjY1NCYmIyIGBhUUFhYBVVRzRh9GhF1PazwFggo+MlFUCQ0POU0tQG5EQnZUKjwgITwrKz8hIj8M'
        'O2J5PnasXjpdNiwulZczHi8cOGZGQGxBeBszIyQzGxsyIyQzHAAAAQAzAAACTgK8AAYAAHMBITUhFQGSASz+dQIb/tQCRHhi/aYA'
        'AwAw//QCWgLIAB0AKQA1AABFIiYmNTQ2NjcmJjU0NjYzMhYWFRQGBx4CFRQGBicyNjU0JiMiBhUUFhMyNjU0JiMiBhUUFgFFTn1K'
        'HzgmMDk5c1VWcjk5MCY4H0p9TkZHR0ZGR0dGPT09PT09PQw0Xj8qRzUOFU4xMVU1NVUxMU4VDjVHKj9eNHQ1NDU1NTU0NQE5LS0u'
        'Li4uLS0AAgAw//QCYQLIACAAMAAARSImJiczFhYzMjYnFw4CIyImJjU0NjYzMh4CFRQGBgMyNjY1NCYmIyIGBhUUFhYBOk5sOwaC'
        'Cj8xUVQJDQ85TC5AbkRCdk1Uc0YfRoRZLD4hIj8sKjwgIT0MOl41Ky+VlzMdMBw4ZkZAbEE7Ynk+da1eAXkbMiMkNBsbMiQkMxsA'
        'AQAaAAAAxgCgAAMAAHM1MxUarKCgAAEADf9QAMgAmQANAABXNTMyNjU1IzUzFRQGIw0sFBRNtElGsGYVFhiguD1UAP//ABoAAADG'
        'AfAGJgBLAAAABwBLAAABUP//AA3/UADIAfAEJwBL//8BUAIGAEwAAAADABoAAAIbAKAAAwAHAAsAAGE1MxUhNTMVMzUzFQGLkP3/'
        'kCmQoKCgoKCgAAIAMwAAAN8CvAADAAcAAHcDMwMHNTMVTQ+WEJGs2wHh/h/boKAAAgAQAAAB3wLIACEAJQAAdzU0NjY3Nz4CNTQm'
        'IyIGFSM0NjYzMhYWFRQGBwcGBhUVBzUzFYsJGxszDSsiNCwuNIU2aEpEaDtHN0gPDY2s2yYdJBkNGQcbMCUqMzQrPF83MV5CQmcc'
        'JAcMEBDboKAAAAEAIQD0AL8BlQALAAB3IiY1NDYzMhYVFAZwIywsIyMsLPQvISMuLiMhLwAAAQAjAMIBOwHZAA8AAHciJiY1NDY2'
        'MzIWFhUUBgauJkAlJUAmKD8mJj/CJT8nKD8lJT8oJz8lAAABACsBbgGjAtwAEQAAUyc3IzUzJzcXNxcHMxUjFwcnpU44ZGQ4TkJB'
        'TjhlZThOQQFuNFReVDRhYTRUXlQ0YQAABAATAAADDQLYAAMABwALAA8AAHMTMwMzEzMDJTUhFQE1IRWBm3+clpx+m/3/AsH9eALB'
        'Atj9KALY/SipeHgBEXl5AAABAAP/jAHTAw0AAwAAVwEzAQMBSIj+t3QDgfx/AAABAAP/jAHTAw0AAwAARQEzAQFM/reIAUh0A4H8'
        'f///ABIBJAHYAZgEBgBvzgAAAQBJAOcCaQFcAAMAAHc1IRVJAiDndXUAAQArAOcDKwFcAAMAAHc1IRUrAwDndXUAAQAo/1MCcv/Z'
        'AAMAAFc1IRUoAkqthoYAAQAm/28BcQMrABMAAFcuAjU0NjY3Mw4DFRQeAhflOFYxMVY4jBxCPScnPUIckTmUsGFir5U4IV14klZW'
        'knhdIQAAAQAQ/28BWwMrABMAAFc+AzU0LgInMx4CFRQGBgcQHEI9Jyc9QhyMOFYxMVY4kSFdeJJWVpJ4XSE4la9iYbCUOQAAAQAc'
        '/00BYAMsAC8AAEUiJjU0NjY1NCYnNTY2NTQmJjU0NjMzFSMiBhUUFhYVFAYHFRYWFRQGBhUUFjMzFQEfUmQQEC8+Pi8QEGRSQScl'
        'Ig8QNkBANhAPIiUns1dTIjg5ISMwB28HMSIiODkhU1dxISQZNDslNUoMAwxKNSQ8MxokIXEAAQAh/00BZQMsAC8AAFc1MzI2NTQm'
        'JjU0Njc1JiY1NDY2NTQmIyM1MzIWFRQGBhUUFhcVBgYVFBYWFRQGIyEnJSIPEDZAQDYQDyIlJ0FSZBAQLz4+LxAQZFKzcSEkGjM8'
        'JDVKDAMMSjUlOzQZJCFxV1MhOTgiIjEHbwcwIyE5OCJTVwAAAQA5/1EBUwMrAAcAAFcRIRUjETMVOQEal5evA9px/QlyAAEALv9R'
        'AUgDKwAHAABXNTMRIzUhES6XlwEar3IC93H8JgACABIBwAGjArwAAwAHAABTNzMHITczB9xpXjX+pGhfNQHA/Pz8/AAAAgASAcEB'
        'pAK9AAMABwAAUzczByE3MwfcNpJo/tY2kmgBwfz8/PwAAAEAHAHAAOMCvAADAABTNzMHHGhfNQHA/PwAAQAfAcAA5wK8AAMAAFM3'
        'MwcfNpJoAcD8/AACAB4CHwE9AvMAAwAHAABTJzMHMyczByoMdwxKDHYLAh/U1NTUAAEAKAIfAKAC8wADAABTJzMHNQ14DAIf1NQA'
        'AgAp/yIDUwKKAD8ASwAARSIuAjU1ND4CMzMyFhYVFRQGIyImJwYGIyImJjU0NjYzMhYXNzMRFBYzMjY1NTQmJiMjIgYGFRUUFhYz'
        'MxUDMjY1NCYjIgYVFBYBikyBYDQ3YYRMb2WZVVpKKEAKDkdBP1owMVs9KD4SAnIQDxcUOGRCb0JpPTpnQvDDMTk3MS49O942YYJM'
        'wkV1VzBPjVx0bXMnIh8vN2JCQmI2GxYq/wAXHS88dDxbMzdfPcJEbD53ATlCNzVDQzU3QgAAAgAl//oCrAK8AAcAJQAAYQE1IRUh'
        'NwEFIiYmNTQ2MzMVIyIGFRQWFjMyPgM3Mw4EAhj+UQGo/rIyAbf+dkpyQYNvJRM6RBw3KjJPOigWA3kEJ0NccAJSanch/ZoGOGZE'
        'ZXBcQDUjMxsrRVNQHzR1b1o1AAABAC//nAC7AtAAAwAAVxEzES+MZAM0/MwAAAIALv+pAk8DGAAxADUAAEUiLgInMx4CMzI2NjU0'
        'JicnJiY1NDY2MzIWFhcjLgIjIgYGFRQWFxcWFhUUDgIHETMRAUswYFE2BnwJNUUhKDwjIDd5WWJCb0VHcUcHfgcpOBwbPCopMnBZ'
        'aC1LXFdCDBs7X0M3PBcaLx0dLgoVEGxJQl0yMGVQMTMUESsmHC0IEw9eXDRQNx1LA2/8kQAAAwAC//QCfgLIABsAHwAjAABFIiYm'
        'NTQ2NjMyFhcjJiYjIgYVFBYzMjY3MwYGJTUhFSU1IRUBe1uDRUWDW2WHF5AKOy5SSUlSLjsKkBeH/iIBiv52AYoMWqNtbaNabWAn'
        'KHd1dXcoJ2Bt8U9PlU9PAAIAMgAAAlACyAAjACcAAHM1PgI1NC4CNTQ2NjMyFhYXIyYmIyIGFRQeAhUUBgchFQE1IRVAGjIgEhcS'
        'PG1JTWU1A4ACNDIxPhIWEigkAWz94gGgUBg2QywaNTg8IUNgNDtjPSw8NDQYNTg5GyxWI28BJ19fAAACAEQAdAIKAkgAAwAHAAB3'
        'ETMRJTUhFex2/uIBxnQB1P4ssHR0AAEARAEkAgoBmAADAABTNSEVRAHGASR0dAAAAgBYAI8B9gItAAMABwAAdycBFwMBNwGrUwFL'
        'U1j+wFIBQI9TAUtT/rsBQFL+wAAAAgBEAMACCgH8AAMABwAAUzUhFQU1IRVEAcb+OgHGAYh0dMh0dAABAHgAZgHqAlYABwAAdzUl'
        'FSU1BRV4ATv+xQFyZpCMSIyQvHgAAAEAZABmAdYCVgAHAABlJTUlFQU1BQHW/o4Bcv7FATtmvHi8kIxIjAACAEQAPgIKAlYABwAL'
        'AAB3NSUVJTUFFQE1IRVJAX7+ggHB/joBxtdzZzVnc4pr/t10dAAAAgBEAD4CCgJWAAcACwAAZSU1JRUFNQUBNSEVAgX+PwHB/oIB'
        'fv4/AcbXimuKc2c1Z/70dHQAAwBEAD4CCgJIAAMABwALAABTNSEVATUhFSURMxFEAcb+OgHG/uJ2AVN0dP7rdHSVAXX+iwAAAQAf'
        'AN8CLwGdABcAAHc2NjMyHgIzMjY3MwYGIyIuAiMiBgcfEVxDIDEqJxYaIgRoEF1EHzAqKBYaIgXfZFoUGhQhIWRaFBoUIiAAAAEA'
        'TgHFAgACvAAGAABTNzMXIycHTp14nXpfXwHF9/ekpAAFABT/9ANHAsgAAwATAB8ALwA7AABzATMBAyImJjU0NjYzMhYWFRQGBicy'
        'NjU0JiMiBhUUFgEiJiY1NDY2MzIWFhUUBgYnMjY1NCYjIgYVFBakAYeI/nlpMU8vL1AxMU8uLk8yHSUlHRwmJgHxMU8vL08xMk8u'
        'L08yHSYlHRwmJQK8/UQBXytRODlRKytROThRK18sKSssLCspLP42K1E4OFErK1E4OFErXywpKysrKyksAAABADAAXwJzAl0ACAAA'
        'ZSc3ITUhJzcXAXRHf/6EAXx/R/9fSYFqgUn/AAABADAAXwJzAl0ACAAAZSc3FwchFSEXAS///0d/AXz+hH9f//9JgWqBAP//AFIC'
        'KwEvAvEEBwA7AQgAAAAAAAAAFgEOAAEAAAAAAQAABgAAAAEAAAAAARQACQAGAAMAAQQJAAAAugAPAAMAAQQJAAEANgDJAAMAAQQJ'
        'AAIADgD/AAMAAQQJAAMAUgENAAMAAQQJAAQANgDJAAMAAQQJAAUAGgFfAAMAAQQJAAYAQAF5AAMAAQQJAAgAGAG5AAMAAQQJAAkA'
        'IgHRAAMAAQQJAAsALAHzAAMAAQQJAAwAKAIfAAMAAQQJAA0BIgJHAAMAAQQJAA4ANgNpAAMAAQQJABAANgDJAAMAAQQJABEADgD/'
        'AAMAAQQJABkAFgOfAAMAAQQJAQAADAO1AAMAAQQJARQAEgPBAAMAAQQJARYADAPTAAMAAQQJARcACgPfV2VpZ2h0RXh0cmFCb2xk'
        'AEMAbwBwAHkAcgBpAGcAaAB0ACAAMgAwADIAMwAgAFQAaABlACAASABvAHMAdAAgAEcAcgBvAHQAZQBzAGsAIABQAHIAbwBqAGUA'
        'YwB0ACAAQQB1AHQAaABvAHIAcwAgACgAaAB0AHQAcABzADoALwAvAGcAaQB0AGgAdQBiAC4AYwBvAG0ALwBFAGwAZQBtAGUAbgB0'
        'AC0AVAB5AHAAZQAvAEgAbwBzAHQARwByAG8AdABlAHMAawApAFMAVABTADIAIABIAG8AcwB0ACAARwByAG8AdABlAHMAawAgAEUA'
        'eAB0AHIAYQBCAG8AbABkAFIAZQBnAHUAbABhAHIAUwBUAFMAMgBIAG8AcwB0AEcAcgBvAHQAZQBzAGsARQB4AHQAcgBhAEIAbwBs'
        'AGQALQBSAGUAZwB1AGwAYQByADsAbQBvAGQAaQBmAGkAZQBkAFYAZQByAHMAaQBvAG4AIAAxAC4AMAAwADMAUwBUAFMAMgBIAG8A'
        'cwB0AEcAcgBvAHQAZQBzAGsARQB4AHQAcgBhAEIAbwBsAGQALQBSAGUAZwB1AGwAYQByAEUAbABlAG0AZQBuAHQAIABUAHkAcABl'
        'AEQAbwEfAHUAawBhAG4AIABLAGEAcgBhAHABMQBuAGEAcgBoAHQAdABwAHMAOgAvAC8AZQBsAGUAbQBlAG4AdAB0AHkAcABlAC4A'
        'YwBvAGgAdAB0AHAAcwA6AC8ALwBkAG8AdQBnAGgAawBhAG4ALgBjAG8AbQBUAGgAaQBzACAARgBvAG4AdAAgAFMAbwBmAHQAdwBh'
        'AHIAZQAgAGkAcwAgAGwAaQBjAGUAbgBzAGUAZAAgAHUAbgBkAGUAcgAgAHQAaABlACAAUwBJAEwAIABPAHAAZQBuACAARgBvAG4A'
        'dAAgAEwAaQBjAGUAbgBzAGUALAAgAFYAZQByAHMAaQBvAG4AIAAxAC4AMQAuACAAVABoAGkAcwAgAGwAaQBjAGUAbgBzAGUAIABp'
        'AHMAIABhAHYAYQBpAGwAYQBiAGwAZQAgAHcAaQB0AGgAIABhACAARgBBAFEAIABhAHQAOgAgAGgAdAB0AHAAcwA6AC8ALwBvAHAA'
        'ZQBuAGYAbwBuAHQAbABpAGMAZQBuAHMAZQAuAG8AcgBnAGgAdAB0AHAAcwA6AC8ALwBvAHAAZQBuAGYAbwBuAHQAbABpAGMAZQBu'
        'AHMAZQAuAG8AcgBnAEgAbwBzAHQARwByAG8AdABlAHMAawBXAGUAaQBnAGgAdABFAHgAdAByAGEAQgBvAGwAZABJAHQAYQBsAGkA'
        'YwBSAG8AbQBhAG4AAAMAAAAAAAD/nAAyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAB//8ADwABAAAADAAAAAAAAAACABIAAQABAAEA'
        'AwAFAAEABwAHAAEACQAMAAEADgAPAAEAEQAVAAEAFwAXAAEAGQAbAAEAHQAfAAEAIQAmAAEAKAApAAEALAAvAAEAMQAxAAEAMwA1'
        'AAEANwA5AAEAPwA/AAIAaQBpAAEAawBrAAEAAQAAAAoAJAA0AAJERkxUAA5sYXRuAA4ABAAAAAD//wABAAAAAWtlcm4ACAAAAAIA'
        'AQAAAAIABh0gAAIACAACAAoREAABAKoABAAAAFAKbADSAQQC2gqeAU4CBALMAkYCbAKeAswCzALaAyQDzgQYBEIEgATKBOwFygYY'
        'BsIHEArqCEIHJgdICwQHWgfICCgH2gfsCCIIKAgoCEIIQgh8CIYItAjuCQQJDgmECbYKFApOCmwKngq0CuoLBAs6DCILXAvOC/gM'
        'IgyQDOoNbA2iDdwORg7gD2oPag9qD3QP7g/8D+4P/A/uD/wQBhCEAAIABgABAAgAAAAKACIACAAkADoAIQBLAFQAOABWAGEAQgBo'
        'AGkATgAMABb/5QAY/+oAMP/gADL/5QA3//sAOv/7AFD/9gBR//QAVP/vAFb/0gBX/9IAW//gABIAFv/SABj/1wAw/+oAMv/qADf/'
        '9AA6/+8AS//vAEz/7wBN//QATv/0AE//7wBQ//QAUf/xAFT/6gBW/7QAV//IAFv/vgBp//YALQAB/7kAA//gAAf/4AAK/74AD//g'
        'ABH/4AAT/+8AG//VAB3/yAAe/8gAH//IACD/7wAh/9IAJ//cACj/3AAp/8gAKv/cACv/yAAs/+EALf/XAC7/5QAv/+AAMP/IADH/'
        'wwAy/7QAM/+0ADT/3AA1/7kANv94ADf/4QA4/9UAOf/VADr/zQA+/+8AP//vAEv/5QBM/+UATf/0AE7/9ABP/9sAUP/2AFb/qgBb'
        '/4wAaP/qAGn/7wAQABb/3AAY/9IAMP/0ADL/4QA6/+8AS//gAEz/4ABN//QATv/0AE//4ABQ//QAUf/0AFT/5QBW/74AV//IAFv/'
        'qgAJADD/8QAy//QAOv/xAEv/9ABM//QAT//0AFD/9ABW/+AAW//cAAwAFv/gADD/qgA3//QAOv/0AFH/6gBS/+AAU//gAFT/7wBX'
        '/+AAW//0AGj/8QBp/9sACwAW/4wAMP+cADL/9AA3/+UAUf/SAFL/4ABT/9wAVP+0AFf/qgBo//YAaf/vAAMAMP/xADL/+wA6//sA'
        'EgAW/8gAGP/WADD/5QAy/9wAN//0ADr/5QBL/9wATP/cAE3/8QBO//EAT//cAFD/6gBR/+AAVP/lAFb/uQBX/74AW/++AGn/8QAq'
        'AAH/qgAD//QAB//0AAr/oAAP//QAEf/0ABP/9AAU/+AAFv/cABf/3AAY/9sAGf/GABr/6gAb/9YAHf/cAB7/3AAf/9wAIf/SACn/'
        '3AAr/9wALf/gAC//9gAw//YAMf/2ADL/8QAz/+oANP/vADX/qgA2/1YAN//0ADj/1gA5/9YAOv/IAEv/lgBM/5YAT/+WAFD/9ABW'
        '/3gAV//cAFv/jABo/90Aaf/lABIAFv/IABj/1gAw/+UAMv/cADf/9AA6/+UASwAOAEz/3ABN//EATv/xAE//3ABQ/+oAUf/gAFT/'
        '5QBW/7kAV/++AFv/vgBp//EACgAW/8gAMP/vADL/7wA6//YAUf/2AFT/9gBW//YAV//cAFv/9gBp//YADwAW/9MAGP/bADD/2wAy'
        '/9wAN//0ADr/7wBL//YATP/2AE//8QBQ//EAVP/0AFb/4ABX/+AAW//cAGn/8QASACr/oQAw/5YAMv+RADf/yAA6/4wAS//IAEz/'
        'yABN/+oATv/qAE//yABR//sAUv/gAFP/3ABU//YAVv+0AFv/yABo/9EAaf/qAAgAMP/0ADL/6gA6//YAS//0AEz/9ABP//QAVv/g'
        'AFv/0gA3AAH/jAAD/8gAB//IAAr/lgAP/8gAEf/IABP/2wAY/+oAG/+bAB3/oAAe/6AAH/+gACD/4AAh/5YAI//gACT/9gAn/8gA'
        'KP/IACn/oAAq/8gAK/+gACz/yAAt/6oALv/gAC//yAAw/8gAMf/IADL/vgAz/7QANP++ADX/jAA2/1oAN/++ADj/mwA5/5sAOv+b'
        'AD7/4AA//+AAS/++AEz/vgBN/+AATv/gAE//vgBQ//QAUf/0AFL/3ABT/9IAVP/0AFb/cgBY/9wAWf/cAFr/3ABb/6oAaP++AGn/'
        '1gATACr/yAAw/9IAMv/IADf/2AA6/7QAS//IAEz/yABN/+AATv/gAE//yABQ//QAUf/qAFL/4ABT/9wAVP/0AFb/lgBb/8gAaP/X'
        'AGn/2wAqAAP/zAAH/8wAD//MABH/zAAT/9sAFv/qABv/4AAd/9cAHv/XAB//1wAg/+8AIf/gACf/9AAo//QAKf/XACr/9AAr/9cA'
        'Lf/lAC7/6wAv/+AAMP+0ADH/tAAy//QAM/+0ADf/9AA4/+AAOf/gADr/9AA+/+8AP//vAFH/6gBS/9wAU//SAFT/5QBW//YAV//0'
        'AFj/3ABZ/9wAWv/cAFv/9ABo//QAaf/qABMAKv+0ADD/vgAy/7QAN//DADr/jABL/74ATP++AE3/3ABO/9wAT/++AFD/9ABR/+AA'
        'Uv/SAFP/uQBU/+oAVv+MAFv/tABo/6oAaf/IAAUAMP/cADL/6gA3//EAU//qAFv/9AAIADD/5QAy/9sAOv/2AFH/6gBU/9wAVv/g'
        'AFf/qgBb/9wABAAb//YAM//2ADj/9gA5//YAGwAb/+cAHf/qAB7/6gAf/+oAIf/lACn/6gAr/+oALf/vADD/9AAx//EAMv/0ADP/'
        '9AA4/+cAOf/nADr/6gBL/9wATP/cAE//3ABQ//QAUf/2AFL/9gBUABQAVv/gAFf/8QBb/8gAaP/2AGn/6gAEAFD/+wBR/+oAV//S'
        'AGn/8QAEAEv/8QBQ//YAV//2AGn/9gANADD/5QA6//YASwAeAEwAHgBNABQATgAUAE8AFABR//EAUv/0AFP/3ABU/+oAV/++AGn/'
        '6gABAGn/9gAGADD/2wAy//QAUf/qAFT/4ABX/7QAaf/2AA4AMP/bADL/3AA6//sAS//0AEz/9ABP//QAUP/xAFH/3ABU/9IAVv/c'
        'AFf/oABb/9wAaP/2AGn/+wACACQAMgBX/9IACwAw//EAMv/vADr/5QBL/9wATP/cAE//3ABW/6oAV//IAFv/yABo//QAaf/qAA4A'
        'MP/WADL/2wBL//sATP/7AE//+wBQ/+8AUf/bAFP/9gBU/9wAVv/XAFf/lgBb/8gAaP/7AGn/9gAFADL/9ABTAA8AVv/2AFf/3ABo'
        '/+cAAgBX/9IAW//0AB0AG//bAB3/2wAe/9sAH//bACH/1gAkAAUAKf/bACv/2wAt/+AAMv/xADP/6gA0//EAOP/bADn/2wA6/9wA'
        'S//XAEz/1wBP/9cAUP/xAFL/9ABT//QAVv+RAFf/3ABb/9IAXf/gAF//4ABh/+AAaP/vAGn/1gAMADr/4ABL/9wATP/cAE//3ABQ'
        '//YAUv/xAFP/8QBW/6AAV//gAFv/0gBo/+oAaf/gABcAG//lAB3/4QAe/+EAH//hACH/6gAp/+EAK//hAC3/8QAuAAUAMP/xADH/'
        '9gA4/+UAOf/lADr/9ABS/+oAU//qAFb/9gBX/9wAXf/2AF//9gBh//YAaP/7AGn/5QAOACr/7wAw/+kAOv/WAEv/tABM/7QAT/+0'
        'AFD/9gBS/+oAU//qAFb/eABX/9wAW/+CAGj/2wBp/8gABwAw//YATwAKAFD/9gBX/8gAW//0AGj/+wBp//EADAAW/4wAMP+qADf/'
        '9gBR/9IAUv/gAFP/4ABU/5YAV/+CAFz/9gBe//YAYP/2AGn/6gAFADD/4AAy//EAOv/0AFf/8QBp//EADQAW/+AAGP/qADD/9AAy'
        '/+oAN//0ADr/9ABR//QAVP/0AFb/yABX//QAW//SAGj/9gBp//QABgAw/6oAUf/lAFP/8QBU/9wAV/+WAFv/9AANADD/3AAy/9wA'
        'S//2AEz/9gBQ/+8AUf/IAFL/9gBT//YAVP/SAFb/0gBX/6oAW//IAGn/+wAIADD/6gAy/+oAS//vAEz/7wBP/+8AVv/SAFf/0gBb'
        '/+oAHAAD/9wAB//cAA//3AAR/9wAE//xABT/yAAV//QAFv++ABf/yAAZ/74AG//xAB3/9AAe//QAH//0ACD/4AAkADIAKf/0ACv/'
        '9AAt//YALv/qADD/1wAx/9wAM//qADQACgA4//EAOf/xAD7/4AA//+AACgAD//EAB//xAA//8QAR//EAFP/qABb/4AAX/+AAGf/c'
        'ACQAHgAuAAoACgAD//EAB//xAA//8QAR//EAFP/qABb/4AAX/+AAGf/cACQAKAAuAAoAGwAD/9wAB//cAA//3AAR/9wAE//xABT/'
        'yAAV//QAFv++ABf/yAAZ/74AG//xAB3/9AAe//QAH//0ACD/4AAkABQAKf/0ACv/9AAt//YALv/qADD/1wAx/9wAM//qADj/8QA5'
        '//EAPv/gAD//4AAWAAP/6gAH/+oAD//qABH/6gAT//sAFv/0ABf/9AAZ//QAG//2AB3/+wAe//sAH//7ACD/9gAp//sAK//7ADD/'
        '8QAx//YAM//0ADj/9gA5//YAPv/2AD//9gAgAAH/uQAD//YAB//2AAr/yAAP//YAEf/2ABP/9gAU//YAFv/0ABf/9AAY/+oAGf/g'
        'ABr/9gAb/+8AHf/qAB7/6gAf/+oAIAAUACH/4AAkABQAKf/qACv/6gAt//QALgAZADX/uQA2/6AAN//qADj/7wA5/+8AOv/0AD4A'
        'FAA/ABQADQAB/+AAFP/gABb/3AAX/+AAGP/cABn/vgAkABQALgAKADD/9AAx//EAMv/qADX/4AA2/9IADgAB/+AAFP/cABb/0gAX'
        '/9wAGP/SABn/uQAa/+oALf/2AC4ACgAw//QAMf/xADL/6gA1/+AANv/IABoAA//lAAf/5QAK/9IAD//lABH/5QAT//QAFP/2ABb/'
        '9AAX//QAGP/lABn/6gAb/9wAHf/bAB7/2wAf/9sAIf++ACQADwAp/9sAK//bAC3/wwAuABQANv9kADf/4AA4/9wAOf/cADr/4AAm'
        'AAH/ggAD/80AB//NAAr/vgAP/80AEf/NABP/3AAY//YAGv/0ABv/lgAd/6AAHv+gAB//oAAg/+oAIf+MACT/9gAn/9IAKP/SACn/'
        'oAAq/9IAK/+gACz/3AAt/5EALv/IAC//3AAw/9wAMf/gADL/3AAz/9wANP/IADX/ggA2/24AN//IADj/lgA5/5YAOv+gAD7/6gA/'
        '/+oAIgAD/80AB//NAA//zQAR/80AE//SABT/tAAV/+AAFv94ABf/mwAY/+oAGf+CABr/9AAb/9IAHf/cAB7/3AAf/9wAIP/gACH/'
        '9AAkAB4AKf/cACv/3AAt/+AALv++AC//9AAw/5EAMf+gADL/9gA0//QAN//qADj/0gA5/9IAOv/2AD7/4AA//+AAAgAW/9wAGP/c'
        'AB4AA/++AAf/vgAP/74AEf++ABP/3AAU/8gAFf/SABb/qgAX/8gAGP/0ABn/tAAa//QAG//cAB3/3AAe/9wAH//cACD/3AAkACgA'
        'Kf/cACv/3AAt/9IALv/gAC//6gAw/9IAMf/SADf/9AA4/9wAOf/cAD7/3AA//9wAAwAw/+AAMv/2ADr/6gACAAH/9gA1//YAHwAB'
        '/+oAA//2AAf/9gAK//YAD//2ABH/9gAT//YAFP/NABb/xAAX/84AGP/lABn/pgAb//YAHf/2AB7/9gAf//YAIf/2ACn/9gAr//YA'
        'Lf/2AC4ACgAw/+8AMf/sADL/5QAz/+8ANP/2ADX/6gA2/9wAN//0ADj/9gA5//YAIAAD//EAB//xAA//8QAR//EAE//7ABT/0gAW'
        '/8gAF//gABj/9AAZ/74AGv/vABv/9AAd//EAHv/xAB//8QAh//YAJAAKACf/9gAo//YAKf/xACr/9gAr//EALf/xAC8ACgAw//QA'
        'Mf/2ADL/6gAz/+oANv/0ADf/9AA4//QAOf/0AAIJ/gAEAAAKYgs2ACkAHwAAAAAAAP/2AAAAAAAA//YAAAAA/9wAAAAAAAD/4v/b'
        'AAAAAAAAAAD/9AAA/9IAAP/xAAAAAAAAAAAAAAAAAAD/8QAA/+D/1gAAAAD/9gAA/77/3P/x/9EAAP/v/+D/yP/b/+UAAP/7/+oA'
        'AAAAAAD/rwAA/9wAAAAA/80AAP/q//T/9AAAAAAAAP/7AAAAAP/b//YAAAAA//H/4AAAAAD/9AAA//EAAAAAAAAAAAAAAAAAAAAA'
        'AAAAAAAAAAAAAP/2AAAAAAAAAAAAAAAA/9YAAAAAAAD/9v/gAAAAAAAAAAD/+f/2/9IAAAAAAAAAAAAAAAAAAAAAAAD/7//W/+8A'
        'AP/qAAD/8QAA/4z/pv/0/6oAAP/n/77/qgAA/+oAAP/WAAAAAAAA//QAAAAA/6r/tP+0AAAAAP/2AAD/8f/vAAAAAAAAAAAAAP/q'
        'AAAAAAAA//H/9AAAAAD/8QAAAAD/9gAAAAAAAP/IAAAAAAAAAAAAAAAA//sAAAAAAAAAAAAAAAAAAAAA/8gAAAAAAAAAAP/bAAAA'
        'AAAAAAr/7wAA/9z/9AAAAAAAAP/qAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/9AAA'
        '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'
        'DwAAAAoAFQAEABkAAAADAAMAAAAAAAAAAAAYABgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
        'AAAAFwAXABcAAAAAABYAAAAWAAAAFgAcAB0AHAAdABsAGwACAAgAAQAIAAEALgAEAAAAEgBQAHYAhACEAIoAmACyALwAxgDcAQoB'
        'IAEuAS4BLgEuATQBNAACAAUASwBPAAAAUQBUAAUAVgBXAAkAWwBbAAsAYgBnAAwACQBR/+AAVP/gAFf/3ABi/+AAY//2AGT/4ABl'
        '//YAZv/gAGf/4AADAFH/4ABU/+AAV//cAAEAV//qAAMAUf/gAFT/6gBX/+AABgBL/8gATP/SAE//0gBW/6oAV//0AFv/oAACAFb/'
        '4ABX/+AAAgBW/9IAV//SAAUAS//gAE//6gBW/4IAV//0AFv/vgALAEv/3ABM/9wATf/qAE7/6gBP/+AAUf/gAFL/4ABT/9IAVP/0'
        'AFb/UABb/1oABQBR/+AAUv/gAFP/0gBU/4IAV/9QAAMAUf/gAFT/yABX/1oAAQBL/+oAAQBL//QAAAABAAAACgAmAEAAAkRGTFQA'
        'DmxhdG4ADgAEAAAAAP//AAIAAAABAAJjYWx0AA5saWdhABQAAAABAAAAAAABAAIAAwAIAHwAlgAGAAAABAAOACIAOABOAAMAAQBc'
        'AAEAeAABAFwAAQAAAAEAAwACAEIASAABAGQAAQBCAAEAAAABAAMAAQAyAAEATgACACwAMgABAAAAAQADAAIAFgAcAAEAOAABABwA'
        'AQAAAAEAAQABAEoAAgABAEAASQAAAAEAAAABAAgAAgAKAAIAcABwAAEAAgAYADIABAAIAAEACAABABoAAQAIAAIABgAMAD4AAgAj'
        'AD8AAgAmAAEAAQAgAAAAAQABAAgAAgAAABQAAgAAACQAAndnaHQBAAAAaXRhbAEWAAEABAAQAAEAAAAAARQDIAAAAAMAAQACARcA'
        'AAAAAAEAAA=='
    ),
}


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else guess_history_dir()
    app = CoachApp(folder)
    app.mainloop()


if __name__ == "__main__":
    main()
