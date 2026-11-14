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
TEMPO_FIGHTS = 4               # hallway fights measured after a pick
SLOW_TURNS_BY_ACT = {1: 3.5, 2: 4.0, 3: 4.5}   # avg turns per normal fight
SLOW_FIGHT_TURNS = 5           # a single hallway fight taking this many turns is "slow"
BIG_HIT_FRACTION = 0.30        # a fight costing >=30% of max HP is a "big hit"
ACT_ORDER = ["ACT.OVERGROWTH", "ACT.UNDERDOCKS", "ACT.HIVE", "ACT.GLORY"]
COMBAT_TYPES = ("monster", "elite", "boss")

# Colours - modern dark theme
BG = "#0f1115"          # window
SIDEBAR = "#14171d"
CARD = "#1b1f27"        # cards / panels
CARD_HI = "#232834"     # hover / selected
BORDER = "#2a303c"
FG = "#e6e8ee"
DIM = "#8a93a6"
FAINT = "#5c6475"
ACCENT = "#f0b35a"
GOOD = "#5fd38d"
BAD = "#ff6b6b"
WARN = "#ffb547"
INFO = "#6cb6ff"
PANEL = CARD
SEL = CARD_HI
CHAR_COLORS = {
    "Ironclad": "#ff6b6b", "Silent": "#5fd38d", "Defect": "#6cb6ff",
    "Regent": "#f0b35a", "Necrobinder": "#c792ea", "Fool": "#ff8fc7",
}
FALLBACK_COLORS = ["#7fdbca", "#f78c6c", "#82aaff", "#c3e88d", "#ffcb6b"]
UI_FONT = "Segoe UI"
UI_FONT_SEMI = "Segoe UI Semibold"
MONO_FONT = "Consolas"


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


def card_pick_impact(runs, include_abandoned, min_offered=MIN_OFFERED):
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
                                   if p and n == name and f["map_type"] != "shop")
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


def char_color(name, _cache={}):
    if name in CHAR_COLORS:
        return CHAR_COLORS[name]
    if name not in _cache:
        _cache[name] = FALLBACK_COLORS[len(_cache) % len(FALLBACK_COLORS)]
    return _cache[name]


# --------------------------------------------------------------------------
# Small modern widgets
# --------------------------------------------------------------------------
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
        "h1": dict(font=(UI_FONT_SEMI, 16), foreground=FG, spacing1=2, spacing3=6),
        "h2": dict(font=(UI_FONT_SEMI, 12), foreground=ACCENT, spacing1=14, spacing3=6),
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
        "actbar": dict(background=CARD_HI, foreground=ACCENT, font=(UI_FONT_SEMI, 11),
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
VIEWS = ("Habits & Fixes", "Stats", "Run Autopsy")


class CoachApp(tk.Tk):
    def __init__(self, history_dir):
        super().__init__()
        self.title("STS2 Coach")
        self.geometry("1440x920")
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
        # Sidebar
        self.sidebar = tk.Frame(self, bg=SIDEBAR, width=250)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Label(self.sidebar, text="STS2 Coach", bg=SIDEBAR, fg=FG,
                 font=(UI_FONT_SEMI, 17)).pack(anchor="w", padx=22, pady=(22, 0))
        tk.Label(self.sidebar, text="Slay the Spire 2 run analysis", bg=SIDEBAR, fg=FAINT,
                 font=(UI_FONT, 9)).pack(anchor="w", padx=22, pady=(0, 18))
        tk.Label(self.sidebar, text="CHARACTERS", bg=SIDEBAR, fg=FAINT,
                 font=(UI_FONT_SEMI, 8)).pack(anchor="w", padx=22, pady=(4, 6))
        self.char_list = tk.Frame(self.sidebar, bg=SIDEBAR)
        self.char_list.pack(fill="x", padx=10)

        bottom = tk.Frame(self.sidebar, bg=SIDEBAR)
        bottom.pack(side="bottom", fill="x", padx=18, pady=16)
        ttk.Checkbutton(bottom, text="Count quits as losses", variable=self.include_abandoned,
                        command=self.refresh_views).pack(anchor="w", pady=2)
        ttk.Checkbutton(bottom, text="Include co-op runs", variable=self.include_multi,
                        command=self.reload).pack(anchor="w", pady=2)
        ttk.Checkbutton(bottom, text="Auto-refresh on new runs", variable=self.auto_refresh).pack(anchor="w", pady=2)
        self._flat_button(bottom, "Change folder...", self._settings, bg=SIDEBAR).pack(anchor="w", pady=(10, 4))
        tk.Label(bottom, textvariable=self.status, bg=SIDEBAR, fg=FAINT, font=(UI_FONT, 8),
                 justify="left", wraplength=210, anchor="w").pack(anchor="w", fill="x")

        # Main area
        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        header = tk.Frame(main, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 8))
        self.title_dot = tk.Label(header, text="●", bg=BG, fg=ACCENT, font=(UI_FONT, 20))
        self.title_dot.pack(side="left")
        self.title_lbl = tk.Label(header, text=ALL, bg=BG, fg=FG, font=(UI_FONT_SEMI, 22))
        self.title_lbl.pack(side="left", padx=(6, 0))
        self.subtitle_lbl = tk.Label(header, text="", bg=BG, fg=DIM, font=(UI_FONT, 10))
        self.subtitle_lbl.pack(side="left", padx=14, pady=(8, 0))

        fbar = tk.Frame(main, bg=BG)
        fbar.pack(fill="x", padx=28, pady=(0, 10))
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
        self.cards_row.pack(fill="x", padx=28, pady=(4, 14))

        # Segmented tabs
        tabs = tk.Frame(main, bg=BG)
        tabs.pack(fill="x", padx=28)
        self.tab_widgets = {}
        for v in VIEWS:
            f = tk.Frame(tabs, bg=BG, cursor="hand2")
            f.pack(side="left", padx=(0, 26))
            lbl = tk.Label(f, text=v, bg=BG, fg=DIM, font=(UI_FONT_SEMI, 11), cursor="hand2")
            lbl.pack(pady=(0, 6))
            bar = tk.Frame(f, bg=BG, height=3)
            bar.pack(fill="x")
            for w in (f, lbl):
                w.bind("<Button-1>", lambda e, v=v: self.set_view(v))
            self.tab_widgets[v] = (lbl, bar)
        tk.Frame(main, bg=BORDER, height=1).pack(fill="x", padx=28)

        self.content = tk.Frame(main, bg=BG)
        self.content.pack(fill="both", expand=True, padx=28, pady=(14, 22))

        # View: habits
        self.habits_view = ScrollFrame(self.content)
        # View: stats
        self.stats_view, self.stats_txt = text_widget(self.content)
        # View: autopsy
        self.autopsy_view = tk.Frame(self.content, bg=BG)
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
        f = tk.Frame(parent, bg=CARD, padx=18, pady=12)
        f.pack(side="left", padx=(0, 12), fill="y")
        tk.Label(f, text=value, bg=CARD, fg=color, font=(UI_FONT_SEMI, 18)).pack(anchor="w")
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
        {"Habits & Fixes": self.habits_view, "Stats": self.stats_view,
         "Run Autopsy": self.autopsy_view}[view].pack(fill="both", expand=True)

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

        if len(losses) < 2:
            box = tk.Frame(inner, bg=CARD, padx=22, pady=20)
            box.pack(fill="x", pady=(0, 12))
            wrap_label(box, "Not enough losses yet to find patterns.", 13, weight="bold").pack(fill="x")
            wrap_label(box, f"Play a few more runs with {who} and this page will rank the habits that "
                            f"keep ending your runs.", 10, fg=DIM).pack(fill="x", pady=(4, 0))
            return

        # Focus banner
        if habits:
            top = habits[0]
            ban = tk.Frame(inner, bg="#2a2216", padx=22, pady=16)
            ban.pack(fill="x", pady=(0, 14))
            tk.Label(ban, text="YOUR #1 FOCUS RIGHT NOW", bg="#2a2216", fg=ACCENT,
                     font=(UI_FONT_SEMI, 8)).pack(anchor="w")
            wrap_label(ban, top["h"]["title"], 15, bg="#2a2216", weight="bold").pack(fill="x", pady=(2, 2))
            wrap_label(ban, top["h"]["fix"][0], 10, bg="#2a2216", fg="#e9d9bf").pack(fill="x")

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
                c = tk.Frame(chips, bg="#16261d", padx=12, pady=7)
                c.grid(row=j // 3, column=j % 3, sticky="ew", padx=(0, 8), pady=4)
                tk.Label(c, text="✓  " + it["h"]["title"], bg="#16261d", fg=GOOD,
                         font=(UI_FONT, 9), anchor="w").pack(anchor="w")
            for col in range(3):
                chips.grid_columnconfigure(col, weight=1)

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
        tk.Label(top, text=f"{rank}", bg=CARD, fg=FAINT, font=(UI_FONT_SEMI, 16)).pack(side="left", padx=(0, 12))
        tk.Label(top, text=h["title"], bg=CARD, fg=FG, font=(UI_FONT_SEMI, 13)).pack(side="left")
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
            tk.Label(row, text="→", bg=CARD, fg=ACCENT, font=(UI_FONT_SEMI, 10)).pack(side="left", anchor="n")
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
        self.selected_file = fname
        self.set_view("Run Autopsy")
        self._render_list()

    # ----- Stats view ----------------------------------------------------
    def _render_stats(self):
        t = self.stats_txt
        t.configure(state="normal")
        t.delete("1.0", "end")
        w = lambda s, *tags: t.insert("end", s, tags)
        runs = self.runs
        if not runs:
            w("No runs found.\n", "h1")
            w("Use 'Change folder...' in the sidebar to point at your STS2 saves\\history folder.\n", "dim")
            t.configure(state="disabled")
            return
        inc = self.include_abandoned.get()
        a = aggregate(runs, inc)
        nw, nl = len(a["wins"]), len(a["losses"])

        w("Record\n", "h2")
        w("  Wins ", "bold"); w(f"{nw}", "good")
        w("   Losses ", "bold"); w(f"{nl}", "bad")
        w(f"   Abandoned {len(a['abandoned'])}", "dim")
        w("   Win rate ", "bold"); w(f"{pct(nw, nw + nl):.1f}%\n", "good" if pct(nw, nw + nl) >= 25 else "warn")
        w(f"  Avg final deck: {a['deck_all']:.1f}   (wins {a['deck_win']:.1f} · losses {a['deck_loss']:.1f})\n")
        if self.character == ALL and a["chars"]:
            w("  By character: ", "dim")
            w("   ".join(f"{c} {v[0]}-{v[1]}" for c, v in sorted(a["chars"].items(), key=lambda kv: -sum(kv[1]))) + "\n")
        asc = Counter(r["ascension"] for r in a["wins"])
        if asc:
            w("  Wins by ascension: " + "   ".join(f"A{k}: {v}" for k, v in sorted(asc.items())) + "\n", "dim")

        w("Card rewards - pick vs skip\n", "h2")
        w(f"  {'Act':<30}{'Rewards':>8}{'Picked':>10}{'Skipped':>10}\n", "faint")
        for act in sorted(a["picks"]):
            offers, picked, names = a["picks"][act]
            lbl = f"Act {act} ({'/'.join(sorted(names))})"
            sk = pct(offers - picked, offers)
            w(f"  {lbl:<30}{offers:>8}{pct(picked, offers):>9.0f}%")
            w(f"{sk:>9.0f}%\n", "warn" if act == 1 and sk > 35 else "")

        w("Fight speed & damage\n", "h2")
        w(f"  {'Act':<26}{'Type':<9}{'Fights':>7}{'Avg turns':>11}{'Avg dmg':>10}\n", "faint")
        order = sorted(a["fights"], key=lambda k: (ACT_ORDER.index(k) if k in ACT_ORDER else 99, k))
        for act_id in order:
            num = a["act_num"].get(act_id, 0)
            for rt in COMBAT_TYPES:
                data = a["fights"][act_id].get(rt)
                if not data:
                    continue
                turns = avg([d[0] for d in data])
                dmg = avg([d[1] for d in data])
                limit = SLOW_TURNS_BY_ACT.get(num)
                slow = rt == "monster" and limit and turns > limit
                w(f"  {'Act ' + str(num) + ' ' + pretty_act(act_id):<26}{rt:<9}{len(data):>7}")
                w(f"{turns:>11.2f}", "bad" if slow else "good" if rt == "monster" else "")
                w(f"{dmg:>10.1f}")
                if slow:
                    w(f"   ◄ slow (target ≤ {limit})", "bad")
                w("\n")

        w("Resource leaks at death\n", "h2")
        if nl:
            gl, pl, al = len(a["gold_leak"]), len(a["pot_leak"]), len(a["any_leak"])
            w(f"  Died with >{GOLD_LEAK_THRESHOLD} unspent gold   ")
            w(f"{gl}/{nl}  ({pct(gl, nl):.0f}%)\n", "bad" if pct(gl, nl) >= 25 else "warn")
            w("  Died holding unused potions   ")
            w(f"{pl}/{nl}  ({pct(pl, nl):.0f}%)\n", "bad" if pct(pl, nl) >= 25 else "warn")
            w(f"  Either leak                   {al}/{nl}  ({pct(al, nl):.0f}%)\n", "bold")
            w(f"  Average gold at death: {a['avg_gold_at_death']:.0f}\n", "dim")
            pots = Counter(p for r in a["pot_leak"] for p in r["unused_potions"]).most_common(5)
            if pots:
                w("  Potions you most often die holding: " + ", ".join(f"{p} ×{n}" for p, n in pots) + "\n", "dim")
        else:
            w("  No losses in this view.\n", "dim")

        w("Nemesis list\n", "h2")
        if a["nemesis"]:
            top = a["nemesis"][0][1]
            for name, n in a["nemesis"]:
                w(f"  {name:<30}", "bold"); w(f"{n:>3}  "); w("█" * max(1, round(24 * n / top)) + "\n", "bad")
            w("  Deaths by act:  " + "   ".join(f"Act {k}: {v}" for k, v in sorted(a["death_act"].items())) + "\n", "dim")
            w("  Deaths by room: " + "   ".join(f"{k}: {v}" for k, v in a["death_room"].most_common()) + "\n", "dim")
        else:
            w("  Nothing has killed you yet here.\n", "good")

        self._card_impact_section(w, runs, inc)

        best, worst = card_insights(runs, inc)
        if best or worst:
            w("Card insights (cards you added, by final-deck win rate)\n", "h2")
            if best:
                w("  Show up in your wins\n", "good")
                for c, wn, n in best:
                    w(f"    {c:<28}{wn}/{n} won  ({pct(wn, n):.0f}%)\n")
            if worst:
                w("  Keep showing up in losses (never won with them)\n", "bad")
                for c, wn, n in worst:
                    w(f"    {c:<28}0/{n} won\n", "dim")
            w("  Small samples - treat as hints, not rules.\n", "faint")
        t.configure(state="disabled")

    def _card_impact_section(self, w, runs, inc):
        rows, meta = card_pick_impact(runs, inc)
        base, tb, lb = meta["base"], meta["tempo_base"], meta["lift_base"]
        w("Card Pick Impact\n", "h2")
        w(f"  Cards offered {MIN_OFFERED}+ times in card rewards (shops excluded), finished runs only. "
          f"Sorted by win-rate lift (weighted by sample size).\n", "dim", "ui")
        if base:
            w("  Act baselines (avg turns per hallway fight): "
              + "   ".join(f"{pretty_act(k)} {v:.2f}" for k, v in
                          sorted(base.items(), key=lambda kv: ACT_ORDER.index(kv[0]) if kv[0] in ACT_ORDER else 99))
              + "\n", "faint", "ui")
        if not rows:
            w(f"  No card has been offered {MIN_OFFERED}+ times with the current filters.\n", "dim")
            return
        hdr = (f"  {'Card':<22}{'Offered':>8}{'Pick%':>7}{'WR picked':>12}{'WR skipped':>12}{'Lift':>7}"
               f"{'Avg deck':>10}{'Tempo':>8}{'Removed':>9}   Flags\n")
        w(hdr, "faint")
        lifters, overdrafts = [], []
        for x in rows:
            w(f"  {x['card'][:21]:<22}", "bold")
            w(f"{x['offered']:>8}")
            w(f"{x['pick_pct']:>6.0f}%", "warn" if x["pick_pct"] >= 75 else "")
            wrp = f"{x['wr_p']:.0f}% ({x['np']})" if x["wr_p"] is not None else "-"
            wrs = f"{x['wr_s']:.0f}% ({x['ns']})" if x["wr_s"] is not None else "-"
            w(f"{wrp:>12}")
            w(f"{wrs:>12}", "dim")
            d = x["delta"]
            dtag = "" if d is None else "good" if d - lb >= 10 else "bad" if d - lb <= -10 else "dim"
            w(f"{('-' if d is None else f'{d:+.0f}'):>7}", dtag)
            deck = "-" if x["deck"] is None else f"{x['deck']:.1f}"
            w(f"{deck:>10}", "bad" if x["bloat"] else ("warn" if x["deck"] and x["deck"] >= BLOAT_DECK else ""))
            t = x["tempo"]
            ttag = "" if t is None else "good" if t - tb <= -0.4 else "bad" if t - tb >= 0.4 else "dim"
            w(f"{('-' if t is None else f'{t:+.2f}'):>8}", ttag)
            w(f"{x['removed']:>9}", "warn" if x["removed"] >= 2 else "dim")
            flags = []
            if d is not None and d - lb >= 10 and x["np"] >= 3:
                flags.append(("LIFTS WR", "good"))
                lifters.append(x)
            if d is not None and d - lb <= -10 and x["pick_pct"] >= 40 and x["np"] >= 3:
                flags.append(("OVER-DRAFTED", "bad"))
                overdrafts.append(x)
            if x["bloat"]:
                flags.append((f"BLOAT {x['bloat_n']}/{x['loss_n']}", "bad"))
            if t is not None and x["tempo_n"] >= 3:
                if t - tb >= 0.4:
                    flags.append(("SLOWS DECK", "warn"))
                elif t - tb <= -0.4:
                    flags.append(("SPEEDS UP", "good"))
            if x["removed"] >= 2 or (x["picks"] and x["removed"] / x["picks"] >= 0.3 and x["removed"] >= 1):
                flags.append(("REGRET", "warn"))
            w("   ")
            for label, tag in flags:
                w(f"{label}  ", tag)
            w("\n")
        w(f"  Lift = WR picked − WR skipped (run-level). Your typical card shows {lb:+.0f} (longer runs see and pick more "
          f"cards), so LIFTS WR / OVER-DRAFTED flag cards 10+ points above/below that.\n", "faint", "ui")
        w("  Tempo = avg turns in the next "
          f"{TEMPO_FIGHTS} hallway fights after picking it, vs that act's baseline (negative = faster).\n"
          f"  A typical pick scores {tb:+.2f} (decks get faster as an act goes on), so SPEEDS UP / SLOWS DECK "
          f"flag cards 0.4+ turns better/worse than that.\n"
          f"  Avg deck = final deck size in runs where you picked it.  BLOAT = 60%+ of its losing runs ended with "
          f"{BLOAT_DECK}+ cards (your overall rate: {meta['bloat_base']:.0%}).  Removed = times you later "
          f"removed it in the same run.\n", "faint", "ui")
        if lifters or overdrafts:
            w("  Takeaways\n", "bold")
            for x in sorted(lifters, key=lambda x: -x["delta"])[:3]:
                w(f"    ✔ {x['card']}: ", "good")
                w(f"you win {x['wr_p']:.0f}% when you take it vs {x['wr_s']:.0f}% when you don't - "
                  f"consider taking it more (picked {x['pick_pct']:.0f}% now).\n", "ui")
            for x in sorted(overdrafts, key=lambda x: x["delta"])[:3]:
                w(f"    ✖ {x['card']}: ", "bad")
                w(f"picked {x['pick_pct']:.0f}% of the time, but its lift ({x['delta']:+.0f}) is well below your "
                  f"typical card ({lb:+.0f}) - try skipping it unless it fills a clear need.\n", "ui")
        w("  Small samples - a card needs many offers before these numbers mean much.\n", "faint", "ui")

    # ----- Autopsy view --------------------------------------------------
    def _render_list(self):
        keep = self.selected_file
        cols = ("date", "char", "asc", "result", "floor", "killer")
        self.tree.configure(displaycolumns=cols if self.character == ALL
                            else tuple(c for c in cols if c != "char"))
        self.tree.delete(*self.tree.get_children())
        for r in self.runs:
            date = datetime.fromtimestamp(r["start"]).strftime("%d %b %H:%M") if r["start"] else "?"
            char = r["character"] + (" (co-op)" if r["multiplayer"] else "")
            res = {"WIN": "✔ Win", "LOSS": "✖ Loss", "ABANDONED": "– Quit"}[r["result"]]
            self.tree.insert("", "end", iid=r["file"], tags=(r["result"],),
                             values=(date, char, r["ascension"], res, r["final_floor"],
                                     "" if r["win"] else r["killer"]))
        target = keep if keep and self.tree.exists(keep) else (self.runs[0]["file"] if self.runs else None)
        if target:
            self.tree.selection_set(target)
            self.tree.see(target)
            self.selected_file = target
            self._render_autopsy(next((r for r in self.runs if r["file"] == target), None))
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


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else guess_history_dir()
    app = CoachApp(folder)
    app.mainloop()


if __name__ == "__main__":
    main()
