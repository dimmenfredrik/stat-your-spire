#!/usr/bin/env python3
"""
sts2_coach_v4.py - Slay the Spire 2 coach, version 4 (local web app).

Starts a tiny built-in web server on http://localhost:8766 and opens it in your browser.
  * Separate from the old versions - sts2_coach.py and sts2_coach_v2 are not touched.
  * Reads only finished *.run files in your history folder (never writes there,
    never opens current_run.save).
  * Same analysis code as v1/v2 (numbers match). The page (index.html) loads Tailwind CSS,
    Chart.js and the Inter font from the internet (CDN), so you need to be online.
  * Settings (history folder, optional character display names) live in settings.json
    next to this file.
"""

import json
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime

# ==========================================================================
# ==========  ANALYSIS CODE COPIED UNCHANGED FROM sts2_coach.py  ===========
# ==========================================================================
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


CHAR_COLORS = {
    "Ironclad": "#ff7b7b", "Silent": "#9be37c", "Defect": "#86c8ff",
    "Regent": "#ff9a52", "Necrobinder": "#d3a6ff", "Fool": "#ffe066",
}
FALLBACK_COLORS = ["#7fdbca", "#f78c6c", "#82aaff", "#c3e88d", "#ffcb6b"]


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
CHARACTER_DISPLAY = {}      # filled from settings.json "character_names", e.g. {"Fool": "New Name"}


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
                "monster_ids": [str(m) for m in (combat_rooms[0].get("monster_ids") or [])] if combat_rooms else [],
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
                # --- added for the Decisions view (nothing existing reads these) ---
                "shop_relics": [pretty(r) for r in s.get("bought_relics") or []],
                "shop_potions": [pretty(r) for r in s.get("bought_potions") or []],
                "ancient": [(pretty("X." + str(c.get("TextKey") or "")), bool(c.get("was_chosen")))
                            for c in s.get("ancient_choice") or []],
                "ancient_name": pretty(rooms[0].get("model_id")) if rooms else "",
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
        "character": CHARACTER_DISPLAY.get(pretty(player.get("character")), pretty(player.get("character"))) or "?",
        "character_id": player.get("character") or "",
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
        "deck": [{"n": pretty(c.get("id")), "u": c.get("current_upgrade_level") or 0, "f": c.get("floor_added_to_deck") or 0} for c in player.get("deck") or []],
        "relics_final": [pretty(x.get("id")) for x in player.get("relics") or []],
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


def gameplan_fixes(runs, include_abandoned, n_last=5):
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
             why=lambda r, v: "Won the run" if r["win"] else (f"Died with {r['final_gold']} gold (goal: {GOLD_LEAK_THRESHOLD} or less)" if not v else f"Died with only {r['final_gold']} gold"),
             ok_word="spent gold well", scope="losses"),
        dict(id="potions", title="Drink your potions",
             check=lambda r: True if r["win"] else not r["unused_potions"],
             detail=lambda bad, rs: (f"Died holding potions in {len(bad)}/{len(rs)} losses "
                                     f"({', '.join(sorted({p for r in bad for p in r['unused_potions']})[:3])})."),
             target="Use a potion the moment a fight will cost 40%+ HP - never die with a full belt.",
             why=lambda r, v: "Won the run" if r["win"] else (f"Died holding {len(r['unused_potions'])} potion{'s' if len(r['unused_potions']) != 1 else ''}" if not v else "Used every potion"),
             ok_word="used their potions", scope="losses"),
        dict(id="slow_a1", title="Kill Act 1 hallways faster",
             check=lambda r: None if a1_avg(r) is None else a1_avg(r) <= SLOW_A1_GAMEPLAN,
             detail=lambda bad, rs: (f"{len(bad)}/{len(rs)} runs averaged >{SLOW_A1_GAMEPLAN} turns per Act 1 "
                                     f"hallway fight (worst {max(a1_avg(r) for r in bad):.1f})."),
             target=f"Take frontloaded damage with your first 3 card rewards; aim for ≤{SLOW_A1_GAMEPLAN} turns per hallway.",
             why=lambda r, v: (f"Act 1 hallway fights took {a1_avg(r):.1f} turns on average (goal: {SLOW_A1_GAMEPLAN} or less)" if a1_avg(r) is not None else ""),
             ok_word="had fast Act 1 fights", scope="runs"),
        dict(id="a2_skip", title="Skip more in Act 2",
             check=lambda r: (None if _act2_rewards(r)[0] < 3 else _act2_rewards(r)[1] >= 1),
             detail=lambda bad, rs: (f"Took a card from every Act 2 reward in {len(bad)}/{len(rs)} runs "
                                     f"that saw 3+ Act 2 rewards."),
             target="In Act 2, skip at least 1-2 rewards that don't add AoE, scaling or block.",
             why=lambda r, v: ("Skipped at least one Act 2 card reward" if v else "Took a card from every Act 2 reward"),
             ok_word="skipped in Act 2", scope="runs"),
        dict(id="lowhp", title="Don't enter fights low",
             check=lambda r: (True if r["win"] else (None if _fatal_entry_hp(r) is None else _fatal_entry_hp(r) >= 0.5)),
             detail=lambda bad, rs: (f"Entered the fight that killed you below 50% HP in {len(bad)}/{len(rs)} losses."),
             target="Below 50% HP: rest at campfires and path around elites until you're healthy.",
             why=lambda r, v: "Won the run" if r["win"] else ((f"Entered the fatal fight at {100 * _fatal_entry_hp(r):.0f}% HP" if _fatal_entry_hp(r) is not None else "") + (" (goal: 50% or more)" if not v else "")),
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
        last5 = [v for _, v in res if v is not None][:n_last]
        runs_n = []   # the same runs as last5, newest first, with a short reason (shown when you hover a run in the focus tab)
        for r, v in res:
            if v is None:
                continue
            b = run_brief(r)
            b["ok"] = bool(v)
            try:
                b["why"] = c["why"](r, v) if c.get("why") else ""
            except Exception:
                b["why"] = ""
            runs_n.append(b)
        out.append(dict(id=c["id"], title=c["title"], rate=rate, detail=c["detail"](bad, [r for r, _ in rel]),
                        target=c["target"], last5=last5, ok_word=c["ok_word"], last_runs=runs_n[:n_last]))
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



# ==========================================================================
# ==========  END OF ANALYSIS CODE COPIED FROM sts2_coach.py  ==============
# ==========================================================================
# Everything below is new for v2: it only arranges the numbers above for the
# HTML interface. The calculations that used to live in the tkinter screens
# (filters, sidebar records, header cards, verdicts...) are ported 1:1.

ALL = "All characters"
HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "settings.json")
LOG_FILE = os.path.join(HERE, "sts2_coach_v4.log")


def log_error(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    # settings.json lives in the sts2_coach_v2 folder - never in the game folder
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def fmt_date(ts, fmt):
    return datetime.fromtimestamp(ts).strftime(fmt) if ts else "?"


def scope_runs(rs, asc, range_filter, current_build):
    """Header filters - same logic as CoachApp._scope in v1."""
    if asc != "All":
        n = int(asc.strip("A+"))
        rs = [r for r in rs if (r["ascension"] >= n if asc.endswith("+") else r["ascension"] == n)]
    if range_filter == "Current build":
        rs = [r for r in rs if r["build"] == current_build]
    rs = sorted(rs, key=lambda r: r["start"], reverse=True)
    if range_filter.startswith("Last "):
        rs = rs[: int(range_filter.split()[1])]
    return rs


def biome_act_ids(runs, biome):
    if biome == "All acts":
        return None
    return {a for r in runs for f in r["floors"] for a in [f["act_id"]] if pretty_act(a) == biome}


def guide_rows(runs, inc, act_ids, n):
    """Port of CoachApp._guide_rows: verdicts + notes for every card."""
    rows, meta = card_pick_impact(runs, inc, min_offered=1, act_ids=act_ids)
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
                notes.append(["faster fights", "good"])
            elif x["trel"] >= 0.4:
                notes.append(["slower fights", "warn"])
        if x["bloat"]:
            notes.append(["bloated losses", "bad"])
        if x["removed"] >= 2 or (x["picks"] and x["removed"] and x["removed"] / x["picks"] >= 0.3):
            notes.append(["often removed", "warn"])
        x["notes"] = notes
    return rows, meta, base


def card_json(x):
    keys = ("card", "offered", "picks", "pick_pct", "np", "ns", "wr_p", "wr_s", "delta", "deck", "tempo",
            "tempo_n", "removed", "verdict", "notes", "score", "bloat")
    return {k: x.get(k) for k in keys}



# --------------------------------------------------------------------------
# Danger list (new in v4): which fights cost the most HP and which ones ended runs.
# Read-only summary of finished runs; does not touch any habit thresholds.
# --------------------------------------------------------------------------
BB_MIN_RUNS = 5          # a character needs this many decided runs to get a builds page
BB_MIN_CARD = 4          # a card/relic needs to show up in this many runs before it counts


def best_builds(runs, inc):
    """Per character: what wins and what loses, read from the final deck + relics of finished runs.
    Only counts and win rates of your own runs - no new scoring, no thresholds beyond LEAN_DECK / BLOAT_DECK."""
    by = defaultdict(list)
    for r in runs:
        if r["win"] or is_loss(r, inc):
            by[r["character"]].append(r)
    out = []
    for ch, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        w = [r for r in rs if r["win"]]
        n, nw = len(rs), len(w)
        base = pct(nw, n)
        lo = [r for r in rs if not r["win"]]

        def picked(r):          # cards taken during the run (not the starting deck), upgraded ones count as the plain card
            return {c["n"] for c in r["deck"] if (c.get("f") or 0) > 1}

        def wr_of(sel):
            return pct(sum(1 for r in sel if r["win"]), len(sel))

        # cards: win rate in runs whose final deck has the card vs runs without it
        cstat = {}
        for r in rs:
            for c in picked(r):
                cstat.setdefault(c, []).append(r)
        cards = []
        for c, has in cstat.items():
            if len(has) < BB_MIN_CARD:
                continue
            hs = set(id(x) for x in has)
            without = [r for r in rs if id(r) not in hs]
            if len(without) < BB_MIN_CARD:
                continue
            up = sum(1 for r in has for d in r["deck"] if d["n"] == c and d["u"]) > len(has) / 2
            cards.append({"n": c, "runs": len(has), "wins": sum(1 for x in has if x["win"]), "wr": round(wr_of(has), 1),
                          "lift": round(wr_of(has) - wr_of(without)), "up": up})
        good = sorted([c for c in cards if c["lift"] >= 10], key=lambda c: (-c["lift"], -c["runs"]))[:5]
        bad = sorted([c for c in cards if c["lift"] <= -10], key=lambda c: (c["lift"], -c["runs"]))[:5]

        def core(sel):          # win rate of runs that hold at least 2 of the shown cards (1 if that is too few runs)
            names = {c["n"] for c in sel}
            for k in (2, 1):
                runs_k = [r for r in rs if len(names & picked(r)) >= k]
                if len(runs_k) >= 3 or k == 1:
                    return {"runs": len(runs_k), "wins": sum(1 for r in runs_k if r["win"]), "wr": round(wr_of(runs_k)), "k": k}

        # relics
        rstat = {}
        for r in rs:
            for x in set(r["relics_final"]):
                rstat.setdefault(x, []).append(r)
        relics = [{"n": x, "runs": len(v), "wins": sum(1 for r in v if r["win"]), "wr": round(wr_of(v))}
                  for x, v in rstat.items() if len(v) >= BB_MIN_CARD]
        relics.sort(key=lambda x: (-x["wr"], -x["runs"]))
        best_relics = [x for x in relics if x["wr"] > base][:4]

        # deck size
        lean = [r for r in rs if r["deck_size"] <= LEAN_DECK]
        bloat = [r for r in rs if r["deck_size"] >= BLOAT_DECK]
        size = lambda sel: {"runs": len(sel), "wins": sum(1 for r in sel if r["win"]), "wr": round(wr_of(sel))}

        # who kills you
        kills = defaultdict(list)
        for r in lo:
            foe, kind, label = _end_foe(r)
            if r["killer"]:
                kills[r["killer"]].append((foe, kind))
        top = sorted(kills.items(), key=lambda kv: -len(kv[1]))[:1]
        killer = None
        if top and lo:
            name, lst = top[0]
            killer = {"name": name, "n": len(lst), "of": len(lo), "foe": lst[0][0], "kind": lst[0][1]}

        # recent form: your 10 newest finished runs of this character that match each build (rs is newest first)
        last10 = rs[:10]

        def recent(match):
            sel = [r for r in last10 if match(r)]
            return {"n": len(sel), "wins": sum(1 for r in sel if r["win"])}

        gnames = {c["n"] for c in good}
        bnames = {c["n"] for c in bad}
        gk = (core(good) or {}).get("k", 1) if good else 1
        bk = (core(bad) or {}).get("k", 1) if bad else 1
        # pairs that win together (same thresholds as the pair table used elsewhere)
        strong = pair_table(rs, inc)
        top_pairs = sorted(strong.values(), key=lambda s: (-s["win_share"], -s["lift"], s["a"], s["b"]))[:3]
        pairs = [{"a": s["a"], "b": s["b"], "n": s["n"], "w": s["w"], "wr": round(s["wr"]), "lift": round(s["lift"]),
                  "recent": recent(lambda r, a=s["a"], b=s["b"]: a in picked(r) and b in picked(r))} for s in top_pairs]

        out.append({
            "pairs": pairs,
            "last10": {"n": len(last10), "wins": sum(1 for r in last10 if r["win"]),
                       "before_n": n - len(last10), "before_wins": nw - sum(1 for r in last10 if r["win"])},
            "lean_recent": recent(lambda r: r["deck_size"] <= LEAN_DECK),
            "bloat_recent": recent(lambda r: r["deck_size"] >= BLOAT_DECK),
            "good_recent": recent(lambda r: len(gnames & picked(r)) >= gk) if good else None,
            "bad_recent": recent(lambda r: len(bnames & picked(r)) >= bk) if bad else None,
            "character": ch, "color": char_color(ch), "runs": n, "wins": nw, "wr": round(base),
            "enough": n >= BB_MIN_RUNS,
            "avg_win": round(avg([r["deck_size"] for r in w])) if w else None,
            "avg_loss": round(avg([r["deck_size"] for r in lo])) if lo else None,
            "best_relic": best_relics[0] if best_relics else None,
            "good_cards": good, "good_core": core(good) if good else None,
            "bad_cards": bad, "bad_core": core(bad) if bad else None,
            "relics": best_relics, "lean": size(lean) if lean else None, "bloat": size(bloat) if bloat else None,
            "killer": killer, "lean_max": LEAN_DECK, "bloat_min": BLOAT_DECK,
        })
    return out


def danger_list(runs, inc, limit=10):
    stats = {}
    for r in runs:
        lost = is_loss(r, inc)
        for i, f in enumerate(r["floors"]):
            if not f["is_combat"] or not f["encounter"]:
                continue
            e = stats.setdefault(f["encounter"], {"name": f["label"], "kind": f["room_type"], "n": 0, "dmg": 0,
                                                  "worst": 0, "maxhp": [], "deaths": 0})
            e["n"] += 1
            e["dmg"] += f["damage"]
            e["worst"] = max(e["worst"], f["damage"])
            if f["max_hp"]:
                e["maxhp"].append(f["max_hp"])
            if lost and i == len(r["floors"]) - 1 and r.get("killer_id") == f["encounter"]:
                e["deaths"] += 1
    out = []
    for enc, e in stats.items():
        if e["n"] < 2 and e["deaths"] < 1:
            continue
        avg_dmg = e["dmg"] / e["n"]
        avg_max = sum(e["maxhp"]) / len(e["maxhp"]) if e["maxhp"] else 0
        out.append({"name": e["name"], "kind": e["kind"], "n": e["n"], "deaths": e["deaths"],
                    "avg_dmg": round(avg_dmg), "worst": e["worst"],
                    "pct": round(avg_dmg / avg_max * 100) if avg_max else 0})
    out.sort(key=lambda x: (-x["deaths"], -x["pct"], -x["n"]))
    return out[:limit]

def _end_foe(r):
    """The last combat of a run: the fight that killed you, or the final boss you beat (for the pictures)."""
    fl = r["floors"][-1] if r["floors"] else None
    if not fl or not fl.get("is_combat"):
        return "", "", ""
    if not r["win"] and r.get("killer_id") != fl.get("encounter"):
        return "", "", ""
    mons = fl.get("monster_ids") or []
    mon = mons[0].split(".")[-1].lower() if mons else ""
    return mon, fl.get("room_type") or "", fl.get("label") or ""


def run_brief(r):
    foe, kind, foe_name = _end_foe(r)
    return {
        "foe": foe, "foe_kind": kind, "foe_name": foe_name,
        "file": r["file"], "character": r["character"], "multiplayer": r["multiplayer"],
        "date": fmt_date(r["start"], "%d %b %H:%M"), "start": r["start"], "ascension": r["ascension"],
        "result": r["result"], "final_floor": r["final_floor"], "killer": "" if r["win"] else r["killer"],
        "win": r["win"],
    }


# --------------------------------------------------------------------------
# Decisions view (new in v2): elites per act, campfires, shops, events, ancients.
# Pure additions - none of the existing analysis above is used or changed.
# --------------------------------------------------------------------------
def _wr(rs):
    n = len(rs)
    w = sum(1 for r in rs if r["win"])
    return {"n": n, "w": w, "pct": pct(w, n) if n else None}


def decisions(runs, inc):
    decided = [r for r in runs if r["win"] or is_loss(r, inc)]
    out = {"n_decided": len(decided), "base": _wr(decided)}

    # 1. Elites per act (only runs that got through that act, so early deaths don't skew it)
    acts = []
    for n in (1, 2, 3):
        fin = [r for r in decided if r["win"] or r["final_act"] > n]
        buckets = {"0": [], "1": [], "2": [], "3+": []}
        elite_fights = []
        deaths = 0
        for r in decided:
            ef = [f for f in r["floors"] if f["act"] == n and f["map_type"] == "elite"]
            elite_fights += ef
            if (not r["win"]) and r["final_act"] == n and r["floors"] and r["floors"][-1]["map_type"] == "elite":
                deaths += 1
        for r in fin:
            c = sum(1 for f in r["floors"] if f["act"] == n and f["map_type"] == "elite")
            buckets["3+" if c >= 3 else str(c)].append(r)
        acts.append({
            "act": n, "finished": len(fin),
            "buckets": [dict(label=k, **_wr(v)) for k, v in buckets.items()],
            "fights": len(elite_fights), "deaths": deaths,
            "avg_dmg": avg([f["damage"] for f in elite_fights]) if elite_fights else None,
            "avg_turns": avg([f["turns"] for f in elite_fights]) if elite_fights else None,
        })
    out["elites"] = acts

    # 2. Campfires
    def hp_bucket(p):
        return "under 50%" if p < 50 else ("50-69%" if p < 70 else "70%+")
    cells = defaultdict(lambda: {"n": 0, "soon": 0})
    totals = defaultdict(int)
    for r in decided:
        for f in r["floors"]:
            if f["map_type"] != "rest_site" or not f["rest"] or not f["max_hp"]:
                continue
            choice = f["rest"][0]
            kind = "Rest" if choice.lower().startswith(("heal", "rest")) else (
                "Smith" if choice.lower().startswith("smith") else "Other")
            before = (f["hp"] or 0) - (f["healed"] if kind == "Rest" else 0)
            b = hp_bucket(100.0 * max(before, 0) / f["max_hp"])
            c = cells[(kind, b)]
            c["n"] += 1
            totals[kind] += 1
            if (not r["win"]) and r["final_floor"] <= f["floor"] + 3:
                c["soon"] += 1
    camp_rows = []
    for kind in ("Rest", "Smith", "Other"):
        for b in ("under 50%", "50-69%", "70%+"):
            c = cells.get((kind, b))
            if c and c["n"]:
                camp_rows.append({"kind": kind, "hp": b, "n": c["n"], "share": pct(c["n"], totals[kind]),
                                  "soon_pct": pct(c["soon"], c["n"])})
    deep = [r for r in decided if r["final_act"] >= 3]
    smith_b = {"0-3 upgrades": [], "4-5 upgrades": [], "6+ upgrades": []}
    for r in deep:
        sm = sum(1 for f in r["floors"] for x in f["rest"] if x.lower().startswith("smith"))
        smith_b["0-3 upgrades" if sm <= 3 else ("4-5 upgrades" if sm <= 5 else "6+ upgrades")].append(r)
    out["camps"] = {"rows": camp_rows, "totals": dict(totals), "deep_n": len(deep),
                    "smith": [dict(label=k, **_wr(v)) for k, v in smith_b.items()]}

    # 3. Shops
    visited = [r for r in decided if any(f["map_type"] == "shop" for f in r["floors"])]
    def shop_has(r, kind):
        for f in r["floors"]:
            if f["map_type"] != "shop":
                continue
            if kind == "Card removal" and f["removed"]:
                return True
            if kind == "Relic" and f["shop_relics"]:
                return True
            if kind == "Potion" and f["shop_potions"]:
                return True
            if kind == "Colorless card" and f["bought_cards"]:
                return True
            if kind == "Card" and any(p for _, p in f["card_choices"]):
                return True
        return False
    items = []
    for kind in ("Card removal", "Relic", "Card", "Colorless card", "Potion"):
        yes = [r for r in visited if shop_has(r, kind)]
        no = [r for r in visited if not shop_has(r, kind)]
        items.append({"kind": kind, "yes": _wr(yes), "no": _wr(no)})
    leave = []
    relic_buys = defaultdict(list)
    for r in visited:
        for f in r["floors"]:
            if f["map_type"] == "shop":
                leave.append(f["gold"] or 0)
                for x in f["shop_relics"]:
                    relic_buys[x].append(r)
    out["shops"] = {
        "visited": len(visited), "visits": len(leave), "items": items,
        "avg_left": avg(leave) if leave else None,
        "leak_pct": pct(sum(1 for g in leave if g > GOLD_LEAK_THRESHOLD), len(leave)) if leave else None,
        "relics": sorted([dict(name=k, **_wr(v)) for k, v in relic_buys.items() if len(v) >= 2],
                         key=lambda x: (-x["n"], x["name"]))[:12],
    }

    # 4. Events (non-ancient)
    seen = defaultdict(lambda: defaultdict(list))     # event -> choice -> [(run, hpnet, goldnet)]
    for r in decided:
        for f in r["floors"]:
            if f["map_type"] == "ancient" or not f["events"]:
                continue
            for ch in f["events"]:
                ev = ch.split(": ")[0]
                seen[ev][ch].append((r, f["healed"] - f["damage"], f["gold_gained"] - f["gold_spent"] - f["gold_lost"]))
    ev_rows = []
    for ev, chs in seen.items():
        for ch, lst in chs.items():
            mine = {id(x[0]) for x in lst}
            other = [x[0] for c2, l2 in chs.items() if c2 != ch for x in l2 if id(x[0]) not in mine]
            rs = {id(x[0]): x[0] for x in lst}.values()
            ev_rows.append({
                "event": ev, "choice": ch.split(": ", 1)[1] if ": " in ch else ch, "times": len(lst),
                "win": _wr(list(rs)), "other": _wr(list({id(o): o for o in other}.values())),
                "hp": avg([x[1] for x in lst]), "gold": avg([x[2] for x in lst]),
            })
    ev_rows = [e for e in ev_rows if e["times"] >= 3]
    ev_rows.sort(key=lambda e: (-e["times"], e["event"], e["choice"]))
    out["events"] = ev_rows[:60]

    # 5. Ancients (Neow + Act 2/3)
    anc = defaultdict(lambda: {"off": [], "took": []})
    for r in decided:
        for f in r["floors"]:
            if f["map_type"] != "ancient":
                continue
            grp = "Neow" if f["act"] == 1 else "Act 2/3 ancient"
            for name, chosen in f["ancient"]:
                a = anc[(grp, name)]
                a["off"].append(r)
                if chosen:
                    a["took"].append(r)
    arows = []
    for (grp, name), a in anc.items():
        took = a["took"]
        ids = {id(r) for r in took}
        passed = [r for r in a["off"] if id(r) not in ids]
        if len(a["off"]) < 3:
            continue
        arows.append({"group": grp, "relic": name, "offered": len(a["off"]), "taken": len(took),
                      "take_pct": pct(len(took), len(a["off"])), "win_taken": _wr(took), "win_passed": _wr(passed)})
    arows.sort(key=lambda x: (x["group"] != "Neow", -x["offered"], x["relic"]))
    out["ancients"] = arows
    return out



# --------------------------------------------------------------------------
# Missed pairings, floor strips and turning points (new in v2).
# Pure additions - none of the existing analysis above is used or changed.
# --------------------------------------------------------------------------
PAIR_MIN_RUNS = 4        # a pair must appear in at least this many finished runs...
PAIR_MIN_WINS = 2        # ...and in at least this many wins
PAIR_MIN_LIFT = 10.0     # and lift win rate by at least this many points (runs with pair vs without)
TP_GOLD = 200            # "200g+ UNSPENT"
TP_BLEED = 20            # "HEAVY BLEED (-20+ HP)"
TP_MAX = 3               # critical floors tagged per run


def _picked_names(f):
    out = [n for n, p in f["card_choices"] if p]
    out += list(f["cards_other"]) + list(f["bought_cards"])
    return out


def pair_table(runs, inc):
    """Card pairs (from the cards you added after floor 1) that lift win rate. Returns dict pair -> stats."""
    from itertools import combinations
    decided = [r for r in runs if r["win"] or is_loss(r, inc)]
    n_all = len(decided)
    n_win = sum(1 for r in decided if r["win"])
    cnt = defaultdict(lambda: [0, 0])
    for r in decided:
        for pair in combinations(sorted(set(r["deck_added"])), 2):
            cnt[pair][0] += 1
            cnt[pair][1] += 1 if r["win"] else 0
    strong = {}
    for pair, (n, w) in cnt.items():
        if n < PAIR_MIN_RUNS or w < PAIR_MIN_WINS or n_all - n < 3:
            continue
        lift = pct(w, n) - pct(n_win - w, n_all - n)
        if lift >= PAIR_MIN_LIFT:
            strong[pair] = {"a": pair[0], "b": pair[1], "n": n, "w": w, "lift": lift,
                            "win_share": pct(w, n_win) if n_win else 0.0, "wr": pct(w, n)}
    return strong


def _skipped_with_partner(r, strong):
    """Yield (floor_dict, skipped_card, partner_card, stats) for every skipped reward where you already
    held a card that pairs well with it (and you never ended up taking the skipped card)."""
    held = set()
    final = set(r["deck_added"])
    for f in r["floors"]:
        if f["card_choices"] and f["map_type"] != "shop":
            for n, p in f["card_choices"]:
                if p or n in final:
                    continue
                best = None
                for a in held:
                    st = strong.get(tuple(sorted((a, n))))
                    if st and (best is None or st["lift"] > best[1]["lift"]):
                        best = (a, st)
                if best:
                    yield f, n, best[0], best[1]
        held.update(_picked_names(f))


def pairings(runs, inc, character):
    if character == ALL:
        return {"single": False}
    strong = pair_table(runs, inc)
    top = sorted(strong.values(), key=lambda s: (-s["win_share"], -s["lift"], s["a"], s["b"]))[:6]
    agg = {}
    for r in sorted(runs, key=lambda r: r["start"], reverse=True):
        if not is_loss(r, inc):
            continue
        for f, b, a, st in _skipped_with_partner(r, strong):
            e = agg.setdefault(b, {"card": b, "partners": defaultdict(int), "runs": {}, "best": st, "best_a": a})
            e["partners"][a] += 1
            if st["lift"] > e["best"]["lift"]:
                e["best"], e["best_a"] = st, a
            e["runs"].setdefault(r["file"], (r, f["floor"]))
    rows = []
    for b, e in agg.items():
        st = e["best"]
        rows.append({
            "card": b, "partner": e["best_a"], "times": len(e["runs"]),
            "win_share": st["win_share"], "lift": st["lift"], "n": st["n"], "w": st["w"],
            "examples": [{"file": r["file"], "label": f"{fmt_date(r['start'], '%d %b')} · F{fl}"}
                         for r, fl in list(e["runs"].values())[:4]],
        })
    rows.sort(key=lambda x: (-(x["times"] * x["lift"]), x["card"]))
    return {"single": True, "n_strong": len(strong), "top_pairs": top, "missed": rows[:8],
            "n_wins": sum(1 for r in runs if r["win"]), "min_runs": PAIR_MIN_RUNS,
            "min_wins": PAIR_MIN_WINS, "min_lift": PAIR_MIN_LIFT}


def _gold_lvl(g):
    return 2 if g >= GOLD_LEAK_THRESHOLD else (1 if g >= 100 else 0)


def _hp_lvl(frac):
    return 2 if frac >= BIG_HIT_FRACTION else (1 if frac >= 0.15 else 0)


def floor_strips(runs, inc):
    """Colour-block data: latest run and the average of your losses, floor by floor."""
    out = {"latest": None, "avg_loss": None}
    if runs:
        r = next((x for x in runs if x["win"] or is_loss(x, inc)), runs[0])     # newest finished run
        fl = []
        for f in r["floors"]:
            mx = f["max_hp"] or 0
            reward = f["card_choices"] and f["map_type"] != "shop"
            fl.append({"floor": f["floor"], "act": f["act"], "label": f["label"],
                       "gold": f["gold"] or 0, "gold_lvl": _gold_lvl(f["gold"] or 0),
                       "dmg": f["damage"], "hp_lvl": _hp_lvl(f["damage"] / mx) if mx else 0,
                       "card": None if not reward else ("pick" if any(p for _, p in f["card_choices"]) else "skip")})
        out["latest"] = {"file": r["file"], "result": r["result"], "character": r["character"],
                         "date": fmt_date(r["start"], "%d %b %H:%M"), "floors": fl}
    losses = [r for r in runs if is_loss(r, inc)]
    if len(losses) >= 3:
        top = max(r["final_floor"] for r in losses)
        rows = []
        for i in range(1, top + 1):
            here = [f for r in losses for f in r["floors"] if f["floor"] == i]
            if len(here) < 3:
                break
            gold = avg([f["gold"] or 0 for f in here])
            frac = avg([f["damage"] / f["max_hp"] if f["max_hp"] else 0 for f in here])
            rew = [any(p for _, p in f["card_choices"]) for f in here if f["card_choices"] and f["map_type"] != "shop"]
            rows.append({"floor": i, "act": here[0]["act"], "n": len(here), "gold": gold, "gold_lvl": _gold_lvl(gold),
                         "dmg": avg([f["damage"] for f in here]),
                         "hp_lvl": 2 if frac >= 0.20 else (1 if frac >= 0.10 else 0),
                         "card": None if len(rew) < 2 else ("pick" if sum(rew) * 2 >= len(rew) else "skip"),
                         "pick_pct": pct(sum(rew), len(rew)) if rew else None})
        out["avg_loss"] = {"n": len(losses), "floors": rows}
    return out


def turning_points(r, strong):
    """Pick the 2-3 most critical floors of a run and tag them with badges."""
    cand = defaultdict(list)       # floor -> [(score, badge)]
    prev_gold = 0
    held = set()
    final = set(r["deck_added"])
    for f in r["floors"]:
        no = f["floor"]
        if f["card_choices"] and f["map_type"] != "shop":
            for n, p in f["card_choices"]:
                if p or n in final:
                    continue
                best = None
                for a in held:
                    st = strong.get(tuple(sorted((a, n))))
                    if st and (best is None or st["lift"] > best[1]["lift"]):
                        best = (a, st)
                if best:
                    a, st = best
                    cand[no].append((25 + st["lift"] / 2, {
                        "k": "synergy", "label": "MISSED SYNERGY",
                        "text": f"Skipped {n} while holding {a} (in {st['win_share']:.0f}% of your wins, {st['lift']:+.0f} pt win lift)"}))
        g = f["gold"] or 0
        if f["map_type"] == "shop" and g >= TP_GOLD:
            cand[no].append((g / 5, {"k": "gold", "label": f"{TP_GOLD}g+ UNSPENT", "text": f"Left the shop with {g} gold"}))
        elif f["map_type"] in ("elite", "boss") and prev_gold >= TP_GOLD:
            cand[no].append((prev_gold / 5, {"k": "gold", "label": f"{TP_GOLD}g+ UNSPENT",
                                              "text": f"Walked into this fight holding {prev_gold} gold"}))
        if f["damage"] >= TP_BLEED:
            cand[no].append((f["damage"] * 1.5, {"k": "bleed", "label": f"HEAVY BLEED (-{f['damage']} HP)",
                                                  "text": f"Lost {f['damage']} HP on this floor"}))
        prev_gold = g
        held.update(_picked_names(f))
    for no, lst in cand.items():           # one MISSED SYNERGY badge per floor (the strongest)
        syn = sorted((x for x in lst if x[1]["k"] == "synergy"), key=lambda x: -x[0])
        cand[no] = [x for x in lst if x[1]["k"] != "synergy"] + syn[:1]
    ranked = sorted(cand.items(), key=lambda kv: -max(s for s, _ in kv[1]))[:TP_MAX]
    return {no: [b for _, b in sorted(v, key=lambda x: -x[0])] for no, v in ranked}



# --------------------------------------------------------------------------
# Dashboard (U.GG-style summary tiles + recent-runs feed). New in v2; additive only.
# --------------------------------------------------------------------------
def _grade(excess, cuts):
    """S/A/B/C/D from how far you are above your winning runs (smaller is better)."""
    for letter, c in zip("SABC", cuts):
        if excess <= c:
            return letter
    return "D"


def dash_summary(runs, inc):
    decided = [r for r in runs if r["win"] or is_loss(r, inc)]
    wins = [r for r in decided if r["win"]]
    losses = [r for r in decided if not r["win"]]

    def a1(rs):
        t = [f["turns"] for r in rs for f in r["floors"] if f["act"] == 1 and f["room_type"] == "monster"]
        return avg(t) if t else None

    def gold(rs):
        return avg([r["final_gold"] for r in rs]) if rs else None

    def potions(rs):
        return pct(sum(1 for r in rs if r["unused_potions"]), len(rs)) if rs else None

    def deck(rs):
        return avg([r["deck_size"] for r in rs]) if rs else None

    ok = len(wins) >= 3
    specs = [
        ("ACT 1 TURNS", a1(decided), a1(wins), (0, 0.3, 0.6, 1.0), lambda v: f"{v:.1f}t", False),
        ("DEATH GOLD", gold(losses), gold(wins), (0, 25, 60, 120), lambda v: f"{v:.0f}g", False),
        ("POTION WASTE", potions(losses), potions(wins), (0, 5, 12, 25), lambda v: f"{v:.0f}%", False),
        ("DECK SIZE", deck(decided), deck(wins), (1, 2, 4, 6), lambda v: f"{v:.1f}", True),
    ]
    tiles = []
    for label, v, w, cuts, fmt, absolute in specs:
        if v is None:
            tiles.append({"label": label, "value": "-", "grade": None, "tip": "No data yet"})
            continue
        grade = None
        if ok and w is not None:
            grade = _grade(abs(v - w) if absolute else v - w, cuts)
        tip = f"Your winning runs: {fmt(w)}" if (ok and w is not None) else "Needs 3+ wins to grade"
        tiles.append({"label": label, "value": fmt(v), "grade": grade, "tip": tip})
    return {"w": len(wins), "l": len(losses), "wr": pct(len(wins), len(decided)), "tiles": tiles}


def run_feed(runs, inc, pool, limit=60):
    """Slim match-history rows with short mistake badges."""
    pairs = {}
    out = []
    for r in runs[:limit]:
        badges = []
        lost = not r["win"] and not r["abandoned"]
        if lost and r["final_gold"] > GOLD_LEAK_THRESHOLD:
            badges.append({"k": "gold", "label": f"{r['final_gold']}g GOLD", "n": r["final_gold"]})
        if lost and r["unused_potions"]:
            n = len(r["unused_potions"])
            badges.append({"k": "potion", "label": f"{n} POTION{'S' if n != 1 else ''}", "n": n})
        ch = r["character"]
        if ch not in pairs:
            pairs[ch] = pair_table([x for x in pool if x["character"] == ch], False)
        if pairs[ch] and any(True for _ in _skipped_with_partner(r, pairs[ch])):
            badges.append({"k": "pair", "label": "MISSED PAIR"})
        bleed = max([f["damage"] for f in r["floors"][:-1]] or [0])
        if bleed >= TP_BLEED:
            badges.append({"k": "bleed", "label": f"-{bleed} HP", "n": bleed})
        b = run_brief(r)
        b["badges"] = badges[:3]
        out.append(b)
    return out



class CoachAPI:
    """Everything the HTML page can ask for. All methods only READ the history folder."""

    def __init__(self):
        self._lock = threading.RLock()
        settings = load_settings()
        self._history_dir = settings.get("history_dir") or guess_history_dir()
        self._cache = {}
        self._last_seen = set()
        self._window = None          # set when running inside pywebview
        self._folder_ok = False

    # ----- loading (same caching rules as v1) -----------------------------
    def _scan(self):
        found = {}
        try:
            with os.scandir(self._history_dir) as it:
                for e in it:
                    if e.is_file() and e.name.endswith(".run"):
                        found[e.path] = e.stat().st_mtime
        except OSError:
            return None
        return found

    def _load_changed(self, found):
        changed = False
        sid = steam_id_from_path(self._history_dir)
        for p, mt in found.items():
            if p not in self._cache or self._cache[p][0] != mt:
                try:
                    run = parse_run(p, sid)
                except (OSError, ValueError, KeyError, TypeError, IndexError):
                    run, mt = None, -1          # half-written file: retry next poll
                self._cache[p] = (mt, run)
                changed = True
        for p in list(self._cache):
            if p not in found:
                del self._cache[p]
                changed = True
        return changed

    def _all_runs(self, include_multi):
        runs = [r for _, r in self._cache.values() if r and r["floors"]]
        if not include_multi:
            runs = [r for r in runs if not r["multiplayer"]]
        return runs

    def _ensure_loaded(self):
        if not self._cache:
            found = self._scan()
            self._folder_ok = found is not None
            if found is not None:
                self._load_changed(found)
                self._last_seen = set(found)

    # ----- public API ------------------------------------------------------
    def init(self):
        with self._lock:
            self._ensure_loaded()
            return {"history_dir": self._history_dir, "folder_ok": self._folder_ok,
                    "can_browse": self._window is not None, "poll_ms": POLL_MS,
                    "char_colors": CHAR_COLORS}

    def poll(self):
        """Called every 3 s by the page. Returns whether anything changed and the newest new run."""
        with self._lock:
            try:
                found = self._scan()
                self._folder_ok = found is not None
                if found is None or not self._load_changed(found):
                    return {"changed": False}
                new = [p for p in found if p not in self._last_seen]
                self._last_seen = set(found)
                out = {"changed": True, "new_run": None}
                if new:
                    newest = max(new, key=lambda p: found[p])
                    r = self._cache.get(newest, (0, None))[1]
                    if r and r["floors"]:
                        out["new_run"] = run_brief(r)
                return out
            except Exception as e:      # never let polling crash the app
                log_error("poll: " + repr(e))
                return {"changed": False}

    def reload(self):
        with self._lock:
            self._cache.clear()
            self._ensure_loaded()
            return True

    def choose_folder(self):
        if self._window is None:
            return None
        try:
            import webview
            folder = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
            res = self._window.create_file_dialog(folder, directory=self._history_dir or "")
        except Exception as e:
            log_error("choose_folder: " + repr(e))
            return None
        if res:
            return res[0] if isinstance(res, (list, tuple)) else res
        return None

    def set_folder(self, path):
        path = os.path.normpath(path.strip().strip('"')) if path else ""
        if not path or not os.path.isdir(path):
            return {"ok": False, "error": "That folder does not exist."}
        with self._lock:
            self._history_dir = path
            data = load_settings()
            data["history_dir"] = path
            try:
                save_settings(data)
            except OSError as e:
                return {"ok": False, "error": f"Could not save settings.json: {e}"}
            self._cache.clear()
            self._ensure_loaded()
            return {"ok": True, "history_dir": path}

    def query(self, p):
        """One call that returns everything the page shows for the current selection."""
        with self._lock:
            try:
                return self._query(p or {})
            except Exception as e:
                import traceback
                log_error("query: " + traceback.format_exc())
                return {"error": repr(e)}

    def _query(self, p):
        self._ensure_loaded()
        inc = bool(p.get("include_abandoned", False))
        include_multi = bool(p.get("include_multi", True))
        asc = p.get("asc", "All")
        rng = p.get("range", "All runs")
        character = p.get("character", ALL)
        biome = p.get("biome", "All acts")
        min_picks = int(p.get("min_picks", 8))
        killer = p.get("killer") or None

        all_runs = self._all_runs(include_multi)
        newest = max(all_runs, key=lambda r: r["start"], default=None)
        current_build = newest["build"] if newest else ""
        if character != ALL and not any(r["character"] == character for r in all_runs):
            character = ALL
        ascs = sorted({r["ascension"] for r in all_runs})
        asc_vals = ["All"] + [f"A{a}" for a in ascs] + [f"A{a}+" for a in ascs if a > 0]
        if asc not in asc_vals:
            asc = "All"

        def scope(rs):
            return scope_runs(rs, asc, rng, current_build)

        base_rs = all_runs if character == ALL else [r for r in all_runs if r["character"] == character]
        runs = scope(base_rs)

        out = {
            "status": {"folder_ok": self._folder_ok, "history_dir": self._history_dir, "loaded": len(all_runs),
                       "time": time.strftime("%H:%M:%S")},
            "effective": {"character": character, "asc": asc, "range": rng},
            "asc_values": asc_vals, "current_build": current_build,
        }

        # --- sidebar (port of _render_sidebar) ---
        groups = defaultdict(list)
        for r in all_runs:
            groups[r["character"]].append(r)
        entries = [(ALL, scope(all_runs))] + sorted(((k, scope(v)) for k, v in groups.items()),
                                                    key=lambda kv: -len(kv[1]))
        side = []
        for name, rs in entries:
            w = sum(1 for r in rs if r["win"])
            l = sum(1 for r in rs if is_loss(r, inc))
            side.append({"name": name, "w": w, "l": l, "pct": pct(w, w + l),
                         "color": None if name == ALL else char_color(name)})
        out["sidebar"] = side

        # --- header (port of _render_header) ---
        wins = [r for r in runs if r["win"]]
        losses = [r for r in runs if is_loss(r, inc)]
        decided = wins + losses
        filt = []
        if asc != "All":
            filt.append(asc)
        if rng != "All runs":
            filt.append(rng.lower())
        wr = pct(len(wins), len(decided))
        asc_won = max((r["ascension"] for r in wins), default=None)
        recent = sorted(decided, key=lambda r: r["start"], reverse=True)[:10]
        out["header"] = {
            "title": character, "color": None if character == ALL else char_color(character),
            "subtitle": f"{len(runs)} runs  ·  {len([r for r in runs if r['abandoned']])} abandoned"
                        + (f"  ·  filtered: {', '.join(filt)}" if filt else ""),
            "cards": [
                {"value": f"{wr:.0f}%", "caption": "Win rate", "tone": "good" if wr >= 25 else "warn" if wr >= 10 else "bad",
                 "num": wr},
                {"value": f"{len(wins)}–{len(losses)}", "caption": "Wins – Losses"},
                {"value": f"{avg([r['final_floor'] for r in losses]):.0f}" if losses else "-",
                 "caption": "Avg floor reached in losses"},
                {"value": f"{avg([r['deck_size'] for r in decided]):.0f}" if decided else "-",
                 "caption": "Avg final deck size"},
                {"value": f"A{asc_won}" if asc_won is not None else "-", "caption": "Highest ascension won"},
            ],
            "last10": [bool(r["win"]) for r in reversed(recent)],     # oldest -> newest
        }

        # --- habits + gameplan ---
        out["habits"] = self._habits(runs, inc, character, asc, rng)
        out["danger"] = danger_list(runs, inc)
        out["builds"] = best_builds(scope(all_runs), inc)

        # --- stats ---
        present = {f["act_id"] for r in runs for f in r["floors"]}
        opts = [a for a in ACT_ORDER if a in present] + sorted(present - set(ACT_ORDER))
        biome_opts = ["All acts"] + [pretty_act(a) for a in opts]
        if biome not in biome_opts:
            biome = "All acts"
        out["effective"]["biome"] = biome
        out["biomes"] = biome_opts
        act_ids = biome_act_ids(runs, biome)
        rows, meta, base = guide_rows(runs, inc, act_ids, min_picks)
        out["guide"] = self._guide(runs, inc, rows, meta, base, biome, act_ids, min_picks)
        out["table"] = [card_json(x) for x in rows if x["offered"] >= 3]
        out["overview"] = self._overview(runs, inc, character)
        out["decisions"] = decisions(runs, inc)
        out["pairs"] = pairings(runs, inc, character)
        out["dash"] = dash_summary(runs, inc)
        out["feed"] = run_feed([r for r in runs if inc or not r["abandoned"]], inc, all_runs)
        out["strip"] = floor_strips(runs, inc)

        # --- autopsy list ---
        shown = runs if not killer else [r for r in runs if is_loss(r, inc) and r["killer"] == killer]
        out["runs"] = [run_brief(r) for r in shown]
        out["killer"] = killer
        return out

    def _habits(self, runs, inc, character, asc, rng):
        habits, fine, wins, losses = habit_report(runs, inc)
        items = []
        for rank, it in enumerate(habits, 1):
            h = it["h"]
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
            ex = sorted(it["examples"], key=lambda r: r["start"], reverse=True)[:4]
            items.append({
                "rank": rank, "id": h["id"], "title": h["title"], "kind": h["kind"], "sev": it["sev"],
                "loss_rate": it["loss_rate"], "loss_hits": it["loss_hits"], "loss_n": it["loss_n"],
                "win_rate": it.get("win_rate"), "win_hits": it.get("win_hits"), "win_n": it.get("win_n"),
                "show_win_bar": h["kind"] == "run" and bool(it.get("win_n")),
                "nums": nums, "why": h["why"], "fix": h["fix"],
                "examples": [{"file": r["file"], "label": f"{fmt_date(r['start'], '%d %b')} · {r['character']} · F{r['final_floor']}"}
                             for r in ex],
            })
        # gameplan (port of _gameplan_card)
        filtered = asc != "All" or rng != "All runs"
        scope = runs if filtered else runs[:GAMEPLAN_RUNS]
        fixes, n_dec = gameplan_fixes(scope, inc)
        l10x = {x["id"]: x for x in gameplan_fixes(scope, inc, 10)[0]}     # same checks, 10-run trend
        for fx in fixes:
            fx["last10"] = (l10x.get(fx["id"]) or fx)["last5"]
            fx["last10_runs"] = (l10x.get(fx["id"]) or fx)["last_runs"]
        who = character if character != ALL else "all"
        scope_txt = (f"current filter · {n_dec} finished runs" if filtered
                     else f"last {min(GAMEPLAN_RUNS, len(runs))} {who} runs · {n_dec} finished")
        watch = None
        if character != ALL:
            best, trap, n_ok = draft_watchlist(runs, inc)
            watch = {"best": card_json(best) if best else None, "trap": card_json(trap) if trap else None}
        gp = {"scope": scope_txt, "n_dec": n_dec, "fixes": fixes, "watch": watch,
              "single": character != ALL, "min_picks": GAMEPLAN_MIN_PICKS}
        return {"items": items, "fine": [it["h"]["title"] for it in fine], "n_wins": len(wins),
                "n_losses": len(losses), "gameplan": gp,
                "who": "this character" if character != ALL else "all characters"}

    def _guide(self, runs, inc, rows, meta, base, biome, act_ids, n):
        if not runs:
            return {"empty": True}
        rs = reward_stats(runs, inc, act_ids)
        out = {"empty": False, "title": "Draft guide - all acts" if biome == "All acts" else f"Draft guide - {biome}",
               "where": "across all acts" if biome == "All acts" else f"in {biome}", "rewards": rs, "base": base,
               "n": n}
        bt = [meta["base"][a] for a in (act_ids or []) if a in meta["base"]]
        out["hall_turns"] = avg(bt) if bt else None
        out["tip"] = None
        if rs["skip_win"] is not None and rs["skip_loss"] is not None and abs(rs["skip_loss"] - rs["skip_win"]) >= 8:
            out["tip"] = ("You skip more rewards in runs you lose - in this part of the run, taking a playable card "
                          "beats skipping." if rs["skip_loss"] > rs["skip_win"] else
                          "You take more cards in runs you lose - be pickier here and skip cards that don't fix a "
                          "real weakness.")
        take = sorted([x for x in rows if x["verdict"] == "TAKE"], key=lambda x: -x["score"])
        skip = sorted([x for x in rows if x["verdict"] == "SKIP"], key=lambda x: x["score"])
        okay = sorted([x for x in rows if x["verdict"] == "OK"], key=lambda x: -x["np"])
        out["take"] = [card_json(x) for x in take]
        out["okay"] = [card_json(x) for x in okay]
        out["skip"] = [card_json(x) for x in skip]
        out["low"] = len([x for x in rows if x["verdict"] == "LOW"])
        return out

    def _overview(self, runs, inc, character):
        if not runs:
            return {"empty": True}
        a = aggregate(runs, inc)
        nw, nl = len(a["wins"]), len(a["losses"])
        decided = [r for r in runs if r["win"] or is_loss(r, inc)]
        overall = pct(len(a["wins"]), len(decided)) if decided else 0
        fights = []
        order = sorted(a["fights"], key=lambda k: (ACT_ORDER.index(k) if k in ACT_ORDER else 99, k))
        for act_id in order:
            num = a["act_num"].get(act_id, 0)
            fd = a["fights"][act_id]
            row = {"act": num, "name": pretty_act(act_id), "limit": SLOW_TURNS_BY_ACT.get(num),
                   "fights": sum(len(v) for v in fd.values())}
            for rt in COMBAT_TYPES:
                data = fd.get(rt, [])
                row[rt] = ({"turns": avg([d[0] for d in data]), "dmg": avg([d[1] for d in data]), "n": len(data)}
                           if data else None)
            visited = [r for r in decided if any(f["act_id"] == act_id for f in r["floors"])]
            if visited:
                wh = sum(r["win"] for r in visited)
                w_pct = pct(wh, len(visited))
                row["win"] = {"pct": w_pct, "w": wh, "n": len(visited),
                              "tone": "good" if w_pct >= overall + 5 else "bad" if w_pct <= overall - 5 else ""}
            else:
                row["win"] = None
            fights.append(row)
        rewards = []
        acts_present = sorted({f["act_id"] for r in runs for f in r["floors"]},
                              key=lambda k: ACT_ORDER.index(k) if k in ACT_ORDER else 99)
        for act_id in acts_present:
            st = reward_stats(runs, inc, {act_id})
            if not st["rewards"]:
                continue
            st["name"] = pretty_act(act_id)
            st["flag"] = (st["skip_win"] is not None and st["skip_loss"] is not None
                          and abs(st["skip_loss"] - st["skip_win"]) >= 8)
            rewards.append(st)
        pots = Counter(p_ for r in a["pot_leak"] for p_ in r["unused_potions"]).most_common(4)
        asc = Counter(r["ascension"] for r in a["wins"])
        record = [[f"{nw} wins  ·  {nl} losses  ·  {len(a['abandoned'])} quit", ""],
                  [f"Win rate {pct(nw, nw + nl):.1f}%", "good" if pct(nw, nw + nl) >= 25 else "warn"],
                  [f"Avg final deck: {a['deck_win']:.1f} in wins  ·  {a['deck_loss']:.1f} in losses", "dim"]]
        if asc:
            record.append(["Wins by ascension: " + "  ·  ".join(f"A{k} ×{v}" for k, v in sorted(asc.items())), "dim"])
        if character == ALL and a["chars"]:
            record.append(["By character: " + "  ·  ".join(
                f"{c} {v[0]}-{v[1]}" for c, v in sorted(a["chars"].items(), key=lambda kv: -sum(kv[1]))), "dim"])
        # win rate over time (chronological finished runs)
        chron = sorted(decided, key=lambda r: r["start"])
        trend, wsum = [], 0
        for i, r in enumerate(chron):
            wsum += r["win"]
            window = chron[max(0, i - 9): i + 1]
            trend.append({"date": fmt_date(r["start"], "%d %b"), "win": bool(r["win"]),
                          "cum": pct(wsum, i + 1), "roll": pct(sum(x["win"] for x in window), len(window)),
                          "file": r["file"]})
        return {
            "empty": False, "fights": fights, "rewards": rewards, "nl": nl,
            "leaks": [{"label": f"Gold >{GOLD_LEAK_THRESHOLD}", "n": len(a["gold_leak"]), "tone": "warn"},
                      {"label": "Unused potions", "n": len(a["pot_leak"]), "tone": "warn"},
                      {"label": "Either leak", "n": len(a["any_leak"]), "tone": "bad"}],
            "avg_gold_death": a["avg_gold_at_death"], "pots": pots,
            "nemesis": a["nemesis"][:8],
            "death_text": ("By act: " + "  ·  ".join(f"Act {k}: {v}" for k, v in sorted(a["death_act"].items()))
                           + "      By room: " + "  ·  ".join(f"{k} {v}" for k, v in a["death_room"].most_common())),
            "record": record, "trend": trend,
        }

    def card_detail(self, p, card):
        with self._lock:
            try:
                p = p or {}
                self._ensure_loaded()
                inc = bool(p.get("include_abandoned", False))
                all_runs = self._all_runs(bool(p.get("include_multi", True)))
                newest = max(all_runs, key=lambda r: r["start"], default=None)
                cb = newest["build"] if newest else ""
                character = p.get("character", ALL)
                base_rs = all_runs if character == ALL else [r for r in all_runs if r["character"] == character]
                runs = scope_runs(base_rs, p.get("asc", "All"), p.get("range", "All runs"), cb)
                d = card_detail(runs, inc, card)
                return {"card": card, "d": d, "lean_deck": LEAN_DECK, "bloat_deck": BLOAT_DECK,
                        "min_partner": MIN_PARTNER_RUNS}
            except Exception as e:
                import traceback
                log_error("card_detail: " + traceback.format_exc())
                return {"error": repr(e)}

    def autopsy(self, file):
        with self._lock:
            try:
                r = next((r for _, r in self._cache.values() if r and r["file"] == file), None)
                if not r:
                    return None
                floors = []
                for f in r["floors"]:
                    rt = f["room_type"]
                    low = ("Smith" in f["rest"] and f["hp"] and f["max_hp"] and f["hp"] / f["max_hp"] < 0.5)
                    floors.append({
                        "floor": f["floor"], "act": f["act"], "act_name": pretty_act(f["act_id"]),
                        "map_type": f["map_type"], "room_type": rt, "label": f["label"], "is_combat": f["is_combat"],
                        "turns": f["turns"], "slow": bool(f["is_combat"] and rt == "monster" and f["turns"] >= SLOW_FIGHT_TURNS),
                        "damage": f["damage"], "healed": f["healed"],
                        "big": bool(f["max_hp"] and f["damage"] >= BIG_HIT_FRACTION * f["max_hp"]),
                        "hp": f["hp"], "max_hp": f["max_hp"], "gold": f["gold"],
                        "gold_gained": f["gold_gained"], "gold_spent": f["gold_spent"], "gold_lost": f["gold_lost"],
                        "card_choices": f["card_choices"], "cards_other": f["cards_other"],
                        "bought_cards": f["bought_cards"], "relics": f["relics"],
                        "potions_picked": f["potions_picked"], "potions_used": f["potions_used"],
                        "potions_discarded": f["potions_discarded"], "events": f["events"], "rest": f["rest"],
                        "smith_low": bool(low), "upgraded": f["upgraded"], "removed": f["removed"],
                        "max_hp_delta": f["max_hp_delta"],
                    })
                chars = [x for _, x in self._cache.values() if x and x["character"] == r["character"]]
                tps = turning_points(r, pair_table(chars, False))
                for fd in floors:
                    fd["tp"] = tps.get(fd["floor"], [])
                return {
                    "turning": [{"floor": no, "badges": b} for no, b in sorted(tps.items())],
                    "file": r["file"], "character": r["character"], "result": r["result"], "win": r["win"],
                    "color": char_color(r["character"]),
                    "date": fmt_date(r["start"], "%a %d %b %Y, %H:%M"), "ascension": r["ascension"],
                    "mode": r["mode"], "run_time": r["run_time"], "final_floor": r["final_floor"],
                    "deck_size": r["deck_size"], "relic_count": r["relic_count"], "killer": r["killer"],
                    "final_gold": r["final_gold"], "unused_potions": r["unused_potions"],
                    "callouts": autopsy_callouts(r), "floors": floors, "deck": r.get("deck", []), "relics_final": r.get("relics_final", []),
                }
            except Exception as e:
                import traceback
                log_error("autopsy: " + traceback.format_exc())
                return {"error": repr(e)}


# --------------------------------------------------------------------------
# Browser fallback (used if pywebview is missing or fails): serves the same
# page on 127.0.0.1 only and opens it in your default browser.
# --------------------------------------------------------------------------
def apply_character_names():
    """Optional renames from settings.json: {"character_names": {"Fool": "Whatever it is called in game"}}."""
    names = load_settings().get("character_names")
    if isinstance(names, dict):
        for old, new in names.items():
            if isinstance(old, str) and isinstance(new, str) and new.strip():
                CHARACTER_DISPLAY[old] = new.strip()
                if old in CHAR_COLORS:
                    CHAR_COLORS[new.strip()] = CHAR_COLORS[old]


def run_server(api, port=8766):
    import http.server
    import socketserver
    import webbrowser

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                with open(os.path.join(HERE, "index.html"), "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            elif path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            elif path == "/art-list":
                art_dir = os.path.join(HERE, "art")
                names = []
                if os.path.isdir(art_dir):
                    names = sorted(n for n in os.listdir(art_dir) if n.lower().endswith((".png", ".webp", ".jpg", ".jpeg", ".gif", ".svg")))
                self._send(200, json.dumps(names).encode("utf-8"), "application/json")
            elif path.startswith("/static/"):
                from urllib.parse import unquote
                name = os.path.basename(unquote(path[8:]))
                full = os.path.join(HERE, "static", name)
                ctype = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}.get(name.rsplit(".", 1)[-1].lower())
                if ctype and os.path.isfile(full):
                    with open(full, "rb") as fh:
                        self._send(200, fh.read(), ctype)
                else:
                    self._send(404, b"not found", "text/plain")
            elif path == "/art-info":
                try:
                    with open(os.path.join(HERE, "art", "descriptions.json"), "rb") as fh:
                        self._send(200, fh.read(), "application/json")
                except OSError:
                    self._send(200, b"{}", "application/json")
            elif path.startswith("/art/"):
                from urllib.parse import unquote
                name = os.path.basename(unquote(path[5:]))
                full = os.path.join(HERE, "art", name)
                ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
                types = {"png": "image/png", "webp": "image/webp", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "svg": "image/svg+xml"}
                if ext in types and os.path.isfile(full):
                    with open(full, "rb") as fh:
                        self._send(200, fh.read(), types[ext])
                else:
                    self._send(404, b"not found", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            name = self.path.strip("/").split("/")[-1]
            allowed = {"init", "poll", "reload", "set_folder", "query", "card_detail", "autopsy"}
            if name not in allowed:
                return self._send(404, b"{}", "application/json")
            n = int(self.headers.get("Content-Length") or 0)
            try:
                args = json.loads(self.rfile.read(n) or b"[]")
                res = getattr(api, name)(*args)
            except Exception as e:
                log_error("api " + name + ": " + repr(e))
                res = {"error": repr(e)}
            self._send(200, json.dumps(res).encode("utf-8"), "application/json")

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    srv = None
    for p in range(port, port + 10):
        try:
            srv = Server(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    if srv is None:
        print("Could not open a port between %d and %d." % (port, port + 9))
        return
    url = f"http://localhost:{srv.server_address[1]}"
    print("STS2 Coach v4 is running at", url)
    print("Keep this window open while you use it. Close it to stop the app.")
    if "--no-open" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    apply_character_names()
    run_server(CoachAPI())


if __name__ == "__main__":
    main()
