"use strict";

// Interaction over preserved evidence. No model requests, synthetic answers or server-side votes.
const experience = {
  tab: "examples", mode: "all", task: "conduta_bench", category: "all",
  a: "candidate", b: "qwen35-4b", query: "", key: null, highlights: false, resultFilter: "all",
  catalog: null, directory: null, loadedTasks: new Set(), blobs: new Map(), caseCategory: "all", caseLimit: 100, cache: new Map(), loading: new Set(), failed: new Set(), catalogState: "idle",
  error: "", accessStatus: null, round: null, sessionVotes: [], local: false, browser: false, focusRound: false,
};
const experienceTasks = {};
function initializeExperienceTasks() {
  for (const b of D.benchmarks) if (D.case_catalog.benchmarks[b.id]) {
    experienceTasks[b.id] = { title:b.name, short:b.name, text:b.description, category:b.category };
  }
  if (!experienceTasks[experience.task]) experience.task=Object.keys(experienceTasks)[0];
}
function readExperienceHash(params) {
  const previousTab = experience.tab;
  experience.tab = state.view === "casos" ? "blind" : ["examples", "blind"].includes(params.get("tab")) ? params.get("tab") : "examples";
  if (experience.tab === "blind" && previousTab !== "blind") { experience.round = null; experience.focusRound = true; }
  experience.mode = ["all", "thinking", "instruct"].includes(params.get("mode")) ? params.get("mode") : "all";
  if (experienceTasks[params.get("task")]) {
    experience.task = params.get("task");
    if (!matchesCategory(benchmarks.get(experience.task), experience.caseCategory)) experience.caseCategory="all";
  }
  for (const side of ["a", "b"]) if (models.has(params.get(side))) experience[side] = params.get(side);
  if (params.has("case")) experience.key = params.get("case");
  if (D.categories[params.get("category")]) experience.category = params.get("category");
  experience.resultFilter = ["different", "a_better", "b_better"].includes(params.get("result")) ? params.get("result") : "all";
  // Preserve previously shared chart links after moving that view to Comparar.
  if (params.get("tab") === "map") {
    state.mode=experience.mode; state.selected=new Set([experience.a,experience.b]);
    state.scatter=experience.task; state.view="comparar"; writeHash();
  }
}
function experienceURL() {
  const p = new URLSearchParams({ tab: experience.tab, mode: experience.mode, size: state.size });
  p.set("task", experience.task);
  if (experience.tab !== "blind") {
    p.set("a", experience.a); p.set("b", experience.b);
    if (experience.tab === "examples" && experience.key) p.set("case", experience.key);
    if (experience.tab === "examples" && experience.resultFilter !== "all") p.set("result", experience.resultFilter);
  }
  history.replaceState(null, "", `#${state.view}?${p}`);
}
const experienceActive = () => ["descobrir", "casos"].includes(state.view);
const experienceModes = () => experience.mode === "all" ? ["thinking", "instruct"] : [experience.mode];
const variantId = (model, mode) => `${model}:${mode}`;
const randomItem = (rows) => rows[Math.floor(Math.random() * rows.length)];
function examplePairs(metadata, filterResult = true) {
  return experienceModes().map(mode => ({mode, pair:[variantId(experience.a,mode),variantId(experience.b,mode)]}))
    .filter(({pair}) => pair.every(v => metadata.variants.includes(v)) &&
      (!filterResult || matchesCasePerformance(metadata, pair, experience.resultFilter)));
}
function catalogPool({ filterPair = true, search = false, filterResult = true } = {}) {
  return (experience.catalog?.cases || []).filter((c) => c.benchmark_id === experience.task &&
    (!filterPair || examplePairs(c, filterResult && experience.tab === "examples").length) &&
    (!search || `${c.title} ${c.case_id}`.toLocaleLowerCase("pt-BR").includes(experience.query.toLocaleLowerCase("pt-BR"))));
}
function availableExampleModels() {
  const variants = new Set(catalogPool({ filterPair: false }).flatMap((c) => c.variants));
  return D.models.filter((m) => inSizeGroup(m) && experienceModes().some(mode => variants.has(variantId(m.id,mode))));
}
function ensureExperienceSelection() {
  if (!experience.catalog) return;
  const available = availableExampleModels();
  if (experience.tab === "examples" && available.length) {
    if (!available.some((m) => m.id === experience.a)) experience.a = available[0].id;
    if (!available.some((m) => m.id === experience.b) || experience.b === experience.a) experience.b = (available.find((m) => m.id !== experience.a) || available[0]).id;
    const pool = catalogPool();
    if (!pool.some((c) => c.key === experience.key)) experience.key = pool[0]?.key || null;
  }
  if (experience.tab === "blind") {
    const round = experience.round;
    const entry = arenaPool().find(({ meta, mode }) => meta.key === round?.key && mode === round?.mode);
    if (!entry || !round.pair.every((v) => entry.variants.includes(v))) newArenaRound();
  }
}
function arenaPool() {
  return catalogPool({ filterPair: false }).flatMap((meta) => experienceModes().map(mode => ({ meta, mode,
    variants: [...new Set(meta.variants)].filter((v) => v.endsWith(`:${mode}`) && inSizeGroup(models.get(v.split(":")[0]))),
  }))).filter(({ variants }) => variants.length >= 2);
}
function newArenaRound() {
  const eligible = arenaPool();
  const unseen = eligible.filter(({ meta }) => meta.key !== experience.round?.key);
  const pool = unseen.length ? unseen : eligible;
  if (!pool.length) { experience.round = null; return; }
  const { meta, variants, mode } = randomItem(pool);
  const a = randomItem(variants), b = randomItem(variants.filter((v) => v !== a));
  experience.round = { id: crypto.randomUUID(), key: meta.key, pair: [a, b], task: experience.task, mode, size: state.size, revealed: false, vote: null };
}
function selectedExperienceMeta() {
  const key = experience.tab === "blind" ? experience.round?.key : experience.key;
  return experience.catalog?.cases.find((c) => c.key === key);
}
async function digestText(text) {
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function validExperienceCatalog(value) {
  if (![1,2].includes(value.schema_version) || !Array.isArray(value.cases) || !value.cases.length || value.cases.length > 100000) throw Error("Índice de casos inválido.");
  const keys = new Set();
  for (const c of value.cases) {
    if (!/^[a-f0-9]{64}$/.test(c.key) || keys.has(c.key) || !benchmarks.has(c.benchmark_id) ||
      typeof c.case_id !== "string" || typeof c.title !== "string" || !Array.isArray(c.variants) ||
      !(c.file === `cases/${c.key}.json` || /^cases\/chunks\/[a-f0-9]{64}\.json(?:\.gz)?$/.test(c.file)) || !/^[a-f0-9]{64}$/.test(c.sha256) ||
      !c.variants.every((v) => allVariants().some((x) => x.id === v))) throw Error("Identidade dos casos inválida.");
    keys.add(c.key);
    if (c.performance && (Object.keys(c.performance).some(v=>!c.variants.includes(v)) ||
      Object.values(c.performance).some(v=>v!==null && !Number.isFinite(v)))) throw Error("Metadados de desempenho inválidos.");
  }
  return value;
}
async function fetchExperienceText(file, depth = 0) {
  if (depth > 1) throw Error("Referência de entrada inválida.");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const r = await fetch(file, { credentials: "same-origin", cache: "no-store", signal: controller.signal });
    if (!r.ok) {
      const error = Error(`Não foi possível carregar as respostas (${r.status}).`);
      error.status = r.status;
      throw error;
    }
    if (file.endsWith(".gz")) {
      // Some static hosts apply Content-Encoding and fetch already decompresses.
      const bytes = new Uint8Array(await r.arrayBuffer());
      const text = bytes[0] === 0x1f && bytes[1] === 0x8b
        ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text()
        : new TextDecoder().decode(bytes);
      if (!text.startsWith('{"_observatory_delta_v1":true,')) return text;
      const delta = JSON.parse(text);
      if (!/^cases\/blobs\/[a-f0-9]{64}\.json\.gz$/.test(delta.base?.file) ||
          ![delta.prefix,delta.suffix].every(n=>Number.isSafeInteger(n)&&n>=0)) throw Error("Referência de entrada inválida.");
      const baseText = await fetchExperienceText(delta.base.file, depth+1);
      if (await digestText(baseText) !== delta.base.sha256) throw Error("A entrada-base não corresponde ao registro.");
      const base = new TextEncoder().encode(baseText), middle = Uint8Array.from(atob(delta.middle), c=>c.charCodeAt(0));
      if (delta.prefix+delta.suffix > base.length) throw Error("Recorte de entrada inválido.");
      const reconstructed = new Uint8Array(delta.prefix+middle.length+delta.suffix);
      reconstructed.set(base.subarray(0,delta.prefix));
      reconstructed.set(middle,delta.prefix);
      reconstructed.set(base.subarray(base.length-delta.suffix),delta.prefix+middle.length);
      return new TextDecoder("utf-8",{fatal:true}).decode(reconstructed);
    }
    return await r.text();
  } catch (error) {
    if (error.name === "AbortError") throw Error("A conexão demorou demais. Tente carregar novamente.");
    throw error;
  } finally { clearTimeout(timeout); }
}
function experienceSignInURL() {
  const returnTo = `${location.pathname}${location.search}${location.hash}`;
  const endpoint = D.authentication?.mode === "password" ? "/login" : "/signin-with-chatgpt";
  return `${endpoint}?return_to=${encodeURIComponent(returnTo.startsWith("//") ? "/" : returnTo)}`;
}
function renderExperienceAccess() {
  const expired = experience.accessStatus === 401;
  if (D.authentication?.mode === "static") return `<div class="experience-access" role="alert"><h2>Não foi possível abrir as respostas</h2><p>O servidor recusou o acesso ao arquivo (${experience.accessStatus}).</p><button class="btn" data-experience="retry">Tentar novamente</button></div>`;
  if (D.authentication?.mode === "password") return `<div class="experience-access" role="alert"><span class="eyebrow">Acesso privado</span><h2>Entre novamente para abrir as respostas</h2><p>A sessão expirou ou não pôde ser confirmada. Use a senha compartilhada para voltar a esta comparação.</p><div class="access-actions"><a class="btn primary" href="${esc(experienceSignInURL())}" target="_top">Entrar com a senha →</a><button class="btn" data-experience="retry">Tentar novamente</button></div></div>`;
  return `<div class="experience-access" role="alert"><span class="eyebrow">Acesso privado</span><h2>${expired ? "Entre novamente para abrir as respostas" : "Confira a conta usada para entrar"}</h2><p>${expired ? "O site não conseguiu confirmar sua sessão ao carregar os casos. Entre com sua conta autorizada para continuar nesta comparação." : "O acesso às respostas foi recusado. Entre com uma das contas autorizadas para este observatório."}</p><div class="access-actions"><a class="btn primary" href="${esc(experienceSignInURL())}" target="_top">Continuar com minha conta →</a><button class="btn" data-experience="retry">Tentar novamente</button></div></div>`;
}
function focusExperienceRound() {
  if (!experience.focusRound || !experienceActive()) return;
  const question = document.querySelector(".question-sheet");
  if (!question) return;
  experience.focusRound = false;
  question.focus({ preventScroll: true });
  question.scrollIntoView({ block: "start", behavior: "instant" });
}
function updateArenaDock() {
  const dock = document.querySelector(".arena-dock"), answers = document.querySelector(".experience-answers");
  // Do not cover the question with voting controls before the answers are in view.
  if (dock && answers) dock.classList.toggle("is-pinned", answers.getBoundingClientRect().top < innerHeight / 2);
}
window.addEventListener("scroll", updateArenaDock, { passive: true });
window.addEventListener("resize", updateArenaDock, { passive: true });
async function loadExperience() {
  if (!experienceActive()) return;
  updateArenaDock();
  if (experience.catalogState === "loading") return;
  const needsIndex = experience.directory && !experience.loadedTasks.has(experience.task);
  if (experience.catalogState === "idle" || (experience.catalogState === "ready" && needsIndex)) {
    experience.catalogState = "loading";
    const requestedTask=experience.task;
    try {
      if (!experience.catalog || !experience.directory && !experience.local) {
        const directoryText=await fetchExperienceText("cases/index.json");
        if (D.case_catalog.sha256 && await digestText(directoryText)!==D.case_catalog.sha256) throw Error("O catálogo de casos não corresponde ao manifesto.");
        const value=JSON.parse(directoryText);
        if (value.schema_version===2) {
          if (!Array.isArray(value.benchmarks) || value.benchmarks.some(b=>!experienceTasks[b.benchmark_id] || !/^cases\/indexes\/[a-f0-9]{64}\.json(?:\.gz)?$/.test(b.file) || !/^[a-f0-9]{64}$/.test(b.sha256))) throw Error("Índice de benchmarks inválido.");
          experience.directory=value; experience.catalog={schema_version:2,cases:[]};
        } else experience.catalog=validExperienceCatalog(value);
      }
      if (experience.directory && !experience.loadedTasks.has(requestedTask)) {
        const entry=experience.directory.benchmarks.find(b=>b.benchmark_id===requestedTask);
        if (!entry) throw Error("As respostas deste benchmark ainda não foram integradas.");
        const raw=await fetchExperienceText(entry.file);
        if (await digestText(raw)!==entry.sha256) throw Error("O índice não corresponde ao hash registrado.");
        const index=validExperienceCatalog(JSON.parse(raw));
        if (index.cases.length!==entry.cases || index.cases.some(c=>c.benchmark_id!==requestedTask)) throw Error("População do índice divergente.");
        experience.catalog.cases.push(...index.cases);experience.loadedTasks.add(requestedTask);
      }
      experience.catalogState="ready";experience.error="";experience.accessStatus=null;
      ensureExperienceSelection();
      if (experienceActive()) render();
    } catch(error) {
      experience.catalogState=error.status===404 ? "unavailable" : "error";
      experience.error=error.message;experience.accessStatus=error.status;
      if (experienceActive()) render();return;
    }
  }
  ensureExperienceSelection();
  const meta = selectedExperienceMeta();
  if (meta && experience.cache.has(meta.key)) { focusExperienceRound(); updateArenaDock(); }
  if (!meta || experience.cache.has(meta.key) || experience.loading.has(meta.key) || experience.failed.has(meta.key) || experience.catalogState !== "ready") return;
  experience.loading.add(meta.key);
  try {
    const text = await fetchExperienceText(meta.file);
    if (await digestText(text) !== meta.sha256) throw Error("O conteúdo do caso não corresponde ao hash registrado.");
    const parsed=JSON.parse(text),pack=validateCasePack(parsed.cases ? parsed : {schema_version:1,cases:[parsed]});
    // Resolve by the full identity; different protocols may share a case ID.
    let matched=false;
    for (const item of pack.cases) {
      const key=await digestText(caseIdentity(item));
      if (key===meta.key) matched=true;
      experience.cache.set(key,item);
    }
    if (!matched) throw Error("Identidade do caso divergente.");
    while (experience.cache.size>240) {
      const oldest=experience.cache.keys().next().value;
      if (oldest===meta.key) { const value=experience.cache.get(oldest);experience.cache.delete(oldest);experience.cache.set(oldest,value); }
      else experience.cache.delete(oldest);
    }
    experience.error="";experience.accessStatus=null;
  } catch (error) { experience.error = error.message; experience.accessStatus = error.status; experience.failed.add(meta.key); }
  finally {
    experience.loading.delete(meta.key);
    if (experienceActive() && selectedExperienceMeta()?.key === meta.key) { render(); focusExperienceRound(); updateArenaDock(); }
  }
}
function experienceSelector(side, available) {
  return `<label class="experience-model"><span>Modelo ${side === "a" ? "1" : "2"}</span><select data-experience-model="${side}" aria-label="Modelo ${side === "a" ? "1" : "2"}">${available.map((m) => `<option value="${esc(m.id)}" ${experience[side] === m.id ? "selected" : ""}>${optionName(m)}</option>`).join("")}</select></label>`;
}
function performanceFilterControl() {
  const all = catalogPool({filterResult:false});
  const usable = all.filter(c => examplePairs(c, false).some(({pair}) => pair.every(v => Number.isFinite(c.performance?.[v])))).length;
  const binary = casePerformanceKind(experience.task) === "binary";
  const a = models.get(experience.a)?.name || "Modelo 1", b = models.get(experience.b)?.name || "Modelo 2";
  const options = [["all", "Todas as respostas"], ["different", binary ? "Um acertou, o outro errou" : "Resultados diferentes"],
    ["a_better", binary ? `Só ${a} acertou` : `Melhor resultado: ${a}`], ["b_better", binary ? `Só ${b} acertou` : `Melhor resultado: ${b}`]];
  return `<div class="performance-filter"><label>Desempenho<select id="case-performance" ${!usable ? "disabled" : ""}>${options.map(([id,label])=>`<option value="${id}" ${experience.resultFilter===id ? "selected" : ""}>${esc(label)}</option>`).join("")}</select></label><span role="status">${experience.resultFilter !== "all" ? `${integer(catalogPool().length)} de ${integer(all.length)} casos` : `${integer(all.length)} casos`}${!usable ? " · Sem notas individuais comparáveis" : ""}</span>${usable && !binary ? '<small>Compara as notas registradas; não transforma nota parcial em acerto ou erro.</small>' : ""}</div>`;
}
function experienceToolbar() {
  const blind = experience.tab === "blind";
  const available = availableExampleModels();
  return `<div class="experience-toolbar">${blind ? `<div class="blind-label"><span aria-hidden="true">◉</span><div><strong>Escolha uma resposta para revelar os modelos</strong><small>Dois modelos do grupo selecionado, no mesmo modo.</small></div></div>` : `<div class="experience-models">${experienceSelector("a", available)}<button class="pair-divider" data-experience="swap" aria-label="Trocar os lados">⇄</button>${experienceSelector("b", available)}</div>`}<div class="experience-mode"><span>Modo de resposta <button class="help-dot" data-experience="mode-help" aria-label="Entender os modos">?</button></span><div class="segmented">${[["all","Ambos"],["thinking","Thinking"],["instruct","Instruct"]].map(([m,label]) => `<button data-experience-mode="${m}" aria-pressed="${experience.mode === m}">${label}</button>`).join("")}</div></div></div>`;
}
function renderExperience() {
  ensureExperienceSelection();
  const tab = experience.tab;
  const ready = experience.catalogState === "ready";
  return `<header class="workbench-heading"><h1>${tab === "blind" ? "Qual resposta você prefere?" : "Compare as respostas"}</h1><div class="workbench-links"><a href="#panorama?size=${state.size}">Todas as notas ↗</a><span>${integer(D.case_catalog.total)} casos · ${D.case_catalog.model_count} modelos com respostas</span></div></header>
  ${sizeControls()}
  <div class="experience-tabs" role="tablist" aria-label="Como explorar">${[["examples", "↳", "Respostas"], ["blind", "◉", "Escolher às cegas"]].map(([id, n, title]) => `<button role="tab" id="tab-${id}" aria-selected="${tab === id}" aria-controls="experience-panel" data-experience-tab="${id}"><span class="tab-number" aria-hidden="true">${n}</span><strong>${title}</strong></button>`).join("")}</div>
  <section id="experience-panel" class="experience-panel" role="tabpanel" aria-labelledby="tab-${tab}">${renderExperienceTasks()}${ready ? experienceToolbar() + renderExperienceCases() : renderExperienceUnavailable()}</section>
  <div class="experience-footer"><span><i></i>Respostas já geradas nas avaliações. Nada é enviado a um modelo ao navegar.</span><a href="#metodo">Protocolo e fontes ↗</a></div>`;
}
function renderExperienceTasks() {
  const tasks=Object.entries(experienceTasks).filter(([id])=>matchesCategory(benchmarks.get(id),experience.caseCategory));
  return `<div class="experience-tasks"><label>Categoria<select id="case-category" aria-label="Categoria das perguntas">${[["all","Todas"],...Object.entries(D.categories)].map(([id,title])=>`<option value="${id}" ${experience.caseCategory===id?'selected':''}>${esc(title)}</option>`).join("")}</select></label><label>Benchmark<select id="case-benchmark" aria-label="Benchmark das perguntas">${tasks.map(([id,t])=>`<option value="${id}" ${experience.task===id?'selected':''}>${esc(t.short)} · ${integer(D.case_catalog.benchmarks[id])} casos</option>`).join("")}</select></label><button class="more-tasks" data-experience="compare-pair">Ver notas ↗</button></div>`;
}
function renderExperienceUnavailable() {
  if (["idle", "loading"].includes(experience.catalogState)) return `<div class="evidence-loading" role="status"><span class="loading-ring"></span>Carregando respostas…</div>`;
  if ([401, 403].includes(experience.accessStatus)) return renderExperienceAccess();
  return `<div class="experience-unavailable"><div><h2>Não foi possível abrir as respostas.</h2><p>Tente carregar novamente. Você também pode consultar as notas ou abrir um arquivo de respostas salvo.</p><div class="access-actions"><button class="btn primary" data-experience="retry">Tentar novamente</button><button class="btn" data-experience="compare-pair">Explorar resultados →</button></div></div><label class="local-case-picker">Abrir respostas salvas<input id="experience-file" type="file" accept="application/json,.json"><small>O arquivo permanece no seu navegador.</small></label>${experience.error ? `<p class="error-message" role="alert">${esc(experience.error)}</p>` : ""}</div>`;
}
function caseNavigation() {
  const pool = catalogPool({ search: true });
  return `<aside class="case-browser" id="case-browser-panel" ${experience.browser ? "" : "hidden"}><div class="case-browser-head"><strong>Perguntas</strong><span>${pool.length}</span></div><input class="search" id="experience-query" type="search" placeholder="Buscar nos exemplos…" aria-label="Buscar nos exemplos" value="${esc(experience.query)}"><div id="experience-case-list">${caseList(pool)}</div></aside>`;
}
function caseList(pool) {
  return pool.length ? pool.slice(0,experience.caseLimit).map((c, i) => `<button data-experience-case="${c.key}" aria-current="${c.key === experience.key ? "true" : "false"}"><span>${String(i + 1).padStart(2, "0")}</span><div>${esc(c.title)}</div><b aria-hidden="true">↗</b></button>`).join("") + (pool.length>experience.caseLimit ? `<button data-experience="more-cases">Mostrar mais · ${integer(experience.caseLimit)} de ${integer(pool.length)}</button>` : "") : '<p class="small muted">Nenhum caso neste recorte.</p>';
}
function renderExperienceCases() {
  const blind = experience.tab === "blind", meta = selectedExperienceMeta(), c = meta && experience.cache.get(meta.key);
  const task = experienceTasks[experience.task];
  if (availableExampleModels().length < 2) return `<div class="no-case-pair"><h2>Não há respostas de dois modelos deste grupo.</h2><p>Escolha outro modo, tamanho ou benchmark para encontrar um par com respostas preservadas.</p><button class="btn primary" data-experience="compare-pair">Ver notas</button><a href="#panorama?size=${state.size}">Abrir tabela</a></div>`;
  const shell = `<div class="task-description"><span>${esc(task.text)}</span><div>${!blind ? `<button class="btn" data-experience="browser" aria-expanded="${experience.browser}" aria-controls="case-browser-panel">Perguntas <span>${catalogPool().length}</span> ☰</button>` : ""}<button class="btn" data-experience="${blind ? "round" : "random"}">${blind ? "Outro par" : "Outra pergunta"} ↻</button></div></div>`;
  const pending = !meta ? `<div class="empty">${!blind && experience.resultFilter !== "all" ? 'Nenhum caso corresponde a este filtro.<br><button class="btn" data-experience="clear-performance">Ver todas as respostas</button>' : "Não há respostas comuns para este recorte. Experimente outro modo ou tarefa."}</div>` : `<div class="evidence-loading" role="status"><span class="loading-ring"></span>Carregando o caso salvo…</div>`;
  const failure = [401, 403].includes(experience.accessStatus) ? renderExperienceAccess() : `<p class="error-message" role="alert">${esc(experience.error)}</p><button class="btn" data-experience="retry">Tentar abrir novamente</button>`;
  const session = blind ? `<div class="arena-session"><span>Leia → escolha → descubra os modelos</span><button class="text-button" data-experience="history" ${experience.sessionVotes.length ? "" : "disabled"}>Minhas escolhas <b>${experience.sessionVotes.length}</b></button></div>` : "";
  return shell + (!blind ? performanceFilterControl() : "") + session + `<div class="case-workspace ${blind ? "arena-workspace" : experience.browser ? "browser-open" : ""}">${!blind ? caseNavigation() : ""}<div class="case-stage">${experience.error && !c ? failure : c ? renderExperienceAnswer(c, blind) : pending}</div></div>`;
}
function highlightedAnswer(text, other) {
  const words = (s) => s.match(/[\p{L}\p{N}_]+/gu) || [];
  const shared = new Set(words(other).map((w) => w.toLocaleLowerCase("pt-BR")));
  return text.split(/([\p{L}\p{N}_]+)/gu).map((w) => /^[\p{L}\p{N}_]+$/u.test(w) && !shared.has(w.toLocaleLowerCase("pt-BR")) ? `<mark>${esc(w)}</mark>` : esc(w)).join("");
}
function renderExperiencePair(c, pair, mode, blind) {
  const round = experience.round, visible = !blind || round.revealed;
  const answers = pair.map(v => c.responses.find(r => `${r.model_id}:${r.mode}` === v));
  if (answers.some(r => !r)) return "";
  return `<section class="response-mode-group" data-response-mode="${mode}"><h3 class="response-mode-heading">${modeName(mode)}</h3>
  <div class="response-pair experience-answers">${answers.map((r, i) => `<article class="response-card ${round?.vote === (i ? "b" : "a") && blind ? "your-choice" : ""}"><header><div><span class="answer-letter">${i ? "B" : "A"}</span><h3>${visible ? modelName(models.get(r.model_id)) : `Resposta ${i ? "B" : "A"}`}</h3>${visible ? `<span class="answer-size">${esc(models.get(r.model_id).size_label)}</span>` : ""}</div>${visible ? `<span class="answer-score" title="${esc(r.metric_name)}">${number(displayedCaseScore(c.benchmark_id,r))}<small>${esc(r.metric_name)}</small></span>` : '<span class="hidden-identity">Nome oculto</span>'}</header><div class="answer">${renderCaseFinal(r,answers[1-i],visible)}</div>${visible ? `<div class="answer-evidence"><details><summary>Ver correção</summary>${judgmentView(c, r)}</details><details><summary>Resposta original e registro</summary><pre>${esc(r.final)}</pre><p>Protocolo: ${esc(records.get(`${r.model_id}:${r.mode}:${c.benchmark_id}`)?.protocol_id || "Registro individual preservado")}</p>${r.input_messages_ref ? lazyEvidence(r.input_messages_ref,"Entrada efetiva deste modelo") : ""}${r.tool_trace_ref ? lazyEvidence(r.tool_trace_ref,"Conversa e chamadas de ferramentas") : ""}${r.input_messages ? `<details><summary>Entrada efetiva deste modelo</summary><pre>${json(r.input_messages)}</pre></details>` : ""}${r.tool_trace ? `<details><summary>Conversa e chamadas de ferramentas</summary><pre>${json(r.tool_trace)}</pre></details>` : ""}${r.metadata ? `<details><summary>Parâmetros, tokens e custos</summary><pre>${json(r.metadata)}</pre></details>` : ""}${r.source_url ? `<a href="${safeLink(r.source_url)}" target="_blank" rel="noopener noreferrer">Registro completo no GitHub ↗</a>` : ""}${r.final_was_null ? "<p>A execução original não retornou conteúdo final.</p>" : ""}${r.tool_summary ? `<pre>${json(r.tool_summary)}</pre>` : ""}</details></div>` : ""}</article>`).join("")}</div></section>`;
}
function renderExperienceAnswer(c, blind) {
  const round = experience.round, visible = !blind || round.revealed;
  const groups = blind ? [{pair:round.pair,mode:round.mode}] : examplePairs(selectedExperienceMeta());
  const answers = (groups[0]?.pair || []).map(v => c.responses.find(r => `${r.model_id}:${r.mode}` === v));
  if (!groups.length || answers.some(a => !a)) return '<div class="empty">Não há respostas comuns para este par.</div>';
  const references = Array.isArray(c.reference) ? c.reference : c.reference !== null && c.reference !== undefined && c.reference !== "" ? [c.reference] : [];
  const pool = catalogPool(), index = pool.findIndex((x) => x.key === experience.key);
  const chosen = round?.vote && ["a", "b"].includes(round.vote) ? answers[round.vote === "a" ? 0 : 1] : null;
  return `<article class="question-sheet" tabindex="-1"><div class="question-top"><span class="eyebrow">${esc(benchmarks.get(c.benchmark_id).name)}</span>${!blind ? `<span>${index + 1} de ${pool.length}</span>` : '<span class="pill">Comparação às cegas</span>'}</div><h3>${esc(c.question)}</h3>${c.context_ref ? lazyEvidence(c.context_ref, 'Abrir contexto original completo') : ''}${c.context ? `<details class="source-context" ${c.benchmark_id === "conduta_bench" ? "open" : ""}><summary>Texto apresentado aos modelos <span>↗</span></summary><div>${esc(c.context)}</div></details>` : ""}${c.schema ? `<details class="source-context"><summary>Formato JSON solicitado ↗</summary><pre>${typeof c.schema === "string" ? esc(c.schema) : json(c.schema)}</pre></details>` : ""}</article>
  <div class="answer-options"><span>${visible ? "Respostas finais" : "Modelos ocultos"}</span><label><input type="checkbox" id="experience-highlight" ${experience.highlights ? "checked" : ""}> Mostrar diferenças</label></div>
  ${experience.highlights ? '<p class="highlight-note">O destaque mostra palavras que não aparecem na outra resposta; não indica acerto ou erro.</p>' : ""}
  ${groups.map(({pair,mode}) => renderExperiencePair(c,pair,mode,blind)).join("")}
  ${blind ? visible ? `<div class="reveal-summary arena-dock" role="status"><div><span class="eyebrow">Modelos revelados</span><h3>${chosen ? `Você escolheu ${esc(models.get(chosen.model_id).name)}.` : round.vote === "tie" ? "Você considerou as respostas equivalentes." : round.vote === "neither" ? "Você não escolheria nenhuma das duas." : "Agora você conhece os modelos."}</h3><p>Confira a correção nas respostas ou siga para outro par.</p></div><button class="btn primary" data-experience="round">Próxima comparação → <kbd>N</kbd></button></div>` : `<div class="arena-vote arena-dock"><span>Qual resposta você escolheria?</span><div><button data-arena-vote="a" aria-keyshortcuts="1"><kbd>1</kbd> Resposta A</button><button data-arena-vote="b" aria-keyshortcuts="2"><kbd>2</kbd> Resposta B</button><button data-arena-vote="tie" aria-keyshortcuts="3"><kbd>3</kbd> Equivalentes</button><button data-arena-vote="neither" aria-keyshortcuts="4"><kbd>4</kbd> Nenhuma</button></div><button class="text-button" data-experience="reveal">Revelar sem escolher</button></div>` : `<div class="case-bottom"><button class="btn" data-experience="previous" ${index <= 0 ? "disabled" : ""}>← Anterior</button><button class="btn" data-experience="next" ${index >= pool.length - 1 ? "disabled" : ""}>Próxima pergunta →</button></div>`}
  ${visible ? `<div class="evidence-bridge">${references.length ? `<details><summary>Resposta de referência</summary><div>${references.map((s) => `<p>${esc(typeof s === "string" ? s : JSON.stringify(s))}</p>`).join("")}</div></details>` : ""}<button data-experience="compare-pair">Ver as notas desse par em outros testes <span>→</span></button><details><summary>Fonte e identificação do caso</summary><p>ID: ${esc(c.case_id)}</p><a href="${safeLink(benchmarks.get(c.benchmark_id).protocol_url)}" target="_blank" rel="noopener noreferrer">Protocolo deste benchmark ↗</a></details></div>` : ""}
  ${blind ? `<p class="vote-note">${experience.sessionVotes.length ? `${experience.sessionVotes.length} escolhas nesta sessão. ` : ""}Preferências ficam neste navegador e não mudam as notas. Posição e modelos são sorteados; não é um estudo de preferência controlado.</p>` : '<p class="vote-note">Você está lendo respostas já geradas na avaliação. O catálogo inclui acertos, erros e respostas vazias.</p>'}`;
}
function refreshExperience({ url = true } = {}) {
  ensureExperienceSelection();
  if (url) experienceURL();
  render();
}
function showArenaHistory() {
  const votes = [...experience.sessionVotes].reverse();
  const verdict = (v) => v.vote === "tie" ? "Equivalentes" : v.vote === "neither" ? "Nenhuma" : models.get(v.pair[v.vote === "a" ? 0 : 1].split(":")[0]).name;
  $("#detail-content").innerHTML = `<h2 id="detail-title">Suas escolhas às cegas</h2><p>${votes.length} escolhas nesta sessão. Clique para rever as respostas e a correção. Suas preferências não alteram as notas dos benchmarks.</p><div class="arena-history">${votes.map((v, i) => `<button data-arena-history="${esc(v.id)}"><span>${votes.length - i}</span><div><strong>${esc(verdict(v))}</strong><small>${v.pair.map((id) => esc(models.get(id.split(":")[0]).name)).join(" × ")} · ${v.mode === "thinking" ? "Com raciocínio" : "Direto"}<br>${esc(experienceTasks[v.task].short)}</small></div><span aria-hidden="true">↗</span></button>`).join("")}</div>`;
  $("#detail-dialog").showModal();
}
document.addEventListener("click", (event) => {
  const t = event.target.closest("[data-experience],[data-experience-tab],[data-experience-task],[data-experience-mode],[data-experience-case],[data-experience-category],[data-arena-vote],[data-arena-history]");
  if (!t || !D) return;
  if (t.dataset.experienceTab) {
    experience.tab = t.dataset.experienceTab;
    state.view = experience.tab === "blind" ? "casos" : "descobrir";
    if (experience.tab === "blind") { experience.round = null; experience.focusRound = true; }
  }
  if (t.dataset.experienceTask) {
    experience.task = t.dataset.experienceTask; experience.query = ""; experience.round = null;
  }
  if (t.dataset.experienceMode) {
    experience.mode = t.dataset.experienceMode; state.mode = experience.mode; experience.round = null;
  }
  if (t.dataset.experienceCase) experience.key = t.dataset.experienceCase;
  if (t.dataset.experienceCategory) experience.category = t.dataset.experienceCategory;
  if (t.dataset.arenaHistory) {
    const vote = experience.sessionVotes.find((v) => v.id === t.dataset.arenaHistory);
    if (!vote) return;
    experience.round = { ...vote }; experience.mode = vote.mode; experience.task = vote.task;
    state.size = vote.size; experience.tab = "blind"; state.view = "casos"; experience.focusRound = true;
    $("#detail-dialog").close();
  }
  if (t.dataset.arenaVote && experience.round && !experience.round.revealed) {
    const round = experience.round;
    if (!experience.cache.has(round.key)) return;
    round.vote = t.dataset.arenaVote; round.revealed = true;
    const vote = { ...round, time: new Date().toISOString() };
    experience.sessionVotes.push(vote);
    try {
      const saved = JSON.parse(localStorage.getItem("observatorio-local-votes") || "[]");
      localStorage.setItem("observatorio-local-votes", JSON.stringify([...saved, vote].slice(-1000)));
    } catch { toast("Sua escolha foi registrada nesta sessão; armazenamento local indisponível."); }
  }
  const action = t.dataset.experience;
  if (action === "clear-performance") { experience.resultFilter = "all"; experience.key = null; }
  if (action === "more-cases") { experience.caseLimit+=100;$("#experience-case-list").innerHTML=caseList(catalogPool({search:true}));return; }
  if (action === "browser") experience.browser = !experience.browser;
  if (action === "swap") [experience.a, experience.b] = [experience.b, experience.a];
  if (action === "round") { newArenaRound(); experience.focusRound = true; }
  if (action === "history") { showArenaHistory(); return; }
  if (action === "retry") {
    if (experience.catalogState !== "ready") experience.catalogState = "idle";
    experience.failed.delete(selectedExperienceMeta()?.key); experience.error = ""; experience.accessStatus = null;
  }
  if (action === "reveal" && experience.round) experience.round.revealed = true;
  if (["next", "previous", "random"].includes(action)) {
    const pool = catalogPool(), i = pool.findIndex((c) => c.key === experience.key);
    const next = action === "random" ? randomItem(pool.filter((c) => c.key !== experience.key)) || pool[0] : pool[i + (action === "next" ? 1 : -1)];
    if (next) experience.key = next.key;
  }
  if (action === "compare-pair") {
    if (experience.tab === "blind" && experience.round) [experience.a, experience.b] = experience.round.pair.map((v) => v.split(":")[0]);
    state.mode=experience.mode; state.selected=new Set([experience.a,experience.b]);
    state.scatter=experience.task; state.category="all"; navigate("comparar"); return;
  }
  if (action === "mode-help") {
    $("#detail-content").innerHTML = '<h2 id="detail-title">Dois modos de responder</h2><p><strong>Com raciocínio (thinking)</strong>: o modelo recebe a instrução de raciocinar antes da resposta final.</p><p><strong>Direto (instruct)</strong>: usa o modo sem raciocínio separado, quando o modelo oferece essa opção.</p><p>Só a resposta final recebe nota. O modo pode alterar qualidade e consumo; aqui você compara resultados de avaliações já realizadas.</p>';
    $("#detail-dialog").showModal(); return;
  }
  refreshExperience();
});
document.addEventListener("keydown", (event) => {
  if (!experienceActive() || experience.tab !== "blind" || event.repeat || event.ctrlKey || event.altKey || event.metaKey ||
    event.target.closest("input,textarea,select,[contenteditable=true]") || document.querySelector("dialog[open]")) return;
  const vote = { "1": "a", "2": "b", "3": "tie", "4": "neither" }[event.key];
  const button = vote ? document.querySelector(`[data-arena-vote="${vote}"]`) : event.key.toLowerCase() === "n" && experience.round?.revealed ? document.querySelector(".reveal-summary [data-experience=round]") : null;
  if (button) { event.preventDefault(); button.click(); }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "experience-query") {
    experience.query = event.target.value; experience.caseLimit=100;
    $("#experience-case-list").innerHTML = caseList(catalogPool({ search: true }));
  }
});
document.addEventListener("change", async (event) => {
  const t = event.target;
  if (t.id === "case-performance") { experience.resultFilter=t.value;experience.key=null;experience.caseLimit=100;refreshExperience(); }
  if (t.id==="case-benchmark") { experience.task=t.value;experience.query="";experience.caseLimit=100;experience.round=null;experience.key=null;refreshExperience(); }
  if (t.id==="case-category") { experience.caseCategory=t.value;experience.caseLimit=100;const available=Object.keys(experienceTasks).filter(id=>matchesCategory(benchmarks.get(id),t.value));if (!available.includes(experience.task)) experience.task=available[0];experience.round=null;experience.key=null;refreshExperience(); }
  if (t.dataset.experienceModel) { experience[t.dataset.experienceModel] = t.value; refreshExperience(); }
  if (t.id === "experience-highlight") { experience.highlights = t.checked; refreshExperience(); }
  if (t.id === "experience-file" && t.files?.[0]) {
    try {
      if (t.files[0].size > 100 * 1024 * 1024) throw Error("O arquivo excede 100 MB.");
      const pack = validateCasePack(JSON.parse(await t.files[0].text()));
      const entries = [], cache = new Map();
      for (const c of pack.cases) {
        const key = await digestText(caseIdentity(c));
        entries.push({ key, case_id: c.case_id, benchmark_id: c.benchmark_id, title: c.benchmark_id === "conduta_bench" ? c.context.slice(0, 110) : c.question, variants: c.responses.map((r) => `${r.model_id}:${r.mode}`), performance:casePerformanceIndex(c) });
        cache.set(key, c);
      }
      experience.catalog = { schema_version: 1, cases: entries }; experience.directory=null;experience.loadedTasks.clear(); experience.cache = cache;
      experience.catalogState = "ready"; experience.local = true; experience.error = ""; experience.accessStatus = null;
      experience.round = null; experience.failed.clear();
      refreshExperience();
    } catch (error) { experience.error = error.message; refreshExperience(); }
  }
});
function lazyEvidence(ref, label) {
  if (!/^cases\/blobs\/[a-f0-9]{64}\.json(?:\.gz)?$/.test(ref.file) || !/^[a-f0-9]{64}$/.test(ref.sha256)) return '<p>Evidência com referência inválida.</p>';
  return `<details class="source-context lazy-evidence" data-evidence-file="${ref.file}" data-evidence-sha="${ref.sha256}"><summary>${esc(label)} ↗</summary><div class="lazy-body"><button class="text-button" data-load-evidence>Carregar conteúdo preservado</button></div></details>`;
}
function renderCaseFinal(r, other, visible) {
  const answer=text=>text ? experience.highlights ? highlightedAnswer(text,other.final) : readableAnswer(text) : '<em>Resposta final vazia, preservada na avaliação.</em>';
  if (r.turns?.length>1) return r.turns.map(t=>`<section class="saved-turn"><span class="eyebrow">Turno ${Number(t.turn)+ (Number(r.turns[0].turn)===0 ? 1 : 0)}</span><details><summary>Pergunta deste turno</summary><p>${esc(t.question)}</p></details><div>${answer(t.final)}</div></section>`).join("");
  return answer(r.final);
}
document.addEventListener("click", async event=>{
  const button=event.target.closest('[data-load-evidence]');if(!button)return;
  const container=button.closest('[data-evidence-file]');const file=container.dataset.evidenceFile;button.disabled=true;button.textContent='Carregando…';
  try {
    let value=experience.blobs.get(file);
    if (!value) { const raw=await fetchExperienceText(file);if(await digestText(raw)!==container.dataset.evidenceSha)throw Error('Hash da evidência divergente.');value=JSON.parse(raw);experience.blobs.set(file,value);while(experience.blobs.size>6)experience.blobs.delete(experience.blobs.keys().next().value); }
    container.querySelector('.lazy-body').innerHTML=`<pre>${esc(value.text ?? JSON.stringify(value,null,2))}</pre>`;
  } catch(error) {button.disabled=false;button.textContent='Tentar carregar novamente';const p=document.createElement('p');p.textContent=error.message;container.querySelector('.lazy-body').append(p);}
});
