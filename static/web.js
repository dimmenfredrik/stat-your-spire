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
  // the runs themselves are kept in this browser too, so a refresh does not ask for them again
  const savedRuns = () => idb("readonly", s => s.get("runs")).catch(() => null);
  const forgetRuns = () => idb("readwrite", s => s.delete("runs")).catch(() => {});
  async function keepRuns(files) {
    try {
      const out = [];
      for (const f of files.filter(f => f.name.endsWith(".run"))) out.push({name: f.name, lm: f.lastModified, buf: await f.arrayBuffer()});
      if (out.length) await idb("readwrite", s => s.put(out, "runs"));
    } catch (e) {}
  }

  // ---------- start screen
  function screen() {
    const el = document.createElement("div");
    el.id = "webStart";
    el.className = "fixed inset-0 z-50 bg-bg grid place-items-center p-6 overflow-auto";
    el.innerHTML = `<div class="w-full max-w-5xl grid gap-8 lg:grid-cols-[1.15fr_1fr] items-center">
      <div>
        <div class="flex items-center gap-3"><div class="size-10 rounded-lg bg-[#8da2c0] text-[#12151b] grid place-items-center font-extrabold">S2</div><div class="text-xl font-extrabold">STS2 Coach</div></div>
        <h1 class="mt-6 text-3xl sm:text-4xl font-extrabold leading-tight">See exactly where your runs go wrong</h1>
        <p class="mt-3 text-[15px] text-dim leading-relaxed">Habits that cost you runs, the bosses that beat you, your best cards, and a Focus screen for your second monitor. Made from your own finished runs.</p>
        <div class="relative mt-5 h-64 overflow-hidden rounded-xl border border-line"><img src="static/preview.webp" alt="" class="h-full w-full object-cover object-top"><div class="absolute inset-0" style="background:linear-gradient(180deg,transparent 60%,#14171d)"></div></div>
      </div>
      <div class="rounded-2xl border border-line bg-card p-6">
        <div class="text-lg font-bold">Load your runs</div>
        <div class="mt-1 text-xs text-faint">Takes about 30 seconds. Nothing is uploaded and your game files are only read, never changed.</div>
        <div id="wsRes" class="mt-4"></div>
        <ol class="mt-4 space-y-2.5 text-[13px] text-dim leading-snug">
          <li class="flex gap-2.5"><span class="grid size-5 shrink-0 place-items-center rounded-full bg-[var(--accent)]/20 text-[11px] font-extrabold text-[var(--accent)]">1</span><span>Press the button, paste <code class="rounded bg-card2 px-1.5 py-0.5 text-[12px] text-ink">%APPDATA%\\SlayTheSpire2\\steam</code> into the address bar of the window that opens and press Enter. <button id="wsCopy" class="font-semibold text-[var(--accent)]">Copy</button></span></li>
          <li class="flex gap-2.5"><span class="grid size-5 shrink-0 place-items-center rounded-full bg-[var(--accent)]/20 text-[11px] font-extrabold text-[var(--accent)]">2</span><span>Open your number folder, then <code class="rounded bg-card2 px-1.5 py-0.5 text-[12px] text-ink">profile1\\saves\\history</code>. Press <b class="text-ink">Ctrl+A</b> to select all the runs, then <b class="text-ink">Open</b>.</span></li>
          <li class="flex gap-2.5"><span class="grid size-5 shrink-0 place-items-center rounded-full bg-[var(--accent)]/20 text-[11px] font-extrabold text-[var(--accent)]">3</span><span>That is it. You can also drag the run files onto this page.</span></li></ol>
        <div id="wsMsg" class="mt-4 text-sm text-dim"></div>
        <div id="wsErr" class="mt-2 text-sm text-bad"></div>
        <p class="mt-5 text-[11px] text-faint">Want it to refresh by itself while you play? Get the <a class="underline" href="https://github.com/dimmenfredrik/sts2-coach" target="_blank" rel="noopener">downloadable version</a>. Unofficial fan tool, not affiliated with Mega Crit.</p></div></div>`;
    document.body.appendChild(el);
    $("wsCopy").onclick = () => { navigator.clipboard && navigator.clipboard.writeText("%APPDATA%\\SlayTheSpire2\\steam"); $("wsCopy").textContent = "Copied"; };
    return el;
  }
  const btn = (id, text, primary) => `<button id="${id}" class="w-full rounded-xl px-5 py-3 text-[15px] font-bold transition ${primary ? "bg-[var(--accent)] text-[#12151b] hover:opacity-90" : "border border-line bg-card2 hover:border-[var(--accent)]"}">${text}</button>`;

  async function finish(files, el, noSave) {
    $("wsErr").textContent = ""; $("wsMsg").textContent = "Reading your runs...";
    await booted;
    const n = await loadFiles(files, true);
    if (!n) { $("wsMsg").textContent = ""; $("wsErr").textContent = "No .run files in that folder. Pick the folder called history that holds them."; return false; }
    if (!noSave) keepRuns(files);
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
    const saved = await savedRuns();
    if (saved && saved.length) {
      $("wsMsg").textContent = "Loading your saved runs (" + saved.length + ")...";
      const ok = await finish(saved.map(r => new File([r.buf], r.name, {lastModified: r.lm})), el, true).catch(() => false);
      if (ok) return;
      $("wsMsg").textContent = "";
    }
    const last = window.showDirectoryPicker ? await lastHandle() : null;
    $("wsRes").innerHTML = (last ? btn("wsLast", "Use the same folder as last time (" + esc(last.name) + ")", true) + `<div class="h-2"></div>` : "") + btn("wsFiles", "Choose run files", !last) + (window.showDirectoryPicker ? `<div class="mt-2 text-center text-xs text-faint"><button id="wsPick" class="underline hover:text-ink">or choose a whole folder (not inside AppData)</button></div>` : "");
    $("wsFiles").onclick = () => pickFiles(el);
    if ($("wsPick")) $("wsPick").onclick = () => pick(el);
    if (last) $("wsLast").onclick = async () => {
      try { if ((await last.requestPermission({mode: "read"})) !== "granted") throw 0; dirHandle = last; folderName = last.name; await finish(await filesFromHandle(last), el); }
      catch (e) { $("wsErr").textContent = "That folder is not available any more. Choose it again."; }
    };
    el.addEventListener("dragover", e => e.preventDefault());
    el.addEventListener("drop", async e => { e.preventDefault(); const fs = [...(e.dataTransfer.files || [])]; if (fs.length) await finish(fs, el); });
  }


  // ---------- card pictures: built from the player's own game files, kept only in this browser
  window.WEB_ART = {urls: {}, list: [], info: {}};
  window.artUrl = f => window.WEB_ART.urls[f] || "/art/" + encodeURIComponent(f);
  window.webArt = () => ({info: window.WEB_ART.info, list: window.WEB_ART.list});
  const artGet = () => idb("readonly", s => s.get("art")).catch(() => null);
  const artPut = v => idb("readwrite", s => s.put(v, "art"));
  const artDel = () => idb("readwrite", s => s.delete("art")).catch(() => {});
  function applyArt(rec) {
    Object.values(window.WEB_ART.urls).forEach(u => { try { URL.revokeObjectURL(u); } catch (e) {} });
    const urls = {}, list = [];
    if (rec) for (const [n, buf] of Object.entries(rec.files)) { urls[n] = URL.createObjectURL(new Blob([buf], {type: "image/webp"})); list.push(n); }
    window.WEB_ART = {urls, list, info: rec ? JSON.parse(rec.info) : {}};
  }
  async function reloadArtUi() {
    if (typeof loadArt === "function") await loadArt();
    if (typeof renderAll === "function") { try { renderAll(); } catch (e) {} }
    artButton();
  }
  function artButton() {
    let b = $("webArtBtn");
    if (!b) {
      const fb = $("folderBtn"); if (!fb || !fb.parentElement) return;
      b = document.createElement("button"); b.id = "webArtBtn";
      b.className = "mb-2 w-full rounded-lg border border-line bg-card2 px-3 py-2 text-sm font-semibold hover:border-[var(--accent)]";
      b.onclick = artDialog; fb.parentElement.insertAdjacentElement("beforebegin", b);
    }
    b.textContent = window.WEB_ART.list.length ? "Card pictures: on" : "Add card pictures";
  }
  function artDialog() {
    if ($("webArtDlg")) return;
    const have = window.WEB_ART.list.length;
    const el = document.createElement("div");
    el.id = "webArtDlg"; el.className = "fixed inset-0 z-[60] grid place-items-center bg-black/60 p-6 overflow-auto";
    const PATH = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Slay the Spire 2";
    const file = (id, label, note, path) => `<div class="mt-4"><div class="flex items-center gap-3"><button id="${id}" class="shrink-0 rounded-lg border border-line bg-card2 px-3 py-2 text-sm font-semibold hover:border-[var(--accent)]">${label}</button><span id="${id}T" class="text-xs text-faint">${note}</span></div>
      <div class="mt-2 flex items-center gap-2"><code class="min-w-0 flex-1 break-all rounded-md bg-card2 px-2 py-1 text-[11.5px] text-ink">${path}</code><button id="${id}C" class="shrink-0 rounded-md border border-line px-2 py-1 text-xs font-semibold text-[var(--accent)]">Copy path</button></div></div>`;
    el.innerHTML = `<div class="w-full max-w-xl rounded-2xl border border-line bg-card p-7">
      <div class="text-lg font-extrabold">Card pictures</div>
      <p class="mt-2 text-[14px] leading-relaxed text-dim">The pictures are made right here from <b class="text-ink">your own copy of the game</b>, once. They stay in this browser and are <b class="text-ink">never uploaded</b>.</p>
      ${have ? `<p class="mt-3 text-sm text-good">Pictures are on (${have} images).</p>` : ""}
      <p class="mt-4 text-[13px] leading-relaxed text-dim">Press a button, then in the window that opens <b class="text-ink">click the address bar at the top, paste the path (Ctrl+V) and press Enter</b>. The file is then listed: click it and press Open.</p>
      ${file("wdPck", "Choose SlayTheSpire2.pck", "about 2 GB, only read", PATH)}
      ${file("wdDll", "Choose sts2.dll", "optional: real card numbers", PATH + "\\data_sts2_windows_x86_64")}
      <p class="mt-3 text-[12px] text-faint">Not found? Steam may be on another drive. In Steam right-click Slay the Spire 2 → Manage → Browse local files, then copy that folder's address instead.</p>
      <div class="mt-5 flex gap-2"><button id="wdGo" class="flex-1 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-[15px] font-bold text-[#12151b] opacity-50" disabled>Make the pictures</button><button id="wdClose" class="rounded-xl border border-line bg-card2 px-4 py-2.5 text-[15px] font-semibold">Close</button></div>
      ${have ? `<button id="wdRemove" class="mt-3 text-xs text-faint underline">Remove the pictures from this browser</button>` : ""}
      <div id="wdMsg" class="mt-3 text-sm text-dim"></div><div id="wdErr" class="mt-1 text-sm text-bad"></div></div>`;
    document.body.appendChild(el);
    const chosen = {pck: null, dll: null};
    const choose = (key, accept, tid) => { const i = document.createElement("input"); i.type = "file"; i.accept = accept; i.onchange = () => { if (i.files[0]) { chosen[key] = i.files[0]; $(tid).textContent = i.files[0].name; $("wdGo").disabled = !chosen.pck; $("wdGo").style.opacity = chosen.pck ? 1 : .5; } }; i.click(); };
    const copy = (id, text) => { $(id).onclick = async () => { try { await navigator.clipboard.writeText(text); $(id).textContent = "Copied"; } catch (e) { $(id).textContent = "Select and copy it by hand"; } }; };
    copy("wdPckC", PATH); copy("wdDllC", PATH + "\\data_sts2_windows_x86_64");
    $("wdPck").onclick = () => choose("pck", ".pck", "wdPckT");
    $("wdDll").onclick = () => choose("dll", ".dll", "wdDllT");
    $("wdClose").onclick = () => { if (!el.dataset.busy) el.remove(); };
    if ($("wdRemove")) $("wdRemove").onclick = async () => { await artDel(); applyArt(null); await reloadArtUi(); el.remove(); };
    $("wdGo").onclick = () => {
      el.dataset.busy = "1"; $("wdGo").disabled = true; $("wdGo").style.opacity = .5; $("wdErr").textContent = "";
      const root = new URL(".", location.href).href;
      const w = new Worker("static/artworker.js");
      w.onmessage = async ev => {
        const d = ev.data;
        if (d.msg) $("wdMsg").textContent = d.msg;
        if (d.error) { $("wdErr").textContent = "That did not work: " + d.error; delete el.dataset.busy; $("wdGo").disabled = false; $("wdGo").style.opacity = 1; w.terminate(); }
        if (d.done) {
          w.terminate();
          const rec = {files: d.files, info: d.info};
          try { await artPut(rec); } catch (e) { $("wdErr").textContent = "Pictures are ready but could not be kept for next time (browser storage refused)."; }
          applyArt(rec); await reloadArtUi(); $("wdMsg").textContent = "Done."; delete el.dataset.busy; setTimeout(() => el.remove(), 600);
        }
      };
      w.onerror = ev => { $("wdErr").textContent = "That did not work: " + (ev.message || "the worker failed"); delete el.dataset.busy; $("wdGo").disabled = false; $("wdGo").style.opacity = 1; };
      w.postMessage({pck: chosen.pck, dll: chosen.dll, base: BASE, pyBase: root + "py/"});
    };
  }
  window.__webArtApply = async rec => { applyArt(rec); };   // test hook

  // ---------- the page talks to Python through this
  window.WEB_API = async function (name, args) {
    await booted;
    if (name === "set_folder") return {ok: false, error: "Use the folder button."};
    if (name === "poll" && dirHandle) { try { await loadFiles(await filesFromHandle(dirHandle), false); } catch (e) {} }
    if (name === "reload" && dirHandle) { try { await loadFiles(await filesFromHandle(dirHandle), false); } catch (e) {} }
    py.globals.set("_n", name); py.globals.set("_a", JSON.stringify(args || []));
    return JSON.parse(py.runPython("call(_n, _a)"));
  };

  try { navigator.storage && navigator.storage.persist && navigator.storage.persist(); } catch (e) {}   // ask the browser not to clear our saved runs/pictures
  window.__webLoad = fs => finish(fs, $("webStart"));
  window.WEB_ART_READY = artGet().then(rec => { if (rec) applyArt(rec); }).catch(() => {});
  document.addEventListener("DOMContentLoaded", () => {
    startup(); artButton(); window.WEB_ART_READY.then(artButton);
    const fb = $("folderBtn");
    if (fb) fb.addEventListener("click", async e => {
      e.stopImmediatePropagation();
      const el = screen(); el.querySelector("#wsRes").innerHTML = btn("wsFiles2", "Choose run files", true) + `<div class="mt-2 text-center text-xs text-faint"><button id="wsForget" class="underline hover:text-ink">Forget the runs saved in this browser</button></div>`;
      el.querySelector("#wsForget").onclick = async () => { await forgetRuns(); el.querySelector("#wsForget").textContent = "Forgotten. They will not load next time."; };
      el.querySelector("#wsFiles2").onclick = async () => { if (await pickFiles(el)) { await window.WEB_API("reload", []); if (typeof refresh === "function") refresh(); } };
    }, true);
  });
})();
