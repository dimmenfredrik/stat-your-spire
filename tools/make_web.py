"""
make_web.py - builds the browser version (a static site) from the v4 folder.

  python tools/make_web.py <path to sts2_coach_v4> <output folder>

The Python analysis (sts2_coach_v4.py) is copied unchanged, only the personal path/Steam id placeholders are
sanitised. The page code is v4's, with two small changes: api() calls the in-page Python, and start() waits
until the player has picked their history folder. Pictures and the game-file extractor are NOT included.
"""
import os, re, shutil, sys

src, out = sys.argv[1], sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
if os.path.isdir(out):
    shutil.rmtree(out)
os.makedirs(os.path.join(out, "static")); os.makedirs(os.path.join(out, "py"))

for name in ("style.css", "deck.js", "focus.js"):
    shutil.copy(os.path.join(src, "static", name), os.path.join(out, "static", name))
shutil.copy(os.path.join(here, "web", "web.js"), os.path.join(out, "static", "web.js"))
shutil.copy(os.path.join(here, "web", "artworker.js"), os.path.join(out, "static", "artworker.js"))
for name in ("extract_art_from_game.py", "card_values.py", "spine_art.py"):
    shutil.copy(os.path.join(src, name), os.path.join(out, "py", name))
shutil.copy(os.path.join(here, "web", "web_art.py"), os.path.join(out, "py", "web_art.py"))

app = open(os.path.join(src, "static", "app.js"), encoding="utf-8").read()
old = 'async function api(name, ...args) {\n'
assert old in app
app = app.replace(old, old + '  if (window.WEB_API) return window.WEB_API(name, args);\n', 1)
old = '  await loadArt();\n  INIT = await api("init");'
assert old in app
app = app.replace(old, '  if (window.WEB_READY) await window.WEB_READY;\n' + old, 1)
old = 'async function loadArt() {'
assert old in app
app = app.replace(old, old + ' if (window.WEB) { await window.WEB_ART_READY; const a = window.webArt(); INFO = a.info; ART = new Map(a.list.map(f => [artKey(f.replace(/\\.[^.]+$/, "")), f])); return; }', 1)
# picture files come from the player's own browser storage (blob URLs), not from /art/
n_before = app.count("/art/")
app = re.sub(r"/art/\$\{encodeURIComponent\(([^)]*)\)\}", r"${artUrl(\1)}", app)
app = app.replace('"/art/" + encodeURIComponent(file)', "artUrl(file)")
open(os.path.join(out, "static", "app.js"), "w", encoding="utf-8").write(app)

deck = open(os.path.join(out, "static", "deck.js"), encoding="utf-8").read()
deck = re.sub(r"/art/\$\{encodeURIComponent\(([^)]*)\)\}", r"${artUrl(\1)}", deck)
open(os.path.join(out, "static", "deck.js"), "w", encoding="utf-8").write(deck)

html = open(os.path.join(src, "index.html"), encoding="utf-8").read()
html = html.replace('<script src="/static/app.js"></script>', '<script src="static/web.js"></script>\n<script src="static/app.js"></script>')
html = html.replace('/static/', 'static/')
html = html.replace('<script src="static/web.js"></script>\n<script src="static/app.js"></script>', '<script src="static/web.js"></script>\n<script src="static/app.js"></script>')
open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(html)

py = open(os.path.join(src, "sts2_coach_v4.py"), encoding="utf-8").read()
py = py.replace("C:\\Users\\dimme\\AppData", "C:\\Users\\YOU\\AppData").replace("76561198826734184", "YOUR_STEAM_ID")
assert "dimme" not in py and "7656119" not in py
open(os.path.join(out, "py", "sts2_coach_core.py"), "w", encoding="utf-8").write(py)
open(os.path.join(out, ".nojekyll"), "w").write("")
print("built", out)
