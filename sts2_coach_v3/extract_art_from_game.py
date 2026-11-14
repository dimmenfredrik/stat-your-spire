"""
extract_art_from_game.py - builds the picture + description library from the player's OWN installed Slay the Spire 2.

Reads the game's data file (read-only, the game folder is never changed) and writes into the "art" folder next to this file:
  * card, relic, potion and event pictures (small .webp files), named the way STS2 Coach expects
  * descriptions.json with the English card, relic, potion and event text

Everything stays on the player's own PC; the pictures are the game's art and are never uploaded or shared.
Needs Python 3 + Pillow (installed automatically on first run). Run:
  python extract_art_from_game.py                 (auto-finds the game via Steam)
  python extract_art_from_game.py --if-missing    (launcher mode: does nothing if already built)
  python extract_art_from_game.py "path\\to\\SlayTheSpire2.pck"
"""
import io, json, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "art")
MAXW = 420
CANDIDATES = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2\SlayTheSpire2.pck",
    r"C:\Program Files\Steam\steamapps\common\Slay the Spire 2\SlayTheSpire2.pck",
    os.path.expanduser("~/mnt/Slay the Spire 2/SlayTheSpire2.pck"),
]



def steam_roots():
    roots = []
    try:
        import winreg
        for hive, sub, val in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                               (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                               (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    roots.append(os.path.normpath(winreg.QueryValueEx(k, val)[0]))
            except OSError:
                pass
    except ImportError:
        pass
    for r in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        roots.append(r)
    libs = []
    for r in roots:
        libs.append(r)
        vdf = os.path.join(r, "steamapps", "libraryfolders.vdf")
        try:
            txt = open(vdf, encoding="utf-8", errors="ignore").read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
                libs.append(m.group(1).replace("\\\\", "\\"))
        except OSError:
            pass
    return libs


def find_pck():
    for lib in steam_roots():
        c = os.path.join(lib, "steamapps", "common", "Slay the Spire 2", "SlayTheSpire2.pck")
        if os.path.isfile(c):
            return c
    return next((c for c in CANDIDATES if os.path.isfile(c)), None)


try:
    from PIL import Image
except ImportError:
    import subprocess
    print("Installing the picture library (Pillow), one time only...")
    subprocess.call([sys.executable, "-m", "pip", "install", "--quiet", "--user", "--disable-pip-version-check", "pillow"])
    try:
        from PIL import Image
    except ImportError:
        print("Could not install Pillow, so pictures are skipped. The coach still works without them.")
        sys.exit(0 if "--if-missing" in sys.argv else 1)


class Pck:
    def __init__(self, path):
        self.f = open(path, "rb")
        h = self.f.read(40)
        magic, ver, maj, mi, pa, flags, base, dirofs = struct.unpack("<4sIIIIIQQ", h)
        assert magic == b"GDPC" and ver == 3, "unexpected game data format"
        assert not flags & 1, "game data is encrypted"
        self.base = base
        self.f.seek(dirofs)
        n = struct.unpack("<I", self.f.read(4))[0]
        self.ents = {}
        for _ in range(n):
            L = struct.unpack("<I", self.f.read(4))[0]
            p = self.f.read(L).rstrip(b"\0").decode("utf-8", "replace")
            ofs, size = struct.unpack("<QQ", self.f.read(16))
            self.f.read(16)
            self.f.read(4)
            self.ents[p] = (ofs, size)

    def read(self, p):
        ofs, size = self.ents[p]
        self.f.seek(self.base + ofs)
        return self.f.read(size)


BCN = {17: 1, 18: 2, 19: 3, 22: 7}  # Godot image format id -> Pillow bcn mode (DXT1, DXT3, DXT5, BPTC_RGBA)
BLOCK = {17: 8, 18: 16, 19: 16, 22: 16}


def decode_ctex(d):
    if d[:4] != b"GST2":
        return None
    w, h = struct.unpack("<II", d[8:16])
    for sig, end in ((b"\x89PNG\r\n\x1a\n", None), (b"RIFF", None)):
        i = d.find(sig, 36)
        if i > 0 and (sig != b"RIFF" or d[i + 8:i + 12] == b"WEBP"):
            return Image.open(io.BytesIO(d[i:])).convert("RGBA")
    w2, h2, mips, fmt = struct.unpack("<HHII", d[40:52])
    if fmt in BCN:
        need = ((w2 + 3) // 4) * ((h2 + 3) // 4) * BLOCK[fmt]
        return Image.frombytes("RGBA", (w2, h2), d[52:52 + need], "bcn", (BCN[fmt],))
    if fmt == 5:
        return Image.frombytes("RGBA", (w2, h2), d[52:52 + w2 * h2 * 4])
    if fmt == 4:
        return Image.frombytes("RGB", (w2, h2), d[52:52 + w2 * h2 * 3]).convert("RGBA")
    return None


def texture_for(pck, import_path):
    txt = pck.read(import_path).decode("utf-8", "replace")
    for k in ("path.bptc", "path.s3tc", "path"):
        m = re.search(r'^' + re.escape(k) + r'="res://([^"]+)"', txt, re.M)
        if m and m.group(1) in pck.ents:
            return decode_ctex(pck.read(m.group(1)))
    return None


def save(img, key):
    if img.width > MAXW:
        img = img.resize((MAXW, round(img.height * MAXW / img.width)), Image.LANCZOS)
    img.save(os.path.join(ART, key + ".webp"), "WEBP", quality=88)


def resolve_upgrade(t, upgraded):
    """{IfUpgraded:show:A|B} -> A when upgraded else B ({IfUpgraded:show:A} -> A or nothing)."""
    def f(m):
        a, b = m.group(1), m.group(2) or ""
        return a if upgraded else b
    return re.sub(r"\{IfUpgraded:show:([^{}|]*)(?:\|([^{}]*))?\}", f, t)


def clean(t, upgraded=False):
    t = resolve_upgrade(t, upgraded)
    t = re.sub(r"\[/?[a-z_ =#0-9]+\]", "", t)
    t = re.sub(r"\{[^{}]*energy[^{}]*\}", "Energy", t, flags=re.I)
    t = re.sub(r"\{[^{}:]*:plural:([^{}|]*)\|([^{}]*)\}", r"\2", t)
    t = re.sub(r"\{[^{}]*\}", "X", t)
    return re.sub(r"\s+", " ", t).strip()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--if-missing" in sys.argv
    if quiet and os.path.isfile(os.path.join(ART, "descriptions.json")):
        return 0                                   # already built on this PC
    path = args[0] if args else find_pck()
    if not path:
        print("Could not find the Slay the Spire 2 game files, so pictures are skipped (the coach still works).")
        return 0 if quiet else 1
    print("Building pictures from your own game files - about 30 seconds, one time only...")
    pck = Pck(path)
    os.makedirs(ART, exist_ok=True)
    jobs, beta_jobs = [], []
    for p in pck.ents:
        if not p.endswith(".png.import"):
            continue
        stem = os.path.basename(p)[:-11]
        if p.startswith("images/packed/card_portraits/") and p.count("/") >= 4:
            beta = "/beta/" in p
            if beta:
                beta_jobs.append(("card", p, stem))
            else:
                jobs.append(("card", p, stem))
        elif p.startswith("images/relics/") and p.count("/") == 2 and "outline" not in stem:
            jobs.append(("relic", p, stem))
        elif p.startswith("images/potions/large/"):
            jobs.append(("potion", p, stem))
        elif p.startswith("images/events/") and p.count("/") == 2:
            jobs.append(("event", p, stem))
    have = {j[2] for j in jobs}
    jobs += [j for j in beta_jobs if j[2] not in have]   # early-access placeholder art only where nothing better exists
    done = fail = 0
    for kind, p, stem in jobs:
        try:
            img = texture_for(pck, p)
            if img is None:
                fail += 1
                continue
            save(img, stem)
            done += 1
        except Exception as e:
            fail += 1
            print("failed", p, e)
    print(f"pictures saved: {done}, failed: {fail}")
    info = {}
    for name, fields in (("cards", ("description",)), ("relics", ("description",)), ("potions", ("description",)), ("events", ())):
        try:
            data = json.loads(pck.read(f"localization/eng/{name}.json"))
        except KeyError:
            continue
        for k, v in data.items():
            m = re.match(r"^([A-Z0-9_]+)\.description$", k) or re.match(r"^([A-Z0-9_]+)\.pages\.INITIAL\.description$", k)
            if m and v and (name != "events" or "pages.INITIAL" in k):
                entry = {"text": clean(v)[:400]}
                if name == "cards" and "IfUpgraded" in v:
                    up = clean(v, True)[:400]
                    if up != entry["text"]:
                        entry["up"] = up
                info.setdefault(m.group(1).lower(), entry)
    with open(os.path.join(ART, "descriptions.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)
    print(f"descriptions written: {len(info)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
