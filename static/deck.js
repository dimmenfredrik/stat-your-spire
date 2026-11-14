/* Deck view: final deck of a finished run as card pictures, grouped by type, with an energy curve.
   Uses INFO (type/cost/rarity from the game files) and the shared helpers from app.js. */
const DECK_TYPES = ["Attack", "Skill", "Power", "Other"];
function deckEntries(r) {
  const m = new Map();
  (r.deck || []).forEach(c => {
    const k = c.n + "|" + c.u, e = m.get(k) || {n: c.n, u: c.u, count: 0};
    e.count++; m.set(k, e);
  });
  return [...m.values()].map(e => {
    const info = INFO[artKey(e.n)] || {};
    const type = DECK_TYPES.includes(info.type) ? info.type : "Other";
    const cost = info.cost === undefined ? null : (e.u && info.up_cost !== undefined ? info.up_cost : info.cost);
    return {...e, type, cost, rarity: info.rarity};
  });
}
function deckHtml(r) {
  const E = deckEntries(r), total = (r.deck || []).length;
  if (!total) return `<div class="text-sm text-faint">No deck information in this run file.</div>`;
  const hasMeta = E.some(e => e.cost !== null);
  if (!hasMeta) {   // no card library available (browser version, or pictures not built yet): simple list
    const up = E.reduce((a, e) => a + (e.u ? e.count : 0), 0);
    const items = [...E].sort((a, b) => a.n.localeCompare(b.n)).map(e => `<span class="inline-flex items-center rounded-lg border border-line bg-card2 px-2.5 py-1 text-[13px] ${e.u ? "text-[#e8c766]" : "text-ink"}">${wikiA(e.n, esc(e.n) + (e.u ? "+" : ""))}${e.count > 1 ? `<span class="ml-1.5 text-faint">×${e.count}</span>` : ""}</span>`).join("");
    return `<div class="mb-4 grid grid-cols-2 gap-2 max-w-xs">${[[total, "cards"], [up, "upgraded"]].map(([v, l]) => `<div class="rounded-lg bg-card2 px-3 py-2"><div class="num text-xl font-bold">${v}</div><div class="text-[11px] text-faint">${l}</div></div>`).join("")}</div>
      <div class="flex flex-wrap gap-2">${items}</div>
      <div class="mt-4 text-xs text-faint">Pictures, card type and cost are only in the downloadable version (they are built from your own game files).</div>
      ${(r.relics_final || []).length ? `<div class="mt-5 mb-2 text-[11px] font-bold tracking-wider text-faint">RELICS · ${r.relics_final.length}</div><div class="flex flex-wrap gap-2">${r.relics_final.map(n => `<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[12px] bg-warn/15 text-warn">◆ ${wikiA(n, esc(n))}</span>`).join("")}</div>` : ""}`;
  }
  const n = f => E.filter(f).reduce((a, e) => a + e.count, 0);
  const by = t => n(e => e.type === t);
  const upgraded = n(e => e.u > 0), basics = n(e => e.rarity === "Basic");
  const buckets = [["0", e => e.cost === 0], ["1", e => e.cost === 1], ["2", e => e.cost === 2], ["3+", e => e.cost >= 3], ["X", e => e.cost !== null && e.cost < 0]];
  const counts = buckets.map(([l, f]) => [l, n(f)]), maxc = Math.max(1, ...counts.map(c => c[1]));
  const priced = E.filter(e => e.cost !== null && e.cost >= 0), avg = priced.length ? priced.reduce((a, e) => a + e.cost * e.count, 0) / priced.reduce((a, e) => a + e.count, 0) : null;
  const stat = (v, l, c = "") => `<div class="rounded-lg bg-card2 px-3 py-2"><div class="num text-xl font-bold ${c}">${v}</div><div class="text-[11px] text-faint">${l}</div></div>`;
  const facts = [];
  if (hasMeta) {
    if (!by("Power")) facts.push(["warn", "No Power cards in the deck"]);
    if (basics >= 6) facts.push(["warn", `${basics} starter cards (Strike/Defend) still in the deck`]);
    const heavy = n(e => e.cost >= 2);
    if (heavy >= 8) facts.push(["warn", `${heavy} cards cost 2 or more`]);
    if (upgraded === 0) facts.push(["warn", "No upgraded cards"]);
    if (!facts.length) facts.push(["good", "Nothing stands out in the deck shape"]);
  }
  const tile = e => {
    const k = artKey(e.n), file = ART.get(k);
    const img = file ? `<img src="/art/${encodeURIComponent(file)}" alt="" loading="lazy" class="w-full h-28 object-cover rounded-lg ${e.u ? "ring-2 ring-[#d9b44a]" : ""}">`
      : `<div class="w-full h-28 rounded-lg bg-card2 grid place-items-center text-xs text-faint px-2 text-center">${esc(e.n)}</div>`;
    const cost = e.cost === null ? "" : `<span class="absolute top-1 left-1 size-6 rounded-full bg-[#12151b]/90 border border-line grid place-items-center text-xs font-bold ${e.u && e.cost !== (INFO[k] || {}).cost ? "text-good" : "text-ink"}">${e.cost < 0 ? "X" : e.cost}</span>`;
    const cnt = e.count > 1 ? `<span class="absolute top-1 right-1 rounded-full bg-[#12151b]/90 border border-line px-1.5 text-xs font-bold text-ink">×${e.count}</span>` : "";
    return wikiA(e.n + (e.u ? "" : ""), `<span class="relative block">${img}${cost}${cnt}</span><span class="mt-1 block text-[12.5px] font-semibold leading-tight ${e.u ? "text-[#e8c766]" : "text-ink"}">${esc(e.n)}${e.u ? "+" : ""}</span>`)
      .replace('class="underline', 'class="block no-underline ');
  };
  const groups = DECK_TYPES.map(t => {
    const items = E.filter(e => e.type === t).sort((a, b) => (a.cost ?? 9) - (b.cost ?? 9) || a.n.localeCompare(b.n));
    if (!items.length) return "";
    return `<div class="mb-5"><div class="mb-2 text-[11px] font-bold tracking-wider text-faint">${t.toUpperCase()} · ${items.reduce((a, e) => a + e.count, 0)}</div>
      <div class="grid gap-3" style="grid-template-columns:repeat(auto-fill,minmax(116px,1fr))">${items.map(tile).join("")}</div></div>`;
  }).join("");
  const curve = hasMeta ? `<div class="rounded-xl border border-line bg-card p-4"><div class="mb-2 text-[11px] font-bold tracking-wider text-faint">ENERGY CURVE</div>
      <div class="flex items-end gap-3 h-24">${counts.map(([l, c]) => `<div class="flex-1 flex flex-col items-center justify-end h-full"><span class="num text-xs text-dim">${c}</span><div class="w-full rounded-t bg-[var(--accent)]/70" style="height:${Math.round(c / maxc * 70)}%;min-height:${c ? 3 : 0}px"></div><span class="mt-1 text-xs text-faint">${l}</span></div>`).join("")}</div></div>` : "";
  return `<div class="grid gap-4 md:grid-cols-[1fr_1fr] mb-5">
      <div class="grid grid-cols-3 gap-2 content-start">${stat(total, "cards")}${stat(by("Attack"), "attacks")}${stat(by("Skill"), "skills")}${stat(by("Power"), "powers", hasMeta && !by("Power") ? "text-warn" : "")}${stat(upgraded, "upgraded")}${stat(avg === null ? "–" : avg.toFixed(1), "average cost")}</div>
      ${curve}</div>
    ${facts.length ? `<div class="mb-5 flex flex-wrap gap-2">${facts.map(([k, t]) => `<span class="rounded-full px-3 py-1 text-xs font-medium ${k === "good" ? "bg-good/10 text-good" : "bg-warn/15 text-warn"}">${esc(t)}</span>`).join("")}</div>` : ""}
    ${hasMeta ? "" : `<div class="mb-4 text-xs text-faint">Card pictures, type and cost are only in the downloadable version (they are built from your own game files).</div>`}
    ${groups}
    ${(r.relics_final || []).length ? `<div class="mt-2"><div class="mb-2 text-[11px] font-bold tracking-wider text-faint">RELICS · ${r.relics_final.length}</div><div class="flex flex-wrap gap-2">${r.relics_final.map(n => `<span class="inline-flex items-center rounded px-1.5 py-0.5 text-[12px] bg-warn/15 text-warn">◆ ${wikiA(n, artImg(n, 34) + esc(n))}</span>`).join("")}</div></div>` : ""}`;
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-seg]");
  if (!b) return;
  const wrap = b.closest("[data-seg-wrap]");
  wrap.querySelectorAll("[data-seg]").forEach(x => x.classList.toggle("bg-card2", x === b));
  wrap.querySelectorAll("[data-pane]").forEach(p => p.classList.toggle("hidden", p.dataset.pane !== b.dataset.seg));
});
