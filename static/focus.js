/* Focus screen (big reminders for the second monitor) and the danger list (used at the bottom of Habits). */
function dangerKind(k) {
  return ({boss: ["Boss", "bg-bad text-[#12151b]"], elite: ["Elite", "bg-warn text-[#12151b]"]})[k] || ["Fight", "bg-card2 text-dim"];
}
function dangerRow(d, big) {
  const [kl, kc] = dangerKind(d.kind);
  const col = d.deaths ? "#ff6b6b" : d.pct >= 40 ? "#ffb547" : "#6cb6ff";
  const plan = d.kind === "boss" ? "Plan your HP and potions for this boss before the act ends."
    : d.kind === "elite" ? "Optional fight: only take it when you are healthy."
    : "Costs a lot of HP: block earlier and use potions here.";
  const pic = d.kind === "boss" ? bossArt(d.name) : "";
  return `<div class="relative overflow-hidden rounded-xl border border-line bg-card p-4">
    ${pic ? `<div class="pointer-events-none absolute inset-0" style="background:radial-gradient(circle at 92% 40%,rgba(255,107,107,.26),transparent 55%)"></div><div class="pointer-events-none absolute right-3 top-3">${halo(pic, 58, 44, "#ff6b6b")}</div>` : ""}
    <div class="relative flex items-center gap-2 flex-wrap ${pic ? "pr-14" : ""}"><span class="${big ? "text-lg" : "text-base"} font-bold">${wikiMulti(d.name.replace(/\s*\((elite|weak|BOSS)\)\s*$/i, ""))}</span><span class="rounded-full px-2.5 py-0.5 text-[10.5px] font-extrabold ${kc}">${kl}</span></div>
    <div class="relative mt-2 flex items-baseline gap-x-5 gap-y-1 flex-wrap ${pic ? "pr-14" : ""}">
      <span><span class="num ${big ? "text-3xl" : "text-2xl"} font-extrabold" style="color:${col}">${d.deaths}×</span> <span class="text-sm text-dim">killed you in ${d.n} meeting${d.n > 1 ? "s" : ""}</span></span>
      <span><span class="num text-xl font-bold text-ink">${d.avg_dmg}</span> <span class="text-sm text-dim">HP lost on average (${d.pct}% of max)</span></span></div>
    <div class="mt-2 h-2 rounded-full bg-card2 overflow-hidden"><i class="block h-full rounded-full" style="width:${Math.min(100, Math.max(2, d.pct))}%;background:${col}"></i></div>
    <div class="relative mt-2 text-sm text-dim">${plan} <span class="text-faint">Worst fight: −${d.worst} HP.</span></div></div>`;
}
function viewDanger() {
  const L = (D && D.danger) || [];
  if (!L.length) return "";
  return `<div class="mt-8 mb-3 flex items-center justify-between"><h3 class="font-bold">Danger list</h3><span class="text-xs text-faint">Fights that cost you the most, and the ones that ended runs</span></div>
    <div class="grid gap-3 lg:grid-cols-2">${L.map(d => dangerRow(d, false)).join("")}</div>`;
}
/* small round-corner icons for the reminder cards (same drawings as the match-history badges) */
function fixIcon(title, px) {
  const t = String(title || "");
  const k = /gold|shop|buy/i.test(t) ? "gold" : /hp|health|fight|low|heal/i.test(t) ? "bleed" : /potion|drink/i.test(t) ? "potion" : /pair|synerg|card|skip/i.test(t) ? "pair" : "";
  return k ? BADGE[k].svg.replace('width="15" height="15"', `width="${px}" height="${px}"`) : `<span style="color:var(--accent)">${ico("event", px)}</span>`;
}
/* hover card for one run in a reminder's history bar */
function runTip(x, k, ok) {
  const f = foeInfo(x), when = k === 0 ? "LAST RUN" : k + " RUNS AGO";
  const ring = f && ART.size ? foeRing(f, 40, 30) : "";
  const line = x.win ? `<span class="text-good">Won the run</span>` : f ? `killed by <b class="text-ink">${esc(f.name)}</b>` : "run ended";
  const why = x.why && x.why !== "Won the run" ? `<div class="mt-2 text-xs leading-snug text-dim">${esc(x.why)}</div>` : "";
  return `<div class="runtip pointer-events-none absolute bottom-6 right-[-6px] z-30 w-[280px] rounded-xl border border-white/10 bg-[#262c3a] p-3 text-left shadow-2xl">
    <div class="flex justify-between text-[11px] font-extrabold tracking-wider"><span class="${ok ? "text-good" : "text-bad"}">${ok ? "KEPT" : "BROKEN"}</span><span class="text-faint">${when} · ${esc(x.date)}</span></div>
    <div class="mt-2 flex items-center gap-3">${ring}<div class="text-[13px] leading-snug"><div><b class="text-ink">${esc(x.character)}</b> <span class="text-dim">· floor ${x.final_floor}</span></div><div class="text-dim">${line}</div></div></div>${why}</div>`;
}
function reminderCard(p, i) {
  const n = p.l10.length, ok = p.l10.filter(Boolean).length, last = n ? p.l10[0] : null;
  const col = !n ? "#8a93a6" : last ? "#3fbf7f" : "#ff6b6b";
  let streak = 0; while (streak < n && p.l10[streak] === p.l10[0]) streak++;
  const runs = p.runs && p.runs.length === n ? p.runs : [];
  const segs = [...p.l10].map((v, k) => ({v, k})).reverse().map(({v, k}) =>
    `<span class="runseg relative block flex-1 py-2.5 -my-2.5"><i class="block h-2 rounded" style="background:${v ? "#3fbf7f" : "#ff6b6b"}"></i>${runs[k] ? runTip(runs[k], k, v) : ""}</span>`).join("");
  const w = runs[0] && runs[0].why ? runs[0].why : "";
  const ev = w ? `<div class="mt-2 border-t border-line pt-2 text-[12.5px] text-dim">Last run: ${esc(w.charAt(0).toLowerCase() + w.slice(1))}</div>` : "";
  const right = n ? `<div class="w-[240px] shrink-0">
      <div class="text-right text-[11px] font-extrabold tracking-wider" style="color:${col}">${last ? "KEPT LAST RUN" : "BROKEN LAST RUN"}</div>
      <div class="mt-0.5 text-right text-[17px] font-extrabold">${last ? "Kept" : "Broken"} ${streak} in a row</div>
      <div class="mt-1.5 flex gap-[3px]">${segs}</div>
      <div class="mt-1.5 flex items-baseline justify-between"><span class="text-xs text-faint">${ok} of last ${n} kept</span><b class="num text-sm" style="color:${col}">${Math.round(100 * ok / n)}%</b></div></div>` : "";
  return `<section class="flex items-center gap-4 rounded-2xl border border-line bg-card p-5 mb-2.5" style="border-left:4px solid ${col};background-image:linear-gradient(90deg,${hexA(col, .10)},transparent 60%)">
    ${haloIcon(fixIcon(p.title, 28), 56, col)}
    <div class="min-w-0 flex-1"><div class="text-[10px] font-bold tracking-wider text-dim">REMINDER ${i + 1}</div>
      <div class="mt-0.5 text-[21px] font-extrabold leading-tight">${esc(p.title)}</div>
      <div class="mt-1 text-sm leading-snug text-ink/90">${esc(p.text)}</div>${ev}</div>${right}</section>`;
}
function lastRunRow(r) {
  const RES = {WIN: ["WIN", "text-good", "#4fd18b"], LOSS: ["LOSS", "text-bad", "#ff6b6b"], ABANDONED: ["QUIT", "text-faint", "#7d889b"]};
  const [lbl, cls, col] = RES[r.result] || RES.LOSS;
  const cc = themeColor(r.character), cArt = charArt(r.character, "icon");
  const fade = `linear-gradient(90deg,${hexA(col, r.result === "ABANDONED" ? .08 : .20)},${hexA(col, r.result === "ABANDONED" ? .03 : .07)} 35%,transparent 80%)`;
  return `<section class="mb-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-card px-4 py-2.5" style="border-left:4px solid ${col};background-image:${fade}">
    ${cArt ? halo(cArt, 64, 48, cc) : ""}
    <div><div class="text-[10px] font-bold tracking-wider text-faint">LAST RUN</div><div class="text-[17px] font-extrabold ${cls}">${lbl} <span class="text-[13px] font-semibold text-dim">· Floor ${r.final_floor} · ${esc(r.character)} · ${esc(r.date)}</span></div></div>
    <div class="flex min-w-0 flex-1 flex-wrap justify-end gap-1.5">${(r.badges || []).map(badgePill).join("")}</div>
    ${foeBlock(r)}
    <button data-goto="${esc(r.file)}" class="rounded-lg border border-line bg-card2 px-3.5 py-2 text-sm font-semibold transition hover:border-[var(--accent)]">Open run story</button></section>`;
}
function viewFocus() {
  const H = D.habits, G = H.gameplan || {fixes: []};
  const picks = [];
  (G.fixes || []).slice(0, 3).forEach(f => { const l = f.last10 || f.last5 || []; picks.push({title: f.title, text: f.target, l10: l, runs: f.last10 ? f.last10_runs : f.last_runs}); });
  (H.items || []).forEach(it => { if (picks.length < 3 && !picks.some(p => p.title === it.title) && it.fix && it.fix[0]) picks.push({title: it.title, text: it.fix[0], l10: [], runs: []}); });
  const cards = picks.length ? picks.map(reminderCard).join("") : panel(`<div class="text-dim">Play a few more runs and your top reminders will show up here.</div>`);
  const last = (D.feed || [])[0];
  const dg = ((D.danger || []).slice(0, 3));
  const dangerBox = dg.length ? `<div class="mt-6 mb-3 text-[12px] font-bold tracking-wider text-faint">WATCH OUT FOR</div><div class="grid gap-3 lg:grid-cols-3">${dg.map(d => dangerRow(d, false)).join("")}</div>` : "";
  return `${last ? lastRunRow(last) : ""}${cards}${dangerBox}`;
}
