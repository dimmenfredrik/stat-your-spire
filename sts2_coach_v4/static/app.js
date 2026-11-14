/* ================================================================= helpers */
const ALL = "All characters";
const RANGES = ["All runs", "Last 30", "Last 50", "Current build"];
const THEMES = {Ironclad: "#e5484d", Silent: "#34d399", Defect: "#4c8dff", Necrobinder: "#a78bfa", Regent: "#f0b44c", Fool: "#f472b6"};
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const num = (x, d = 0) => (x === null || x === undefined || Number.isNaN(x)) ? "–" : Number(x).toFixed(d);
const sgn = (x, d = 0) => (x === null || x === undefined) ? "–" : (x < 0 ? "−" : "+") + Math.abs(x).toFixed(d);
const hexA = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };
async function api(name, ...args) {
  const r = await fetch("/api/" + name, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(args)});
  return r.json();
}
const S = {character: ALL, asc: "All", range: "All runs", quits: false, coop: true, auto: true, tab: "focus",
           feedN: 12, open: new Set(), sort: {key: "lift", desc: true}, search: "", expandedHabits: new Set()};
let D = null, busy = false, again = false, charts = {}, INIT = null;

// character pictures (built from the player's own game files; absent -> the coloured dot is used)
const charKey = n => String(n || "").toLowerCase().replace(/[^a-z]+/g, "");
const charArt = (n, kind) => { const f = ART.get("char_" + kind + "_" + charKey(n)); return f ? `/art/${encodeURIComponent(f)}` : ""; };
const charIcon = (n, px) => { const u = charArt(n, "icon"); return u ? `<img src="${u}" alt="" style="height:${px}px;width:${px}px" class="object-contain drop-shadow">` : ""; };
function themeColor(name) {
  if (!name || name === ALL) return "#7d93b5";
  if (THEMES[name]) return THEMES[name];
  const e = D && D.sidebar.find(x => x.name === name);
  return (e && e.color) || "#7d93b5";
}
const PILL = {
  gold: "bg-warn/15 text-warn", potion: "bg-info/15 text-info", pair: "bg-violet/15 text-violet", bleed: "bg-bad/15 text-bad",
  synergy: "bg-violet/15 text-violet",
};
const GRADE = {S: "bg-violet", A: "bg-good", B: "bg-info", C: "bg-warn", D: "bg-bad", N: "bg-card2 text-faint"};
const pill = (k, label) => `<span class="rounded-full px-2.5 py-1 text-[10.5px] font-extrabold tracking-wide whitespace-nowrap ${PILL[k] || "bg-card2 text-dim"}">${esc(label)}</span>`;
const panel = (inner, cls = "") => `<section class="rounded-xl border border-line bg-card p-5 ${cls}">${inner}</section>`;
const head = (title, tag = "") => `<div class="flex items-center justify-between mb-3"><h3 class="text-sm font-bold tracking-wide">${esc(title)}</h3><span class="text-[10.5px] font-semibold tracking-wider text-faint">${esc(tag)}</span></div>`;

/* ================================================================= icons, wiki links, optional local art */
const ICON_PATHS = {
  monster: '<path d="M4 20L19 5M14 5h5v5M20 20L5 5M10 5H5v5"/>',
  elite: '<path d="M12 3a7 7 0 0 0-4 12.7V19h8v-3.7A7 7 0 0 0 12 3z"/><path d="M9.5 11h.01M14.5 11h.01"/>',
  boss: '<path d="M3 9l5 4 4-7 4 7 5-4-2 10H5z"/>',
  rest_site: '<path d="M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-3-1-6 1-9z"/>',
  shop: '<path d="M5 8h14l-1 12H6zM9 8a3 3 0 0 1 6 0"/>',
  event: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17h.01"/>',
  treasure: '<path d="M4 10h16v9H4zM4 10a8 5 0 0 1 16 0M12 13v3"/>',
  ancient: '<path d="M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>'
};
const ico = (k, px = 14) => `<svg width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="shrink-0">${ICON_PATHS[k] || ""}</svg>`;
const WIKI = "https://slaythespire.wiki.gg/wiki/Special:Search?go=Go&search=";
const wikiUrl = n => WIKI + encodeURIComponent("Slay the Spire 2:" + n);
const wikiName = n => String(n).replace(/\s*\((elite|weak|boss)\)\s*$/i, "").split(":")[0].trim();
const wikiA = (n, inner) => `<a data-tip="${esc(wikiName(n))}" href="${wikiUrl(wikiName(n))}" target="_blank" rel="noopener" class="underline decoration-dotted decoration-white/25 underline-offset-[3px] hover:text-[var(--accent)] hover:decoration-[var(--accent)]">${inner ?? esc(n)}</a>`;
const wikiMulti = label => String(label).split(" / ").map(x => wikiA(x, `${artImg(wikiName(x), 36)}${esc(x)}`)).join(' <span class="text-faint">/</span> ');
let ART = new Map();
const artKey = n => String(n).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
const artImg = (n, px = 24) => { const f = ART.get(artKey(n)); return f ? `<img src="/art/${encodeURIComponent(f)}" alt="" style="height:${px}px;width:auto;max-width:${Math.round(px * 1.5)}px" data-art="/art/${encodeURIComponent(f)}" class="artthumb inline-block rounded-md object-contain align-middle mr-2 cursor-zoom-in">` : ""; };
let INFO = {};
async function loadArt() { try { INFO = await (await fetch("/art-info")).json(); } catch (e) { INFO = {}; } await loadArtFiles(); }
async function loadArtFiles() { try { const r = await fetch("/art-list"); const l = await r.json(); ART = new Map(l.map(f => [artKey(f.replace(/\.[^.]+$/, "")), f])); } catch (e) { ART = new Map(); } }

/* ================================================================= data */
function params() {
  return {character: S.character, asc: S.asc, range: S.range, include_abandoned: S.quits, include_multi: S.coop,
          biome: "All acts", min_picks: 8, killer: null};
}
async function refresh() {
  if (busy) { again = true; return; }
  busy = true;
  try {
    const res = await api("query", params());
    if (res && res.error) { $("#view").innerHTML = panel(`<b class="text-bad">Something went wrong.</b><div class="text-sm text-dim mt-1">${esc(res.error)}<br>Details are in sts2_coach_v3.log next to the program.</div>`); return; }
    D = res;
    S.character = D.effective.character; S.asc = D.effective.asc;
    renderAll();
  } finally {
    busy = false;
    if (again) { again = false; refresh(); }
  }
}

/* ================================================================= chrome */
function renderAll() {
  const col = themeColor(S.character);
  document.documentElement.style.setProperty("--accent", col);
  renderSidebar(); renderBanner(); renderTabs(); renderView();
}
function renderSidebar() {
  $("#chars").innerHTML = D.sidebar.map(e => {
    const sel = e.name === S.character, c = e.name === ALL ? "#e9edf3" : themeColor(e.name);
    return `<button data-char="${esc(e.name)}" class="flex items-center gap-3 rounded-lg px-3 py-2 text-left text-sm transition ${sel ? "bg-card2 font-semibold" : "text-dim hover:bg-card"}" ${sel ? `style="box-shadow:inset 3px 0 0 ${c};background-image:linear-gradient(90deg,${hexA(c, .42)},transparent 90%)"` : e.name !== ALL && charArt(e.name, "icon") ? `style="background-image:linear-gradient(90deg,${hexA(c, .13)},transparent 70%)"` : ""}>
      ${e.name !== ALL && charArt(e.name, "icon") ? `<span class="grid size-5 place-items-center">${charIcon(e.name, 20)}</span>` : `<span class="size-2.5 rounded-full" style="background:${c}"></span>`}<span class="flex-1 truncate">${esc(e.name)}</span>
      <span class="num text-xs text-faint">${e.w}-${e.l}</span><span class="num text-xs w-9 text-right font-semibold ${e.pct >= 25 ? "text-good" : "text-faint"}">${num(e.pct)}%</span></button>`;
  }).join("");
  const st = D.status;
  $("#status").innerHTML = st.folder_ok ? `${st.loaded} runs loaded · ${esc(st.time)}` : `<span class="text-warn">History folder not found.</span>`;
}
function renderBanner() {
  const h = D.header;
  $("#title").textContent = h.title;
  $("#subtitle").textContent = h.subtitle;
  $("#asc").innerHTML = D.asc_values.map(v => `<option ${v === S.asc ? "selected" : ""}>${esc(v)}</option>`).join("");
  $("#range").innerHTML = RANGES.map(r => `<button data-range="${r}" class="rounded-md px-3 py-1 text-sm font-medium transition ${r === S.range ? "bg-card2 text-[var(--accent)]" : "text-dim hover:text-ink"}">${r}</button>`).join("");
  $("#build").textContent = D.current_build ? "build " + D.current_build : "";
  const dot = `<span class="size-3.5 rounded-full" style="background:var(--accent);box-shadow:0 0 0 5px color-mix(in srgb,var(--accent) 18%,transparent)"></span>`;
  const chars = D.sidebar.filter(e => e.name !== ALL && charArt(e.name, "icon"));
  $("#bannerIcon").innerHTML = S.character !== ALL ? (charArt(S.character, "icon") ? charIcon(S.character, 52) : dot)
    : (chars.length ? `<span class="flex gap-1">${chars.map(e => charIcon(e.name, 32)).join("")}</span>` : dot);
  const splash = S.character !== ALL ? charArt(S.character, "splash") : "";
  const por = S.character !== ALL && !splash ? charArt(S.character, "portrait") : "";
  const ba = $("#bannerArt");
  ba.classList.toggle("hidden", !splash && !por);
  ba.className = "pointer-events-none absolute " + (splash ? "inset-y-0 right-0 w-[66%]" : "inset-y-3 right-3 aspect-[132/196]") + (splash || por ? "" : " hidden");
  const fade = "-webkit-mask-image:linear-gradient(90deg,transparent,#000 60%);mask-image:linear-gradient(90deg,transparent,#000 60%);object-position:50% 18%";
  ba.innerHTML = splash ? `<img src="${splash}" alt="" style="${fade}" class="h-full w-full object-cover">`
    : por ? `<img src="${por}" alt="" class="h-full w-full rounded-xl object-cover ring-1 ring-white/15 shadow-lg">` : "";
}
function renderTabs() {
  const tabs = [["focus", "Focus"], ["dash", "Dashboard"], ["habits", "Habits"], ["cards", "Cards"]];
  $("#tabs").innerHTML = tabs.map(([k, l]) => `<button data-tab="${k}" class="relative py-3 text-[15px] font-semibold transition ${S.tab === k ? "text-ink" : "text-dim hover:text-ink"}">${l}
    ${S.tab === k ? `<span class="absolute inset-x-0 -bottom-px h-[3px] rounded-t bg-[var(--accent)]"></span>` : ""}</button>`).join("");
}
function renderView() {
  Object.values(charts).forEach(c => c.destroy()); charts = {};
  const v = $("#view");
  v.innerHTML = `<div class="fade">${S.tab === "focus" ? viewFocus() : S.tab === "dash" ? viewDash() : S.tab === "habits" ? viewHabits() + viewDanger() : viewCards()}</div>`;
  if (S.tab === "dash") for (const f of S.open) openRunBody(f, true);
}

/* ================================================================= dashboard */
function donut(p) {
  const R = 54, C = 2 * Math.PI * R, v = Math.max(0, Math.min(100, p));
  return `<svg width="148" height="148" viewBox="0 0 132 132" class="-rotate-90"><circle cx="66" cy="66" r="${R}" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="11"/>
    <circle cx="66" cy="66" r="${R}" fill="none" stroke="var(--accent)" stroke-width="11" stroke-linecap="round" stroke-dasharray="${(C * v / 100).toFixed(1)} ${C.toFixed(1)}" style="transition:stroke-dasharray .6s ease"/></svg>`;
}
function viewDash() {
  const Sm = D.dash;
  const tiles = Sm.tiles.map(t => `<div title="${esc(t.tip)}" class="relative rounded-xl border accent-line bg-card2 p-4">
      <div class="num text-[34px] leading-none font-bold tracking-tight">${esc(t.value)}</div>
      <div class="mt-2 text-[11px] font-bold tracking-wider text-dim">${esc(t.label)}</div>
      <div class="absolute top-3 right-3 size-8 rounded-lg grid place-items-center font-extrabold text-[#12151b] ${GRADE[t.grade || "N"]}">${t.grade || "–"}</div></div>`).join("");
  const top = `<section class="rounded-2xl border border-line bg-card p-6 mb-5 flex items-center gap-8 flex-wrap">
      <div class="relative size-[148px] shrink-0">${donut(Sm.wr)}<div class="absolute inset-0 grid place-items-center text-center"><div><div class="num text-3xl font-bold leading-none">${num(Sm.wr)}%</div><div class="num text-xs text-dim mt-1.5">${Sm.w}W · ${Sm.l}L</div></div></div></div>
      <div class="grid grid-cols-2 xl:grid-cols-4 gap-3 flex-1 min-w-[320px]">${tiles}</div></section>`;

  const cards = D.table.filter(x => x.delta !== null && x.np >= 3).sort((a, b) => b.np - a.np || b.delta - a.delta).slice(0, 8);
  const crow = cards.map(x => `<div class="grid grid-cols-[minmax(0,1.25fr)_30px_minmax(0,1.1fr)_46px] gap-3 items-center py-2 border-t border-line first:border-0">
      <span class="truncate font-semibold text-sm">${wikiA(x.card, artImg(x.card, 34) + esc(x.card))}</span><span class="num text-right text-xs text-dim">${x.np}</span>
      <div class="relative h-5 rounded-md bg-card2 overflow-hidden"><i class="absolute inset-y-0 left-0 bg-[var(--accent)] opacity-55" style="width:${Math.max(2, x.wr_p)}%"></i><b class="num relative block text-center text-xs leading-5">${num(x.wr_p)}%</b></div>
      <span class="num text-center text-xs font-extrabold rounded-md py-0.5 ${x.delta >= 5 ? "bg-good/15 text-good" : x.delta <= -5 ? "bg-bad/15 text-bad" : "bg-card2 text-dim"}">${sgn(x.delta)}</span></div>`).join("");
  const cardPanel = panel(head("Card performance", "PICKS · WIN % · LIFT") + (crow || `<div class="text-faint text-sm">–</div>`));

  const P = D.pairs;
  const prow = (P && P.single) ? P.missed.slice(0, 5).map(m => `<div class="grid grid-cols-[minmax(0,1fr)_44px_76px] gap-3 items-center py-2 border-t border-line first:border-0 text-sm">
      <span class="truncate font-semibold" title="${esc(m.partner)} + ${esc(m.card)}">${esc(m.partner)} <span class="text-faint">+</span> ${esc(m.card)}</span>
      <span class="num text-right font-bold text-good">${num(m.n ? 100 * m.w / m.n : 0)}%</span><span class="num text-right text-xs font-bold text-warn">Skipped ${m.times}×</span></div>`).join("") : "";
  const pairPanel = panel(head("Top missed synergies", "PAIR WIN % · SKIPPED") + (prow || `<div class="text-faint text-sm">${P && P.single ? "–" : "Pick a character"}</div>`));

  const shown = D.feed.slice(0, S.feedN);
  const RES = {WIN: ["WIN", "text-good", "#4fd18b"], LOSS: ["LOSS", "text-bad", "#ff6b6b"], ABANDONED: ["QUIT", "text-faint", "#7d889b"]};
  const feed = shown.map(r => {
    const [lbl, cls, col] = RES[r.result];
    const cc = themeColor(r.character);
    const open = S.open.has(r.file);
    return `<article class="rounded-xl border border-line bg-card overflow-hidden mb-2.5 transition hover:border-white/15" style="border-left:4px solid ${col}">
      <button data-feed="${esc(r.file)}" class="relative w-full flex flex-wrap items-center gap-x-6 gap-y-2 pl-4 pr-12 py-3.5 text-left">
        <div class="w-[92px] shrink-0"><div class="font-extrabold tracking-wide ${cls}">${lbl}</div><div class="num text-xs text-dim mt-0.5">Floor ${r.final_floor}</div></div>
        <div class="flex items-center gap-2 shrink-0"><span class="rounded-md px-2 py-1 text-xs font-bold" style="background:${hexA(cc, .16)};color:${cc}">${esc(r.character)}</span>
          <span class="rounded-md bg-card2 px-2 py-1 text-xs font-semibold text-dim">A${r.ascension}</span><span class="text-xs text-faint">${esc(r.date)}</span></div>
        <div class="flex-1 min-w-[150px]"><div class="text-[10px] font-semibold tracking-wider text-faint">${r.result === "WIN" ? "RESULT" : "KILLED BY"}</div><div class="font-semibold leading-snug">${r.result === "WIN" ? "Victory" : esc(r.killer || "–")}</div></div>
        <div class="flex gap-1.5 flex-wrap justify-end">${r.badges.map(b => pill(b.k, b.label)).join("")}</div>
        <svg class="absolute right-4 top-1/2 -translate-y-1/2 size-5 text-dim shrink-0 transition-transform ${open ? "rotate-180" : ""}" id="chev-${cssId(r.file)}" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 8l5 5 5-5"/></svg>
      </button>
      <div class="exp ${open ? "open" : ""}" id="exp-${cssId(r.file)}"><div><div id="body-${cssId(r.file)}" class="border-t border-line bg-side/60 p-5"></div></div></div></article>`;
  }).join("");
  const more = D.feed.length > S.feedN ? `<button data-more="1" class="w-full rounded-xl border border-line bg-card hover:bg-card2 py-2.5 text-sm font-semibold transition">Show more</button>` : "";
  const feedPanel = `<div>${head("Match history", D.feed.length + " RUNS")}${feed || `<div class="text-faint text-sm">–</div>`}${more}</div>`;
  return top + `<div class="grid gap-5 lg:grid-cols-[minmax(0,35fr)_minmax(0,65fr)] items-start"><div class="flex flex-col gap-5">${cardPanel}${pairPanel}</div>${feedPanel}</div>`;
}
const cssId = s => String(s).replace(/\W/g, "_");

/* ---- expandable run (autopsy) ---- */
async function toggleRun(file) {
  const exp = $("#exp-" + cssId(file)), chev = $("#chev-" + cssId(file));
  if (!exp) return;
  if (S.open.has(file)) { S.open.delete(file); exp.classList.remove("open"); chev && chev.classList.remove("rotate-180"); return; }
  S.open.add(file); exp.classList.add("open"); chev && chev.classList.add("rotate-180");
  openRunBody(file, false);
}
async function openRunBody(file, silent) {
  const el = $("#body-" + cssId(file));
  if (!el) return;
  if (!silent || !el.dataset.done) {
    el.innerHTML = `<div class="skel h-40"></div>`;
  }
  const r = await api("autopsy", file);
  if (!r || r.error) { el.innerHTML = `<div class="text-bad text-sm">Could not load this run.</div>`; return; }
  el.dataset.done = "1";
  mountAutopsy(el, r, file, false);
}
function mountAutopsy(el, r, file, tpOnly) {
  el.innerHTML = autopsyHtml(r, file, tpOnly);
  drawHp(r, file);
  const tg = el.querySelector("[data-tponly]");
  if (tg) tg.addEventListener("change", e => mountAutopsy(el, r, file, e.target.checked));
}
const ROOM = {monster: "#ff9b9b", elite: "#ffb547", boss: "#ff6b6b", rest_site: "#5fd38d", shop: "#ffd479", event: "#6cb6ff", treasure: "#e0b0ff", ancient: "#b28cff"};
const roomKey = f => ["monster", "elite", "boss", "rest_site", "shop", "treasure"].includes(f.room_type) ? f.room_type : (f.map_type === "ancient" ? "ancient" : "event");
const ROOM_NAME = {monster: "Fight", elite: "Elite", boss: "Boss", rest_site: "Campfire", shop: "Shop", event: "Event", treasure: "Treasure", ancient: "Ancient"};
function autopsyStory(r, file, tpOnly = false) {
  const tps = r.turning.length ? r.turning.map(t => `<div class="rounded-lg border border-line bg-card px-3 py-2 text-sm flex items-center gap-2 flex-wrap"><b class="text-dim">Floor ${t.floor}</b>${t.badges.map(b => pill(b.k, b.label)).join("")}</div>`).join("")
    : `<span class="text-sm text-faint">No standout mistakes</span>`;
  const rows = [];
  let act = null;
  for (const f of r.floors) {
    if (tpOnly && !f.tp.length) continue;
    if (f.act !== act) { act = f.act; rows.push(`<tr><td colspan="6" class="bg-card2/60 px-3 py-1.5 text-xs font-bold tracking-wide text-dim">ACT ${f.act} · ${esc(f.act_name).toUpperCase()}</td></tr>`); }
    const k = roomKey(f), c = ROOM[k];
    const hp = [f.damage ? `<span class="${f.big ? "text-bad font-bold" : "text-warn"}">−${f.damage}</span>` : "", f.healed ? `<span class="text-good">+${f.healed}</span>` : ""].filter(Boolean).join(" ") || `<span class="text-faint">0</span>`;
    const chips = [];
    if (f.card_choices.length && f.map_type !== "shop") {
      const tiles = f.card_choices.map(([n, p]) => {
        const file = ART.get(artKey(n));
        if (!file) return `<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] ${p ? "bg-good/15 text-good font-semibold" : "bg-card2 text-faint line-through"}">${p ? "✔ " : ""}${wikiA(n, esc(n))}</span>`;
        return wikiA(n, `<span class="block w-[80px]"><img src="/art/${encodeURIComponent(file)}" alt="" loading="lazy" class="h-[52px] w-[80px] object-cover rounded-md ${p ? "ring-2 ring-good" : "opacity-40 grayscale"}"><span class="mt-0.5 block text-[11px] leading-tight ${p ? "text-good font-semibold" : "text-faint"}">${p ? "✔ " : ""}${esc(n)}</span></span>`)
          .replace('class="underline', 'class="block no-underline ');
      });
      chips.push(`<div class="flex flex-wrap gap-2 items-start w-full mb-1">${tiles.join("")}${f.card_choices.some(c => c[1]) ? "" : `<span class="self-center text-[11px] font-semibold text-warn">skipped</span>`}</div>`);
    }
    const gained = [...f.cards_other, ...f.bought_cards];
    gained.forEach(n => chips.push(`<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] bg-info/15 text-info">+ ${wikiA(n, artImg(n, 44) + esc(n))}</span>`));
    f.relics.forEach(n => chips.push(`<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] bg-warn/15 text-warn">◆ ${wikiA(n, artImg(n, 44) + esc(n))}</span>`));
    f.potions_picked.forEach(n => chips.push(`<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] bg-info/15 text-info">⚗ ${esc(n)}</span>`));
    f.potions_used.forEach(n => chips.push(`<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] bg-good/15 text-good">used ${esc(n)}</span>`));
    f.potions_discarded.forEach(n => chips.push(`<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] bg-warn/15 text-warn">tossed ${esc(n)}</span>`));
    f.events.forEach(n => chips.push(`<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] bg-card2 text-dim">${esc(n)}</span>`));
    f.rest.forEach(n => chips.push(`<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] ${f.smith_low ? "bg-warn/15 text-warn" : "bg-good/15 text-good"}">${esc(n)}</span>`));
    f.removed.forEach(n => chips.push(`<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[11.5px] bg-good/15 text-good">removed ${esc(n)}</span>`));
    const tp = f.tp.map(b => pill(b.k, b.label)).join(" ");
    rows.push(`<tr class="border-t border-line ${f.tp.length ? "bg-warn/[.05]" : ""}">
      <td class="num px-3 py-2 text-xs text-faint align-top">${f.floor}</td>
      <td class="px-3 py-2 align-top"><div class="flex items-center gap-2"><span title="${ROOM_NAME[k]}" class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold" style="background:${hexA(c, .16)};color:${c}">${ico(k)}${ROOM_NAME[k]}</span><span class="text-sm font-medium ${k === "boss" ? "text-bad" : k === "elite" ? "text-warn" : ""}">${["monster", "elite", "boss", "event", "ancient"].includes(k) ? wikiMulti(f.label) : esc(f.label)}</span></div>${tp ? `<div class="mt-1.5 flex gap-1.5 flex-wrap">${tp}</div>` : ""}</td>
      <td class="num px-3 py-2 text-xs text-right align-top ${f.slow ? "text-bad font-bold" : "text-dim"}">${f.is_combat ? f.turns : "–"}</td>
      <td class="num px-3 py-2 text-sm text-right align-top">${hp}</td>
      <td class="num px-3 py-2 text-xs text-right align-top ${f.hp === 0 ? "text-bad font-bold" : "text-dim"}">${f.hp === null ? "?" : f.hp + "/" + f.max_hp}</td>
      <td class="num px-3 py-2 text-xs text-right align-top ${f.gold >= 200 ? "text-warn font-bold" : "text-dim"}">${f.gold ?? "?"}</td>
      <td class="px-3 py-2 align-top min-w-[280px]"><div class="flex flex-wrap gap-1">${chips.join("")}</div></td></tr>`);
  }
  return `<div class="flex items-center justify-between gap-3 flex-wrap mb-3">
      <div class="flex flex-wrap gap-2 items-center"><span class="text-[11px] font-bold tracking-wider text-faint mr-1">TURNING POINTS</span>${tps}</div>
      <label class="flex items-center gap-2 text-sm text-dim cursor-pointer"><input type="checkbox" data-tponly class="sw" ${tpOnly ? "checked" : ""}>Turning points only</label></div>
    <div class="h-64 rounded-xl border border-line bg-card p-3 mb-4"><canvas id="hp-${cssId(file)}"></canvas></div>
    <div class="overflow-x-auto rounded-xl border border-line bg-card"><table class="w-full text-left"><thead><tr class="text-[10.5px] tracking-wider text-faint uppercase"><th class="px-3 py-2 font-semibold">#</th><th class="px-3 py-2 font-semibold">Room</th><th class="px-3 py-2 font-semibold text-right">Turns</th><th class="px-3 py-2 font-semibold text-right">HP ±</th><th class="px-3 py-2 font-semibold text-right">HP</th><th class="px-3 py-2 font-semibold text-right">Gold</th><th class="px-3 py-2 font-semibold">Cards &amp; items</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
function autopsyHtml(r, file, tpOnly = false) {
  const seg = (k, label, on) => `<button data-seg="${k}" class="px-3 py-1.5 rounded-md text-sm font-semibold text-dim hover:text-ink transition ${on ? "bg-card2" : ""}">${label}</button>`;
  return `<div data-seg-wrap><div class="inline-flex gap-1 rounded-lg border border-line bg-card p-1 mb-4">${seg("story", "Story", true)}${seg("deck", "Deck", false)}</div>
    <div data-pane="story">${autopsyStory(r, file, tpOnly)}</div>
    <div data-pane="deck" class="hidden">${typeof deckHtml === "function" ? deckHtml(r) : ""}</div></div>`;
}
Chart.defaults.color = "#a9b2c1"; Chart.defaults.borderColor = "rgba(255,255,255,.06)"; Chart.defaults.font.family = "Inter, system-ui, sans-serif"; Chart.defaults.font.size = 11.5;
const actLines = {id: "actLines", afterDatasetsDraw(chart, _a, opts) {
  const xs = opts.boundaries || [], {ctx, chartArea: {top, bottom}, scales: {x}} = chart;
  ctx.save(); ctx.strokeStyle = "rgba(255,255,255,.14)"; ctx.setLineDash([3, 4]); ctx.fillStyle = "#7d889b";
  xs.forEach(b => { if (b.index === 0) return; const px = x.getPixelForValue(b.index) - (x.getPixelForValue(1) - x.getPixelForValue(0)) / 2; ctx.beginPath(); ctx.moveTo(px, top); ctx.lineTo(px, bottom); ctx.stroke(); ctx.fillText(b.label, px + 5, top + 11); });
  ctx.restore(); }};
function drawHp(r, file) {
  const cv = document.getElementById("hp-" + cssId(file)); if (!cv) return;
  if (charts[file]) charts[file].destroy();
  const col = themeColor(r.character), keys = r.floors.map(roomKey);
  const marker = k => ({elite: "triangle", boss: "rectRot", rest_site: "circle"})[k];
  const bounds = [];
  r.floors.forEach((f, i) => { if (i === 0 || f.act !== r.floors[i - 1].act) bounds.push({index: i, label: "Act " + f.act}); });
  charts[file] = new Chart(cv, {type: "line",
    data: {labels: r.floors.map(f => f.floor), datasets: [
      {label: "HP", data: r.floors.map(f => f.hp), borderColor: col, backgroundColor: hexA(col, .12), fill: true, tension: .25, borderWidth: 2,
       pointStyle: keys.map(k => marker(k) || "circle"), pointRadius: keys.map(k => marker(k) ? 6 : 0), pointHoverRadius: 7,
       pointBackgroundColor: keys.map(k => ({elite: "#ffb547", boss: "#ff6b6b", rest_site: "#5fd38d"})[k] || col), pointBorderColor: "#1c2029", pointBorderWidth: 1.5, yAxisID: "y"},
      {label: "Max HP", data: r.floors.map(f => f.max_hp), borderColor: "#6b7487", borderDash: [4, 4], borderWidth: 1.5, pointRadius: 0, fill: false, yAxisID: "y"},
      {label: "Gold", data: r.floors.map(f => f.gold), borderColor: "#ffd479", borderWidth: 1.5, pointRadius: 0, tension: .2, yAxisID: "y2"}]},
    options: {maintainAspectRatio: false, responsive: true, interaction: {mode: "index", intersect: false},
      plugins: {legend: {display: true, position: "bottom", labels: {boxWidth: 10, boxHeight: 10, usePointStyle: true}}, actLines: {boundaries: bounds},
        tooltip: {backgroundColor: "#12151b", borderColor: "rgba(255,255,255,.12)", borderWidth: 1, padding: 10, callbacks: {title: it => { const f = r.floors[it[0].dataIndex]; return `Floor ${f.floor} · ${f.label}`; }}}},
      scales: {x: {grid: {display: false}, ticks: {maxTicksLimit: 18}}, y: {beginAtZero: true, grid: {color: "rgba(255,255,255,.05)"}}, y2: {position: "right", beginAtZero: true, grid: {display: false}}}},
    plugins: [actLines]});
}

/* ================================================================= habits */
function viewHabits() {
  const H = D.habits, G = H.gameplan;
  const cells = [0, 1].map(i => {
    const f = G.fixes[i];
    if (!f) return panel(`<div class="text-[11px] font-bold tracking-wider text-faint">PRIORITY ${i + 1}</div><div class="mt-2 text-good font-semibold">${G.n_dec >= 3 ? "Nothing above 25%" : "Not enough runs"}</div>`);
    const l10 = f.last10 || f.last5, ok = l10.filter(Boolean).length;
    return panel(`<div class="flex justify-between text-[11px] font-bold tracking-wider"><span class="text-[var(--accent)]">PRIORITY ${i + 1}</span><span class="${ok >= 7 ? "text-good" : ok >= 4 ? "text-warn" : "text-bad"}">${ok}/${l10.length} RECENT OK</span></div>
      <div class="mt-2 text-xl font-bold">${esc(f.title)}</div>
      <div class="flex gap-1 my-3">${[...l10].reverse().map(v => `<i class="h-5 flex-1 max-w-6 rounded ${v ? "bg-good/80" : "bg-bad"}"></i>`).join("")}</div>
      <div class="text-[15px] text-ink leading-snug">${esc(f.target)}</div>`, "accent-line");
  }).join("");
  let out = `<div class="grid md:grid-cols-2 gap-4 mb-6">${cells}</div>`;
  if (H.n_losses < 2) return out + panel(`<div class="text-dim text-sm">Play a few more runs with this character to rank your habits.</div>`);
  const sev = {high: ["Major leak", "bg-bad text-[#12151b]", "#ff6b6b"], med: ["Leak", "bg-warn text-[#12151b]", "#ffb547"], low: ["Minor", "bg-info text-[#12151b]", "#6cb6ff"]};
  out += `<div class="flex items-center justify-between mb-3"><h3 class="font-bold">Run-killing habits</h3><span class="text-xs text-faint num">Click a habit for all tips · ${H.n_losses} losses · ${H.n_wins} wins</span></div>`;
  out += H.items.map(it => {
    const [lbl, cls, col] = sev[it.sev];
    const bar = (name, v, c, cnt) => `<div class="flex items-center gap-3 text-xs"><span class="w-24 text-dim">${name}</span><div class="flex-1 h-2 rounded-full bg-card2 overflow-hidden"><i class="block h-full rounded-full" style="width:${Math.max(1, v || 0)}%;background:${c}"></i></div><span class="num w-20 text-right font-semibold">${num(v)}% <span class="text-faint font-normal">(${cnt})</span></span></div>`;
    const isOpen = S.expandedHabits.has(it.title), more = it.fix.slice(1);
    return `<article class="hab rounded-xl border border-line bg-card mb-3 overflow-hidden flex ${isOpen ? "open" : ""}"><div class="w-1" style="background:${col}"></div><div class="flex-1 p-5">
      <div data-hab="${esc(it.title)}" class="cursor-pointer">
        <div class="flex items-center gap-3 flex-wrap"><span class="size-7 rounded-md bg-card2 grid place-items-center text-sm font-bold">${it.rank}</span><span class="text-lg font-bold">${esc(it.title)}</span><span class="rounded-full px-2.5 py-0.5 text-[11px] font-extrabold ${cls}">${lbl}</span></div>
        <div class="mt-3 flex items-baseline gap-x-6 gap-y-1 flex-wrap"><span><span class="num text-3xl font-extrabold" style="color:${col}">${num(it.loss_rate)}%</span> <span class="text-sm text-dim">of your losses (${it.loss_hits}/${it.loss_n})</span></span>${it.show_win_bar ? `<span><span class="num text-xl font-bold text-good">${num(it.win_rate)}%</span> <span class="text-sm text-dim">of your wins (${it.win_hits}/${it.win_n})</span></span>` : ""}</div>
        <div class="mt-3 rounded-lg bg-good/10 border border-good/20 px-4 py-3 text-[17px] leading-snug text-ink"><span class="text-good font-bold mr-1">Do this:</span>${esc(it.fix[0] || it.why)}</div>
        <div class="mt-3 flex items-center gap-1.5 text-xs font-bold tracking-wider text-[var(--accent)]"><span class="hcar inline-block transition-transform">▸</span>${more.length ? `${more.length} MORE TIP${more.length > 1 ? "S" : ""}` : "WHY"}${it.examples.length ? ` AND ${it.examples.length} RUN${it.examples.length > 1 ? "S" : ""}` : ""}</div>
      </div>
      <div class="hmore"><div>
        <div class="pt-3 text-[15px] text-dim leading-snug">${esc(it.why)}</div>
        ${more.length ? `<ul class="mt-3 space-y-2">${more.map((t, i) => `<li class="flex gap-3 text-[16px] leading-snug text-ink"><span class="shrink-0 size-6 rounded-full bg-good/15 text-good text-xs font-bold grid place-items-center mt-0.5">${i + 2}</span><span>${esc(t)}</span></li>`).join("")}</ul>` : ""}
        ${it.examples.length ? `<div class="mt-4 flex gap-2 flex-wrap">${it.examples.map(e => `<button data-goto="${esc(e.file)}" class="rounded-full border border-line bg-card2 px-3 py-1 text-xs text-info hover:border-info transition">${esc(e.label)}</button>`).join("")}</div>` : ""}
      </div></div>
    </div></article>`;
  }).join("");
  if (H.fine.length) out += `<div class="mt-5 flex flex-wrap gap-2">${H.fine.map(t => `<span class="rounded-full bg-good/10 text-good text-xs font-medium px-3 py-1">✓ ${esc(t)}</span>`).join("")}</div>`;
  return out;
}

/* ================================================================= cards */
const VERDICT = {TAKE: "bg-good/15 text-good", OK: "bg-card2 text-dim", SKIP: "bg-bad/15 text-bad", LOW: "bg-card2 text-faint"};
function viewCards() {
  const cols = [["card", "Card", "left"], ["offered", "Offered", "right"], ["pick_pct", "Picked", "right"], ["wr_p", "Win % picked", "right"], ["wr_s", "Win % skipped", "right"], ["lift", "Lift", "right"], ["verdict", "Verdict", "right"]];
  const rows = D.table.filter(x => !S.search || x.card.toLowerCase().includes(S.search.toLowerCase()));
  const key = {card: x => x.card.toLowerCase(), offered: x => x.offered, pick_pct: x => x.pick_pct, wr_p: x => x.wr_p ?? -1, wr_s: x => x.wr_s ?? -1, lift: x => x.delta ?? -999, verdict: x => ({TAKE: 0, OK: 1, SKIP: 2, LOW: 3})[x.verdict]}[S.sort.key];
  rows.sort((a, b) => { const A = key(a), B = key(b); return (A < B ? -1 : A > B ? 1 : 0) * (S.sort.desc ? -1 : 1); });
  const body = rows.slice(0, 200).map(x => `<tr class="border-t border-line hover:bg-card2/60 transition"><td class="px-4 py-2.5 font-semibold">${wikiA(x.card, artImg(x.card, 40) + esc(x.card))}</td><td class="num px-4 py-2.5 text-right text-dim">${x.offered}</td>
    <td class="num px-4 py-2.5 text-right text-dim">${num(x.pick_pct)}%</td><td class="num px-4 py-2.5 text-right">${x.wr_p === null ? "–" : num(x.wr_p) + "%"}</td><td class="num px-4 py-2.5 text-right text-dim">${x.wr_s === null ? "–" : num(x.wr_s) + "%"}</td>
    <td class="num px-4 py-2.5 text-right font-bold ${x.delta >= 5 ? "text-good" : x.delta <= -5 ? "text-bad" : "text-dim"}">${x.delta === null ? "–" : sgn(x.delta)}</td><td class="px-4 py-2.5 text-right"><span class="rounded-full px-2.5 py-0.5 text-[10.5px] font-extrabold ${VERDICT[x.verdict]}">${x.verdict}</span></td></tr>`).join("");
  return `<div class="flex items-center justify-between mb-3 gap-3"><h3 class="font-bold">Card impact</h3>
      <input id="cardSearch" value="${esc(S.search)}" placeholder="Search cards" class="w-60 rounded-lg border border-line bg-card px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"></div>
    <div class="rounded-xl border border-line bg-card overflow-hidden"><table class="w-full"><thead><tr class="text-[10.5px] tracking-wider text-faint uppercase">${cols.map(([k, l, al]) => `<th data-sort="${k}" class="px-4 py-3 font-semibold cursor-pointer select-none hover:text-ink text-${al}">${l}${S.sort.key === k ? (S.sort.desc ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/* ================================================================= events */
function toast(msg) {
  const el = document.createElement("div");
  el.className = "fade rounded-xl border accent-line bg-card2 px-4 py-3 text-sm shadow-xl";
  el.innerHTML = msg; $("#toast").appendChild(el);
  setTimeout(() => { el.style.transition = "opacity .4s"; el.style.opacity = 0; setTimeout(() => el.remove(), 400); }, 6000);
}
document.addEventListener("click", e => {
  const t = e.target.closest("[data-char],[data-range],[data-tab],[data-feed],[data-more],[data-sort],[data-goto],[data-hab]");
  if (!t) return;
  if (t.dataset.hab !== undefined) { const k = t.dataset.hab, art = t.closest("article"); if (S.expandedHabits.has(k)) S.expandedHabits.delete(k); else S.expandedHabits.add(k); art && art.classList.toggle("open", S.expandedHabits.has(k)); return; }
  if (t.dataset.char !== undefined) { S.character = t.dataset.char; refresh(); }
  else if (t.dataset.range) { S.range = t.dataset.range; refresh(); }
  else if (t.dataset.tab) { S.tab = t.dataset.tab; renderTabs(); renderView(); }
  else if (t.dataset.feed) toggleRun(t.dataset.feed);
  else if (t.dataset.more) { S.feedN += 12; renderView(); }
  else if (t.dataset.goto) { S.tab = "dash"; S.open.add(t.dataset.goto); const i = D.feed.findIndex(r => r.file === t.dataset.goto); if (i >= S.feedN) S.feedN = i + 1; renderTabs(); renderView(); setTimeout(() => { const el = document.getElementById("exp-" + cssId(t.dataset.goto)); el && el.scrollIntoView({behavior: "smooth", block: "center"}); }, 120); }
  else if (t.dataset.sort) { const k = t.dataset.sort; S.sort = {key: k, desc: S.sort.key === k ? !S.sort.desc : k !== "card"}; renderView(); }
});
const artPrev = $("#artPrev");
let tipFor = null;
let upView = false;
function showTip(el, quiet) {
  const name = el.dataset.tip, k = artKey(name), file = ART.get(k), info = INFO[k];
  const text = info && (info.text || (typeof info === "string" ? info : ""));
  if (!file && !text) return;
  tipFor = el;
  const canUp = !!(info && info.up);
  const up = upView && !!(info && info.cost !== undefined);
  const img = artPrev.querySelector("img");
  if (file) { img.src = "/art/" + encodeURIComponent(file); img.classList.remove("hidden"); } else img.classList.add("hidden");
  img.style.boxShadow = up ? "0 0 0 2px #d9b44a, 0 0 22px rgba(217,180,74,.35)" : "none";
  const T = $("#apT"); T.textContent = name + (up ? "+" : ""); T.style.color = up ? "#e8c766" : "";
  const shown = (up && canUp ? info.up : text) || "";
  if (up && canUp) {
    const a = text.split(" "), b = shown.split(" ");
    $("#apD").innerHTML = a.length === b.length ? b.map((w, i) => w !== a[i] ? `<b style="color:#6ee7a0">${esc(w)}</b>` : esc(w)).join(" ")
      : `<span style="color:#6ee7a0">${esc(shown)}</span>`;
  } else $("#apD").textContent = shown;
  const bits = [];
  if (info && info.type) bits.push(esc(info.type));
  if (info && info.rarity && info.rarity !== "None") bits.push(esc(info.rarity));
  if (info && info.cost !== undefined) {
    const c = v => v < 0 ? "X" : v, base = c(info.cost);
    bits.push(up && info.up_cost !== undefined ? `<span style="color:#6ee7a0">${c(info.up_cost)} Energy</span> <span class="text-faint">(was ${base})</span>` : `${base} Energy`);
  }
  $("#apM").innerHTML = bits.join(" · ");
  $("#apH").innerHTML = (info && info.cost !== undefined ? `Hold <kbd class="px-1 rounded bg-card2 border border-line">Shift</kbd> to see the upgraded version` +
    (up && !canUp && info.up_cost === undefined ? `<div class="mt-1">This card gets no change from upgrading beyond what the wiki lists.</div>` : "") : "") +
    `<div class="mt-1">Click the name to open the wiki page</div>`;
  artPrev.classList.remove("hidden", "pop"); if (!quiet) { void artPrev.offsetWidth; artPrev.classList.add("pop"); }
}
function setUp(v) { if (upView === v) return; upView = v; if (tipFor && !artPrev.classList.contains("hidden")) showTip(tipFor, true); }
document.addEventListener("keydown", e => { if (e.key === "Shift") setUp(true); });
document.addEventListener("keyup", e => { if (e.key === "Shift") setUp(false); });
window.addEventListener("blur", () => setUp(false));
document.addEventListener("mouseover", e => { const t = e.target.closest && e.target.closest("[data-tip]"); if (t && t !== tipFor) showTip(t); });
document.addEventListener("mouseout", e => { const t = e.target.closest && e.target.closest("[data-tip]"); if (t && !t.contains(e.relatedTarget)) { tipFor = null; artPrev.classList.add("hidden"); } });
document.addEventListener("mousemove", e => { if (artPrev.classList.contains("hidden")) return; const w = artPrev.offsetWidth, h = artPrev.offsetHeight; let x = e.clientX + 20, y = e.clientY + 16; if (x + w > innerWidth - 8) x = e.clientX - w - 20; if (y + h > innerHeight - 8) y = innerHeight - h - 8; artPrev.style.left = x + "px"; artPrev.style.top = Math.max(8, y) + "px"; });
document.addEventListener("input", e => { if (e.target.id === "cardSearch") { S.search = e.target.value; const p = e.target.selectionStart; renderView(); const n = $("#cardSearch"); n.focus(); n.setSelectionRange(p, p); } });
$("#asc").addEventListener("change", e => { S.asc = e.target.value; refresh(); });
$("#optQuits").addEventListener("change", e => { S.quits = e.target.checked; refresh(); });
$("#optCoop").addEventListener("change", e => { S.coop = e.target.checked; refresh(); });
$("#optAuto").addEventListener("change", e => { S.auto = e.target.checked; });
$("#reloadBtn").addEventListener("click", async () => { await api("reload"); refresh(); });
$("#folderBtn").addEventListener("click", () => { $("#mPath").value = (D && D.status.history_dir) || ""; $("#mErr").textContent = ""; $("#modal").classList.remove("hidden"); $("#mPath").focus(); });
$("#mCancel").addEventListener("click", () => $("#modal").classList.add("hidden"));
$("#mSave").addEventListener("click", async () => {
  const res = await api("set_folder", $("#mPath").value);
  if (!res.ok) { $("#mErr").textContent = res.error; return; }
  $("#modal").classList.add("hidden"); refresh();
});
$("#mPath").addEventListener("keydown", e => { if (e.key === "Enter") $("#mSave").click(); if (e.key === "Escape") $("#mCancel").click(); });

async function pollLoop() {
  try {
    if (S.auto) {
      const p = await api("poll");
      if (p && p.changed) {
        await refresh();
        const n = p.new_run;
        if (n) toast(`<b class="${n.win ? "text-good" : "text-bad"}">${n.win ? "WIN" : n.result === "LOSS" ? "LOSS" : "QUIT"}</b> · ${esc(n.character)} · Floor ${n.final_floor}${n.killer ? " · " + esc(n.killer) : ""}`);
      }
    }
  } catch (e) { /* server restarting - try again */ }
  setTimeout(pollLoop, 3000);
}
(async function start() {
  if (!window.Chart) $("#cdnwarn").classList.remove("hidden");
  $("#view").innerHTML = `<div class="grid gap-4"><div class="skel h-44"></div><div class="grid grid-cols-3 gap-4"><div class="skel h-72"></div><div class="skel h-72 col-span-2"></div></div></div>`;
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get("char")) S.character = h.get("char");
  if (h.get("tab")) S.tab = h.get("tab");
  if (h.get("open")) { S.open.add(h.get("open")); S.feedN = 60; }
  await loadArt();
  INIT = await api("init");
  await refresh();
  setTimeout(pollLoop, 3000);
})();
