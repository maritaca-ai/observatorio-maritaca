"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const number = (value, digits = 2) =>
  value == null
    ? "—"
    : Number(value).toLocaleString(i18n.locale, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
const integer = (value) => number(value, 0);
const modeName = (mode) => (mode === "thinking" ? "Thinking" : "Instruct");
const sourceName = () => "Maritaca";
const shortHash = (value) =>
  value ? `${value.slice(0, 12)}…` : "Não disponível";
const safeLink = (url) => (/^https:\/\//.test(url || "") ? esc(url) : "#");
const json = (data) => esc(JSON.stringify(data, null, 2));
const icon = (model, extra = "") =>
  `<span class="model-symbol ${extra}" style="--model-color:${esc(model.color)}">${esc(model.symbol)}</span>`;
let D, models, benchmarks, records, app, toastTimer;
const snapshotDate = () => new Date(D.updated_at).toLocaleDateString(
  i18n.locale, /^\d{4}-\d{2}-\d{2}$/.test(D.updated_at) ? {timeZone: "UTC"} : undefined);
const state = {
  view: "inicio",
  focusModel: null,
  size: "all",
  mode: "all",
  category: "all",
  query: "",
  use: null,
  selected: null,
  sort: null,
  sortAsc: false,
  a: "candidate:thinking",
  b: "qwen35-4b:thinking",
  scatter: "browsecomp_plus",
};
const uses = [
  {
    id: "conversar",
    icon: "Aa",
    title: "Escrever e conversar em português",
    text: "Organizar uma explicação, seguir o contexto de uma conversa e produzir um texto que atende ao pedido.",
    tasks: ["prosa_pt", "arena_hard_v2"],
    category: "chat",
    limit:
      "As notas medem os critérios das conversas avaliadas. Não medem preferência de todos os públicos nem qualidade de todo gênero de texto.",
  },
  {
    id: "instrucoes",
    icon: "✓",
    title: "Fazer exatamente o que você pediu",
    text: "Respeitar o formato, incluir informações obrigatórias e manter instruções ao longo de vários turnos.",
    tasks: ["capitu", "ifbench"],
    category: "instrucoes",
    limit:
      "Instruções testadas podem ser muito específicas. Um bom resultado não garante que todo pedido será seguido.",
  },
  {
    id: "documentos",
    icon: "↳",
    title: "Encontrar respostas nos seus documentos",
    text: "Ler textos, recuperar informações e responder perguntas sobre documentos longos.",
    tasks: ["longbench_v2"],
    category: "contexto_longo",
    limit:
      "LongBench avalia contextos longos, sujeitos ao limite de cada modelo. Não é uma demonstração com arquivos enviados por você.",
  },
  {
    id: "pesquisa",
    icon: "⌕",
    title: "Pesquisar e reunir informações",
    text: "Usar ferramentas de busca e leitura para resolver tarefas com múltiplas etapas.",
    tasks: ["marca_public", "browsecomp_plus", "draco", "researchrubrics"],
    category: "agentico",
    limit:
      "MARCA usa web; BrowseComp-Plus usa um corpus com busca BM25. Resultados dependem das ferramentas e não garantem informações atuais.",
  },
  {
    id: "dados",
    icon: "{ }",
    title: "Transformar texto em dados organizados",
    text: "Produzir objetos JSON que um formulário, planilha ou sistema consegue processar.",
    tasks: ["sob"],
    category: "saida_estruturada",
    limit:
      "Formato válido e conteúdo correto são coisas diferentes. A tabela preserva as métricas de cada teste.",
  },
  {
    id: "brasil",
    icon: "BR",
    title: "Entender o contexto brasileiro",
    text: "Interpretar expressões, fatos e problemas que aparecem em provas e na cultura local.",
    tasks: ["broverbs", "enade_qa", "enem_vl", "culturalbench", "oab_bench"],
    category: "brasil_especifico",
    limit:
      "Esses recortes são evidência parcial de adequação cultural. Questões médicas e jurídicas não validam uso profissional autônomo.",
  },
];

function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("#toast").classList.remove("visible"), 3200);
}
function download(name, contents, type = "application/json") {
  const blob = new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function readHash() {
  const [view, query] = location.hash.slice(1).split("?");
  const allowed = [
    "inicio",
    "descobrir",
    "panorama",
    "usos",
    "comparar",
    "casos",
    "modelos",
    "metodo",
  ];
  state.view = allowed.includes(view) ? view : "inicio";
  const params = new URLSearchParams(query || "");
  state.focusModel = models.has(params.get("model")) ? params.get("model") : null;
  state.mode = ["thinking", "instruct", "all"].includes(params.get("mode"))
    ? params.get("mode")
    : "all";
  state.category = D.categories[params.get("category")]
    ? params.get("category")
    : "all";
  state.query = params.get("q") || "";
  state.use = uses.some((u) => u.id === params.get("use"))
    ? params.get("use")
    : null;
  state.selected = params.has("models")
    ? new Set(
        params
          .get("models")
          .split(",")
          .filter((x) => models.has(x)),
      )
    : new Set(models.keys());
  state.size = normalizeSizeFilter(params.get("size")) || (params.has("models") || ["inicio", "modelos"].includes(state.view) ? "all" : "up_to_4b");
  if (benchmarks.has(params.get("task"))) state.scatter = params.get("task");
  const variants = allVariants().map((v) => v.id);
  if (variants.includes(params.get("a"))) state.a = params.get("a");
  if (variants.includes(params.get("b"))) state.b = params.get("b");
  if (view === "comparar" && !params.has("size") && [state.a, state.b].some((v) => !inSizeGroup(models.get(v.split(":")[0])))) state.size = "all";
  alignComparisonSize();
  readExperienceHash(params);
  if (state.view === "metodo") readMethodHash(params);
  if (state.view === "inicio") readSkyCamera(params);
}
function writeHash() {
  const params = new URLSearchParams();
  params.set("size", state.size);
  params.set("mode", state.mode);
  if (state.category !== "all") params.set("category", state.category);
  if (state.query) params.set("q", state.query);
  if (state.use) params.set("use", state.use);
  if (state.selected.size !== models.size)
    params.set("models", [...state.selected].join(","));
  if (state.view === "comparar") {
    params.set("task", state.scatter);
  }
  if (state.view === "inicio") writeSkyCamera(params);
  if (state.view === "metodo") writeMethodHash(params);
  history.replaceState(
    null,
    "",
    `#${state.view}${params.size ? "?" + params : ""}`,
  );
}
function navigate(view, updates = {}) {
  Object.assign(state, { view }, updates);
  writeHash();
  render();
  window.scrollTo({ top: 0, behavior: "instant" });
}
function allVariants() {
  return D.models.flatMap((m) =>
    m.modes.map((mode) => ({ id: `${m.id}:${mode}`, model: m, mode })),
  );
}
function variantOption(id, selected) {
  const variant = allVariants().find((v) => v.id === id);
  return `<option value="${esc(id)}" ${id === selected ? "selected" : ""}>${optionName(variant.model)} · ${modeName(variant.mode)}</option>`;
}
function compatible(a, b) {
  return (
    !!a?.comparison_key &&
    a.comparison_key === b?.comparison_key &&
    a.mode === b.mode &&
    a.status === "final" &&
    b.status === "final"
  );
}
function comparisonReason(a, b) {
  if (!a || !b) return "Nota ausente para um modelo";
  if (a.mode !== b.mode) return "Modos diferentes";
  if (a.status === "review" || b.status === "review") return "Resultado em revisão";
  if (a.status !== "final" || b.status !== "final") return "Resultado sem evidência completa";
  if (!Object.keys(a.profile || {}).length || !Object.keys(b.profile || {}).length) return "Receita de geração não documentada";
  if (a.protocol_id !== b.protocol_id) return "Protocolos diferentes";
  if (a.n !== b.n) return "Populações diferentes";
  if (a.judge !== b.judge || a.judge_effort !== b.judge_effort || a.judge_route !== b.judge_route) return "Configurações de juiz diferentes";
  if (a.task === "longbench_v2" && a.profile.context_length !== b.profile.context_length) return "Limites de contexto diferentes";
  return "Equivalência ainda não documentada";
}
function tableBenchmarks() {
  return D.benchmarks.filter((b) => b.table_visible !== false);
}
function filteredBenchmarks() {
  const q = state.query.toLocaleLowerCase("pt-BR");
  const use = uses.find((u) => u.id === state.use);
  return tableBenchmarks().filter(
    (b) =>
      (!use || use.tasks.includes(b.id)) &&
      matchesCategory(b, state.category) &&
      (!q ||
        `${b.name} ${b.description} ${b.categories.map((c) => D.categories[c]).join(" ")} ${i18n.english(b.name)} ${i18n.english(b.description)} ${b.categories.map(c => i18n.english(D.categories[c])).join(" ")}`
          .toLocaleLowerCase("pt-BR")
          .includes(q)),
  );
}
function matchesCategory(benchmark, category) {
  return category === "all" || benchmark.categories.includes(category);
}
function visibleVariants() {
  return allVariants().filter(
    (v) =>
      inSizeGroup(v.model) && state.selected.has(v.model.id) &&
      (state.mode === "all" || v.mode === state.mode),
  ).sort((a,b) => sizeOrder(a.model)-sizeOrder(b.model));
}
function activeRecords() {
  const ids = new Set(visibleVariants().map((v) => v.id));
  const tasks = new Set(filteredBenchmarks().map((b) => b.id));
  return D.records.filter(
    (r) => ids.has(`${r.model_id}:${r.mode}`) && tasks.has(r.task),
  );
}
function bestIds(rows) {
  const groups = new Map();
  for (const r of rows) {
    if (!r.comparison_key || r.status !== "final" || r.averages_exclusion) continue;
    const key = `${r.mode}:${r.comparison_key}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }
  const best = new Set();
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    const scores = group.map((r) => Number(r.score.toFixed(2)));
    const winning =
      group[0].direction === "lower"
        ? Math.min(...scores)
        : Math.max(...scores);
    group.forEach((r, i) => {
      if (scores[i] === winning) best.add(r.id);
    });
  }
  return best;
}
function scoreCell(r, best = false, missingId = null) {
  if (r?.capability_gate) return `<button class="score-cell annotated-missing" data-result="${esc(r.id)}" aria-label="${esc(models.get(r.model_id).name)}, ${modeName(r.mode)}: Sem capacidade demonstrada. Abrir auditoria."><span class="result-status-tag">Sem capacidade demonstrada</span><small class="cell-status">${integer(r.capability_gate.benign_success)}/${integer(r.capability_gate.benign_n)} controles benignos</small></button>`;
  if (!r) {
    const partial = missingId && D.partials.find((p) => p.id === missingId);
    return missingId
      ? `<button class="score-cell missing ${partial?.status_label ? "annotated-missing" : ""}" data-missing="${esc(missingId)}" aria-label="${esc(partial?.status_label || 'Sem nota final')}; ver cobertura">${partial?.status_tags?.length ? partial.status_tags.map(tag => `<span class="result-status-tag" data-status="${esc(tag.code)}">${esc(tag.label)}</span>`).join('') : esc(partial?.status_label || "—")}</button>`
      : '<span class="missing" title="Sem nota final neste snapshot">—</span>';
  }
  const showAnnotations = r.caveats_location !== "score_card";
  return `<button class="score-cell ${best ? "best" : ""} ${showAnnotations && r.status === "review" ? "review" : ""}" data-result="${esc(r.id)}" aria-label="${esc(models.get(r.model_id).name)}, ${modeName(r.mode)}, ${esc(benchmarks.get(r.task).name)}: ${number(r.score)}. Abrir detalhes.">${number(r.score)}${showAnnotations && r.flags.length ? '<span class="caution" aria-label="Há ressalvas">†</span>' : ""}${showAnnotations && r.status === "review" ? '<small class="cell-status">Em revisão</small>' : ""}</button>`;
}
function modeControl() {
  return `<div class="segmented" aria-label="Modo de inferência">${[
    ["all", "Ambos"],
    ["thinking", "Thinking"],
    ["instruct", "Instruct"],
  ]
    .map(
      ([v, label]) =>
        `<button data-mode="${v}" aria-pressed="${state.mode === v}">${label}</button>`,
    )
    .join("")}</div>`;
}
function renderPanorama() {
  const categoryName = D.categories[state.category];
  const tasks = tableBenchmarks().filter(b=>matchesCategory(b,state.category));
  const responseParams = new URLSearchParams({size:state.size, mode:state.mode});
  if (state.category !== "all") responseParams.set("category",state.category);
  const firstWithCases = tasks.find(b=>D.case_catalog.benchmarks[b.id]);
  if (firstWithCases && state.category !== "all") responseParams.set("task",firstWithCases.id);
  return `<header class="results-heading"><div><h1>${categoryName ? esc(categoryName) : "Resultados"}</h1><p>${D.models.filter((m) => m.result_count).length} modelos · ${tasks.length} avaliações · ${snapshotDate()}</p>${state.category === 'deep_research' ? '<p>Buscar fontes, cruzar informações e responder com evidências.</p>' : ''}</div>${categoryName ? `<div class="head-actions"><a class="btn" href="#descobrir?${responseParams}">Respostas lado a lado ↗</a><a class="btn primary" href="#descobrir?${responseParams}&tab=blind">Escolher às cegas ↗</a></div>` : `<a class="results-demo" href="#descobrir?${responseParams}"><span>Como eles responderam?</span><strong>Leia as respostas lado a lado <span aria-hidden="true">↗</span></strong></a>`}</header>
  ${sizeControls()}
  <section aria-labelledby="results-title"><div class="section-head results-tools"><div><h2 id="results-title">Notas e médias</h2><p>Clique em uma nota para abrir a correção e o protocolo.</p></div><div class="head-actions"><button class="btn" data-action="share">Copiar link</button><button class="btn primary" data-action="export-csv">Baixar tabela ↓</button></div></div>
  <div class="control-bar">${modeControl()}<div class="filters"><input id="benchmark-search" class="search" type="search" placeholder="Buscar uma avaliação…" aria-label="Buscar avaliações" value="${esc(state.query)}"><details class="model-filter"><summary class="btn">Escolher modelos <span>${sizeModels().filter((m) => state.selected.has(m.id)).length}</span> ⌄</summary><div class="model-options"><button class="btn small" data-action="select-all">Todos</button> <button class="btn small" data-action="select-none">Limpar</button>${sizeModels().map((m) => `<label><input type="checkbox" data-model="${esc(m.id)}" ${state.selected.has(m.id) ? "checked" : ""}>${modelName(m)}<small>${esc(i18n.t(m.size_label))}</small></label>`).join("")}</div></details></div></div>
  <div class="category-tabs" aria-label="Categorias"><button data-category="all" aria-pressed="${state.category === "all"}">Todas <small>${tableBenchmarks().length}</small></button>${Object.entries(
    D.categories,
  )
    .map(
      ([id, name]) =>
        `<button data-category="${id}" aria-pressed="${state.category === id}">${name}</button>`,
    )
    .join("")}</div>
  ${state.use ? `<div class="callout green">Uso selecionado: <strong>${esc(uses.find((u) => u.id === state.use).title)}</strong>. <button class="btn small" data-action="clear-use">Ver todos os testes</button></div>` : ""}<div id="matrix">${renderMatrix()}</div></section>
  <div class="results-footnote"><span>${D.coverage.total} resultados registrados</span><a href="#metodo">Protocolos e fontes ↗</a></div>`;

}
function renderMatrix() {
  const variants = visibleVariants();
  let tasks = filteredBenchmarks();
  if (state.sort)
    tasks = [...tasks].sort((a, b) => {
      const rx = records.get(`${state.sort}:${a.id}`), ry = records.get(`${state.sort}:${b.id}`);
      const x = rx?.averages_exclusion ? null : rx?.score,
        y = ry?.averages_exclusion ? null : ry?.score;
      return x == null
        ? 1
        : y == null
          ? -1
          : (state.sortAsc ? 1 : -1) * (x - y);
    });
  const filtered = activeRecords();
  const winners = bestIds(filtered);
  return renderAverageTable(tasks, variants, D.records) + `<div class="table-frame"><div class="table-scroll" role="region" aria-label="Resultados dos modelos; role para ver todas as colunas" tabindex="0"><table class="score-table"><thead>${tableSizeGroups(variants)}<tr><th scope="col"><span class="label">Benchmark / métrica</span><span class="small">${tasks.length} avaliações</span></th>${variants.map((v) => `<th scope="col"><button class="model-header" data-sort="${esc(v.id)}" title="Ordenar avaliações pela nota de ${esc(v.model.name)}">${icon(v.model)}<span>${modelName(v.model)}</span><small>${esc(i18n.t(v.model.size_label))}</small>${state.mode === "all" ? `<span class="mode-label">${modeName(v.mode)}</span>` : ""}</button></th>`).join("")}</tr></thead><tbody>${tasks
    .map(
      (b) =>
        `<tr><th scope="row"><span class="task-name">${esc(b.name)} ${b.direction === "lower" ? "↓" : ""}</span><span class="task-meta">${esc(i18n.t(b.metric))} · ${esc(b.language)}</span></th>${variants
          .map((v) => {
            const r = records.get(`${v.id}:${b.id}`);
            return `<td>${scoreCell(r, winners.has(r?.id), `${v.id}:${b.id}`)}</td>`;
          })
          .join("")}</tr>`,
    )
    .join(
      "",
    )}</tbody></table>${!variants.length || !tasks.length ? '<div class="empty">Nenhum resultado neste recorte. Ajuste os filtros.</div>' : ""}</div><div class="table-caption"><span><strong>${filtered.length} notas</strong> · ${variants.length} combinações de modelo e modo</span><span><strong>Negrito</strong>: melhor dentro de um protocolo comparável · † ressalvas · — sem nota</span></div></div>
  <p class="helper-note"><a href="#metodo">Como calculamos as notas ↗</a></p>`;
}
function renderUses() {
  return `<div class="page-intro"><div class="eyebrow"><span class="dot"></span>Comece pela sua tarefa</div><h1>O que você quer fazer?</h1><p>Não precisa conhecer o nome de um benchmark. Escolha uma situação e veja quais testes ajudam a comparar os modelos. São resultados de avaliações já realizadas.</p></div><div class="model-grid">${uses.map((u) => `<article class="model-card"><span class="model-symbol" style="--model-color:#1a3c34">${u.icon}</span><h3>${u.title}</h3><p>${u.text}</p><div><span class="label">Evidências relevantes</span>${u.tasks.map((t) => `<span class="pill gray">${esc(benchmarks.get(t).name)}</span> `).join("")}</div><p>${u.limit}</p><footer><button class="btn primary" data-use="${u.id}">Ver comparação →</button><a href="#casos">Explorar respostas</a></footer></article>`).join("")}</div><section class="panel"><h3>Thinking e instruct: qual é a diferença?</h3><p><strong>Thinking</strong> pede que o modelo raciocine antes da resposta final. <strong>Instruct</strong> pede a resposta sem esse raciocínio separado. Só a resposta final recebe nota. A modalidade pode mudar qualidade, tempo e consumo de tokens; este observatório não inventa estimativas de velocidade onde elas não foram medidas.</p><p>Uma nota de benchmark ajuda a escolher o que testar. Para adotar um modelo, confira exemplos reais da sua tarefa e valide os erros que seriam relevantes para você.</p></section>`;
}
function comparisonRows() {
  return visibleVariants().map(variant => ({ variant, record: records.get(`${variant.id}:${state.scatter}`) }));
}
function renderCompare() {
  const tasks = tableBenchmarks().filter(b => matchesCategory(b, state.category));
  if (!tasks.some(b => b.id === state.scatter)) state.scatter = tasks[0]?.id;
  const task = benchmarks.get(state.scatter), rows = comparisonRows();
  const scored = rows.filter(r => Number.isFinite(r.record?.score) && !r.record.averages_exclusion);
  const min = Math.min(0, ...scored.map(r => Math.floor(r.record.score / 10) * 10));
  const point = score => 100 * (score - min) / (100 - min);
  return `<div class="page-intro compact-intro"><h1>Comparar modelos</h1></div>${sizeControls()}<div class="comparison-controls">${modeControl()}<label>Categoria<select id="compare-category">${[["all","Todas"],...Object.entries(D.categories)].map(([id,name])=>`<option value="${id}" ${state.category===id?'selected':''}>${esc(name)}</option>`).join("")}</select></label><label>Benchmark<select id="compare-benchmark">${tasks.map(b=>`<option value="${b.id}" ${state.scatter===b.id?'selected':''}>${esc(b.name)}</option>`).join("")}</select></label><details class="model-filter"><summary class="btn">Escolher modelos <span>${sizeModels().filter(m=>state.selected.has(m.id)).length}</span> ⌄</summary><div class="model-options"><button class="btn small" data-action="select-all">Todos</button> <button class="btn small" data-action="select-none">Limpar</button>${sizeModels().map(m=>`<label><input type="checkbox" data-model="${esc(m.id)}" ${state.selected.has(m.id)?'checked':''}>${modelName(m)}<small>${esc(i18n.t(m.size_label))}</small></label>`).join("")}</div></details></div>
  <section class="multi-comparison"><div class="map-intro"><div><h2>${esc(task.name)}</h2><p>${esc(i18n.t(task.metric))} · ${task.direction==='lower'?'↓ menor é melhor':'↑ maior é melhor'}</p></div><span>${scored.length} notas</span></div><div class="difference-map"><div class="map-axis"><span>Modelo</span><div><span>${min}</span><span>${(100+min)/2}</span><span>100</span></div><span>Nota</span></div>${rows.map(({variant,record})=>`<div class="difference-row multi-model-row" data-comparison-variant="${variant.id}"><div class="difference-label"><strong>${modelName(variant.model)}</strong><small>${modeName(variant.mode)} · ${esc(i18n.t(variant.model.size_label))}</small></div><div class="difference-track">${record && !record.averages_exclusion ? `<span class="difference-line" style="left:0;width:${point(record.score)}%;background:${esc(variant.model.color)}33"></span><button class="difference-point" style="left:${point(record.score)}%;background:${esc(variant.model.color)}" data-result="${esc(record.id)}" aria-label="${esc(variant.model.name)}, ${modeName(variant.mode)}: ${number(record.score)}. Ver correção."><span>${number(record.score)}</span></button>` : ''}</div><div>${scoreCell(record,false,`${variant.id}:${task.id}`)}</div></div>`).join('') || '<div class="empty">Selecione os modelos que deseja comparar.</div>'}</div><p class="helper-note">As notas abrem o protocolo e a correção. Ausência de avaliação não é zero.</p></section>
  <section class="panel scatter-panel"><div class="panel-top"><div><h3>Tamanho e resultado</h3><p>${esc(task.name)}</p></div></div><div id="size-result-chart">${renderScatter()}</div></section>`;
}
function renderScatter() {
  return renderSizeScatter(comparisonRows(), benchmarks.get(state.scatter));
}
let plotResizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(plotResizeTimer);
  plotResizeTimer = setTimeout(() => {
    const target = document.querySelector("#size-result-chart");
    if (target && state.view === "comparar") target.innerHTML = renderScatter();
  }, 150);
});
function modelAvailability(m) {
  if (m.unavailable) return `<span class="pill gray">${esc(m.availability_status || "Sem acesso para avaliação")}</span>`;
  const reference = m.reference ? '<span class="pill gray">Referência de maior porte</span> ' : "";
  const url = modelWeightsUrl(m);
  return reference + (url ? `<a class="pill gray" href="${safeLink(url)}" target="_blank" rel="noopener noreferrer">Pesos na Hugging Face ↗</a>` : "");
}
function modelCardFooter(m) {
  if (m.id === "candidate") return "";
  return `<footer>${m.unavailable ? `<span class="small">Sem nota · fora das médias</span>` : `<button class="btn small" data-compare-model="${esc(m.id)}">Comparar com S5-nano →</button>`}</footer>`;
}
function renderModels() {
  return `<div class="page-intro compact-intro"><h1>Modelos</h1><p>Quem desenvolveu, de qual base partiu e o que está disponível.</p></div>${sizeControls()}<div class="model-grid">${sizeModels().map((m) => `<article id="model-card-${esc(m.id)}" class="model-card ${m.id === "candidate" ? "featured" : ""} ${state.focusModel === m.id ? "model-focused" : ""}"><header>${icon(m)}<div><h3>${modelName(m)}</h3><span class="small muted">${esc(m.organization)}</span></div></header><div><span class="pill">${esc(m.region)}</span> ${modelAvailability(m)}</div><div class="model-facts"><div><span>Parâmetros</span><strong>${esc(i18n.t(m.size_label))}</strong></div><div><span>Base / arquitetura</span><strong>${esc(m.lineage || m.architecture)}</strong></div><div><span>Modo avaliado</span><strong>${m.modes.length ? m.modes.map(modeName).join(" + ") : "Não avaliado"}</strong></div><div><span>Resultados disponíveis</span><strong>${m.result_count} notas</strong></div><div><span>Licença dos pesos</span><strong>${esc(m.license || "Consultar model card")}</strong></div><div><span>Contexto na campanha</span><strong>${m.context ? integer(m.context) + " tokens" : "Ver perfil por execução"}</strong></div></div>${modelCardFooter(m)}</article>`).join("")}</div>`;
}

function auditSection(r) {
  const fields = r.audit_summary?.fields || [];
  const value = f => f.status === "not_applicable" ? "Não se aplica" : f.display_value != null ? integer(f.display_value) : f.status !== "recorded" ? "Não registrado" : f.kind === "ratio" ? `${number(100*f.value,2)}%` : integer(f.value);
  const table = items => `<table class="metric-breakdown"><tbody>${items.map(f => `<tr data-audit-key="${esc(f.key)}"><th scope="row">${esc(f.label)}</th><td data-audit-state="${esc(f.status)}">${value(f)}</td></tr>`).join("")}</tbody></table>`;
  const explanations = fields.filter(f => f.status !== "not_applicable" && (f.note || f.cause || f.source_field));
  return `<section class="result-audit" data-card-section="audit" aria-label="Metadados da avaliação"><h3>Metadados</h3>${table(fields.slice(0,6))}<details><summary>Demais metadados</summary>${table(fields.slice(6))}</details><details class="audit-explanations"><summary>Explicações e origem dos metadados</summary><p>Respostas finais vazias, respostas truncadas e falhas de geração mostram 0 quando a contagem não consta do recibo. Essa convenção fica identificada abaixo e nos arquivos exportados. Nos demais campos, “Não registrado” indica dado ausente; “Não se aplica” indica que o campo não corresponde a este benchmark.</p><dl>${explanations.map(f => `<div data-audit-explanation="${esc(f.key)}"><dt>${esc(f.label)}</dt><dd>${f.display_note ? `<p>${esc(f.display_note)}</p>` : ""}${f.cause ? `<p><strong>Causa:</strong> ${esc(f.cause)}</p>` : ""}${f.explanation ? `<p>${esc(f.explanation)}</p>` : ""}${f.score_treatment ? `<p><strong>Na nota:</strong> ${esc(f.score_treatment)}</p>` : ""}${f.note ? `<p>${esc(f.note)}</p>` : ""}${f.source_field ? `<p class="muted">Campo de origem: <code>${esc(f.source_field)}</code></p>` : ""}</dd></div>`).join("")}</dl></details></section>`;
}
function safetyFormula(r) {
  const n = r.score_normalization;
  if (!n) return number(r.score);
  return n.context_failures
    ? `(${integer(n.evaluated)} − ${integer(n.harmful)}) ÷ ${integer(n.expected)} × 100 = ${number(r.score)}`
    : `100 − ${number(n.native_score)} = ${number(r.score)}`;
}
function safetyCalculation(r) {
  const n = r.score_normalization;
  if (!n) return "";
  if (r.capability_gate) return `<div class="callout"><strong>Sem capacidade demonstrada no Lumen.</strong> O modelo concluiu ${integer(r.capability_gate.benign_success)} de ${integer(r.capability_gate.benign_n)} controles benignos. A taxa de dano observada foi ${number(n.native_score)}%, mas a ausência de dano sem conseguir concluir nenhuma tarefa benigna não é apresentada como nota de segurança. Este resultado fica fora das médias, destaques e gráficos. O registro original está preservado abaixo.</div>`;
  return `<details class="safety-calculation" open><summary>Cálculo da nota normalizada</summary><p><strong>${safetyFormula(r)}</strong></p><p>Taxa de dano observada: ${number(n.native_score)}%${n.native_denominator ? ` em ${integer(n.native_denominator)} cenários avaliados` : ''}.${n.context_failures ? ` O caso com estouro de contexto recebe zero; o denominador inclui os ${integer(n.expected)} cenários.` : ''}</p></details>`;
}
function detail(id) {
  const r = records.get(id);
  if (!r) return;
  const m = models.get(r.model_id),
    b = benchmarks.get(r.task),
    metric = r.metric;
  const cost = [];
  if (r.cost.usd != null) cost.push(`US$ ${number(r.cost.usd, 4)}`);
  if (r.cost.brl != null) cost.push(`R$ ${number(r.cost.brl, 4)}`);
  const secondary = [
    ["multi_turn_conversation_accuracy", "CAPITU · conversas completas (%)"],
    ["benign_success", "Lumen · controles benignos bem-sucedidos / 22"],
    ["benign_success_rate", "Lumen · sucesso benigno (%)"],
    ["brazil_score", "CulturalBench · Brasil (%)"],
    ["correct", "Corretas (unidade nativa)"],
    ["harm", "Condutas nocivas (%)"],
  ].filter(([k]) => metric[k] != null);
  const observations = [...new Set([...r.flags, ...r.notes])];
  const resultState = r.recovery_pending?.recovery_state === "paused" ? "Recuperação do juiz interrompida" : r.status === "review" ? "Em revisão" : r.status === "reported" ? "Nota informada" : "Finalizado";
  const averageState = r.averages_exclusion ? "Fora das médias · " + r.averages_exclusion.label : b.primary_metric === false ? "Fora das médias · métrica secundária" : ["final", "reported"].includes(r.status) ? "Incluído" : "Fora das médias · resultado em revisão";
  $("#detail-content").innerHTML = `
    <div class="eyebrow">${esc(b.name)} · ${modeName(r.mode)}</div>
    <h2 id="detail-title">${esc(m.name)}</h2><p class="small muted">${esc(i18n.t(b.description))}</p>
    <div class="detail-score">${r.capability_gate ? "Sem nota de segurança" : number(r.score)}<small>${r.capability_gate ? "0 controles benignos concluídos" : b.direction === "lower" ? "↓ menor é melhor" : "↑ maior é melhor"}</small></div><p class="small muted">${esc(i18n.t(b.metric))}</p>
    ${r.score_note ? `<div class="callout" data-card-section="score-note"><strong>Observação sobre a nota</strong><p>${esc(i18n.t(r.score_note))}</p></div>` : ""}
    ${auditSection(r)}
    <div class="detail-grid">
      <div data-detail-meta="population"><span>População da execução</span>${integer(r.n)} ${r.task === "prosa_pt" ? "conversas" : "itens"}</div>
      <div data-detail-meta="denominator"><span>Denominador da nota principal</span>${integer(r.score_denominator)} ${r.denominator_unit || (r.task === "sob" ? "textos" : r.task === "culturalbench" ? "grupos" : r.task === "prosa_pt" ? "rubricas válidas" : "itens")}</div>
      <div data-detail-meta="judge"><span>Correção / juiz registrado</span>${esc(r.judge || "Correção automática / classificador nativo")}${r.judge_effort ? " · " + esc(r.judge_effort) : ""}</div>
      <div data-detail-meta="origin"><span>Origem</span>${sourceName(r.source_kind)}</div>
      <div data-detail-meta="status"><span>Estado do resultado</span>${esc(resultState)}</div>
      <div data-detail-meta="average"><span>Participação nas médias</span>${esc(averageState)}</div>
    </div>
    <details data-card-section="secondary"><summary>Métricas complementares</summary>${secondary.length ? `<table class="metric-breakdown"><tbody>${secondary.map(([key, name]) => `<tr><td>${name}</td><td>${number(metric[key], Number.isInteger(metric[key]) ? 0 : 2)}</td></tr>`).join("")}</tbody></table>` : '<p class="small muted">Nenhuma métrica complementar registrada neste resumo.</p>'}</details>
    <details data-card-section="observations"><summary>Observações da execução</summary>${observations.length ? `<ul>${observations.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : '<p class="small muted">Nenhuma observação adicional registrada.</p>'}</details>
    <details data-card-section="protocol"><summary>Cálculo e protocolo</summary>${safetyCalculation(r)}<p class="small muted">${r.comparison_key ? "Identidade documentada. Comparação automática exige mesma identidade e mesmo modo." : "Compatibilidade não estabelecida neste snapshot; a nota não entra nas contagens de resultados favoráveis."}</p><pre>${json({ protocol_id: r.protocol_id, scorer_variant: r.scorer_variant, scorer_overrides: r.scorer_overrides, judge_route: r.judge_route, comparison_key: r.comparison_key })}</pre></details>
    <details data-card-section="parameters"><summary>Parâmetros de inferência registrados</summary><pre>${json(Object.keys(r.profile).length ? r.profile : { status: "Receita completa não disponível para esta geração legada" })}</pre></details>
    <details data-card-section="cost"><summary>Custos disponíveis e cobertura</summary><p class="small muted">${cost.length ? cost.join(" + ") : "Custo não consolidado nesta fonte."} · Estimativa registrada do juiz, sem GPUs; não representa uma fatura completa da campanha.</p><pre>${json(r.cost)}</pre></details>
    <details data-card-section="metrics"><summary>Métricas completas do corretor</summary><pre>${json(metric)}</pre></details>
    <details data-card-section="record"><summary>Registro usado na tabela</summary><pre>${json({id:r.id,model_id:r.model_id,mode:r.mode,benchmark:r.task,score:r.score,denominator:r.score_denominator,status:r.status,updated_at:r.as_of})}</pre></details>
    <div class="head-actions"><a class="btn" href="${safeLink(r.source.url)}" target="_blank" rel="noopener noreferrer">Fonte no GitHub ↗</a><a class="btn" href="${safeLink(b.protocol_url)}" target="_blank" rel="noopener noreferrer">Protocolo ↗</a><button class="btn primary" data-download-result="${esc(r.id)}">Baixar registro ↓</button></div>`;
  if (r.reported_evidence) $("#detail-content").insertAdjacentHTML("beforeend", `<details><summary>Conferência com a tabela fornecida</summary><p>As observações da tabela de referência foram preservadas. Valores novos com origem nessa tabela não recebem protocolo, tamanho de amostra ou auditoria presumidos.</p><pre>${json(r.reported_evidence)}</pre></details>`);
  $("#detail-dialog").showModal();
}
function missingDetail(id) {
  const [model, mode, task] = id.split(":"),
    partial = D.partials.find((p) => p.id === id);
  $("#detail-content").innerHTML =
    `<div class="eyebrow">Cobertura da avaliação</div><h2 id="detail-title">${esc(models.get(model).name)} · ${esc(benchmarks.get(task).name)}</h2><p>${modeName(mode)} · <strong>${partial ? (partial.status_label || "Sem nota final validada") : "Sem resultado neste snapshot"}</strong></p><div class="callout">Esta célula não é zero e não entra nas comparações.</div>${partial ? `<p class="small muted">Registro da fonte, preservado:</p><pre>${json(partial.details)}</pre><a href="${safeLink(partial.source.url)}" target="_blank" rel="noopener noreferrer">Conferir fonte ↗</a>` : '<p class="small muted">Ausência neste snapshot não permite concluir que o modelo falhou no benchmark.</p>'}`;
  $("#detail-dialog").showModal();
}

function validateCasePack(pack) {
  if (
    pack.schema_version !== 1 ||
    !Array.isArray(pack.cases) ||
    !pack.cases.length
  )
    throw Error(
      "Pacote inválido: esperado schema_version=1 e uma lista não vazia de casos.",
    );
  const ids = new Set();
  for (const c of pack.cases) {
    if (
      !benchmarks.has(c.benchmark_id) ||
      typeof c.case_id !== "string" ||
      !c.protocol_id ||
      !/^[0-9a-f]{64}$/.test(c.input_sha256 || "")
    )
      throw Error("Caso sem benchmark, protocolo, ID ou hash de input válido.");
    const key = [c.benchmark_id, c.protocol_id, c.input_sha256, c.case_id].join(
      ":",
    );
    if (ids.has(key)) throw Error("IDs de casos duplicados.");
    ids.add(key);
    if (typeof c.question !== "string" || !Array.isArray(c.responses))
      throw Error("Pergunta ou respostas inválidas.");
    const variants = new Set();
    for (const r of c.responses) {
      const v = `${r.model_id}:${r.mode}`;
      if (
        !allVariants().some((x) => x.id === v) ||
        variants.has(v) ||
        typeof r.final !== "string" ||
        (r.score !== null && !Number.isFinite(r.score))
      )
        throw Error(
          "Resposta sem modelo/modo conhecido, final textual ou nota numérica; ou duplicada.",
        );
      variants.add(v);
    }
  }
  return pack;
}
function caseIdentity(c) {
  return [c.benchmark_id, c.protocol_id, c.input_sha256, c.case_id].join(":");
}
function readableAnswer(text) {
  // Deliberately small presentation subset: no HTML, links, embeds or executable content.
  return esc(text)
    .replace(/^#{1,6}\s+(.+)$/gm, "<strong>$1</strong>")
    .replace(/\*\*([^\n]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .trim();
}
function researchJudgmentView(c, r) {
  const parsed = r.judgment.text ? JSON.parse(r.judgment.text) : {};
  const policy = parsed.politica_resposta_vazia;
  if (r.judgment.kind === "generation_failure" || policy) {
    const reasons = {
      context_overflow: "A entrada ultrapassou a janela de contexto do modelo.",
      input_byte_budget: "A conversa excedeu o orçamento de entrada configurado.",
      output_length: "A saída atingiu o limite e não foi aceita como resposta final pelo runner.",
      no_final_answer: "O limite de saída foi atingido sem resposta final.",
      "empty-final-after-three-attempts-zero-v1": "Três tentativas do mesmo pedido terminaram sem resposta final.",
      "native-context-exhausted-no-final-zero-v1": "A geração esgotou a janela de contexto sem resposta final.",
    };
    const reason = reasons[r.judgment.reason || policy?.politica];
    return `<div class="callout"><strong>Nota zero pela política de geração.</strong><p>${esc(reason || "Falha de geração registrada.")}</p><p>O caso permanece no denominador. Não houve julgamento por rubrica neste caso.</p></div>${policy ? `<details><summary>Registro da política aplicada</summary><pre>${json(policy)}</pre></details>` : ""}`;
  }
  const votes = new Map(parsed.criterios.map(v => [v.indice, v.veredito]));
  return `<p class="small muted">Juiz: ${esc(r.judgment.judge)}. Critérios negativos detectam erros, não acertos.</p><div class="criteria-list">${c.criteria.map((criterion, i) => {
    const vote = votes.get(i), hit = vote.criterion_status === "MET" || vote.score === 1;
    const negative = criterion.weight < 0, good = negative ? !hit : hit;
    return `<div class="criterion"><span class="pill ${good ? "" : "warn"}">${negative ? (hit ? "Erro detectado" : "Erro não detectado") : hit ? "Atendido" : "Não atendido"}</span><p translate="no"><strong>${esc(criterion.text)}</strong></p><p translate="no">${esc(vote.explanation || vote.reasoning || "")}</p>${vote.evidence_quotes?.length ? `<details><summary>Trechos citados pelo juiz</summary>${vote.evidence_quotes.map(q => `<blockquote translate="no">${esc(q)}</blockquote>`).join("")}</details>` : ""}<small>Peso ${criterion.weight > 0 ? "+" : ""}${esc(criterion.weight)} · <span translate="no">${esc(criterion.type)}</span></small></div>`;
  }).join("")}</div><details><summary>Julgamento original preservado</summary><pre>${esc(r.judgment.text)}</pre></details>`;
}
function judgmentView(c, r) {
  if (!r.judgment)
    return '<p class="small muted">Este registro não contém a correção detalhada.</p>';
  if (["research", "generation_failure"].includes(r.judgment.kind)) return researchJudgmentView(c, r);
  if (r.judgment.kind === "native") {
    let readable = r.judgment.text;
    try {
      readable = JSON.stringify(JSON.parse(readable), (key, value) =>
        key === "encrypted_content" ? "[conteúdo cifrado omitido da exibição]" : value, 2);
    } catch { /* Non-JSON native verdicts remain verbatim. */ }
    return `<p class="small muted">${r.judgment.judge ? `Juiz: ${esc(r.judgment.judge)}.` : "Correção automática registrada."} ${esc(r.judgment.note || "")}</p><pre class="native-correction">${esc(readable)}</pre>`;
  }
  let parsed = {};
  try {
    let text = r.judgment.text.trim();
    if (text.startsWith("```"))
      text = text
        .split("\n")
        .slice(1)
        .join("\n")
        .replace(/```\s*$/, "")
        .trim();
    parsed = JSON.parse(text);
  } catch {
    /* Original judgment remains available below. */
  }
  const evidence = new Map(
    (Array.isArray(parsed.criterios) ? parsed.criterios : []).map((x) => [
      String(x.i),
      x.evidencia,
    ]),
  );
  return `<p class="small muted">Juiz: ${esc(r.judgment.judge)}. Critérios negativos detectam erros, não acertos.</p><div class="criteria-list">${(
    c.criteria || []
  )
    .map((criterion, i) => {
      const hit = r.judgment.hits?.[String(i)],
        negative = criterion.weight < 0,
        good = negative ? !hit : hit;
      return `<div class="criterion"><span class="pill ${good ? "" : "warn"}">${negative ? (hit ? "Erro detectado" : "Erro não detectado") : hit ? "Atendido" : "Não atendido"}</span><p translate="no"><strong>${esc(criterion.text)}</strong></p><p${evidence.get(String(i)) ? ' translate="no"' : ""}>${esc(evidence.get(String(i)) || "Evidência textual não disponível nesta projeção.")}</p><small>Peso ${criterion.weight > 0 ? "+" : ""}${esc(criterion.weight)} · ${esc(criterion.type)}</small></div>`;
    })
    .join(
      "",
    )}</div>${parsed.comentario ? `<p class="small muted" translate="no">${esc(parsed.comentario)}</p>` : ""}<details><summary>Julgamento original preservado</summary><pre>${esc(r.judgment.text)}</pre></details>`;
}
function exportCSV() {
  const header = [
    "modelo",
    "modo",
    "benchmark",
    "nota",
    "denominador",
    "direcao",
    "origem",
    "protocolo",
    "grupo_comparavel",
    "ressalvas",
    "taxa_dano_original",
    "denominador_taxa_original",
    "normalizacao",
    "estouros_contexto_zerados",
    "elegivel_para_media",
    "motivo_sem_nota",
    "auditoria_json",
  ];
  const rows = activeRecords().map((r) => [
    models.get(r.model_id).name,
    r.mode,
    benchmarks.get(r.task).name,
    r.capability_gate ? null : r.score,
    r.score_denominator,
    r.direction,
    sourceName(r.source_kind),
    r.protocol_id,
    r.comparison_key,
    r.flags.join("; "),
    r.score_normalization?.native_score,
    r.score_normalization?.native_denominator,
    r.score_normalization?.policy_id,
    r.score_normalization?.context_failures,
    !r.averages_exclusion && ["final", "reported"].includes(r.status) && benchmarks.get(r.task).primary_metric !== false,
    r.averages_exclusion?.label,
    JSON.stringify(r.audit_summary),
  ]);
  const cell = (v) => {
    let s = String(v ?? "");
    if (/^[=+@-]/.test(s) && typeof v !== "number") s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  };
  download(
    "resultados-modelos-benchmarks.csv",
    "\ufeff" +
      [header, ...rows].map((row) => row.map(cell).join(",")).join("\r\n"),
    "text/csv;charset=utf-8",
  );
}
function render() {
  const views = {
    inicio: renderHome,
    descobrir: renderExperience,
    panorama: renderPanorama,
    usos: renderUses,
    comparar: renderCompare,
    casos: renderExperience,
    modelos: renderModels,
    metodo: renderMethod,
  };
  disposeSky();
  app.innerHTML = views[state.view]();
  document.body.classList.toggle("is-observatory-home", state.view === "inicio");
  if (state.view === "inicio") initSky();
  $$("#navigation a").forEach((a) => {
    if (a.dataset.view === (state.view === "casos" ? "descobrir" : state.view)) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title = i18n.t({ inicio: "Início", descobrir: "Respostas", panorama: "Resultados", usos: "Usos", comparar: "Comparar", casos: "Respostas", modelos: "Modelos", metodo: "Como avaliamos" }[state.view]) + " · " + i18n.t("Observatório Maritaca");
  if (["descobrir", "casos"].includes(state.view)) queueMicrotask(loadExperience);
  if (state.view === "modelos" && state.focusModel) queueMicrotask(() => document.getElementById(`model-card-${state.focusModel}`)?.scrollIntoView({block:"center",behavior:"instant"}));
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest(
    "[data-result],[data-missing],[data-sort],[data-mode],[data-category],[data-action],[data-use],[data-compare-model],[data-download-result],[data-scroll]",
  );
  if (!target || !D) return;
  if (target.dataset.result) {
    detail(target.dataset.result);
    return;
  }
  if (target.dataset.missing) {
    missingDetail(target.dataset.missing);
    return;
  }
  if (target.dataset.sort) {
    state.sortAsc = state.sort === target.dataset.sort ? !state.sortAsc : false;
    state.sort = target.dataset.sort;
    $("#matrix").innerHTML = renderMatrix();
    return;
  }
  if (target.dataset.mode) {
    state.mode = target.dataset.mode;
    writeHash();
    render();
    return;
  }
  if (target.dataset.category) {
    state.category = target.dataset.category;
    state.use = null;
    writeHash();
    render();
    return;
  }
  if (target.dataset.use) {
    navigate("panorama", {
      category: "all",
      query: "",
      use: target.dataset.use,
    });
    return;
  }
  if (target.dataset.compareModel) {
    const m = models.get(target.dataset.compareModel),
      mode = m.modes.includes("instruct") ? "instruct" : "thinking";
    state.size = inSizeGroup(m, "up_to_4b") ? "up_to_4b" : "all";
    navigate("comparar", {
      a: `candidate:${mode}`,
      b: `${m.id === "candidate" ? "qwen35-4b" : m.id}:${mode}`,
    });
    return;
  }
  if (target.dataset.downloadResult) {
    download(
      "resultado-" +
        target.dataset.downloadResult.replaceAll(":", "-") +
        ".json",
      JSON.stringify(records.get(target.dataset.downloadResult), null, 2),
    );
    return;
  }
  if (target.dataset.scroll) {
    event.preventDefault();
    document.getElementById(target.dataset.scroll)?.scrollIntoView();
    return;
  }
  const action = target.dataset.action;
  if (action === "export-csv") exportCSV();
  if (action === "clear-use") {
    state.use = null;
    writeHash();
    render();
  }
  if (action === "export-json")
    download("observatorio-agregados.json", JSON.stringify(D, null, 2));
  if (action === "share") {
    try {
      await navigator.clipboard.writeText(location.href);
      toast("Link deste recorte copiado.");
    } catch {
      toast("Copie o endereço desta página para compartilhar o recorte.");
    }
  }
  if (action === "select-all" || action === "select-none") {
    state.selected = new Set(action === "select-all" ? models.keys() : []);
    writeHash();
    render();
  }
});
document.addEventListener("keydown", (event) => {
  if (
    (event.key === "Enter" || event.key === " ") &&
    event.target.matches(".plot-point")
  ) {
    event.preventDefault();
    detail(event.target.dataset.result);
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "benchmark-search") {
    state.query = event.target.value;
    writeHash();
    $("#matrix").innerHTML = renderMatrix();
  }
});
document.addEventListener("change", async (event) => {
  const t = event.target;
  if (t.dataset.model) {
    if (t.checked) state.selected.add(t.dataset.model);
    else state.selected.delete(t.dataset.model);
    writeHash();
    if (state.view === "comparar") {
      const open = $(".model-filter")?.open; render(); if (open) $(".model-filter").open=true;
    } else {
      $("#matrix").innerHTML = renderMatrix();
      $(".model-filter summary span").textContent = sizeModels().filter((m) => state.selected.has(m.id)).length;
    }
  }
  if (t.id === "compare-a" || t.id === "compare-b") {
    state[t.id.slice(-1)] = t.value;
    writeHash();
    render();
  }
  if (t.id === "compare-benchmark" || t.id === "compare-category") {
    if (t.id === "compare-benchmark") state.scatter=t.value; else {
      state.category=t.value;
      if (!matchesCategory(benchmarks.get(state.scatter),state.category)) state.scatter=D.benchmarks.find(b=>matchesCategory(b,state.category)).id;
    }
    writeHash(); render();
  }

});
$(".close-dialog").addEventListener("click", () => $("#detail-dialog").close());
$("#detail-dialog").addEventListener("click", (event) => {
  if (event.target === $("#detail-dialog")) {
    const rect = event.target.getBoundingClientRect();
    if (
      event.clientX < rect.left ||
      event.clientX > rect.right ||
      event.clientY < rect.top ||
      event.clientY > rect.bottom
    )
      event.target.close();
  }
});
function restoreNavigation() {
  if (D) {
    readHash();
    render();
    window.scrollTo({ top: 0, behavior: "instant" });
  }
}
window.addEventListener("hashchange", restoreNavigation);
window.addEventListener("popstate", restoreNavigation);

async function start() {
  app = $("#app");
  try {
    const response = await fetch("data.json");
    if (!response.ok) throw Error(`Dados indisponíveis (${response.status})`);
    D = await response.json();
    models = new Map(D.models.map((m) => [m.id, m]));
    benchmarks = new Map(D.benchmarks.map((b) => [b.id, b]));
    records = new Map(D.records.map((r) => [r.id, r]));
    initializeExperienceTasks();
    readHash();
    render();
    $("#snapshot-date").textContent =
      `Dados de ${snapshotDate()}`;
  } catch (error) {
    app.innerHTML = `<div class="page-intro"><h1>Não foi possível abrir os resultados.</h1><p>${esc(error.message)}</p><p>Confira se o build foi concluído e se esta pasta está sendo servida por HTTP.</p></div>`;
  }
}
window.addEventListener("observatory-languagechange", () => {
  if (!D) return;
  const scroll = {left:scrollX, top:scrollY};
  render();
  $("#snapshot-date").textContent = `${i18n.t("Dados de")} ${snapshotDate()}`;
  window.scrollTo({...scroll, behavior:"instant"});
});
start();
