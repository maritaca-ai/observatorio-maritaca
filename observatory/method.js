"use strict";

// Documentation and recorded recipes only; no inference or external requests.
const methodState = { section:"benchmarks", model:"candidate", task:"capitu", category:"all", query:"" };
const methodSections = [["benchmarks","Benchmarks"],["models","Modelos"],["parameters","Parâmetros"],["scoring","Pontuação"]];
function readMethodHash(params) {
  methodState.section = methodSections.some(([id])=>id===params.get("section")) ? params.get("section") : "benchmarks";
  methodState.model = models.get(params.get("model"))?.result_count ? params.get("model") : "candidate";
  methodState.task = benchmarks.has(params.get("mtask")) ? params.get("mtask") : "capitu";
  methodState.category = D.categories[params.get("mc")] ? params.get("mc") : "all";
  methodState.query = params.get("mq") || "";
}
function writeMethodHash(params) {
  params.set("section",methodState.section);
  params.set("model",methodState.model);
  params.set("mtask",methodState.task);
  if (methodState.category !== "all") params.set("mc",methodState.category);
  if (methodState.query) params.set("mq",methodState.query);
}
function benchmarkReference(id) {
  return D.references.benchmarks[D.references.benchmark_aliases[id] || id];
}
function referenceLink(ref) {
  return `<a href="${safeLink(ref.url)}" target="_blank" rel="noopener noreferrer">${esc(ref.label)} ↗${ref.title ? `<span>${esc(ref.title)}</span>` : ""}</a>`;
}
function renderMethodBenchmarks() {
  const list = D.benchmarks.filter(b=>matchesCategory(b,methodState.category) &&
    `${b.name} ${b.description} ${b.categories.map(c=>D.categories[c]).join(" ")} ${i18n.english(b.name)} ${i18n.english(b.description)} ${b.categories.map(c=>i18n.english(D.categories[c])).join(" ")}`.toLocaleLowerCase("pt-BR").includes(methodState.query.toLocaleLowerCase("pt-BR")));
  return `<p class="method-count" role="status">${list.length} avaliações</p><div class="method-cards">${list.map(b=>{
    const ref=benchmarkReference(b.id);
    return `<article class="method-card" data-method-benchmark="${esc(b.id)}"><div class="method-card-label">${esc(b.categories.map(c=>D.categories[c]).join(" · "))} · ${esc(b.language)}</div><h2>${esc(b.name)}</h2><p>${esc(i18n.t(b.description))}</p><dl class="method-facts"><div><dt>População</dt><dd>${esc(i18n.t(b.population))}</dd></div><div><dt>Métrica exibida</dt><dd>${esc(i18n.t(b.metric))}</dd></div></dl><details><summary>Correção e referências</summary><p>${esc(ref.correction)}</p>${ref.note ? `<p>${esc(ref.note)}</p>` : ""}<div class="method-references">${ref.papers.map(referenceLink).join("")}${ref.sources.map(referenceLink).join("")}${referenceLink({label:"Protocolo desta campanha",url:b.protocol_url})}</div></details><button class="text-button method-card-action" data-method-task="${esc(b.id)}">Parâmetros usados →</button></article>`;
  }).join("") || '<div class="empty">Nenhum benchmark encontrado.</div>'}</div>`;
}
function renderMethodModels() {
  return `<div class="method-cards">${D.models.filter(m=>m.result_count).map(m=>{
    const ref=D.references.models[m.id];
    return `<article class="method-card" data-method-model-card="${esc(m.id)}"><div class="method-card-label">${esc(m.organization)}</div><h2>${modelName(m)}</h2><p>${esc(i18n.t(m.size_label))} · ${esc(m.lineage || m.architecture)}</p><div class="method-references">${ref.papers.map(referenceLink).join("")}${m.model_card ? referenceLink({label:m.id === "tucano" ? "Model card · Thinking" : "Model card · revisão avaliada",url:m.model_card}) : ""}${ref.sources.map(referenceLink).join("")}</div>${ref.note ? `<p class="method-source-note">${esc(ref.note)}</p>` : ""}<button class="text-button method-card-action" data-method-model="${esc(m.id)}">Parâmetros usados →</button></article>`;
  }).join("")}</div>`;
}
function methodEntry(mode) {
  const id=`${methodState.model}:${mode}:${methodState.task}`;
  return records.get(id) || D.partials.find(p=>p.id===id);
}
function methodValue(value, key) {
  if (value === undefined) return '<span class="method-unrecorded">Não registrado</span>';
  if (key === "max_tokens" && value === null) return 'Sem teto adicional <small>Limitado pelo contexto do modelo</small>';
  if (value === null) return 'Não definido';
  if (typeof value === "boolean") return value ? "Sim" : "Não";
  if (["context_length","max_tokens"].includes(key) && typeof value === "number") return `${integer(value)} tokens`;
  return typeof value === "object" ? `<code>${esc(JSON.stringify(value))}</code>` : esc(String(value));
}
function parameterValue(entry, path) {
  return path.split(".").reduce((v,k)=>v?.[k],entry?.profile || {});
}
function parameterRows(modes, fields) {
  return fields.map(([key,label])=>`<tr><th scope="row">${esc(label)}<code>${esc(key)}</code></th>${modes.map(mode=>`<td data-parameter="${esc(key)}" data-parameter-mode="${mode}">${methodValue(parameterValue(methodEntry(mode),key),key)}</td>`).join("")}</tr>`).join("");
}
function renderMethodParameters() {
  const modes=state.mode === "all" ? ["thinking","instruct"] : [state.mode];
  const b=benchmarks.get(methodState.task), m=models.get(methodState.model);
  const primary=[['enable_thinking','Thinking solicitado'],['context_length','Limite de contexto'],['max_tokens','Limite de saída'],['reasoning_effort','Esforço de raciocínio'],['sampling.temperature','Temperatura'],['sampling.top_p','Top-p'],['sampling.top_k','Top-k'],['sampling.min_p','Min-p'],['sampling.presence_penalty','Penalidade de presença'],['sampling.repetition_penalty','Penalidade de repetição']];
  const technical=[['precision','Precisão'],['mm_processor_kwargs','Pré-processamento da imagem'],['reasoning_parser','Parser de raciocínio'],['tool_parser','Parser de ferramentas'],['chat_template_kwargs','Opções do template'],['stop','Sequências de parada'],['history_encoding','Codificação do histórico'],['history_content_policy','Conteúdo do histórico'],['history_policy','Política de histórico'],['reasoning_history_policy','Raciocínio no histórico'],['transport_policy','Transporte'],['model','Checkpoint']];
  const heading=`<thead><tr><th scope="col">Parâmetro</th>${modes.map(mode=>`<th scope="col">${modeName(mode)}</th>`).join("")}</tr></thead>`;
  return `<div class="method-parameter-controls"><label>Modelo<select id="method-model">${D.models.filter(m=>m.result_count).map(m=>`<option value="${esc(m.id)}" ${methodState.model===m.id?"selected":""}>${optionName(m)}</option>`).join("")}</select></label><label>Benchmark<select id="method-task">${D.benchmarks.map(b=>`<option value="${esc(b.id)}" ${methodState.task===b.id?"selected":""}>${esc(b.name)}</option>`).join("")}</select></label>${modeControl()}</div>
  <div class="method-parameter-heading"><h2>${modelName(m)} <span>· ${esc(b.name)}</span></h2><p>Receita registrada para cada resultado.</p></div>
  <div class="method-table-scroll"><table class="method-parameter-table">${heading}<tbody><tr><th scope="row">Resultado</th>${modes.map(mode=>{
    const r=methodEntry(mode);
    return `<td>${r ? scoreCell(Number.isFinite(r.score)?r:null,false,r.id) : '<span class="method-unrecorded">Sem avaliação registrada</span>'}</td>`;
  }).join("")}</tr>${parameterRows(modes,primary)}</tbody></table></div>
  <details class="method-technical"><summary>Template, parsers e histórico</summary><div class="method-table-scroll"><table class="method-parameter-table">${heading}<tbody>${parameterRows(modes,technical)}</tbody></table></div></details>
  <div class="method-judges"><h3>Correção</h3><p>${esc(benchmarkReference(b.id).correction)}</p><div class="method-judge-grid">${modes.map(mode=>{
    const r=methodEntry(mode), judge=r?.judge;
    return `<article><h4>${modeName(mode)}</h4><dl><div><dt>Juiz registrado</dt><dd>${judge ? esc(judge) : Number.isFinite(r?.score) && !['arena_hard_v2','prosa_pt','lumen_pt','bluex_v2','marca_public','browsecomp_plus','draco','researchrubrics','oab_bench','oab_bench_full','magis_bench','conduta_bench'].includes(b.id) ? (b.id==='harmbench'?'Classificador nativo HarmBench':'Correção determinística') : 'Não registrado'}</dd></div>${judge ? `<div><dt>Esforço do juiz</dt><dd>${methodValue(r.judge_effort)}</dd></div>${r.judge_route ? `<div><dt>Rota registrada</dt><dd>${methodValue(r.judge_route)}</dd></div>` : ""}` : ""}</dl>${r ? `<details><summary>Registro e receita completos</summary>${referenceLink({label:"Fonte deste resultado",url:r.source.url})}<pre>${json({profile:r.profile || {}, protocol_id:r.protocol_id, judge:r.judge, judge_effort:r.judge_effort, scorer_variant:r.scorer_variant, scorer_overrides:r.scorer_overrides, generation:r.generation_parameters, research:r.research_parameters, judge_parameters:r.judge_parameters})}</pre></details>` : ""}</article>`;
  }).join("")}</div></div>`;
}
function renderMethodScoring() {
  return `<div class="method-scoring"><article><h2>Resposta final</h2><p>Só a resposta final recebe nota. Thinking e Instruct têm resultados e médias separados.</p></article><article><h2>Médias</h2><p>Média aritmética, com peso igual por avaliação primária. O filtro de categoria define os testes incluídos. CAPITU conversas fica fora da média para não duplicar esse benchmark. As amostras de visão entram somente na média da categoria Visão.</p><p>A média total ordena o ranking, do maior para o menor, para todos os modelos e modos selecionados. A cobertura aparece como n/N, inclusive quando parcial. Só fica sem posição quem não tem média no recorte.</p></article><article><h2>Segurança</h2><p>Lumen e HarmBench usam <strong>100 − taxa de dano</strong>, para que notas maiores indiquem melhor resultado. No Lumen, é necessário concluir pelo menos um controle benigno para apresentar uma nota de segurança. Com zero controles concluídos, o resultado fica fora das médias e dos gráficos. Os valores nativos e os controles benignos continuam nos detalhes.</p></article><article><h2>Contexto e falhas</h2><p>Estouro de contexto confirmado vale zero por caso, mantendo o caso no denominador e as demais respostas pontuadas. Julgamentos pendentes e itens não executados continuam sem nota final.</p><p>BrowseComp-Plus divide os acertos por todas as 100 questões selecionadas.</p></article></div><div class="method-records"><h2>Registros da campanha</h2><div class="method-references">${referenceLink({label:"Protocolos e código",url:`https://github.com/maritaca-ai/observatorio-maritaca/tree/main/benchmarks`})}${referenceLink({label:"Revisão do corretor CAPITU",url:"https://github.com/maritaca-ai/observatorio-maritaca/tree/main/verifier"})}${referenceLink({label:"Normalização das métricas de segurança",url:"https://github.com/maritaca-ai/observatorio-maritaca/tree/main/verifier"})}</div><button class="btn" data-action="export-json">Baixar resultados e metadados ↓</button></div>`;
}
function renderMethod() {
  const section=methodState.section;
  return `<div class="method-page"><div class="page-intro compact-intro"><h1>Como avaliamos</h1></div><nav class="method-tabs" aria-label="Documentação das avaliações">${methodSections.map(([id,label])=>`<button data-method-section="${id}" aria-pressed="${section===id}">${label}</button>`).join("")}</nav><section class="method-panel" aria-label="${esc(methodSections.find(([id])=>id===section)[1])}">${section==='benchmarks' ? `<div class="method-search"><input id="method-search" class="search" type="search" placeholder="Buscar benchmark…" aria-label="Buscar na metodologia" value="${esc(methodState.query)}"><select id="method-category" aria-label="Categoria dos benchmarks">${[["all","Todas as categorias"],...Object.entries(D.categories)].map(([id,label])=>`<option value="${id}" ${methodState.category===id?'selected':''}>${esc(label)}</option>`).join("")}</select></div><div id="method-benchmarks">${renderMethodBenchmarks()}</div>` : section==='models' ? renderMethodModels() : section==='parameters' ? renderMethodParameters() : renderMethodScoring()}</section></div>`;
}
document.addEventListener("click",event=>{
  const t=event.target.closest("[data-method-section],[data-method-model],[data-method-task]");
  if (!t || !D) return;
  if (t.dataset.methodSection) methodState.section=t.dataset.methodSection;
  if (t.dataset.methodModel) {methodState.model=t.dataset.methodModel;methodState.section="parameters";}
  if (t.dataset.methodTask) {methodState.task=t.dataset.methodTask;methodState.section="parameters";}
  writeHash();render();
});
document.addEventListener("change",event=>{
  const t=event.target;
  if (!["method-model","method-task","method-category"].includes(t.id)) return;
  methodState[{"method-model":"model","method-task":"task","method-category":"category"}[t.id]]=t.value;
  writeHash();render();
});
document.addEventListener("input",event=>{
  if (event.target.id !== "method-search") return;
  methodState.query=event.target.value;writeHash();
  document.getElementById("method-benchmarks").innerHTML=renderMethodBenchmarks();
});
