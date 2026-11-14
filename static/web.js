/* STS2 Coach, browser version.
   Runs the unchanged Python analysis inside this page (Pyodide) and reads the player's finished
   .run files from a folder they pick. Nothing is uploaded: the files are only read inside this page. */
(function () {
  const BASE = window.PYODIDE_BASE || "https://cdn.jsdelivr.net/pyodide/v0.27.8/full/";
  const $ = id => document.getElementById(id);
  let py = null, dirHandle = null, folderName = "", booted = null, resolveReady;
  const seen = new Map();                       // file name -> lastModified already written to the virtual disk
  window.WEB = true;
  window.WEB_READY = new Promise(r => resolveReady = r);

  const loadScript = src => new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = () => rej(new Error("Could not load " + src)); document.head.appendChild(s); });

  async function bootPython() {
    await loadScript(BASE + "pyodide.js");
    py = await loadPyodide({indexURL: BASE});
    const code = await (await fetch("py/sts2_coach_core.py")).text();
    py.FS.mkdirTree("/app"); py.FS.writeFile("/app/sts2_coach_core.py", code);
    py.globals.set("_tzoff", new Date().getTimezoneOffset());
    py.runPython(`
import sys, json, time as _t
sys.path.insert(0, "/app")
import sts2_coach_core as core
from datetime import datetime, timedelta
def _local(ts):
    return datetime(1970, 1, 1) + timedelta(seconds=ts - _tzoff * 60)
core.fmt_date = lambda ts, fmt: _local(ts).strftime(fmt) if ts else "?"
class _Clock:
    def __getattr__(self, n): return getattr(_t, n)
    def strftime(self, fmt, t=None): return _local(_t.time()).strftime(fmt)
core.time = _Clock()
api = core.CoachAPI()
def call(name, args_json):
    if name not in ("init", "poll", "reload", "query", "card_detail", "autopsy"):
        return json.dumps({"error": "unknown call"})
    try:
        return json.dumps(getattr(api, name)(*json.loads(args_json)))
    except Exception as e:
        return json.dumps({"error": repr(e)})
`);
  }

  // ---------- files -> virtual disk
  function mostCommonPlayerId(texts) {
    const c = new Map();
    for (const t of texts) { try { for (const p of (JSON.parse(t).players || [])) { const id = String(p.id || ""); if (/^\d{17}$/.test(id)) c.set(id, (c.get(id) || 0) + 1); } } catch (e) {} }
    let best = "", n = 0; c.forEach((v, k) => { if (v > n) { n = v; best = k; } }); return best;
  }
  async function loadFiles(files, first) {
    const runs = files.filter(f => f.name.endsWith(".run"));
    if (!runs.length) return 0;
    let dir = window._histDir;
    if (first || !dir) {
      const sample = await Promise.all(runs.slice(0, 40).map(f => f.text()));
      const sid = mostCommonPlayerId(sample);
      dir = sid ? `/steam/${sid}/profile1/saves/history` : "/history";
      py.FS.mkdirTree(dir); window._histDir = dir;
      py.runPython(`api._history_dir = ${JSON.stringify(dir)}\napi._cache.clear()\napi._last_seen = set()`);
    }
    let changed = 0;
    const names = new Set();
    for (const f of runs) {
      names.add(f.name);
      if (seen.get(f.name) === f.lastModified) continue;
      const path = dir + "/" + f.name;
      py.FS.writeFile(path, new Uint8Array(await f.arrayBuffer()));
      py.FS.utime(path, f.lastModified, f.lastModified);
      seen.set(f.name, f.lastModified); changed++;
    }
    for (const n of [...seen.keys()]) if (!names.has(n)) { try { py.FS.unlink(dir + "/" + n); } catch (e) {} seen.delete(n); changed++; }
    return changed;
  }
  async function filesFromHandle(h) {
    const out = [];
    for await (const e of h.values()) if (e.kind === "file" && e.name.endsWith(".run")) out.push(await e.getFile());
    return out;
  }

  // ---------- remembered folder (so the next visit is one click)
  const idb = (mode, fn) => new Promise((res, rej) => { const o = indexedDB.open("sts2coach", 1); o.onupgradeneeded = () => o.result.createObjectStore("kv"); o.onerror = () => rej(o.error); o.onsuccess = () => { const tx = o.result.transaction("kv", mode), r = fn(tx.objectStore("kv")); tx.oncomplete = () => res(r && r.result); tx.onerror = () => rej(tx.error); }; });
  const saveHandle = h => idb("readwrite", s => s.put(h, "dir")).catch(() => {});
  const lastHandle = () => idb("readonly", s => s.get("dir")).catch(() => null);

  // ---------- start screen
  function screen() {
    const el = document.createElement("div");
    el.id = "webStart";
    el.className = "fixed inset-0 z-50 bg-bg grid place-items-center p-6 overflow-auto";
    el.innerHTML = `<div class="w-full max-w-xl rounded-2xl border border-line bg-card p-8">
      <div class="flex items-center gap-3"><div class="size-10 rounded-lg bg-[#8da2c0] text-[#12151b] grid place-items-center font-extrabold">S2</div><div><div class="text-xl font-extrabold">STS2 Coach</div><div class="text-xs text-faint">Slay the Spire 2 run analytics, in your browser</div></div></div>
      <p class="mt-5 text-[15px] text-dim leading-relaxed">Pick your finished runs (the .run files). Everything is worked out inside this page. <b class="text-ink">Nothing is uploaded</b> and your game files are only read, never changed.</p>
      <div class="mt-5 rounded-xl bg-card2 p-4 text-sm">
        <div class="text-[11px] font-bold tracking-wider text-faint">WHERE IS IT?</div>
        <code class="mt-1 block break-all text-[13px] text-ink">%APPDATA%\\SlayTheSpire2\\steam\\&lt;your steam id&gt;\\profile1\\saves\\history</code>
        <button id="wsCopy" class="mt-2 text-xs font-semibold text-[var(--accent)]">Copy the start of this path</button>
        <span class="text-xs text-faint"> and paste it into the address bar of the folder window.</span></div>
      <div id="wsRes" class="mt-5"></div>
      <div id="wsMsg" class="mt-4 text-sm text-dim"></div>
      <div id="wsErr" class="mt-2 text-sm text-bad"></div>
      <p class="mt-6 text-[11px] text-faint">Unofficial fan tool, not affiliated with Mega Crit. Card pictures and exact card numbers are only in the downloadable version, because they come from your own game files.</p></div>`;
    document.body.appendChild(el);
    $("wsCopy").onclick = () => { navigator.clipboard && navigator.clipboard.writeText("%APPDATA%\\SlayTheSpire2\\steam"); $("wsCopy").textContent = "Copied"; };
    return el;
  }
  const btn = (id, text, primary) => `<button id="${id}" class="w-full rounded-xl px-5 py-3 text-[15px] font-bold transition ${primary ? "bg-[var(--accent)] text-[#12151b] hover:opacity-90" : "border border-line bg-card2 hover:border-[var(--accent)]"}">${text}</button>`;

  async function finish(files, el) {
    $("wsErr").textContent = ""; $("wsMsg").textContent = "Reading your runs...";
    await booted;
    const n = await loadFiles(files, true);
    if (!n) { $("wsMsg").textContent = ""; $("wsErr").textContent = "No .run files in that folder. Pick the folder called history that holds them."; return false; }
    el.remove(); resolveReady(); return true;
  }
  async function pick(el) {
    if (window.showDirectoryPicker) {
      try { dirHandle = await showDirectoryPicker({id: "sts2-history", mode: "read"}); } catch (e) { return false; }
      folderName = dirHandle.name; saveHandle(dirHandle);
      return finish(await filesFromHandle(dirHandle), el);
    }
    return new Promise(res => { const i = document.createElement("input"); i.type = "file"; i.webkitdirectory = true; i.multiple = true; i.onchange = async () => res(await finish([...i.files], el)); i.click(); });
  }
  function pickFiles(el) {   // plain file chooser: not subject to Chrome's folder block
    return new Promise(res => { const i = document.createElement("input"); i.type = "file"; i.multiple = true; i.accept = ".run"; i.onchange = async () => { dirHandle = null; res(await finish([...i.files], el)); }; i.click(); });
  }
  function pickLegacy(el) {   // old-style folder chooser: Chrome does not block AppData here
    return new Promise(res => { const i = document.createElement("input"); i.type = "file"; i.webkitdirectory = true; i.multiple = true; i.onchange = async () => { dirHandle = null; res(await finish([...i.files], el)); }; i.click(); });
  }
  async function startup() {
    const el = screen();
    $("wsMsg").textContent = "Loading the analysis engine (about 10 MB, first time only)...";
    booted = bootPython().then(() => { $("wsMsg").textContent = ""; }).catch(e => { $("wsErr").textContent = "Could not load the analysis engine: " + e.message + ". Check your connection and reload."; throw e; });
    const last = window.showDirectoryPicker ? await lastHandle() : null;
    const hint = `<div class="mt-3 rounded-xl border border-dashed border-line p-4 text-[13px] text-dim leading-relaxed"><b class="text-ink">Easiest:</b> press the button, paste the path into the address bar of the window that opens, press Enter, then press <b class="text-ink">Ctrl+A</b> to select all the runs and <b class="text-ink">Open</b>. Or open that folder in Explorer, press Ctrl+A, and <b class="text-ink">drag the files onto this page</b>.</div>`;
    $("wsRes").innerHTML = (last ? btn("wsLast", "Use the same folder as last time (" + esc(last.name) + ")", true) + `<div class="h-2"></div>` : "") + btn("wsFiles", "Choose run files", !last) + hint + (window.showDirectoryPicker ? `<div class="h-3"></div>` + btn("wsPick", "Or choose a whole folder (not inside AppData)", false) : "");
    $("wsFiles").onclick = () => pickFiles(el);
    if ($("wsPick")) $("wsPick").onclick = () => pick(el);
    if (last) $("wsLast").onclick = async () => {
      try { if ((await last.requestPermission({mode: "read"})) !== "granted") throw 0; dirHandle = last; folderName = last.name; await finish(await filesFromHandle(last), el); }
      catch (e) { $("wsErr").textContent = "That folder is not available any more. Choose it again."; }
    };
    el.addEventListener("dragover", e => e.preventDefault());
    el.addEventListener("drop", async e => { e.preventDefault(); const fs = [...(e.dataTransfer.files || [])]; if (fs.length) await finish(fs, el); });
  }

  // ---------- the page talks to Python through this
  window.WEB_API = async function (name, args) {
    await booted;
    if (name === "set_folder") return {ok: false, error: "Use the folder button."};
    if (name === "poll" && dirHandle) { try { await loadFiles(await filesFromHandle(dirHandle), false); } catch (e) {} }
    if (name === "reload" && dirHandle) { try { await loadFiles(await filesFromHandle(dirHandle), false); } catch (e) {} }
    py.globals.set("_n", name); py.globals.set("_a", JSON.stringify(args || []));
    return JSON.parse(py.runPython("call(_n, _a)"));
  };

  window.__webLoad = fs => finish(fs, $("webStart"));
  document.addEventListener("DOMContentLoaded", () => {
    startup();
    const fb = $("folderBtn");
    if (fb) fb.addEventListener("click", async e => {
      e.stopImmediatePropagation();
      const el = screen(); el.querySelector("#wsRes").innerHTML = btn("wsFiles2", "Choose run files", true);
      el.querySelector("#wsFiles2").onclick = async () => { if (await pickFiles(el)) { await window.WEB_API("reload", []); if (typeof refresh === "function") refresh(); } };
    }, true);
  });
})();
