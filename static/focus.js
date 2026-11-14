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
function viewFocus() {
  const H = D.habits, G = H.gameplan || {fixes: []};
  const picks = [];
  (G.fixes || []).slice(0, 3).forEach(f => picks.push({title: f.title, text: f.target, l10: f.last10 || f.last5 || []}));
  (H.items || []).forEach(it => { if (picks.length < 3 && !picks.some(p => p.title === it.title) && it.fix && it.fix[0]) picks.push({title: it.title, text: it.fix[0], l10: []}); });
  const cards = picks.length ? picks.map((p, i) => {
    const ok = p.l10.filter(Boolean).length, last = p.l10.length ? p.l10[0] : null;
    return `<section class="rounded-2xl border border-line bg-card p-6 accent-line">
      <div class="flex items-center justify-between text-[12px] font-bold tracking-wider"><span class="text-[var(--accent)]">REMINDER ${i + 1}</span>
        ${p.l10.length ? `<span class="${last ? "text-good" : "text-bad"}">${last ? "KEPT LAST RUN" : "BROKEN LAST RUN"}</span>` : ""}</div>
      <div class="mt-3 text-3xl font-extrabold leading-tight">${esc(p.title)}</div>
      <div class="mt-3 text-xl leading-snug text-ink">${esc(p.text)}</div>
      ${p.l10.length ? `<div class="mt-4 flex items-center gap-3"><div class="flex gap-1">${[...p.l10].reverse().map(v => `<i class="h-5 w-6 rounded ${v ? "bg-good/80" : "bg-bad"}"></i>`).join("")}</div><span class="text-sm text-dim">${ok} of ${p.l10.length} recent runs OK</span></div>` : ""}
    </section>`;
  }).join("") : panel(`<div class="text-dim">Play a few more runs and your top reminders will show up here.</div>`);
  const last = (D.feed || [])[0];
  const lastBox = last ? `<section class="rounded-2xl border border-line bg-card p-5 mt-4 flex items-center justify-between gap-4 flex-wrap">
      <div><div class="text-[12px] font-bold tracking-wider text-faint">LAST RUN</div>
      <div class="mt-1 text-xl font-bold"><span class="${last.win ? "text-good" : "text-bad"}">${last.win ? "WIN" : "LOSS"}</span> <span class="text-dim font-semibold">· floor ${last.final_floor} · ${esc(last.date)}${last.killer ? " · killed by " + esc(last.killer) : ""}</span></div></div>
      <button data-goto="${esc(last.file)}" class="rounded-lg border border-line bg-card2 px-4 py-2 text-sm font-semibold hover:border-[var(--accent)] transition">Open run story</button></section>` : "";
  const dg = ((D.danger || []).slice(0, 3));
  const dangerBox = dg.length ? `<div class="mt-6 mb-3 text-[12px] font-bold tracking-wider text-faint">WATCH OUT FOR</div><div class="grid gap-3 lg:grid-cols-3">${dg.map(d => dangerRow(d, false)).join("")}</div>` : "";
  return `<div class="grid gap-4 xl:grid-cols-1">${cards}</div>${lastBox}${dangerBox}`;
}
