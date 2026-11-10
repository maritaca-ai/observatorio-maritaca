"use strict";

// Equal weight per primary evaluation row. No averaging of modes or missing results.
function calculateAverages(tasks, variants, rows) {
  const eligible = tasks.filter((t) => t.primary_metric !== false);
  const indexed = new Map(rows.map((r) => [r.id, r]));
  const valid = (r) => r && ["final", "reported"].includes(r.status) && Number.isFinite(r.score) && !r.averages_exclusion;
  const groups = ["native_br", "translated_pt", "international", "total"];
  return variants.map((variant) => {
    const cells = Object.fromEntries(groups.map((group) => {
      const population = eligible.filter((t) => group === "total" || t.origin === group);
      const entries = population.flatMap((t) => {
        const record = indexed.get(`${variant.id}:${t.id}`);
        if (!valid(record)) return [];
        return [{ task: t, record, score: t.direction === "lower" ? 100 - record.score : record.score }];
      });
      return [group, { entries, n: entries.length, expected: population.length,
        value: entries.length ? entries.reduce((sum, r) => sum + r.score, 0) / entries.length : null }];
    }));
    return { variant, cells };
  });
}
const averagesState = { cells: new Map() };
const completeAverage = c => c.expected > 0 && c.n === c.expected;
// Rank every visible numeric average. Modes remain separate rows, never pooled.
function rankAverages(results) {
  const scored = r => Number.isFinite(r.cells.total.value);
  const sorted = [...results].sort((a, b) => {
    if (scored(a) !== scored(b)) return scored(a) ? -1 : 1;
    if (scored(a) && a.cells.total.value !== b.cells.total.value)
      return b.cells.total.value - a.cells.total.value;
    return a.variant.model.name.localeCompare(b.variant.model.name, "pt-BR")
      || a.variant.id.localeCompare(b.variant.id);
  });
  let rank = null;
  return sorted.map((r, i) => {
    if (!scored(r)) return { ...r, rank: null };
    if (!i || r.cells.total.value !== sorted[i - 1].cells.total.value) rank = i + 1;
    return { ...r, rank };
  });
}
function averageRankLabel(variant, rank) {
  return `<span class="average-rank">${rank === null ? "—" : `${rank}º`}</span>`;
}
function renderAverageTable(tasks, variants, rows) {
  const columns = [["native_br", "Nativo BR"], ["translated_pt", "Traduzido PT"], ["international", "Não nativo"], ["total", "Total"]];
  const results = rankAverages(calculateAverages(tasks, variants, rows));
  averagesState.cells.clear();
  return `<section class="average-section" id="category-averages"><div class="average-head"><div><h2>Médias e ranking</h2><p>${state.category === "all" ? "Todas as categorias" : esc(D.categories[state.category])}</p></div></div><div class="table-frame"><div class="table-scroll"><table class="average-table"><thead><tr><th>Modelo / modo</th>${columns.map(([group, label]) => `<th${group === "total" ? ' aria-sort="descending"' : ""}>Avg · ${label}${group === "total" ? " ↓" : ""}</th>`).join("")}</tr></thead><tbody>${results.map(({ variant, cells, rank }) => `<tr><th>${averageRankLabel(variant, rank)}${icon(variant.model)}<span>${modelWeightsLink(variant.model, variant.mode)}<small>${esc(i18n.t(variant.model.size_label))} · ${modeName(variant.mode)}</small></span></th>${columns.map(([group]) => {
    const cell = cells[group], id = `${variant.id}:${group}`;
    averagesState.cells.set(id, { ...cell, model: variant.model, mode: variant.mode, group });
    return `<td><button data-average-detail="${esc(id)}" aria-label="${esc(variant.model.name)}, ${modeName(variant.mode)}, média ${group}: ${number(cell.value)}"><strong>${number(cell.value)}</strong><small>${cell.n} de ${cell.expected} testes${cell.n && !completeAverage(cell) ? " · Parcial" : ""}</small></button></td>`;
  }).join("")}</tr>`).join("")}</tbody></table></div></div></section>`;
}
function showAverageDetail(id) {
  const c = averagesState.cells.get(id);
  if (!c) return;
  $("#detail-content").innerHTML = `<div class="eyebrow">Média do recorte · ${modeName(c.mode)}</div><h2 id="detail-title">${esc(c.model.name)}</h2><div class="detail-score">${number(c.value)}<small>${c.n} de ${c.expected} avaliações${c.n && !completeAverage(c) ? " · Média parcial" : ""}</small></div><p>Média aritmética simples, com peso igual por avaliação primária. Cada modo é calculado separadamente. Casos com estouro de contexto confirmado valem zero; avaliações sem execução ou com julgamentos pendentes continuam sem nota. Resultados do Lumen sem nenhum controle benigno concluído ficam fora da média e aparecem como “Sem capacidade demonstrada”.</p><table class="metric-breakdown"><thead><tr><th>Avaliação</th><th>Métrica de origem</th><th>Valor na média</th></tr></thead><tbody>${c.entries.map(({ task, record, score }) => `<tr><td><button class="text-button" data-result="${esc(record.id)}">${esc(task.name)}</button><small>${esc(i18n.t(task.origin_label))}${record.status === "reported" ? " · tabela fornecida" : ""}</small></td><td>${number(record.score_normalization?.native_score ?? record.score)}${record.score_normalization ? "<small>Taxa de dano observada (%)</small>" : ""}</td><td>${record.score_normalization ? safetyFormula(record) : number(score)}</td></tr>`).join("")}</tbody></table>${c.n ? `<p>Soma ${number(c.entries.reduce((s, r) => s + r.score, 0), 4)} ÷ ${c.n} = ${number(c.value, 4)}.</p>` : '<p>Não há resultados elegíveis neste conjunto.</p>'}<details><summary>Origem dos benchmarks e casos mistos</summary>${Object.entries(D.origins.notes).map(([id, text]) => `<p><strong>${esc(benchmarks.get(id)?.name || id)}:</strong> ${esc(text)}</p>`).join("")}<p>${Object.entries(D.origins.sources).map(([name, url]) => `<a href="${safeLink(url)}" target="_blank" rel="noopener noreferrer">${esc(name)} ↗</a>`).join(" · ")}</p></details>`;
  $("#detail-dialog").showModal();
}
if (typeof document !== "undefined") document.addEventListener("click", (event) => {
  const t = event.target.closest("[data-average-detail],[data-average-open]");
  if (!t || !D) return;
  if (t.dataset.averageDetail) showAverageDetail(t.dataset.averageDetail);
  if (t.hasAttribute("data-average-open")) {
    navigate("panorama", { mode: experience.mode, category: experience.category });
    $("#category-averages").scrollIntoView();
  }
});
