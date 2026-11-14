"""
card_values.py - reads base numbers, cost, type and rarity of every card from the player's own sts2.dll (read-only).
Used by extract_art_from_game.py. Needs the pure-Python packages dnfile and dncil (installed automatically).
Never changes the game; if anything fails the caller just skips numbers.
"""
import re, dnfile
from dncil.cil.body import CilMethodBody
from dncil.cil.body.reader import CilMethodBodyReaderBase
from dncil.clr.token import Token

class _R(CilMethodBodyReaderBase):
    def __init__(s, data): s.data = data; s.offset = 0
    def read(s, n): r = s.data[s.offset:s.offset+n]; s.offset += n; return r
    def tell(s): return s.offset
    def seek(s, o): s.offset = o; return o

def load(path):
    dn = dnfile.dnPE(path); t = dn.net.mdtables
    m2t = {}
    for tr in t.TypeDef.rows:
        for m in tr.MethodList: m2t[m.row_index] = str(tr.TypeName)
    typedef_name = lambda rid: str(t.TypeDef.get_with_row_index(rid).TypeName)
    typeref_name = lambda rid: str(t.TypeRef.get_with_row_index(rid).TypeName)
    def spec_name(rid):
        sig = t.TypeSpec.get_with_row_index(rid).Signature; blob = bytes(sig.value) if sig is not None else b""
        # GENERICINST(0x15) CLASS/VALUETYPE(0x12/0x11) coded-token count args...
        def cu(i):
            b = blob[i]
            if b & 0x80 == 0: return b, i+1
            if b & 0xC0 == 0x80: return ((b & 0x3F) << 8) | blob[i+1], i+2
            return ((b & 0x1F) << 24) | (blob[i+1] << 16) | (blob[i+2] << 8) | blob[i+3], i+4
        def coded(v):
            tag, rid2 = v & 3, v >> 2
            return typedef_name(rid2) if tag == 0 else typeref_name(rid2) if tag == 1 else "?"
        if not blob or blob[0] != 0x15: return "?"
        v, i = cu(2); base = coded(v); n, i = cu(i); args = []
        for _ in range(n):
            if blob[i] in (0x11, 0x12):
                v, i = cu(i+1); args.append(coded(v))
            else: args.append("?"); break
        return base + "<" + ",".join(args) + ">"
    def method_ref(tokval):
        tk = Token(tokval)
        if tk.table == 0x06:
            r = t.MethodDef.get_with_row_index(tk.rid); return (m2t.get(tk.rid, "?"), str(r.Name))
        if tk.table == 0x0A:
            r = t.MemberRef.get_with_row_index(tk.rid); c = r.Class
            row = c.row; tab = type(row).__name__
            if tab == "TypeRefRow": owner = str(row.TypeName)
            elif tab == "TypeSpecRow": owner = spec_name(c.row_index)
            elif tab == "TypeDefRow": owner = str(row.TypeName)
            else: owner = "?"
            return (owner, str(r.Name))
        if tk.table == 0x2B:
            r = t.MethodSpec.get_with_row_index(tk.rid); return method_ref(r.Method.row_index | (0x06 << 24) if type(r.Method.row).__name__ == "MethodDefRow" else r.Method.row_index | (0x0A << 24))
        return ("?", hex(tokval))
    return dn, t, method_ref

def insns(dn, mr):
    return list(CilMethodBody(_R(dn.get_data(mr.Rva))).instructions)

def val(ins):
    n = ins.opcode.name
    if n.startswith("ldc.i4."):
        s = n[7:]
        if s == "m1": return -1
        if s.isdigit(): return int(s)
        if s == "s": return ins.operand
    if n == "ldc.i4": return ins.operand
    return None

def run(dn, t, method_ref, mr):
    """Tiny stack simulator. Returns list of (kind, owner, name, args) for newobj/call/callvirt."""
    st = []; ev = []; after_dup = False
    for ins in insns(dn, mr):
        n = ins.opcode.name; v = val(ins)
        if v is not None:
            st.append(("x" if after_dup else "i", v)); after_dup = False; continue
        after_dup = False
        if n == "dup": st.append(("o", "dup")); after_dup = True; continue
        if n == "ldstr":
            tk = Token(ins.operand.value) if hasattr(ins.operand, "value") else None
            st.append(("s", dn.net.user_strings.get(tk.rid).value if tk is not None else "?")); continue
        if n in ("ldc.r4", "ldc.r8"): st.append(("f", ins.operand)); continue
        if n == "newarr":
            while st and st[-1][0] == "i": st.pop()
            st.append(("o", "arr")); continue
        if n.startswith("stelem"):
            # pop value, index, array ref
            if st: st.pop()
            while st and st[-1][0] == "x": st.pop()
            if st and st[-1] == ("o", "dup"): st.pop()
            continue
        if n in ("newobj", "call", "callvirt"):
            op = ins.operand.value if hasattr(ins.operand, "value") else ins.operand
            owner, name = method_ref(op)
            if n == "newobj" and owner == "Decimal":
                a = []
                while st and st[-1][0] == "i": a.append(st.pop()[1])
                a.reverse()
                if len(a) == 5:
                    lo, mid, hi, neg, sc = a; d = (lo + (mid << 32) + (hi << 64)) / (10 ** sc); d = -d if neg else d
                else: d = a[0] if a else None
                st.append(("d", d)); continue
            a = []
            while st and st[-1][0] in ("i", "s", "d", "f"): a.append(st.pop())
            a.reverse(); ev.append((n, owner, name, a)); st.append(("o", None)); continue
        if n == "ldsfld":
            fn = None
            try:
                tk = Token(ins.operand.value)
                if tk.table == 0x0A: fn = str(t.MemberRef.get_with_row_index(tk.rid).Name)
                elif tk.table == 0x04: fn = str(t.Field.get_with_row_index(tk.rid).Name)
            except Exception: pass
            if fn in ("One", "Zero", "MinusOne"): st.append(("d", {"One": 1, "Zero": 0, "MinusOne": -1}[fn]))
            else: st.append(("o", "fld:" + str(fn)))
            continue
        if n in ("ldarg.0", "ldarg.1", "ldfld", "ldloc.0"): st.append(("o", n)); continue
    return ev

def card_methods(t, want, ns="Models.Cards"):
    for tr in t.TypeDef.rows:
        if ns not in str(tr.TypeNamespace): continue
        for m in tr.MethodList:
            if str(m.row.Name) in want and m.row.Rva: yield str(tr.TypeName), str(m.row.Name), m.row


TYPES = ["None", "Attack", "Skill", "Power", "Status", "Curse", "Quest"]
RARITIES = ["None", "Basic", "Common", "Uncommon", "Rare", "Ancient", "Event", "Token", "Status", "Curse", "Quest"]


def snake(name):
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def var_name(owner, args):
    strs = [a[1] for a in args if a[0] == "s"]
    if strs:
        return strs[0]
    m = re.match(r"PowerVar`1<(\w+)>", owner)
    if m:
        return m.group(1)
    return owner[:-3] if owner.endswith("Var") else owner


def var_value(args):
    nums = [a[1] for a in args if a[0] in ("d", "i") and a[1] is not None]
    saw_str = any(a[0] == "s" for a in args)
    if saw_str:
        after = []
        seen = False
        for a in args:
            if a[0] == "s":
                seen = True
            elif seen and a[0] in ("d", "i"):
                after.append(a[1])
        if after:
            return after[0]
    return nums[0] if nums else None


def read_cards(dll_path):
    dn, t, mref = load(dll_path)
    cards = {}
    for cls, m, row in card_methods(t, (".ctor", "get_CanonicalVars", "OnUpgrade")):
        c = cards.setdefault(cls, {"vars": {}, "delta": {}, "cost": None})
        ev = run(dn, t, mref, row)
        if m == ".ctor":
            for e in ev:
                if e[0] == "call" and e[1] == "CardModel" and e[2] == ".ctor":
                    ints = [a[1] for a in e[3] if a[0] == "i"]
                    if len(ints) >= 4:
                        c["cost"], ty, ra, _tg = ints[:4]
                        c["type"] = TYPES[ty] if 0 <= ty < len(TYPES) else None
                        c["rarity"] = RARITIES[ra] if 0 <= ra < len(RARITIES) else None
        elif m == "get_CanonicalVars":
            for e in ev:
                if e[0] == "newobj" and (e[1].endswith("Var") or e[1].startswith("PowerVar")) and not e[1].startswith("Calculated"):
                    v = var_value(e[3])
                    if v is not None:
                        c["vars"][var_name(e[1], e[3])] = v
        else:  # OnUpgrade
            last = None
            for e in ev:
                if e[1] == "DynamicVarSet" and e[2].startswith("get_"):
                    last = e[3][0][1] if (e[2] == "get_Item" and e[3]) else e[2][4:]
                elif e[1] == "DynamicVar" and e[2] == "UpgradeValueBy" and last:
                    d = next((a[1] for a in e[3] if a[0] in ("d", "i")), None)
                    if d is not None:
                        c["delta"][last] = c["delta"].get(last, 0) + d
                    last = None
                elif e[1] == "CardEnergyCost" and e[2] == "UpgradeBy":
                    d = next((a[1] for a in e[3] if a[0] == "i"), None)
                    if d is not None:
                        c["cost_delta"] = c.get("cost_delta", 0) + d
    out = {}
    for cls, c in cards.items():
        if c.get("cost") is None:
            continue
        vars_ = c["vars"]
        up = dict(vars_)
        for g, d in c["delta"].items():
            key = g if g in vars_ else (g + "Power" if g + "Power" in vars_ else None)
            if key:
                up[key] = vars_[key] + d
        out[snake(cls)] = {"cost": c["cost"], "type": c.get("type"), "rarity": c.get("rarity"),
                           "vars": vars_, "up_vars": up, "up_cost": c["cost"] + c.get("cost_delta", 0)}
    return out


def read_vars(dll_path, ns):
    """Base numbers for relics (ns='Models.Relics') or potions (ns='Models.Potions')."""
    dn, t, mref = load(dll_path)
    out = {}
    for cls, m, row in card_methods(t, ("get_CanonicalVars",), ns):
        vs = {}
        for e in run(dn, t, mref, row):
            if e[0] == "newobj" and (e[1].endswith("Var") or e[1].startswith("PowerVar")) and not e[1].startswith("Calculated"):
                v = var_value(e[3])
                if v is not None:
                    vs[var_name(e[1], e[3])] = v
        if vs:
            out[snake(cls)] = vs
    return out
