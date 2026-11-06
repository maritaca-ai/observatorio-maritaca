"use strict";

const sizeBands = [
  { max: 2, label: "Até 2B", color: "#28765f" },
  { max: 5, label: "2–5B", color: "#5266ad" },
  { max: 10, label: "5–10B", color: "#945918" },
  { max: Infinity, label: "Acima de 10B", color: "#88527f" },
];
const plotNames = { candidate: "S5-nano", "qwen35-4b": "Qwen", "gemma4-e4b": "Gemma",
  "nemotron35-bolt-e4b": "Nemotron", "lfm3-1.7b": "LFM3", "lfm25-24b-a2b": "LFM2.5",
  gaia: "Gaia", manaca: "Manacá", tucano: "Tucano", "lumi-hf": "Lumi", latamgpt: "Latam" };
const sizeBand = value => sizeBands.find(b => value <= b.max);

function scatterDomain(rows) {
  const sizes = rows.map(r => r.variant.model.total_b), scores = rows.map(r => r.record.score);
  const lo = Math.log10(Math.min(...sizes)), hi = Math.log10(Math.max(...sizes));
  const padding = Math.max(.08, (hi - lo) * .08);
  return { xmin: lo - padding, xmax: hi + padding,
    ymin: Math.min(0, Math.floor(Math.min(...scores) / 10) * 10),
    ymax: Math.max(20, Math.ceil(Math.max(...scores) / 10) * 10) };
}

// Only the label moves. Its small anchor always retains the exact data position.
function placeScatterLabels(points, bounds, radius) {
  const placed = [], distance = 2 * radius + 5;
  return points.map(point => {
    let best = null, bestCost = Infinity;
    for (let ring = 0; ring < Math.ceil(Math.hypot(bounds.right-bounds.left, bounds.bottom-bounds.top)/12); ring++) {
      const reach = ring * 12, angles = ring ? 32 : 1;
      if (best && reach * reach > bestCost) break;
      for (let i = 0; i < angles; i++) {
        const angle = i * Math.PI * 2 / angles;
        const x = point.x + Math.cos(angle) * reach, y = point.y + Math.sin(angle) * reach;
        if (x < bounds.left+radius || x > bounds.right-radius || y < bounds.top+radius || y > bounds.bottom-radius) continue;
        if (placed.some(p => Math.hypot(p.lx-x, p.ly-y) < distance)) continue;
        const cost = reach*reach + (y-point.y)**2 * 3;
        if (cost < bestCost) { best = { ...point, lx: x, ly: y }; bestCost = cost; }
      }
    }
    if (!best) throw new Error("Insufficient chart space for model labels");
    placed.push(best);
    return best;
  });
}

function renderSizeScatter(allRows, task) {
  const rows = allRows.filter(({variant,record}) => Number.isFinite(record?.score) && !record.averages_exclusion && variant.model.total_b > 0);
  if (!rows.length) return '<div class="empty">Sem notas para esta seleção.</div>';
  const domain = scatterDomain(rows), modes = ["thinking","instruct"].filter(mode => rows.some(r => r.variant.mode === mode));
  const available = Math.max(280, (document.querySelector(".scatter-panel")?.clientWidth || app.clientWidth) - 56);
  const columns = modes.length === 2 && available >= 900 ? 2 : 1;
  const width = Math.floor((available - (columns-1)*20) / columns), height = 430, radius = 26;
  const bounds = { left: 44, right: width-18, top: 64, bottom: height-74 };
  const x = n => bounds.left + (Math.log10(n)-domain.xmin)/(domain.xmax-domain.xmin)*(bounds.right-bounds.left);
  const y = n => bounds.bottom - (n-domain.ymin)/(domain.ymax-domain.ymin)*(bounds.bottom-bounds.top);
  const yTicks = Array.from({length:5},(_,i)=>domain.ymin+(domain.ymax-domain.ymin)*i/4);
  const inDomain = n => Math.log10(n) >= domain.xmin && Math.log10(n) <= domain.xmax;
  let candidates = [1,2,4,8,16,32,64,128].filter(inDomain);
  if (candidates.length < 2) candidates = [1,1.5,2,3,4,5,6,8,10,15,20,30,50,70,100].filter(inDomain);
  const xTicks = candidates.reduce((kept,n) => !kept.length || x(n)-x(kept.at(-1)) > 38 ? [...kept,n] : kept, []);
  return `<div class="scatter-legend" aria-label="Cores por parâmetros totais">${sizeBands.map(b => `<span><i style="background:${b.color}"></i>${b.label}</span>`).join("")}</div>
    <div class="scatter-charts" style="--plot-columns:${columns}">${modes.map(mode => {
      const subset = rows.filter(r => r.variant.mode === mode).sort((a,b) => a.record.score-b.record.score || a.variant.id.localeCompare(b.variant.id));
      const points = placeScatterLabels(subset.map(row => ({...row, x:x(row.variant.model.total_b), y:y(row.record.score)})), {...bounds,top:28,bottom:height-40}, radius);
      return `<section class="scatter-card" data-plot-mode="${mode}"><div class="scatter-card-head"><h4>${modeName(mode)}</h4><span>${points.length} modelos</span></div>
        <svg class="scatter" viewBox="0 0 ${width} ${height}" role="group" aria-label="Tamanho e resultado em ${esc(task.name)}, ${modeName(mode)}" data-ymin="${domain.ymin}" data-ymax="${domain.ymax}" data-xmin="${domain.xmin}" data-xmax="${domain.xmax}">
          <text class="plot-axis-title" x="${bounds.left}" y="17">Nota ↑</text>
          ${yTicks.map(n => `<line class="plot-grid" x1="${bounds.left}" x2="${bounds.right}" y1="${y(n)}" y2="${y(n)}"/><text x="${bounds.left-10}" y="${y(n)+4}" text-anchor="end">${number(n,Number.isInteger(n)?0:1)}</text>`).join("")}
          ${xTicks.map(n => `<line class="plot-grid vertical" x1="${x(n)}" x2="${x(n)}" y1="${bounds.top}" y2="${bounds.bottom}"/><text x="${x(n)}" y="${height-33}" text-anchor="middle">${number(n,n%1?1:0)}</text>`).join("")}
          <text class="plot-axis-title" x="${(bounds.left+bounds.right)/2}" y="${height-9}" text-anchor="middle">Parâmetros totais (B)</text>
          ${points.map(p => `<line class="plot-leader" x1="${p.x}" y1="${p.y}" x2="${p.lx}" y2="${p.ly}"/><circle class="plot-anchor" cx="${p.x}" cy="${p.y}" r="4" fill="${sizeBand(p.variant.model.total_b).color}"/>`).join("")}
          ${points.map(p => {
            const {variant,record,lx,ly} = p, band = sizeBand(variant.model.total_b);
            return `<g class="plot-point" data-result="${esc(record.id)}" data-size-band="${esc(band.label)}" data-anchor-x="${p.x}" data-anchor-y="${p.y}" tabindex="0" role="button" aria-label="${esc(variant.model.name)}, ${modeName(mode)}, ${number(variant.model.total_b)} bilhões de parâmetros, nota ${number(record.score)}. Abrir resultado.">
              <title>${esc(variant.model.name)} · ${modeName(mode)} · ${number(variant.model.total_b)}B · nota ${number(record.score)}</title>
              <circle class="plot-bubble" cx="${lx}" cy="${ly}" r="${radius}" fill="${band.color}"/>
              <text class="plot-model" x="${lx}" y="${ly-3}" text-anchor="middle">${esc(plotNames[variant.model.id] || variant.model.symbol)}</text>
              <text class="plot-score" x="${lx}" y="${ly+11}" text-anchor="middle">${number(record.score,1)}</text>
            </g>`;
          }).join("")}
        </svg></section>`;
    }).join("")}</div><p class="scatter-caption">1B = 1 bilhão de parâmetros · escala horizontal logarítmica. As linhas ligam os nomes à posição exata de cada resultado.</p>`;
}

if (typeof module !== "undefined") module.exports = {sizeBand, scatterDomain, placeScatterLabels};
