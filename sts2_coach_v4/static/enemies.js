/* Enemies tab: every boss/elite/fight that costs you HP or ends runs, and the problem that usually shows up.
   Data: D.enemies (made in Python from HP lost, HP going in, fight length and unused potions). */
const EN_COL = {boss: "#ff6b6b", elite: "#ffb547", monster: "#8aa0d6"};
const EN_LVL = {bad: "bg-bad/15 text-[#ff8a93]", warn: "bg-warn/15 text-[#ffcf7a]"};
function enemyCard(e) {
  const col = e.good ? "#4ade80" : EN_COL[e.kind] || EN_COL.monster;
  const nm = e.name.replace(/\s*\((elite|weak|boss)\)\s*$/i, "");
  const url = enemyUrl(e.foe) || (e.kind === "boss" ? bossArt(nm) : "");
  const ring = url ? halo(url, 78, 58, col, true) : haloIcon(BB_ICON.skull.replace(/16/g, "30"), 78, col);
  const tag = e.good ? ["GOING WELL", "#4ade80"] : e.kind === "boss" ? ["BOSS", EN_COL.boss] : e.kind === "elite" ? ["ELITE", EN_COL.elite] : ["FIGHT", "#8aa0d6"];
  const chips = e.problems.map(p => `<span class="inline-flex rounded-full px-2.5 py-1 text-xs font-bold ${p.k === "dmg" || p.k === "potions" ? EN_LVL.bad : EN_LVL.warn}">${esc(p.label)}</span>`).join("");
  const text = e.problems.map(p => esc(p.detail)).join(" ");
  const box = e.good
    ? `<div class="mt-3.5 rounded-xl bg-white/[.04] p-3"><div class="mb-1.5 text-[10.5px] font-extrabold tracking-[.14em] text-good">GOING WELL</div><div class="text-[13px] text-ink/90">You got through it ${e.survived} of ${e.n} times and lose only ${e.avg_dmg} HP on average.</div></div>`
    : e.problems.length
      ? `<div class="mt-3.5 rounded-xl bg-white/[.04] p-3"><div class="mb-1.5 text-[10.5px] font-extrabold tracking-[.14em] text-[#ffcf7a]">USUALLY THE PROBLEM</div><div class="mb-1.5 flex flex-wrap gap-1.5">${chips}</div><div class="text-[13px] text-ink/90">${text}</div>${e.tries.length ? `<div class="mt-1.5 text-[13px] text-good">Try: ${esc(e.tries[0])}</div>` : ""}</div>`
      : `<div class="mt-3.5 rounded-xl bg-white/[.04] p-3 text-[13px] text-dim">No single problem stands out yet. It costs you ${e.avg_dmg} HP on average (${e.pct}% of your max).</div>`;
  return `<div class="rounded-2xl border p-4" style="border-color:${hexA(col, .4)};background:linear-gradient(135deg,${hexA(col, .16)},#1c2029 60%)">
    <div class="flex items-center gap-3.5">${ring}<div class="min-w-0 flex-1"><div class="flex flex-wrap items-center gap-2"><span class="text-lg font-extrabold">${esc(nm)}</span><span class="rounded-full px-2.5 py-0.5 text-[10.5px] font-extrabold text-[#12151b]" style="background:${tag[1]}">${tag[0]}</span></div>
      <div class="mt-1 flex flex-wrap gap-x-5 text-[12.5px] text-dim"><span><b class="num text-xl" style="color:${e.deaths ? "#ff6b77" : "#4ade80"}">${e.deaths}×</b> killed you</span><span><b class="num text-xl text-ink">${e.n}</b> meetings</span><span><b class="num text-xl text-ink">${e.avg_dmg}</b> HP lost on average</span></div></div></div>
    ${box}
    <div class="mt-3 flex items-center gap-2 text-[11.5px] text-faint"><span>HP lost</span><div class="h-[7px] flex-1 overflow-hidden rounded bg-card2"><i class="block h-full rounded" style="width:${Math.min(100, Math.max(2, e.pct))}%;background:${col}"></i></div><span class="num">${e.pct}% of max</span></div></div>`;
}
function viewEnemies() {
  const L = (D && D.enemies) || [];
  if (!L.length) return `<div class="rounded-2xl border border-line bg-card p-6 text-sm text-dim">Play a few more runs and the enemies that cost you the most will show up here.</div>`;
  return `<div class="mb-1 text-xl font-extrabold">Enemies</div><div class="mb-4 text-sm text-faint">Every fight that cost you HP or ended a run, and the problem that usually shows up against it.</div>
    <div class="grid gap-4 lg:grid-cols-2">${L.map(enemyCard).join("")}</div>
    <div class="mt-5 text-xs text-faint">The run files record HP lost, HP going in, fight length and unused potions. They do not record block or damage per turn, so "too little block" shows up as "took too much damage".</div>`;
}
