#!/usr/bin/env python3
"""
sts2_coach.py - Slay the Spire 2 second-monitor coaching tool.

Reads the plain-JSON .run files from your STS2 history folder and shows:
  1. Coaching Insights & Leaks (across all runs)
  2. Run Autopsy (floor-by-floor review with automatic callouts)

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
SLOW_TURNS_BY_ACT = {1: 3.5, 2: 4.0, 3: 4.5}   # avg turns per normal fight
SLOW_FIGHT_TURNS = 5           # a single hallway fight taking this many turns is "slow"
BIG_HIT_FRACTION = 0.30        # a fight costing >=30% of max HP is a "big hit"
ACT_ORDER = ["ACT.OVERGROWTH", "ACT.UNDERDOCKS", "ACT.HIVE", "ACT.GLORY"]
COMBAT_TYPES = ("monster", "elite", "boss")

# Colours (dark theme for a second monitor)
BG = "#16181d"
PANEL = "#1f232b"
FG = "#d7dae0"
DIM = "#7f8796"
ACCENT = "#e5c07b"
GOOD = "#98c379"
BAD = "#e06c75"
WARN = "#d19a66"
INFO = "#61afef"
SEL = "#2c3340"


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
# GUI
# --------------------------------------------------------------------------
class CoachApp(tk.Tk):
    def __init__(self, history_dir):
        super().__init__()
        self.title("STS2 Coach")
        self.geometry("1400x900")
        self.configure(bg=BG)
        self.history_dir = tk.StringVar(value=history_dir)
        self.auto_refresh = tk.BooleanVar(value=True)
        self.include_abandoned = tk.BooleanVar(value=False)
        self.include_multi = tk.BooleanVar(value=True)
        self.char_filter = tk.StringVar(value="All")
        self.mode_filter = tk.StringVar(value="All")
        self.status = tk.StringVar(value="")
        self.cache = {}          # path -> (mtime, run dict or None)
        self.runs = []           # filtered, newest first
        self.selected_file = None

        self._style()
        self._build()
        self.reload(force=True)
        self.after(POLL_MS, self._poll)

    # ----- look & feel ---------------------------------------------------
    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, font=("Segoe UI", 10))
        st.configure("TFrame", background=BG)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Dim.TLabel", foreground=DIM)
        st.configure("TCheckbutton", background=BG, foreground=FG)
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("TButton", background=PANEL, foreground=FG, borderwidth=1, padding=(10, 3))
        st.map("TButton", background=[("active", SEL)])
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=PANEL, foreground=DIM, padding=(16, 6),
                     font=("Segoe UI", 10, "bold"))
        st.map("TNotebook.Tab", background=[("selected", SEL)], foreground=[("selected", ACCENT)])
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                     rowheight=24, borderwidth=0)
        st.configure("Treeview.Heading", background=BG, foreground=ACCENT, relief="flat",
                     font=("Segoe UI", 9, "bold"))
        st.map("Treeview", background=[("selected", SEL)], foreground=[("selected", ACCENT)])
        st.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG,
                     arrowcolor=FG)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", FG)])
        self.option_add("*TCombobox*Listbox.background", PANEL)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        st.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG)

    def _make_text(self, parent):
        frame = ttk.Frame(parent)
        txt = tk.Text(frame, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", wrap="word",
                      font=("Consolas", 10), padx=14, pady=10, borderwidth=0,
                      highlightthickness=0, cursor="arrow")
        sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for tag, opts in {
            "h1": dict(font=("Segoe UI", 15, "bold"), foreground=ACCENT, spacing1=4, spacing3=6),
            "h2": dict(font=("Segoe UI", 12, "bold"), foreground=INFO, spacing1=12, spacing3=4),
            "dim": dict(foreground=DIM),
            "good": dict(foreground=GOOD),
            "bad": dict(foreground=BAD),
            "warn": dict(foreground=WARN),
            "info": dict(foreground=INFO),
            "bold": dict(font=("Consolas", 10, "bold")),
            "picked": dict(foreground=GOOD, font=("Consolas", 10, "bold")),
            "skipped": dict(foreground=DIM, overstrike=True),
            "floorhead": dict(font=("Consolas", 10, "bold")),
            "combat": dict(foreground="#e2a0a6"),
            "elite": dict(foreground=WARN, font=("Consolas", 10, "bold")),
            "boss": dict(foreground=BAD, font=("Consolas", 10, "bold")),
            "callout": dict(lmargin1=6, lmargin2=26, spacing1=2, font=("Segoe UI", 10)),
            "actbar": dict(background=SEL, foreground=ACCENT, font=("Segoe UI", 11, "bold"),
                           spacing1=10, spacing3=4),
        }.items():
            txt.tag_configure(tag, **opts)
        txt.configure(state="disabled")
        return frame, txt

    # ----- layout --------------------------------------------------------
    def _build(self):
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="History folder:").pack(side="left")
        ttk.Entry(top, textvariable=self.history_dir, width=70).pack(side="left", padx=6)
        ttk.Button(top, text="Browse...", command=self._browse).pack(side="left")
        ttk.Button(top, text="Refresh", command=lambda: self.reload(force=True)).pack(side="left", padx=6)
        ttk.Checkbutton(top, text="Auto-refresh", variable=self.auto_refresh).pack(side="left", padx=6)

        filt = ttk.Frame(self, padding=(10, 0, 10, 6))
        filt.pack(fill="x")
        ttk.Label(filt, text="Character:").pack(side="left")
        self.char_box = ttk.Combobox(filt, textvariable=self.char_filter, width=14, state="readonly",
                                     values=["All"])
        self.char_box.pack(side="left", padx=(4, 12))
        self.char_box.bind("<<ComboboxSelected>>", lambda e: self.reload())
        ttk.Label(filt, text="Mode:").pack(side="left")
        self.mode_box = ttk.Combobox(filt, textvariable=self.mode_filter, width=10, state="readonly",
                                     values=["All"])
        self.mode_box.pack(side="left", padx=(4, 12))
        self.mode_box.bind("<<ComboboxSelected>>", lambda e: self.reload())
        ttk.Checkbutton(filt, text="Count abandoned runs as losses", variable=self.include_abandoned,
                        command=self.reload).pack(side="left", padx=6)
        ttk.Checkbutton(filt, text="Include co-op runs", variable=self.include_multi,
                        command=self.reload).pack(side="left", padx=6)
        ttk.Label(filt, textvariable=self.status, style="Dim.TLabel").pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Tab 1
        f1, self.insights = self._make_text(nb)
        nb.add(f1, text="  Coaching Insights & Leaks  ")

        # Tab 2
        f2 = ttk.Frame(nb)
        nb.add(f2, text="  Run Autopsy  ")
        pane = ttk.PanedWindow(f2, orient="horizontal")
        pane.pack(fill="both", expand=True)

        left = ttk.Frame(pane)
        cols = ("date", "char", "asc", "result", "floor", "killer")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for c, w, t in (("date", 128, "Date"), ("char", 96, "Character"), ("asc", 36, "Asc"),
                        ("result", 104, "Result"), ("floor", 44, "Floor"), ("killer", 170, "Killer")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w" if c in ("date", "char", "killer") else "center",
                             stretch=(c == "killer"))
        self.tree.tag_configure("WIN", foreground=GOOD)
        self.tree.tag_configure("LOSS", foreground=BAD)
        self.tree.tag_configure("ABANDONED", foreground=DIM)
        tsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        pane.add(left, weight=3)

        right, self.autopsy = self._make_text(pane)
        pane.add(right, weight=5)

    # ----- data loading --------------------------------------------------
    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.history_dir.get() or os.path.expanduser("~"))
        if d:
            self.history_dir.set(os.path.normpath(d))
            self.cache.clear()
            self.reload(force=True)

    def _scan(self):
        folder = self.history_dir.get()
        found = {}
        try:
            with os.scandir(folder) as it:
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
                    run = None   # half-written file - try again next poll
                    mt = -1
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
                new = [p for p in found if p not in self._last_seen] if hasattr(self, "_last_seen") else []
                self.reload()
                if new:
                    newest = max(new, key=lambda p: found[p])
                    self._select_file(os.path.basename(newest))
                    self.status.set(self.status.get() + f"  |  new run: {os.path.basename(newest)}")
        self.after(POLL_MS, self._poll)

    def reload(self, force=False):
        found = self._scan()
        if found is None:
            self.status.set("Folder not found - use Browse...")
            self.runs = []
            self._render_insights()
            self._render_list()
            return
        if force:
            self.cache.clear()
        self._load_changed(found)
        self._last_seen = set(found)

        all_runs = [r for _, r in self.cache.values() if r and r["floors"]]
        chars = sorted({r["character"] for r in all_runs})
        modes = sorted({r["mode"] for r in all_runs})
        self.char_box["values"] = ["All"] + chars
        self.mode_box["values"] = ["All"] + modes

        runs = all_runs
        if self.char_filter.get() != "All":
            runs = [r for r in runs if r["character"] == self.char_filter.get()]
        if self.mode_filter.get() != "All":
            runs = [r for r in runs if r["mode"] == self.mode_filter.get()]
        if not self.include_multi.get():
            runs = [r for r in runs if not r["multiplayer"]]
        self.runs = sorted(runs, key=lambda r: r["start"], reverse=True)
        self.status.set(f"{len(self.runs)} runs loaded  |  updated {time.strftime('%H:%M:%S')}")
        self._render_insights()
        self._render_list()

    # ----- Tab 1: insights ----------------------------------------------
    def _render_insights(self):
        t = self.insights
        t.configure(state="normal")
        t.delete("1.0", "end")
        w = lambda s, *tags: t.insert("end", s, tags)

        runs = self.runs
        if not runs:
            w("No runs found.\n", "h1")
            w("Point the folder box at your STS2 'saves\\history' folder.\n", "dim")
            t.configure(state="disabled")
            return
        inc = self.include_abandoned.get()
        a = aggregate(runs, inc)
        nw, nl = len(a["wins"]), len(a["losses"])

        w("Coaching Insights & Leaks\n", "h1")
        w(f"{len(runs)} runs analysed  ·  abandoned runs "
          f"{'counted as losses (floor-1 resets ignored)' if inc else 'excluded from loss stats'}\n", "dim")

        # Record
        w("Record\n", "h2")
        w("  Wins ", "bold"); w(f"{nw}", "good")
        w("   Losses ", "bold"); w(f"{nl}", "bad")
        w(f"   Abandoned {len(a['abandoned'])}", "dim")
        w(f"   Win rate ", "bold"); w(f"{pct(nw, nw + nl):.1f}%\n", "good" if pct(nw, nw + nl) >= 30 else "warn")
        w(f"  Avg final deck size: {a['deck_all']:.1f}   (wins {a['deck_win']:.1f}  ·  losses {a['deck_loss']:.1f})\n")
        if a["chars"]:
            w("  By character: ", "dim")
            w("   ".join(f"{c} {v[0]}-{v[1]} ({pct(v[0], sum(v)):.0f}%)"
                         for c, v in sorted(a["chars"].items(), key=lambda kv: -sum(kv[1]))) + "\n")

        # Card picks
        w("Card rewards: pick vs skip by Act\n", "h2")
        w(f"  {'Act':<28}{'Rewards':>8}{'Picked':>10}{'Skipped':>10}\n", "dim")
        for act in sorted(a["picks"]):
            offers, picked, names = a["picks"][act]
            lbl = f"Act {act} ({'/'.join(sorted(names))})"
            w(f"  {lbl:<28}{offers:>8}{pct(picked, offers):>9.0f}%")
            sk = pct(offers - picked, offers)
            w(f"{sk:>9.0f}%\n", "warn" if act == 1 and sk > 35 else "")

        # Fights
        w("Fight speed & damage (per fight)\n", "h2")
        w(f"  {'Act':<26}{'Type':<9}{'Fights':>7}{'Avg turns':>11}{'Avg dmg':>10}\n", "dim")
        order = sorted(a["fights"], key=lambda k: (ACT_ORDER.index(k) if k in ACT_ORDER else 99, k))
        slow_flags = []
        for act_id in order:
            num = a["act_num"].get(act_id, 0)
            for rt in COMBAT_TYPES:
                data = a["fights"][act_id].get(rt)
                if not data:
                    continue
                turns = avg([d[0] for d in data])
                dmg = avg([d[1] for d in data])
                lbl = f"Act {num} {pretty_act(act_id)}"
                w(f"  {lbl:<26}{rt:<9}{len(data):>7}")
                limit = SLOW_TURNS_BY_ACT.get(num)
                slow = rt == "monster" and limit and turns > limit
                w(f"{turns:>11.2f}", "bad" if slow else "good" if rt == "monster" else "")
                w(f"{dmg:>10.1f}")
                if slow:
                    w(f"   ◄ SLOW (target ≤ {limit})", "bad")
                    slow_flags.append((num, act_id, turns, limit))
                w("\n")
        if slow_flags:
            for num, act_id, turns, limit in slow_flags:
                if num == 1:
                    w(f"  ► Act 1 ({pretty_act(act_id)}) hallway fights average {turns:.2f} turns (target {limit}). "
                      f"Prioritise frontloaded damage / AoE in your first 3-4 card rewards.\n", "warn")
                else:
                    w(f"  ► Act {num} ({pretty_act(act_id)}) hallways are slow ({turns:.1f} turns) - "
                      f"your scaling/damage isn't keeping up.\n", "warn")

        # Leaks
        w("Resource leaks at death\n", "h2")
        if nl:
            gl, pl, al = len(a["gold_leak"]), len(a["pot_leak"]), len(a["any_leak"])
            w(f"  Died with >{GOLD_LEAK_THRESHOLD} unspent gold:  ")
            w(f"{gl}/{nl}  ({pct(gl, nl):.0f}%)\n", "bad" if pct(gl, nl) >= 25 else "warn")
            w("  Died holding unused potions: ")
            w(f"{pl}/{nl}  ({pct(pl, nl):.0f}%)\n", "bad" if pct(pl, nl) >= 25 else "warn")
            w(f"  Either leak:                 {al}/{nl}  ({pct(al, nl):.0f}%)\n", "bold")
            w(f"  Average gold at death: {a['avg_gold_at_death']:.0f}\n", "dim")
            pots = Counter(p for r in a["pot_leak"] for p in r["unused_potions"]).most_common(5)
            if pots:
                w("  Potions you most often die holding: " + ", ".join(f"{p} ×{n}" for p, n in pots) + "\n", "dim")
            w("  (Potions at death are reconstructed from pickups/uses, since the game clears the belt on death.)\n", "dim")
        else:
            w("  No losses in the current filter.\n", "dim")

        # Nemesis
        w("Nemesis list (what kills you)\n", "h2")
        if a["nemesis"]:
            top = a["nemesis"][0][1]
            for name, n in a["nemesis"]:
                bar = "█" * max(1, round(20 * n / top))
                w(f"  {name:<30}", "bold"); w(f"{n:>3}  ", ""); w(bar + "\n", "bad")
            da = a["death_act"]
            w("  Deaths by act: " + "   ".join(f"Act {k}: {v}" for k, v in sorted(da.items())) + "\n", "dim")
            dr = a["death_room"]
            w("  Deaths by room: " + "   ".join(f"{k}: {v}" for k, v in dr.most_common()) + "\n", "dim")
        else:
            w("  Nothing has killed you yet in this filter.\n", "good")

        t.configure(state="disabled")

    # ----- Tab 2: run list + autopsy -------------------------------------
    def _render_list(self):
        keep = self.selected_file
        self.tree.delete(*self.tree.get_children())
        for r in self.runs:
            date = datetime.fromtimestamp(r["start"]).strftime("%Y-%m-%d %H:%M") if r["start"] else "?"
            char = r["character"] + (" (co-op)" if r["multiplayer"] else "")
            self.tree.insert("", "end", iid=r["file"], tags=(r["result"],),
                             values=(date, char, r["ascension"], r["result"], r["final_floor"],
                                     "" if r["win"] else r["killer"]))
        if keep and self.tree.exists(keep):
            self._select_file(keep)
        elif self.runs:
            self._select_file(self.runs[0]["file"])
        else:
            self._render_autopsy(None)

    def _select_file(self, fname):
        if self.tree.exists(fname):
            self.tree.selection_set(fname)
            self.tree.see(fname)

    def _on_select(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        self.selected_file = sel[0]
        run = next((r for r in self.runs if r["file"] == sel[0]), None)
        self._render_autopsy(run)

    def _render_autopsy(self, r):
        t = self.autopsy
        t.configure(state="normal")
        t.delete("1.0", "end")
        w = lambda s, *tags: t.insert("end", s, tags)
        if not r:
            w("Select a run on the left.\n", "dim")
            t.configure(state="disabled")
            return

        res_tag = {"WIN": "good", "LOSS": "bad"}.get(r["result"], "dim")
        date = datetime.fromtimestamp(r["start"]).strftime("%a %d %b %Y, %H:%M") if r["start"] else "?"
        w(f"{r['character']} - ", "h1"); w(f"{r['result']}\n", "h1", res_tag)
        w(f"{date}  ·  Ascension {r['ascension']}  ·  {r['mode']}  ·  {r['run_time'] // 60}m "
          f"{r['run_time'] % 60:02d}s  ·  floor {r['final_floor']}  ·  deck {r['deck_size']}  ·  "
          f"{r['build']}  ·  {r['file']}\n", "dim")

        w("Coach's callouts\n", "h2")
        icon = {"bad": "✖", "warn": "▲", "info": "•", "good": "✔"}
        for sev, text in autopsy_callouts(r):
            w(f"{icon.get(sev, '•')}  ", sev); w(text + "\n", "callout")

        w("\nFloor-by-floor\n", "h2")
        w(f"{'#':>3}  {'Room / Enemy':<34}{'Turns':>5}  {'HP change':<11}{'HP':>9}  {'Gold':>5} {'(±)':<9}\n", "dim")

        cur_act = None
        for f in r["floors"]:
            if f["act"] != cur_act:
                cur_act = f["act"]
                w(f"  Act {f['act']} - {pretty_act(f['act_id'])}  \n", "actbar")

            rt = f["room_type"]
            row_tag = {"elite": "elite", "boss": "boss"}.get(rt, "combat" if f["is_combat"] else "")
            label = f["label"][:33]
            w(f"{f['floor']:>3}  ", "floorhead")
            w(f"{label:<34}", row_tag)
            turns = f"{f['turns']}" if f["is_combat"] else "-"
            slow = f["is_combat"] and rt == "monster" and f["turns"] >= SLOW_FIGHT_TURNS
            w(f"{turns:>5}", "bad" if slow else "")
            hp_change = []
            if f["damage"]:
                hp_change.append(f"-{f['damage']}")
            if f["healed"]:
                hp_change.append(f"+{f['healed']}")
            hpc = " ".join(hp_change) or "0"
            big = f["max_hp"] and f["damage"] >= BIG_HIT_FRACTION * f["max_hp"]
            w(f"  {hpc:<11}", "bad" if big else "warn" if f["damage"] else "good" if f["healed"] else "dim")
            hp = f"{f['hp']}/{f['max_hp']}" if f["hp"] is not None else "?"
            w(f"{hp:>9}", "bad" if f["hp"] == 0 else "")
            gdelta = []
            if f["gold_gained"]:
                gdelta.append(f"+{f['gold_gained']}")
            if f["gold_spent"]:
                gdelta.append(f"-{f['gold_spent']}")
            if f["gold_lost"]:
                gdelta.append(f"-{f['gold_lost']}!")
            w(f"  {f['gold'] if f['gold'] is not None else '?':>5} ")
            w(f"{' '.join(gdelta):<9}\n", "dim")

            # Detail lines
            pad = "       "
            if f["card_choices"] and f["map_type"] == "shop":
                gained = set(f["cards_other"]) | set(f["bought_cards"])
                w(pad + "Shop stock: ", "dim")
                for i, (name, picked) in enumerate(f["card_choices"]):
                    if i:
                        w("  ")
                    bought = picked or name in gained
                    w(("$ " if bought else "") + name, "picked" if bought else "dim")
                w("\n")
            elif f["card_choices"]:
                w(pad + "Cards: ", "dim")
                for i, (name, picked) in enumerate(f["card_choices"]):
                    if i:
                        w("  ")
                    w(("✔ " if picked else "") + name, "picked" if picked else "skipped")
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
            if f["potions_skipped"]:
                extras.append(("Potion skipped: " + ", ".join(f["potions_skipped"]), "dim"))
            if f["events"]:
                extras.append(("Event: " + "; ".join(f["events"]), ""))
            if f["rest"]:
                extras.append(("Campfire: " + ", ".join(f["rest"]), "warn" if "Smith" in f["rest"]
                               and f["hp"] and f["max_hp"] and f["hp"] / f["max_hp"] < 0.5 else ""))
            if f["upgraded"]:
                extras.append(("Upgraded: " + ", ".join(f["upgraded"]), "dim"))
            if f["removed"]:
                extras.append(("Removed: " + ", ".join(f["removed"]), "good"))
            if f["max_hp_delta"]:
                extras.append((f"Max HP {f['max_hp_delta']:+d}", "good" if f["max_hp_delta"] > 0 else "bad"))
            for text, tag in extras:
                w(pad + text + "\n", tag or "dim")

        if not r["win"] and r["floors"]:
            w("\n", "")
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
