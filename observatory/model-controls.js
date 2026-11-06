"use strict";

// These are browsing groups, not a claim of equal compute or equal capability.
const sizeGroups = {
  up_to_4b: { label: "Até 4B", detail: "Modelos menores e da faixa nominal 4B. A contagem exata aparece junto ao nome." },
  all: { label: "Todos", detail: "Todos os tamanhos. Parâmetros totais, ativos e efetivos continuam identificados." },
};
const sizeLabels = {similar: "Faixa 4B", small: "Até 2B", effective: "8B · 4B efetivos", moe: "24B · 2B ativos", large: "70B", unknown: "Sem tamanho verificado"};
function modelSizeGroup(m) {
  if (!Number.isFinite(m.total_b)) return "unknown";
  if (m.size_kind === "moe") return "moe";
  if (m.size_kind === "effective") return "effective";
  if (m.total_b <= 2) return "small";
  if (m.total_b >= 3 && m.total_b <= 5) return "similar";
  return "large";
}
function inSizeGroup(m, group = state.size) {
  return group === "all" || ["small", "similar"].includes(modelSizeGroup(m));
}
function normalizeSizeFilter(value) {
  if (sizeGroups[value]) return value;
  if (["similar", "small"].includes(value)) return "up_to_4b";
  if (["effective", "moe", "large"].includes(value)) return "all";
  return null;
}
function sizeModels() {
  return D.models.filter((m) => inSizeGroup(m)).sort((a,b) => sizeOrder(a)-sizeOrder(b));
}
function sizeOrder(m) { return ["similar","small","effective","moe","large","unknown"].indexOf(modelSizeGroup(m)); }
function tableSizeGroups(variants) {
  if (state.size !== "all") return "";
  const groups=[];
  for (const v of variants) {
    const id=modelSizeGroup(v.model), last=groups.at(-1);
    if (last?.id === id) last.n++; else groups.push({id,n:1});
  }
  return `<tr class="size-table-groups"><th scope="col">Parâmetros</th>${groups.map((g) => `<th scope="colgroup" colspan="${g.n}">${esc(sizeLabels[g.id])}</th>`).join("")}</tr>`;
}
function originBadge(m) {
  if (m.brazilian_project) return `<span class="origin-flag" role="img" aria-label="Projeto brasileiro" title="${esc(m.origin_note)}">🇧🇷</span>`;
  if (m.id === "tucano") return '<span class="origin-flag" role="img" aria-label="Modelo para português brasileiro" title="Modelo para português brasileiro · University of Bonn">🇧🇷</span>';
  if (m.id === "latamgpt") return '<span class="origin-note" title="Projeto latino-americano, com participação brasileira">LatAm</span>';
  return "";
}
function modelName(m) { return `${esc(m.name)} ${originBadge(m)}`; }
function optionName(m) { return `${m.brazilian_project || m.id === "tucano" ? "🇧🇷 " : ""}${esc(m.name)} · ${esc(i18n.t(m.size_label))}`; }
function sizeControls() {
  return `<section class="size-controls" aria-label="Filtrar modelos por tamanho"><div class="size-heading"><strong>Tamanho dos modelos</strong><span>🇧🇷 projeto brasileiro</span></div><div class="size-buttons">${Object.entries(sizeGroups).map(([id, group]) => `<button data-size-group="${id}" aria-pressed="${state.size === id}"><span>${group.label}</span><small>${D.models.filter((m) => inSizeGroup(m,id)).length}</small></button>`).join("")}</div><p>${esc(sizeGroups[state.size].detail)} <button class="text-button" data-size-help>Entenda os tamanhos</button></p></section>`;
}
function groupedModelOptions(selected) {
  return Object.entries(sizeLabels).map(([group, label]) => {
    const variants = allVariants().filter((v) => inSizeGroup(v.model) && modelSizeGroup(v.model) === group);
    return variants.length ? `<optgroup label="${label}">${variants.map((v) => variantOption(v.id, selected)).join("")}</optgroup>` : "";
  }).join("");
}
function alignComparisonSize() {
  const available = allVariants().filter((v) => inSizeGroup(v.model));
  for (const side of ["a", "b"]) {
    if (available.some((v) => v.id === state[side])) continue;
    const mode = state[side].split(":")[1], other = state[side === "a" ? "b" : "a"];
    state[side] = (available.find((v) => v.mode === mode && v.id !== other) || available.find((v) => v.id !== other) || available[0])?.id || state[side];
  }
}
document.addEventListener("click", (event) => {
  const t = event.target.closest("[data-size-group],[data-size-help]");
  if (!t || !D) return;
  if (t.hasAttribute("data-size-help")) {
    $("#detail-content").innerHTML = '<h2 id="detail-title">Como separamos os tamanhos</h2><p><strong>B = bilhão de parâmetros.</strong> “Até 4B” reúne os modelos menores e os da faixa nominal 4B: S5-nano, Qwen3.5-4B, Gaia, Lumi, Tucano, LFM3 e Manacá. O nome da faixa usa o porte nominal: S5-nano tem cerca de 4,2B no componente de texto; Qwen3.5-4B tem 4,66B incluindo visão. As contagens exatas permanecem visíveis. Gemma E4B, Nemotron E4B e LFM2.5-A2B ficam em “Todos”, pois seus totais são maiores.</p><p><strong>Total:</strong> todos os parâmetros do checkpoint. Nos modelos multimodais, o total pode incluir visão, mesmo quando a avaliação usa apenas texto.</p><p><strong>Ativo:</strong> a parte de um MoE usada para cada token. O LFM2.5 tem cerca de 24B totais e 2B ativos; os 24B continuam necessários para armazenar o modelo.</p><p><strong>Efetivo:</strong> medida reportada pelos autores de Gemma 4 E4B e Nemotron Bolt E4B. Ambos têm 8B totais. Essa medida não é a contagem ativa de um MoE.</p><p>Esses grupos ajudam a navegar. Não afirmam mesmo consumo de memória, velocidade, custo ou protocolo.</p><p>🇧🇷 identifica projetos brasileiros, incluindo colaborações internacionais. Tucano é identificado como modelo para português ligado à University of Bonn; LatamGPT, como projeto regional com participação brasileira.</p>';
    $("#detail-dialog").showModal(); return;
  }
  state.size = t.dataset.sizeGroup;
  alignComparisonSize();
  experience.round = null;
  ensureExperienceSelection();
  if (experienceActive()) experienceURL(); else writeHash();
  render();
});
