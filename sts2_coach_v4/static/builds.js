/* Best builds tab: pick a character, then see what wins and what keeps losing for them.
   Everything is read from the final deck + relics of your finished runs (D.builds, made in Python). */
const BB_ICON = {
  cards: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="6" width="12" height="15" rx="2"/><path d="M8 3h10a2 2 0 0 1 2 2v13"/></svg>`,
  relic: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/></svg>`,
  skull: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a7 7 0 0 0-4 12.7V19h8v-3.7A7 7 0 0 0 12 3z"/><path d="M9.5 11h.01M14.5 11h.01"/></svg>`,
  up: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 16l6-6 4 4 6-7"/><path d="M15 7h5v5"/></svg>`,
  down: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8l6 6 4-4 6 7"/><path d="M15 17h5v-5"/></svg>`,
};
const BB_MIN_RUNS = 5, BB_MIN_CARD = 4;   // same limits as in Python
const BB_GOOD = "#4ade80", BB_BAD = "#ff6b77", BB_WARN = "#ffb547";

/* recent form of a build: your last 10 runs of this character that used it, compared with its all-time win rate */
function bbTrend(rec, allWr) {
  if (!rec || rec.n < 3) return `<span class="text-faint">Recent form: not enough recent runs yet</span>`;
  const p = Math.round(100 * rec.wins / rec.n), d = p - allWr;
  const [arrow, col, word] = d > 0 ? ["▲", BB_GOOD, "better than usual"] : d < 0 ? ["▼", BB_BAD, "worse than usual"] : ["►", "#8b93a3", "same as usual"];
  return `<span style="color:${col}" class="font-bold">${arrow}</span> <span class="text-dim">Last 10 runs: <b class="text-ink">${rec.wins} of ${rec.n}</b> won · ${word}</span>`;
}
/* round win-rate meter */
const bbRing = (p, c) => `<span class="relative grid shrink-0 place-items-center rounded-full" style="width:76px;height:76px;background:conic-gradient(${c} ${Math.max(2, p)}%,#2a303c 0)"><span class="absolute rounded-full bg-[#1b1f28]" style="inset:7px"></span><b class="num relative text-[19px]" style="color:${c}">${p}%</b></span>`;
const bbPill = (icon, text, c) => `<span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold" style="background:${hexA(c, .18)};color:${c}">${icon}${esc(text)}</span>`;

/* one card picture: hover shows the card and its upgraded version side by side */
function bbCardTile(c, good, note) {
  const k = artKey(c.n), file = ART.get(k), col = good ? BB_GOOD : BB_BAD;
  const img = file
    ? `<img src="/art/${encodeURIComponent(file)}" alt="" loading="lazy" class="h-[84px] w-[84px] rounded-lg object-cover" style="border:1px solid rgba(255,255,255,.12)">`
    : `<span class="grid h-[84px] w-[84px] place-items-center rounded-lg bg-card2 px-1 text-center text-[11px] text-faint" style="border:1px solid rgba(255,255,255,.12)">${esc(c.n)}</span>`;
  const badge = c.lift === undefined ? "" : `<span class="num absolute -bottom-2 left-1/2 -translate-x-1/2 rounded-full px-2 py-0.5 text-[11px] font-extrabold" style="background:#12151b;border:1px solid ${hexA(col, .6)};color:${col}">${c.lift > 0 ? "+" : ""}${c.lift}</span>`;
  return `<div class="bbtile w-[88px] cursor-pointer text-center" data-bb="card" data-n="${esc(c.n)}" data-lift="${c.lift ?? ""}" data-runs="${c.runs ?? ""}" data-wins="${c.wins ?? ""}" data-wr="${c.wr ?? ""}" data-note="${esc(note || "")}">
    <div class="relative mx-auto w-[84px]">${img}${badge}</div>
    <div class="mt-3.5 text-[11.5px] font-semibold leading-tight text-ink">${esc(c.n)}</div></div>`;
}
function bbRelicTile(x) {
  const k = artKey(x.n), file = ART.get(k);
  const img = file ? `<img src="/art/${encodeURIComponent(file)}" alt="" class="h-[52px] w-[52px] object-contain">` : `<span class="text-lg text-warn">◆</span>`;
  return `<div class="bbtile w-[88px] text-center" data-bb="relic" data-n="${esc(x.n)}" data-runs="${x.runs}" data-wins="${x.wins}" data-wr="${x.wr}">
    <div class="relative mx-auto grid h-[64px] w-[64px] place-items-center rounded-full" style="background:${hexA("#ffb547", .12)};box-shadow:0 0 0 2px ${hexA("#ffb547", .55)}">${img}
      <span class="num absolute -bottom-2 left-1/2 -translate-x-1/2 rounded-full px-2 py-0.5 text-[11px] font-extrabold" style="background:#12151b;border:1px solid ${hexA(BB_GOOD, .6)};color:${BB_GOOD}">${x.wr}%</span></div>
    <div class="mt-3.5 text-[11.5px] font-semibold leading-tight text-ink">${esc(x.n)}</div></div>`;
}
function bbCard(col, ring, ringCol, title, sub, pill, body, why, trend) {
  return `<div class="mb-3 rounded-2xl border border-line p-4" style="border-left:4px solid ${col};background:linear-gradient(90deg,${hexA(col, .13)},#1c2029 65%)">
    <div class="flex items-center gap-4">${ring}<div class="min-w-0"><div class="text-[17px] font-extrabold leading-tight">${title}</div><div class="mt-0.5 text-xs text-faint">${sub}</div>${pill ? `<div class="mt-2">${pill}</div>` : ""}</div></div>
    ${body ? `<div class="mt-4 flex flex-wrap gap-3">${body}</div>` : ""}
    ${why ? `<div class="mt-3 rounded-lg bg-white/[.04] px-3 py-2 text-[12.5px] text-dim">${why}</div>` : ""}
    ${trend ? `<div class="mt-2 text-[12.5px]">${trend}</div>` : ""}</div>`;
}
const bbStat = (icon, v, l, c) => `<div class="flex flex-1 items-center gap-2.5 rounded-xl bg-white/[.04] px-3 py-2.5"><span class="grid size-9 shrink-0 place-items-center rounded-full" style="background:${hexA(c, .2)};color:${c}">${icon}</span><div class="min-w-0"><div class="num truncate text-[17px] font-bold leading-tight">${esc(v)}</div><div class="text-[11px] text-faint">${l}</div></div></div>`;

function bbPicker(B) {
  const tiles = B.map(b => {
    const c = b.color || "#8aa0d6", u = charArt(b.character, "icon"), off = !b.enough;
    return `<button ${off ? "disabled" : `data-bbchar="${esc(b.character)}"`} class="rounded-2xl p-5 text-center transition ${off ? "opacity-40 cursor-not-allowed" : "hover:-translate-y-0.5 hover:brightness-110"}" style="border:2px solid ${hexA(c, off ? .4 : .85)};background:linear-gradient(180deg,${hexA(c, .42)},${hexA(c, .13)} 75%,#1c2029);box-shadow:0 8px 24px ${hexA(c, .16)}">
      <div class="mx-auto mb-3 grid h-[96px] place-items-center">${u ? `<img src="${u}" alt="" style="height:92px;width:92px;filter:drop-shadow(0 6px 10px rgba(0,0,0,.55))" class="object-contain">` : ""}</div>
      <div class="text-lg font-extrabold" style="color:${c}">${esc(b.character)}</div><div class="text-xs text-dim">${b.runs} runs · ${b.wins} wins</div>
      <div class="mt-3 text-xs text-dim"><b class="num text-[17px]" style="color:${c}">${b.wr}%</b> win rate${off ? ` · needs ${BB_MIN_RUNS}+ runs` : ""}</div></button>`;
  }).join("");
  return `<div class="mb-1 text-xl font-extrabold">Your best builds</div><div class="mb-4 text-sm text-faint">Pick a character to see what wins and what loses for them.</div>
    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">${tiles}</div>`;
}

function bbWins(b) {
  const out = [];
  if (b.lean && b.lean.runs >= BB_MIN_CARD && b.lean.wr > b.wr) {
    const p = b.lean.wr;
    out.push(bbCard("#3fbf7f", bbRing(p, BB_GOOD), BB_GOOD, "Small, focused deck", `${b.lean.runs} runs · ${b.lean.wins} win${b.lean.wins === 1 ? "" : "s"}`,
      bbPill(BB_ICON.cards, `${b.lean_max} cards or fewer`, BB_GOOD), "",
      b.avg_win && b.avg_loss && b.avg_win < b.avg_loss ? `Your winning decks average <b class="text-ink">${b.avg_win}</b> cards, your losing decks <b class="text-ink">${b.avg_loss}</b>.` : "Lean decks win more often than your average run.", bbTrend(b.lean_recent, b.lean.wr)));
  }
  if (b.good_cards.length) {
    const g = b.good_core;
    out.push(bbCard("#3fbf7f", bbRing(g.wr, BB_GOOD), BB_GOOD, "Cards that win for you",
      `${g.runs} runs held ${g.k === 2 ? "2 or more of these" : "one of these"} · ${g.wins} win${g.wins === 1 ? "" : "s"}`, "",
      b.good_cards.map(c => bbCardTile(c, true)).join(""),
      `The number under each card is how much your win rate changes when it is in your final deck. <span class="text-faint">Hover a card to see it upgraded, click it to open it in the Cards tab.</span>`, bbTrend(b.good_recent, g.wr)));
  }
  if (b.pairs && b.pairs.length) {
    const rows = b.pairs.map(p => `<div class="w-full rounded-xl bg-white/[.04] p-3"><div class="flex flex-wrap items-center gap-2">${bbCardTile({n: p.a}, true, `Pair with ${p.b}: in ${p.n} runs, ${p.w} won (${p.wr}%), +${p.lift} vs runs without the pair`)}<span class="text-2xl font-extrabold text-faint">+</span>${bbCardTile({n: p.b}, true, `Pair with ${p.a}: in ${p.n} runs, ${p.w} won (${p.wr}%), +${p.lift} vs runs without the pair`)}
      <div class="ml-3 min-w-0 flex-1"><div class="num text-2xl font-extrabold" style="color:${BB_GOOD}">${p.wr}%</div><div class="text-xs text-faint">${p.w} wins in ${p.n} runs · <b style="color:${BB_GOOD}">+${p.lift}</b> vs without</div><div class="mt-1.5 text-[12px]">${bbTrend(p.recent, p.wr)}</div></div></div></div>`).join("");
    out.push(bbCard("#3fbf7f", haloIcon(BB_ICON.cards.replace(/16/g, "30"), 76, BB_GOOD), "", "Pairs that win together", `Two cards you took together in runs that won more often`, "", rows,
      `Taking one of these when you already have the other is worth it. <span class="text-faint">Click a card to open it in the Cards tab.</span>`));
  }
  if (b.relics.length) {
    out.push(bbCard("#3fbf7f", haloIcon(BB_ICON.relic.replace(/16/g, "30"), 76, "#ffb547"), "", "Relics that win for you", `Win rate in runs that had the relic`, "",
      b.relics.map(bbRelicTile).join(""), ""));
  }
  if (!out.length) out.push(`<div class="rounded-2xl border border-line bg-card p-5 text-sm text-dim">Not enough wins for ${esc(b.character)} yet to see a pattern (a card or relic needs ${BB_MIN_CARD}+ runs).</div>`);
  return out.join("");
}
function bbLoses(b) {
  const out = [];
  if (b.bloat && b.bloat.runs >= BB_MIN_CARD && b.bloat.wr < b.wr) {
    out.push(bbCard("#ef4d5a", bbRing(b.bloat.wr, BB_BAD), BB_BAD, "Bloated decks", `${b.bloat.runs} runs · ${b.bloat.wins} win${b.bloat.wins === 1 ? "" : "s"}`,
      bbPill(BB_ICON.cards, `${b.bloat_min}+ cards`, BB_BAD), "",
      (b.avg_win && b.avg_loss && b.avg_win < b.avg_loss ? `Your wins average ${b.avg_win} cards, your losses ${b.avg_loss}. ` : "") + "Skip more rewards, or remove cards at shops.", bbTrend(b.bloat_recent, b.bloat.wr)));
  }
  if (b.bad_cards.length) {
    const g = b.bad_core;
    out.push(bbCard("#ef4d5a", bbRing(g.wr, BB_BAD), BB_BAD, "Cards that keep losing",
      `${g.runs} runs held ${g.k === 2 ? "2 or more of these" : "one of these"} · ${g.wins} win${g.wins === 1 ? "" : "s"}`, "",
      b.bad_cards.map(c => bbCardTile(c, false)).join(""),
      `Runs with these cards in the final deck win less often than runs without them. <span class="text-faint">Hover to see it upgraded, click to open it in the Cards tab.</span>`, bbTrend(b.bad_recent, g.wr)));
  }
  if (b.killer) {
    const k = b.killer, u = enemyUrl(k.foe), share = Math.round(100 * k.n / k.of);
    const kc = ({boss: "#ff6b6b", elite: "#ffb547"})[k.kind] || "#8b93a3";
    out.push(bbCard(BB_WARN, u ? halo(u, 76, 58, kc, true) : haloIcon(BB_ICON.skull.replace(/16/g, "30"), 76, kc), "", `Most deaths: ${esc(k.name.replace(/\s*\((elite|weak|boss)\)\s*$/i, ""))}`, `${k.n} of ${k.of} losses (${share}%)`, "", "",
      `Open the Habits tab for the full list of what ends your runs.`));
  }
  if (!out.length) out.push(`<div class="rounded-2xl border border-line bg-card p-5 text-sm text-dim">No clear losing pattern for ${esc(b.character)} yet.</div>`);
  return out.join("");
}

function bbHeadTrend(b) {
  const l = b.last10; if (!l || l.n < 5 || l.before_n < 5) return "";
  const a = Math.round(100 * l.wins / l.n), z = Math.round(100 * l.before_wins / l.before_n), d = a - z;
  const [arrow, col] = d > 0 ? ["▲", BB_GOOD] : d < 0 ? ["▼", BB_BAD] : ["►", "#8b93a3"];
  return `<div class="mt-0.5 text-xs text-dim"><span style="color:${col}" class="font-bold">${arrow}</span> Last ${l.n} runs: <b class="text-ink">${a}%</b> wins, before that ${z}%</div>`;
}
function viewBuilds() {
  const B = (D && D.builds) || [];
  if (!B.length) return `<div class="rounded-2xl border border-line bg-card p-6 text-sm text-dim">No finished runs yet.</div>`;
  if (S.character === ALL) return bbPicker(B);
  const b = B.find(x => x.character === S.character);
  if (!b) return bbPicker(B);
  const c = b.color || "#8aa0d6", u = charArt(b.character, "icon");
  const stats = [bbStat(BB_ICON.cards, b.avg_win ?? "–", "cards in your wins", BB_GOOD), bbStat(BB_ICON.skull, b.avg_loss ?? "–", "cards in your losses", BB_BAD),
    bbStat(BB_ICON.relic, b.best_relic ? b.best_relic.n : "–", b.best_relic ? `best relic · ${b.best_relic.wins} win${b.best_relic.wins === 1 ? "" : "s"}` : "no relic stands out", "#fde047")].join("");
  return `<button data-bbchar="" class="mb-3 text-sm text-dim hover:text-ink">← All characters</button>
    <div class="mb-5 flex flex-wrap items-center gap-4">${u ? halo(u, 84, 62, c) : ""}<div><div class="text-xl font-extrabold">${esc(b.character)} builds</div><div class="text-sm text-faint">${b.runs} runs · ${b.wins} wins · ${b.wr}% win rate</div>${bbHeadTrend(b)}</div>
      <div class="ml-auto flex w-full max-w-[640px] gap-3">${stats}</div></div>
    <div class="grid gap-5 lg:grid-cols-2">
      <div><div class="mb-2 flex items-center gap-2 text-[11px] font-extrabold tracking-[.14em]" style="color:${BB_GOOD}">${BB_ICON.up}WHAT WINS FOR YOU</div>${bbWins(b)}</div>
      <div><div class="mb-2 flex items-center gap-2 text-[11px] font-extrabold tracking-[.14em]" style="color:${BB_BAD}">${BB_ICON.down}WHAT KEEPS LOSING</div>${bbLoses(b)}</div></div>`;
}

/* hover: card + upgraded card side by side */
function bbPanel(name, up) {
  const k = artKey(name), file = ART.get(k), info = INFO[k] || {};
  const text = info.text || (typeof info === "string" ? info : "");
  const canUp = !!(info.up || info.up_cost !== undefined && info.up_cost !== info.cost);
  const shown = (up && info.up) || text;
  let body = esc(shown);
  if (up && info.up && text) {
    const a = text.split(" "), b = shown.split(" ");
    body = a.length === b.length ? b.map((w, i) => w !== a[i] ? `<b style="color:#6ee7a0">${esc(w)}</b>` : esc(w)).join(" ") : `<span style="color:#6ee7a0">${esc(shown)}</span>`;
  }
  const cost = info.cost === undefined ? "" : (c => c < 0 ? "X" : c)(up && info.up_cost !== undefined ? info.up_cost : info.cost);
  const costChanged = up && info.up_cost !== undefined && info.up_cost !== info.cost;
  const meta = [info.type, info.rarity && info.rarity !== "None" ? info.rarity : ""].filter(Boolean).map(esc).join(" · ");
  return `<div class="w-[230px]"><div class="mb-1.5 text-[10.5px] font-extrabold tracking-[.14em] ${up ? "" : "text-faint"}" style="${up ? "color:#e8c766" : ""}">${up ? "UPGRADED" : "NORMAL"}</div>
    ${file ? `<img src="/art/${encodeURIComponent(file)}" alt="" class="mb-2 max-h-[210px] w-full rounded-lg object-contain" style="${up ? "box-shadow:0 0 0 2px #d9b44a,0 0 22px rgba(217,180,74,.35)" : ""}">` : ""}
    <div class="text-[15px] font-bold" style="${up ? "color:#e8c766" : ""}">${esc(name)}${up ? "+" : ""}</div>
    <div class="text-xs text-dim">${meta}${cost !== "" ? ` · <span ${costChanged ? 'style="color:#6ee7a0"' : ""}>${cost} Energy</span>${costChanged ? ` <span class="text-faint">(was ${info.cost < 0 ? "X" : info.cost})</span>` : ""}` : ""}</div>
    ${body ? `<div class="mt-1 text-[13.5px] leading-snug text-ink">${body}</div>` : ""}
    ${up && !canUp ? `<div class="mt-1 text-xs text-faint">Upgrade changes are not listed for this card.</div>` : ""}</div>`;
}
let bbEl = null;
function bbShow(t) {
  if (!bbEl) { bbEl = document.createElement("div"); bbEl.className = "fixed z-[70] hidden pointer-events-none rounded-xl border border-line bg-card p-3 shadow-2xl"; document.body.appendChild(bbEl); }
  const n = t.dataset.n, isCard = t.dataset.bb === "card", lift = +t.dataset.lift;
  const stat = t.dataset.note
    ? `<div class="mt-3 border-t border-line pt-2 text-xs text-dim">${esc(t.dataset.note)}</div>`
    : isCard
    ? `<div class="mt-3 border-t border-line pt-2 text-xs text-dim">In ${t.dataset.runs} runs · ${t.dataset.wins} won (${t.dataset.wr}%) · <b style="color:${lift >= 0 ? BB_GOOD : BB_BAD}">${lift > 0 ? "+" : ""}${lift}</b> vs runs without it<div class="mt-1 text-faint">Counts runs where the card ended in your final deck (the Cards tab compares picking vs skipping). Click to open it there.</div></div>`
    : `<div class="mt-3 border-t border-line pt-2 text-xs text-dim">In ${t.dataset.runs} runs · ${t.dataset.wins} won (${t.dataset.wr}%)</div>`;
  bbEl.innerHTML = `<div class="flex gap-4">${bbPanel(n, false)}${isCard ? bbPanel(n, true) : ""}</div>${stat}`;
  bbEl.classList.remove("hidden");
}
function bbMove(e) {
  if (!bbEl || bbEl.classList.contains("hidden")) return;
  const w = bbEl.offsetWidth, h = bbEl.offsetHeight; let x = e.clientX + 20, y = e.clientY + 16;
  if (x + w > innerWidth - 8) x = e.clientX - w - 20; if (x < 8) x = 8;
  if (y + h > innerHeight - 8) y = innerHeight - h - 8;
  bbEl.style.left = x + "px"; bbEl.style.top = Math.max(8, y) + "px";
}
document.addEventListener("mouseover", e => { const t = e.target.closest && e.target.closest("[data-bb]"); if (t) { bbShow(t); bbMove(e); } });
document.addEventListener("mouseout", e => { const t = e.target.closest && e.target.closest("[data-bb]"); if (t && !t.contains(e.relatedTarget) && bbEl) bbEl.classList.add("hidden"); });
document.addEventListener("mousemove", bbMove);
document.addEventListener("click", e => {
  const c = e.target.closest('[data-bb="card"]');
  if (c) { S.search = c.dataset.n; S.tab = "cards"; if (bbEl) bbEl.classList.add("hidden"); renderTabs(); renderView(); window.scrollTo(0, 0); return; }
  const t = e.target.closest("[data-bbchar]");
  if (!t) return;
  S.character = t.dataset.bbchar || ALL; refresh();
});
