/* Builds the picture library from the player's OWN Slay the Spire 2 files, inside this browser (Web Worker).
   Nothing is uploaded. The game file is read in small pieces (it is about 2 GB), never loaded whole. */
let py;
const post = m => postMessage({msg: m});
onmessage = async e => {
  const {pck, dll, base, pyBase} = e.data;
  try {
    post("Loading the analysis engine (first time only)...");
    importScripts(base + "pyodide.js");
    py = await loadPyodide({indexURL: base});
    await py.loadPackage(["pillow", "micropip"]);
    post("Loading the code reader...");
    await py.runPythonAsync("import micropip\nawait micropip.install(['dnfile', 'dncil'])");
    py.FS.mkdirTree("/app");
    for (const n of ["extract_art_from_game.py", "card_values.py", "spine_art.py", "web_art.py"])
      py.FS.writeFile("/app/" + n, await (await fetch(pyBase + n)).text());
    const frs = new FileReaderSync();
    py.globals.set("read_range", (o, n) => new Uint8Array(frs.readAsArrayBuffer(pck.slice(o, o + n))));
    py.globals.set("pck_size", pck.size);
    py.globals.set("progress", post);
    let haveDll = false;
    if (dll) { py.FS.writeFile("/app/sts2.dll", new Uint8Array(frs.readAsArrayBuffer(dll))); haveDll = true; }
    py.globals.set("have_dll", haveDll);
    const res = await py.runPythonAsync(`
import sys, json
sys.path.insert(0, "/app")
import web_art
from pyodide.ffi import to_js
import js
files, info = web_art.build(web_art.RangeFile(pck_size, read_range), "/app/sts2.dll" if have_dll else None, progress)
to_js({"files": files, "info": json.dumps(info)}, dict_converter=js.Object.fromEntries, depth=2)
`);
    const out = res.files ? res : res;
    const files = {}, buffers = [];
    for (const [k, u] of Object.entries(res.files)) { const b = new Uint8Array(u).slice().buffer; files[k] = b; buffers.push(b); }   // copies: the originals may live in the wasm heap
    postMessage({done: true, files, info: res.info}, buffers);
  } catch (err) {
    postMessage({error: String(err && err.message || err).slice(0, 600)});
  }
};
