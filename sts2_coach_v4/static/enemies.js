/* Enemies tab: every boss/elite/fight that costs you HP or ends runs, and the problem that usually shows up.
   Data: D.enemies (made in Python from HP lost, HP going in, fight length and unused potions). */
const EN_COL = {boss: "#ff6b6b", elite: "#ffb547", monster: "#8aa0d6"};
const EN_LVL = {bad: "bg-bad/15 text-[#ff8a93]", warn: "bg-warn/15 text-[#ffcf7a]"};
function enemyCard(e) {
  const col = e.good ? "#4ade80" : EN_COL[e.kind] || EN_COL.monster;
  const nm = e.name.replace(/\s*\((elite|weak|boss)\)\s*$/i, "");
  const url = enemyPic(e.foe, nm, e.kind);
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


/* Before you start: one character's briefing, built only from your finished runs (D.prerun). */
function prepPick(p, overall) {
  const good = p.wr >= overall;
  const col = good ? "text-good" : "text-warn", bar = good ? "bg-good" : "bg-warn";
  const li = l => l.map(s => `<li>${esc(s)}</li>`).join("");
  return `<div tabindex="0" class="prow relative mt-2 grid cursor-default grid-cols-[34px_minmax(0,1.3fr)_minmax(0,2fr)_90px] items-center gap-3 rounded-xl border border-line bg-card2 p-3 outline-none transition hover:border-white/25 focus:border-white/25">
    <div class="grid size-[34px] place-items-center">${artImg(p.name, 34) || `<span class="grid size-[30px] place-items-center rounded-full bg-white/[.07] text-[13px] font-bold text-dim">${esc(p.name.charAt(0))}</span>`}</div>
    <div class="min-w-0"><div class="truncate text-[14px] font-semibold">${esc(p.name)}</div><div class="text-[11.5px] text-faint">Taken ${p.n} of the ${p.offered} times it was offered</div></div>
    <div class="h-1.5 overflow-hidden rounded bg-white/10"><i class="block h-full ${bar}" style="width:${Math.max(2, p.wr).toFixed(0)}%"></i></div>
    <div class="text-right"><div class="num font-bold ${col}">${num(p.wr)}% won</div><div class="text-[11px] text-faint">${p.n} run${p.n === 1 ? "" : "s"}${p.small ? ` <span class="ml-1 rounded bg-warn/15 px-1 text-[10px] font-semibold text-warn">few</span>` : ""}</div></div>
    <div class="ptip pointer-events-none absolute inset-x-3 top-full z-20 mt-1.5 grid-cols-2 gap-4 rounded-xl border border-white/20 bg-[#232938] p-4 shadow-xl">
      <div><div class="mb-1.5 text-[10.5px] font-extrabold tracking-[.14em] text-bad">WHAT GOES WRONG</div><ul class="list-disc space-y-1 pl-4 text-[12.5px] leading-snug text-ink/90">${li(p.bad)}</ul></div>
      <div><div class="mb-1.5 text-[10.5px] font-extrabold tracking-[.14em] text-good">WHAT YOU DO WELL</div><ul class="list-disc space-y-1 pl-4 text-[12.5px] leading-snug text-ink/90">${li(p.good)}</ul></div>
      <div class="col-span-2 border-t border-white/10 pt-2 text-[11px] text-faint">Based on ${p.n} finished run${p.n === 1 ? "" : "s"} with this pick${p.small ? ". That is a small sample, so read it as a hint." : "."}</div>
    </div></div>`;
}
function prepFight(e) {
  const nm = e.name.replace(/\s*\((elite|weak|boss)\)\s*$/i, "");
  const url = enemyPic(e.foe, nm, e.kind);
  const col = EN_COL[e.kind] || EN_COL.monster;
  const tag = e.kind === "boss" ? "BOSS" : e.kind === "elite" ? "ELITE" : "FIGHT";
  const head = e.deaths ? `It ended ${e.deaths} of your runs.` : "It has not killed you yet.";
  const dmg = `You lose ${e.avg_dmg} HP on average (${e.pct}% of your max).`;
  const probs = e.problems.filter(p => p.k !== "dmg").map(p => esc(p.detail)).join(" ");
  const tryIt = (e.tries && e.tries[0]) ? `<div class="mt-1.5 text-[12px] text-dim"><b class="text-ink/90">Try:</b> ${esc(e.tries[0])}</div>` : "";
  return `<div class="flex gap-3.5 rounded-xl border border-line bg-card2 p-3.5">
    <div class="grid size-[56px] shrink-0 place-items-center overflow-hidden rounded-lg bg-white/[.04]">${url ? `<img src="${url}" alt="" class="max-h-full max-w-full object-contain">` : `<span class="text-faint">?</span>`}</div>
    <div class="min-w-0 flex-1"><div class="flex flex-wrap items-center gap-2"><span class="text-[15px] font-bold">${esc(nm)}</span><span class="rounded-full px-2 py-0.5 text-[10px] font-extrabold tracking-wider" style="background:${hexA(col, .18)};color:${col}">${tag}</span><span class="text-[11.5px] text-faint">met ${e.n}×</span></div>
      <div class="mt-1 text-[13px] text-ink/90">${head} ${dmg} ${probs}</div>${tryIt}</div></div>`;
}
function viewPrep() {
  const P = D && D.prerun;
  if (!P) return `<div class="mb-1 text-xl font-extrabold">Before you start</div><div class="rounded-2xl border border-line bg-card p-6 text-sm text-dim">Pick a character in the sidebar and you will see which opening choices, fights and habits to think about before you start a run with it.</div>`;
  S.prepAct = S.prepAct || 1;
  const total = P.picks.reduce((s, p) => s + p.n, 0), wonAll = P.picks.reduce((s, p) => s + p.wins, 0);
  const overall = total ? wonAll / total * 100 : 0;
  const shown = P.picks.filter(p => p.n >= 2), list = shown.length ? shown : P.picks, hid = P.picks.length - list.length;
  const picks = P.picks.length ? list.map(p => prepPick(p, overall)).join("") + (hid ? `<div class="mt-2 text-[12px] text-faint">${hid} more pick${hid === 1 ? "" : "s"} taken only once ${hid === 1 ? "is" : "are"} hidden until you have tried ${hid === 1 ? "it" : "them"} again.</div>` : "") : `<div class="mt-2 rounded-xl border border-line bg-card2 p-4 text-sm text-dim">No finished runs with a recorded opening pick yet.</div>`;
  const acts = [1, 2, 3].map(a => `<button data-prepact="${a}" class="rounded-lg px-3.5 py-1.5 text-[13px] font-semibold ${S.prepAct === a ? "bg-white/10 text-ink" : "text-dim hover:text-ink"}">Act ${a}</button>`).join("");
  const fl = P.fights[S.prepAct] || [];
  const fights = fl.length ? `<div class="grid gap-3 lg:grid-cols-2">${fl.map(prepFight).join("")}</div>` : `<div class="rounded-xl border border-line bg-card2 p-4 text-sm text-dim">Nothing in Act ${S.prepAct} has cost you much yet.</div>`;
  const items = ((D.habits && D.habits.items) || []).slice(0, 3);
  const habits = items.length ? items.map(it => `<div class="mt-2 rounded-xl border border-line bg-card2 p-3.5"><div class="text-[14px] font-semibold">${esc(it.title)}</div><div class="mt-1 text-[12.5px] text-dim">${esc(it.nums)}</div>${it.fix && it.fix[0] ? `<div class="mt-1.5 text-[12.5px] text-ink/90"><b>Try:</b> ${esc(it.fix[0])}</div>` : ""}</div>`).join("") : `<div class="mt-2 rounded-xl border border-line bg-card2 p-4 text-sm text-dim">No clear habits yet. Play a few more runs.</div>`;
  const wins = P.wins.length ? `<div class="mt-2 grid grid-cols-3 gap-3">${P.wins.map(w => `<div class="rounded-xl border border-line bg-card2 p-3.5"><div class="num text-2xl font-bold">${esc(w.value)}</div><div class="mt-1 text-[11.5px] text-dim">${esc(w.label)}</div></div>`).join("")}</div>` : `<div class="mt-2 rounded-xl border border-line bg-card2 p-4 text-sm text-dim">Needs at least 3 wins with this character.</div>`;
  const H = (t, s) => `<div class="mb-1 mt-7 text-[12px] font-bold tracking-wider text-faint">${t}</div><div class="text-[12.5px] text-faint">${s}</div>`;
  return `<div class="mb-1 text-xl font-extrabold">${esc(S.character)}: before you start</div>
    <div class="text-sm text-faint">Built from your finished runs with this character. It does not follow the game live.</div>
    ${H("OPENING PICKS", "How each first choice went for you. Hover a pick to see what goes wrong and what you do well with it.")}${picks}
    <div class="mb-1 mt-7 flex flex-wrap items-center gap-3"><span class="text-[12px] font-bold tracking-wider text-faint">FIGHTS TO WATCH</span><span class="flex gap-1">${acts}</span></div>${fights}
    ${H("HABITS TO KEEP AN EYE ON", "The habits that cost this character the most runs.")}${habits}
    ${H("WHAT YOUR WINS LOOK LIKE", "Use these as targets.")}${wins}`;
}
