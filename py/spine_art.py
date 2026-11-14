"""spine_art.py - draws the game's character-select pictures (Spine setup pose) with Pillow only.
Runs from your own game files; nothing is stored in the repository."""
import struct


class R:
    def __init__(s, b):
        s.b = b; s.p = 0
    def byte(s):
        v = s.b[s.p]; s.p += 1; return v
    def bool(s): return s.byte() != 0
    def int(s):
        v = struct.unpack_from(">i", s.b, s.p)[0]; s.p += 4; return v
    def short(s):
        v = struct.unpack_from(">h", s.b, s.p)[0]; s.p += 2; return v
    def float(s):
        v = struct.unpack_from(">f", s.b, s.p)[0]; s.p += 4; return v
    def varint(s, pos=True):
        r = 0; sh = 0
        while True:
            c = s.byte(); r |= (c & 0x7F) << sh
            if not c & 0x80: break
            sh += 7
        return r if pos else ((r >> 1) ^ -(r & 1))
    def string(s):
        n = s.varint()
        if n == 0: return None
        if n == 1: return ""
        v = s.b[s.p:s.p + n - 1].decode("utf8", "replace"); s.p += n - 1; return v
    def sref(s):
        i = s.varint()
        return None if i == 0 else s.strings[i - 1]
    def floats(s, n):
        v = struct.unpack_from(">%df" % n, s.b, s.p); s.p += 4 * n; return list(v)
    def shorts(s):
        n = s.varint()
        return [s.varint() for _ in range(n)]


def read_vertices(r, count, weighted):
    """returns ('plain', floats) or ('weighted', [[(bone,x,y,w),...],...])"""
    if not weighted:
        return ("plain", r.floats(count * 2))
    out = []
    for _ in range(count):
        n = r.varint(); L = []
        for _ in range(n):
            bi = r.varint(); x = r.float(); y = r.float(); w = r.float()
            L.append((bi, x, y, w))
        out.append(L)
    return ("weighted", out)


VARIANT = 1
PATHW = 64
CLIPW = 16
BBW = 16


def read_constraints(r, sk):
    v = VARIANT
    nb = len(sk["bones"])
    def bones_list():
        n = r.varint()
        return [r.varint() for _ in range(n)]
    for _ in range(r.varint()):          # IK
        r.string(); r.varint()
        if v == 0:
            r.bool(); bones_list(); r.varint()
            fl = r.byte()
            if fl & 16: r.float() if fl & 32 else None
            if fl & 64: r.float()
        else:
            bones_list(); r.varint()
            fl = r.byte()
            if fl & 32: r.float() if fl & 64 else None
            if fl & 128: r.float()
    for _ in range(r.varint()):          # transform
        r.string(); r.varint()
        if v == 0:
            r.bool(); bones_list(); r.varint()
            fl = r.byte()
            for bit in (4, 8, 16, 32, 64): 
                if fl & bit: r.float()
            fl2 = r.byte()
            for bit in (1, 2, 4, 8, 16, 32, 64):
                if fl2 & bit: r.float()
        else:
            bones_list(); r.varint()
            fl = r.byte()
            for bit in (8, 16, 32, 64, 128):
                if fl & bit: r.float()
            fl2 = r.byte()
            for bit in (1, 2, 4, 8, 16, 32, 64):
                if fl2 & bit: r.float()
    for _ in range(r.varint()):          # path
        r.string(); r.varint(); r.bool(); bones_list(); r.varint()
        fl = r.byte()
        if fl & 128: r.float()
        for _ in range(5): r.float()
    for _ in range(r.varint()):          # physics
        r.string(); r.varint(); r.varint()
        fl = r.byte()
        for bit in (2, 4, 8, 16, 32, 64):
            if fl & bit: r.float()
        r.byte()
        for _ in range(3): r.float()
        if fl & 128: r.float()
        r.float(); r.float()
        fl2 = r.byte()
        if fl2 & 128: r.float()


def parse(data, log=False):
    r = R(data)
    r.p = 8
    ver = r.string()
    sk = {"version": ver}
    sk["x"], sk["y"], sk["w"], sk["h"] = r.float(), r.float(), r.float(), r.float()
    sk["ref"] = r.float()
    ne = r.bool(); sk["ne"] = ne; r.ne = ne
    if ne:
        r.float(); r.string(); r.string()
    r.strings = [r.string() for _ in range(r.varint())]
    bones = []
    for i in range(r.varint()):
        b = {"name": r.string()}
        b["parent"] = r.varint() if i > 0 else -1
        for k in ("rot", "x", "y", "sx", "sy", "shx", "shy", "len"):
            b[k] = r.float()
        b["tm"] = r.varint(); r.bool()
        if ne:
            r.int(); r.string(); r.bool()
        bones.append(b)
    sk["bones"] = bones
    slots = []
    for i in range(r.varint()):
        s = {"name": r.string(), "bone": r.varint()}
        c = r.int() & 0xFFFFFFFF
        s["color"] = ((c >> 24) & 255, (c >> 16) & 255, (c >> 8) & 255, c & 255)
        r.int()
        s["att"] = r.sref(); s["blend"] = r.varint()
        if ne: r.bool()
        slots.append(s)
    sk["slots"] = slots
    read_constraints(r, sk)
    # skins
    nslot = r.varint()
    atts = {}
    for _ in range(nslot):
        si = r.varint()
        for _ in range(r.varint()):
            key = r.sref()
            a = read_att(r, key)
            atts[(si, key)] = a
            if log: print(" att", slots[si]["name"], key, a["type"], a.get("w"), a.get("h"))
    sk["atts"] = atts
    sk["pos_end"] = r.p
    return sk


def read_att(r, slotkey):
    flags = r.byte()
    name = r.sref() if flags & 8 else slotkey
    t = flags & 7
    a = {"name": name, "type": t}
    if t == 0:  # region
        a["path"] = r.sref() if flags & 16 else name
        a["color"] = r.int() if flags & 32 else -1
        if flags & 64: r.int(); r.int(); r.int()  # sequence
        a["rot"] = r.float() if flags & 128 else 0.0
        a["x"], a["y"], a["sx"], a["sy"], a["w"], a["h"] = [r.float() for _ in range(6)]
    elif t == 2:  # mesh
        a["path"] = r.sref() if flags & 16 else name
        a["color"] = r.int() if flags & 32 else -1
        if flags & 64: r.int(); r.int(); r.int()
        a["hull"] = r.varint()
        n = r.varint(); a["n"] = n
        a["verts"] = read_vertices(r, n, bool(flags & 128))
        a["uvs"] = r.floats(n * 2)
        a["tris"] = [r.varint() for _ in range(3 * (2 * n - a["hull"] - 2))]
        if r.ne:
            a["edges"] = r.shorts()
            a["w"], a["h"] = r.float(), r.float()
    elif t == 6:  # clipping
        a["end"] = r.varint()
        n = r.varint(); a["n"] = n
        a["verts"] = read_vertices(r, n, bool(flags & CLIPW))
        if r.ne: r.int()
    elif t == 3:  # linked mesh
        a["path"] = r.sref() if flags & 16 else name
        a["color"] = r.int() if flags & 32 else -1
        if flags & 64: r.int(); r.int(); r.int()
        a["skin"] = r.sref(); a["parent"] = r.sref()
        if r.ne: r.float(); r.float()
    elif t == 1:  # bounding box
        n = r.varint(); a["verts"] = read_vertices(r, n, bool(flags & BBW))
        if r.ne: r.int()
    elif t == 4:  # path
        n = r.varint()
        a["verts"] = read_vertices(r, n, bool(flags & PATHW))
        for _ in range(n // 3): r.float()
        if r.ne: r.int()
    elif t == 5:  # point
        r.float(); r.float(); r.float()
        if r.ne: r.int()
    else:
        raise SystemExit("attachment type %d at %d" % (t, r.p))
    return a




# ---------------------------------------------------------------- rendering (Pillow only)
import math
from PIL import Image, ImageDraw, ImageChops


def parse_atlas(text):
    regions, cur, page = {}, None, {}
    for ln in text.replace("\r", "").split("\n"):
        if not ln.strip():
            continue
        if ":" not in ln:
            if not page.get("file") and ln.strip().lower().endswith((".png", ".jpg")):
                page["file"] = ln.strip(); cur = None
            else:
                cur = {"name": ln.strip()}; regions[cur["name"]] = cur
            continue
        k, v = ln.strip().split(":", 1)
        (cur if cur is not None else page)[k] = v
    return page, regions


def region_image(atlas, rg):
    x, y, w, h = [int(t) for t in rg["bounds"].split(",")]
    rv = rg.get("rotate", "false")
    rot = 90 if rv == "true" else (0 if rv == "false" else int(rv))
    if rot == 90:
        crop = atlas.crop((x, y, x + h, y + w)).transpose(Image.ROTATE_90)
    else:
        crop = atlas.crop((x, y, x + w, y + h))
    if "offsets" in rg:
        ox, oy, ow, oh = [int(t) for t in rg["offsets"].split(",")]
        full = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
        full.paste(crop, (ox, oh - oy - crop.height))
        crop = full
    return crop


def bone_world(bones):
    W = []
    for b in bones:
        rot = math.radians(b["rot"]); shx = math.radians(b["shx"]); shy = math.radians(b["shy"])
        la = math.cos(rot + shx) * b["sx"]; lb = math.cos(rot + math.pi / 2 + shy) * b["sy"]
        lc = math.sin(rot + shx) * b["sx"]; ld = math.sin(rot + math.pi / 2 + shy) * b["sy"]
        if b["parent"] < 0:
            W.append((la, lb, b["x"], lc, ld, b["y"]))
        else:
            pa, pb, px, pc, pd, py = W[b["parent"]]
            W.append((pa * la + pb * lc, pa * lb + pb * ld, pa * b["x"] + pb * b["y"] + px,
                      pc * la + pd * lc, pc * lb + pd * ld, pc * b["x"] + pd * b["y"] + py))
    return W


def _inv_affine(src, dst):
    """Pillow wants output->input coefficients: input = A*output + t. Solve from 3 point pairs."""
    (x0, y0), (x1, y1), (x2, y2) = dst
    det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(det) < 1e-9:
        return None
    out = []
    for k in (0, 1):
        s0, s1, s2 = src[0][k], src[1][k], src[2][k]
        a = ((s1 - s0) * (y2 - y0) - (s2 - s0) * (y1 - y0)) / det
        b = ((s2 - s0) * (x1 - x0) - (s1 - s0) * (x2 - x0)) / det
        c = s0 - a * x0 - b * y0
        out += [a, b, c]
    return out


def render_skeleton(skel_bytes, atlas_text, atlas_img, scale=0.25, ss=2):
    sk = parse(skel_bytes)
    page, regions = parse_atlas(atlas_text)
    atlas = atlas_img.convert("RGBA")
    W = bone_world(sk["bones"])
    items = []
    minx = miny = 1e9; maxx = maxy = -1e9
    for si, s in enumerate(sk["slots"]):
        if not s["att"]:
            continue
        a = sk["atts"].get((si, s["att"]))
        if a and a["type"] == 3:          # linked mesh: same shape as its parent, other picture
            par = sk["atts"].get((si, a["parent"]))
            if par and par["type"] == 2:
                a = dict(par, path=a["path"], color=a["color"])
        if not a or a["type"] not in (0, 2):
            continue
        rg = regions.get(a.get("path") or a["name"])
        if rg is None:
            continue
        img = region_image(atlas, rg)
        w, h = img.size
        pa, pb, px, pc, pd, py = W[s["bone"]]
        if a["type"] == 0:
            hw, hh = a["w"] / 2 * a["sx"], a["h"] / 2 * a["sy"]
            cr, sr = math.cos(math.radians(a["rot"])), math.sin(math.radians(a["rot"]))
            pos = []
            for (cx, cy) in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
                lx = cx * cr - cy * sr + a["x"]; ly = cx * sr + cy * cr + a["y"]
                pos.append((pa * lx + pb * ly + px, pc * lx + pd * ly + py))
            uv = [(0, h), (w, h), (w, 0), (0, 0)]
            tris = [(0, 1, 2), (0, 2, 3)]
        else:
            kind, vv = a["verts"]
            pos = []
            if kind == "plain":
                for i in range(a["n"]):
                    lx, ly = vv[2 * i], vv[2 * i + 1]
                    pos.append((pa * lx + pb * ly + px, pc * lx + pd * ly + py))
            else:
                for L in vv:
                    X = Y = 0.0
                    for (bi, lx, ly, wt) in L:
                        a2, b2, x2, c2, d2, y2 = W[bi]
                        X += (a2 * lx + b2 * ly + x2) * wt; Y += (c2 * lx + d2 * ly + y2) * wt
                    pos.append((X, Y))
            uv = [(a["uvs"][2 * i] * w, a["uvs"][2 * i + 1] * h) for i in range(a["n"])]
            t = a["tris"]
            tris = [(t[i], t[i + 1], t[i + 2]) for i in range(0, len(t), 3)]
        for p in pos:
            minx = min(minx, p[0]); maxx = max(maxx, p[0]); miny = min(miny, p[1]); maxy = max(maxy, p[1])
        sc = s["color"]; ac = a.get("color", -1) & 0xFFFFFFFF
        ac = ((ac >> 24) & 255, (ac >> 16) & 255, (ac >> 8) & 255, ac & 255)
        col = [sc[i] * ac[i] / 65025.0 for i in range(4)]
        items.append((img, pos, uv, tris, col, s["blend"]))
    if not items:
        return None
    k = scale * ss
    Wd = int((maxx - minx) * k) + 2; Hd = int((maxy - miny) * k) + 2
    canvas = Image.new("RGBA", (Wd, Hd), (0, 0, 0, 0))
    for img, pos, uv, tris, col, blend in items:
        dpos = [((p[0] - minx) * k, (maxy - p[1]) * k) for p in pos]
        bx0 = max(int(min(p[0] for p in dpos)) - 1, 0); by0 = max(int(min(p[1] for p in dpos)) - 1, 0)
        bx1 = min(int(max(p[0] for p in dpos)) + 2, Wd); by1 = min(int(max(p[1] for p in dpos)) + 2, Hd)
        if bx1 <= bx0 or by1 <= by0:
            continue
        src = img.convert("RGBa")
        layer = Image.new("RGBa", (bx1 - bx0, by1 - by0), (0, 0, 0, 0))
        for (i, j, kk) in tris:
            dst = [(dpos[q][0] - bx0, dpos[q][1] - by0) for q in (i, j, kk)]
            co = _inv_affine([uv[i], uv[j], uv[kk]], dst)
            if co is None:
                continue
            tx0 = max(int(min(p[0] for p in dst)) - 1, 0); ty0 = max(int(min(p[1] for p in dst)) - 1, 0)
            tx1 = min(int(max(p[0] for p in dst)) + 2, layer.width); ty1 = min(int(max(p[1] for p in dst)) + 2, layer.height)
            if tx1 <= tx0 or ty1 <= ty0:
                continue
            # shift the affine so the patch starts at (tx0, ty0)
            a_, b_, c_, d_, e_, f_ = co
            c2 = c_ + a_ * tx0 + b_ * ty0; f2 = f_ + d_ * tx0 + e_ * ty0
            patch = src.transform((tx1 - tx0, ty1 - ty0), Image.AFFINE, (a_, b_, c2, d_, e_, f2), Image.BILINEAR)
            mask = Image.new("L", patch.size, 0)
            ImageDraw.Draw(mask).polygon([(p[0] - tx0, p[1] - ty0) for p in dst], fill=255)
            layer.paste(patch, (tx0, ty0), mask)
        lay = layer.convert("RGBA")
        if col[:3] != [1.0, 1.0, 1.0] or col[3] != 1.0:
            r, g, b, al = lay.split()
            r = r.point(lambda v: int(v * col[0])); g = g.point(lambda v: int(v * col[1])); b = b.point(lambda v: int(v * col[2]))
            al = al.point(lambda v: int(v * col[3]))
            lay = Image.merge("RGBA", (r, g, b, al))
        if blend == 3:   # screen
            full = Image.new("RGBa", canvas.size, (0, 0, 0, 0)); full.paste(lay.convert("RGBa"), (bx0, by0))
            canvas = ImageChops.screen(canvas.convert("RGBa"), full).convert("RGBA")
        elif blend == 1:  # additive
            full = Image.new("RGBa", canvas.size, (0, 0, 0, 0)); full.paste(lay.convert("RGBa"), (bx0, by0))
            canvas = ImageChops.add(canvas.convert("RGBa"), full).convert("RGBA")
        else:
            canvas.alpha_composite(lay, (bx0, by0))
    if ss > 1:
        canvas = canvas.resize((canvas.width // ss, canvas.height // ss), Image.LANCZOS)
    return canvas
