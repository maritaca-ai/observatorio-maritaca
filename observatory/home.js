"use strict";

// The camera selects models; star positions and brightness never encode scores.
const home = { selected: "candidate", paused: false, zoom: 1, panX: 0, panY: 0, cleanup: null };
function readSkyCamera(params) {
  const values = (params.get("sky") || "1,0,0").split(",").map(Number);
  const valid = values.length === 3 && values.every(Number.isFinite);
  [home.zoom,home.panX,home.panY] = valid ? values : [1,0,0];
}
function writeSkyCamera(params) {
  if (home.zoom !== 1 || home.panX !== 0 || home.panY !== 0)
    params.set("sky", [home.zoom,home.panX,home.panY].map(n => +n.toFixed(6)).join(","));
}
const skyPositions = {
  candidate: [.53, .49], "qwen35-4b": [.35, .29], "lumi-hf": [.75, .18],
  gaia: [.84, .45], tucano: [.32, .71], manaca: [.69, .78],
  "lfm3-1.7b": [.16, .50], "gemma4-e4b": [.47, .105],
  "nemotron35-bolt-e4b": [.49, .90], "lfm25-24b-a2b": [.16, .88],
  latamgpt: [.78, .65], soberania: [.17, .16],
};
const skyNames = { "nemotron35-bolt-e4b": "Nemotron E4B", "lfm25-24b-a2b": "LFM2.5 A2B", tucano: "Tucano2", latamgpt: "LatamGPT" };
function homeModelLinks(m) {
  const query = new URLSearchParams({ size: state.size, models: m.id, mode: "all" });
  return `<div class="sky-model-links">${m.result_count ? `<a href="#panorama?${query}">Ver resultados <span aria-hidden="true">↗</span></a>` : ""}<a href="#modelos?size=${state.size}&model=${encodeURIComponent(m.id)}">Sobre o modelo <span aria-hidden="true">↗</span></a></div>`;
}
function selectedSkyModel() {
  const m = models.get(home.selected);
  return `<div class="sky-model-info"><span class="sky-info-label">${m.unavailable ? "Acesso solicitado · sem avaliação" : "Em observação"}</span><h2>${modelName(m)}</h2><p>${esc(m.organization)}</p><div class="sky-model-facts"><span>${esc(i18n.t(m.size_label))}</span><span>${m.result_count ? `${m.result_count} notas` : esc(m.availability_status)}</span></div>${homeModelLinks(m)}</div>`;
}
function renderHomeAverages() {
  const variants = allVariants().filter(v => inSizeGroup(v.model) && state.selected.has(v.model.id) && (state.mode === "all" || v.mode === state.mode));
  const tasks = D.benchmarks.filter(b => matchesCategory(b, state.category));
  const values = rankAverages(calculateAverages(tasks, variants, D.records));
  const columns = [["native_br", "Nativo BR"], ["translated_pt", "Traduzido PT"], ["international", "Não nativo"], ["total", "Total ↓"]];
  averagesState.cells.clear();
  const best = Object.fromEntries(columns.map(([g]) => [g, Math.max(...values.map(r => r.cells[g].value ?? -Infinity))]));
  const rows = values.map(({variant,cells,rank}) => {
    return `<tr data-average-model="${variant.model.id}" data-ranking-mode="${variant.mode}" data-rank="${rank ?? ''}" class="${variant.model.id === 'candidate' ? 'home-candidate' : ''}"><th><div class="home-model-name">${averageRankLabel(variant,rank)}${modelWeightsLink(variant.model, variant.mode)}</div><small>${esc(i18n.t(variant.model.size_label))} · ${modeName(variant.mode)}</small></th>${columns.map(([g]) => {
      const c = cells[g], id = `home:${variant.id}:${g}`;
      averagesState.cells.set(id,{...c,model:variant.model,mode:variant.mode,group:g});
      const winner = c.value !== null && c.value === best[g];
      return `<td><button data-average-detail="${id}" class="${winner ? 'home-best' : ''}" aria-label="${esc(variant.model.name)}, ${modeName(variant.mode)}, ${g}: ${number(c.value)}, ${c.n} testes">${winner ? '<strong>' : '<span>'}${number(c.value)}${winner ? '</strong>' : '</span>'}<small>${c.n} de ${c.expected}${c.n && !completeAverage(c) ? " · Parcial" : " testes"}</small></button></td>`;
    }).join("")}</tr>`;
  }).join("");
  const query = new URLSearchParams({size:state.size,mode:state.mode,models:[...state.selected].join(",")});
  if (state.category !== "all") query.set("category",state.category);
  return `<section class="home-results" aria-label="Médias dos resultados"><div class="home-results-heading"><div><span class="home-section-label">RESULTADOS</span><h2>Ranking dos modelos</h2></div><a href="#panorama?${query}">Tabela completa ↗</a></div><div class="home-filters"><div class="segmented" aria-label="Tamanho dos modelos">${Object.entries(sizeGroups).map(([id,g]) => `<button data-size-group="${id}" aria-pressed="${state.size === id}">${g.label}</button>`).join("")}</div><div class="segmented" aria-label="Modo das médias">${[["all","Ambos"],["thinking","Thinking"],["instruct","Instruct"]].map(([id,label]) => `<button data-mode="${id}" aria-pressed="${state.mode === id}">${label}</button>`).join("")}</div><select data-home-category aria-label="Categoria das médias">${[["all","Todas as categorias"],...Object.entries(D.categories)].map(([id,label]) => `<option value="${id}" ${state.category === id ? "selected" : ""}>${esc(label)}</option>`).join("")}</select></div><div class="home-average-scroll"><table class="home-average-table"><thead><tr><th>Modelo</th>${columns.map(([group,title]) => `<th${group === "total" ? ' aria-sort="descending"' : ""}>${title}</th>`).join("")}</tr></thead><tbody>${rows || '<tr><td colspan="5">Nenhum modelo com resultados neste campo. <button class="text-button" data-sky-reset>Recentrar</button></td></tr>'}</tbody></table></div></section>`;
}
function renderHome() {
  const visible = sizeModels();
  if (!visible.some(m => m.id === home.selected)) home.selected = "candidate";
  const points = visible.map((m,i) => `<button class="sky-model ${m.unavailable ? 'sky-unavailable' : ''}" style="--float-delay:${-i * .61}s" data-sky-model="${esc(m.id)}" aria-pressed="${home.selected === m.id}" aria-label="${esc(m.name)}: abrir resumo"><span class="sky-hit" aria-hidden="true"><i></i></span><span class="sky-name">${esc(skyNames[m.id] || m.name)}${originBadge(m)}</span></button>`).join("");
  return `<section class="observatory-home ${home.paused ? 'sky-paused' : ''}" aria-labelledby="home-title"><header class="home-copy"><div><div class="home-eyebrow"><span></span>Maritaca</div><h1 id="home-title">${i18n.language === "en" ? "Maritaca <span>Observatory</span>" : "Observatório <span>Maritaca</span>"}</h1></div><div class="home-actions"><a class="home-primary" href="#descobrir">Comparar respostas ↗</a><a href="#casos">Escolher às cegas →</a></div></header>${renderHomeAverages()}<div class="sky-stage"><div class="sky-top"><span class="sky-instrument-label"><span id="sky-field-count" role="status" aria-live="polite"></span></span><button class="text-button" data-sky-reset>Recentrar ⌾</button></div><div class="model-sky" tabindex="0" role="region" aria-label="Filtro circular de modelos. A tabela mostra os modelos dentro do círculo. Arraste ou use as setas para mover; use mais, menos ou a roda do mouse para aproximar. Tab percorre as estrelas visíveis."><canvas id="sky-canvas" aria-hidden="true"></canvas><div class="sky-reticle" aria-hidden="true"></div><div class="sky-points">${points}</div></div><div class="sky-tools"><span class="sky-hint">Arraste ou aproxime para filtrar.</span><div class="sky-tool-buttons"><button data-sky-zoom="out" aria-label="Afastar">−</button><output id="sky-zoom" aria-live="polite">1,0×</output><button data-sky-zoom="in" aria-label="Aproximar">+</button><button data-sky-motion aria-pressed="${home.paused}" aria-label="${home.paused ? 'Retomar' : 'Pausar'} animação">${home.paused ? '▷' : 'Ⅱ'}</button></div></div><div id="sky-selection" aria-live="polite" aria-atomic="true">${selectedSkyModel()}</div><p class="sky-bottom">Céu ilustrativo: posição e brilho não representam notas.</p></div></section><section class="home-paths" aria-label="Explorar as avaliações"><a href="#descobrir"><span>01</span><h2>A mesma pergunta.<br>Respostas diferentes.</h2><p>Leia, compare e abra a correção de cada caso.</p><b>↗</b></a><a href="#casos"><span>02</span><h2>Sem o nome,<br>qual você escolheria?</h2><p>Escolha uma resposta e revele os modelos.</p><b>↗</b></a><a href="#metodo"><span>03</span><h2>O que entra<br>em cada nota?</h2><p>Conheça os testes, as fontes e os limites da avaliação.</p><b>↗</b></a></section><div class="home-inventory"><a href="#modelos"><strong>${D.models.filter(m => m.result_count).length}</strong><span>modelos com resultados</span></a><a href="#panorama?size=all&mode=all"><strong>${D.coverage.total}</strong><span>notas registradas</span></a><a href="#descobrir"><strong>${integer(D.case_catalog.total)}</strong><span>casos para explorar</span></a></div>`;
}
document.addEventListener("change", event => {
  if (!event.target.matches("[data-home-category]")) return;
  state.category = event.target.value; writeHash(); render();
});
function disposeSky() { if (home.cleanup) home.cleanup(); home.cleanup = null; }
function initSky() {
  const stage = document.querySelector(".model-sky"), canvas = document.querySelector("#sky-canvas");
  if (!stage || !canvas) return;
  const ctx = canvas.getContext("2d"), reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let width = 1, height = 1, radius = 1, frame = 0, last = 0, elapsed = 0, drag = null, backdropDirty = true, urlTimer;
  const saveCamera = () => { clearTimeout(urlTimer); urlTimer = setTimeout(writeHash,150); };
  const backdrop = document.createElement("canvas");
  let seed = 72108;
  const rand = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const stars = Array.from({ length: 270 }, () => ({ x: rand(), y: rand(), r: .4 + rand() ** 3 * 1.9, a: .3 + rand() * .7, phase: rand() * 6.28, depth: .4 + rand() * .6 }));
  const dust = Array.from({ length: 18 }, () => ({ x: rand(), y: rand(), r: 18 + rand() * 80, a: .025 + rand() * .05 }));
  const points = [...stage.querySelectorAll("[data-sky-model]")];
  const bounds = () => { home.zoom = Math.max(.8, Math.min(2.4, home.zoom)); home.panX = Math.max(-.65, Math.min(.65, home.panX)); home.panY = Math.max(-.65, Math.min(.65, home.panY)); };
  const scale = () => 2 * radius * .82 * home.zoom;
  function labelPositions() {
    const placed = [];
    for (const p of points.filter(p => !p.classList.contains("out-of-field"))) {
      const label = p.querySelector(".sky-name"), w = label.offsetWidth, h = label.offsetHeight;
      const x = parseFloat(p.style.left), y = parseFloat(p.style.top);
      const choices = [[-w/2,24],[-w/2,-h-24],[24,-h/2],[-w-24,-h/2],[-w-12,18],[12,18],[-w-12,-h-18],[12,-h-18]];
      for (const distance of [36,48,64,80])
        for (let i=0;i<24;i++) choices.push([Math.cos(i*Math.PI/12)*distance-w/2,Math.sin(i*Math.PI/12)*distance-h/2]);
      const fits = ([dx,dy]) => {
        const box = {x:x+dx,y:y+dy,w,h};
        return [[0,0],[w,0],[0,h],[w,h]].every(([a,b]) => Math.hypot(box.x+a-width/2,box.y+b-height/2)<radius-3)
          && !placed.some(b => box.x<b.x+b.w+3 && box.x+w+3>b.x && box.y<b.y+b.h+3 && box.y+h+3>b.y);
      };
      const [dx,dy] = choices.find(fits) || choices[0];
      label.style.left = `${22+dx}px`; label.style.top = `${22+dy}px`;
      placed.push({x:x+dx,y:y+dy,w,h});
    }
  }
  function position() {
    backdropDirty = true;
    bounds();
    const visible = new Set();
    points.forEach((p) => {
      const [x, y] = skyPositions[p.dataset.skyModel];
      const px = width/2 + (x-.5+home.panX)*scale();
      const py = height/2 + (y-.5+home.panY)*scale();
      p.style.left = `${px}px`; p.style.top = `${py}px`;
      const inside = Math.hypot(px-width/2,py-height/2) <= radius;
      p.classList.toggle("out-of-field", !inside);
      p.setAttribute("aria-hidden",String(!inside));
      p.tabIndex = inside ? 0 : -1;
      if (inside) visible.add(p.dataset.skyModel);
    });
    labelPositions();
    const changed = visible.size !== state.selected.size || [...visible].some(id => !state.selected.has(id));
    state.selected = visible;
    if (changed) document.querySelector(".home-results").outerHTML = renderHomeAverages();
    document.querySelector("#sky-field-count").textContent = `${visible.size} modelos no círculo`;
    document.querySelector("#sky-zoom").textContent = number(home.zoom, 1) + "×";
    stage.dataset.zoom = home.zoom.toFixed(2);
    stage.dataset.pan = [home.panX, home.panY].map(x => x.toFixed(3)).join(",");
    stage.dataset.radius = radius;
  }
  function paint() {
    ctx.clearRect(0, 0, width, height);
    if (backdropDirty) {
    const base = ctx.createLinearGradient(0, 0, width, height);
    base.addColorStop(0, "#173f35"); base.addColorStop(.50, "#285e49"); base.addColorStop(1, "#133c33");
    ctx.fillStyle = base; ctx.fillRect(0, 0, width, height);
    // A diffuse diagonal dust band; no photographic assets or network requests.
    for (const d of dust) {
      const x = (d.x - .5 + home.panX * .25) * width * home.zoom + width * .5;
      const y = ((d.x * .6 + d.y * .34) - .5 + home.panY * .25) * height * home.zoom + height * .4;
      const g = ctx.createRadialGradient(x, y, 0, x, y, d.r * home.zoom);
      g.addColorStop(0, `rgba(174,211,137,${d.a*1.8})`); g.addColorStop(1, "rgba(111,156,109,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, d.r * home.zoom, 0, Math.PI * 2); ctx.fill();
    }
    ctx.lineWidth = .6; ctx.strokeStyle = "rgba(194,221,178,.13)";
    for (let i = -3; i < 6; i++) {
      ctx.beginPath(); ctx.ellipse(width * (.5 + home.panX), height * (1.7 + home.panY), width * (1 + i * .12), height * (1.05 + i * .1), -.13, 3.3, 6.15); ctx.stroke();
    }
    backdrop.width = canvas.width; backdrop.height = canvas.height;
    backdrop.getContext("2d").drawImage(canvas, 0, 0); backdropDirty = false;
    } else ctx.drawImage(backdrop, 0, 0, width, height);
    for (const s of stars) {
      const x = ((s.x - .5 + home.panX * s.depth) * home.zoom + .5) * width + Math.sin(elapsed * .00032 + s.phase) * 12;
      const y = ((s.y - .5 + home.panY * s.depth) * home.zoom + .5) * height + Math.cos(elapsed * .00026 + s.phase) * 10;
      if (x < 0 || y < 0 || x > width || y > height) continue;
      const alpha = s.a * (.55 + .45 * Math.sin(elapsed * .002 + s.phase));
      ctx.fillStyle = `rgba(237,245,214,${alpha})`; ctx.beginPath(); ctx.arc(x, y, s.r * Math.sqrt(home.zoom), 0, Math.PI * 2); ctx.fill();
      if (s.r > 1.8) {
        const glow = ctx.createRadialGradient(x, y, s.r, x, y, s.r * 6);
        glow.addColorStop(0, `rgba(207,234,161,${alpha * .4})`);
        glow.addColorStop(1, "rgba(207,234,161,0)");
        ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(x, y, s.r * 6, 0, Math.PI * 2); ctx.fill();
        if (s.r > 2.05) {
          ctx.strokeStyle = `rgba(237,245,214,${alpha * .65})`; ctx.lineWidth = .7;
          ctx.beginPath(); ctx.moveTo(x - s.r * 2, y); ctx.lineTo(x + s.r * 2, y);
          ctx.moveTo(x, y - s.r * 2); ctx.lineTo(x, y + s.r * 2); ctx.stroke();
        }
      }
    }
  }
  function loop(now) {
    if (!canvas.isConnected) return;
    if (now - last >= 40) { const dt = Math.min(now - (last || now), 80); last = now; if (!document.hidden && !home.paused && !reduced.matches && stage.getBoundingClientRect().bottom > 0) { elapsed += dt; paint(); } }
    frame = requestAnimationFrame(loop);
  }
  const resize = () => {
    const box = stage.getBoundingClientRect(); width = box.width; height = box.height;
    radius = Math.min(width,height)/2-8;
    stage.style.clipPath = `circle(${radius}px at 50% 50%)`;
    stage.style.setProperty("--sky-diameter",`${radius*2}px`);
    const dpr = Math.min(devicePixelRatio || 1, 2); canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`; canvas.style.height = `${height}px`; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); position(); paint();
  };
  const observer = new ResizeObserver(resize); observer.observe(stage);
  const move = (dx, dy) => { home.panX += dx; home.panY += dy; position(); paint(); };
  const down = (e) => {
    if (e.target.closest("button") || e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY }; stage.setPointerCapture(e.pointerId); stage.classList.add("is-dragging");
  };
  const pointer = (e) => { if (!drag) return; move((e.clientX - drag.x) / scale(), (e.clientY - drag.y) / scale()); drag = { x: e.clientX, y: e.clientY }; };
  const up = () => { drag = null; stage.classList.remove("is-dragging"); writeHash(); };
  const keyboard = (e) => {
    if (e.target !== stage) return;
    const delta = { ArrowLeft: [.035, 0], ArrowRight: [-.035, 0], ArrowUp: [0, .035], ArrowDown: [0, -.035] }[e.key];
    if (delta) { e.preventDefault(); move(...delta); }
    if (["+", "=", "-"].includes(e.key)) { e.preventDefault(); home.zoom += e.key === "-" ? -.2 : .2; position(); paint(); }
    if (delta || ["+", "=", "-"].includes(e.key)) saveCamera();
  };
  const controls = (e) => {
    const t = e.target.closest("[data-sky-zoom],[data-sky-reset],[data-sky-explore],[data-sky-motion],[data-sky-model]");
    if (!t) return;
    if (t.dataset.skyModel) {
      home.selected = t.dataset.skyModel;
      points.forEach((p) => p.setAttribute("aria-pressed", String(p === t)));
      document.querySelector("#sky-selection").innerHTML = selectedSkyModel();
    }
    if (t.dataset.skyZoom) home.zoom += t.dataset.skyZoom === "in" ? .2 : -.2;
    if (t.hasAttribute("data-sky-reset")) { home.zoom = 1; home.panX = 0; home.panY = 0; }
    if (t.hasAttribute("data-sky-explore")) { stage.focus({ preventScroll: true }); stage.scrollIntoView({ block: "center", behavior: reduced.matches ? "instant" : "smooth" }); }
    if (t.hasAttribute("data-sky-motion")) {
      home.paused = !home.paused; document.querySelector(".observatory-home").classList.toggle("sky-paused", home.paused);
      t.setAttribute("aria-pressed", String(home.paused)); t.setAttribute("aria-label", `${home.paused ? 'Retomar' : 'Pausar'} animação`); t.textContent = home.paused ? "▷" : "Ⅱ";
    }
    position(); paint(); writeHash();
  };
  const wheel = e => {
    e.preventDefault(); home.zoom += e.deltaY < 0 ? .1 : -.1; position(); paint(); saveCamera();
  };
  stage.addEventListener("pointerdown", down); stage.addEventListener("pointermove", pointer); stage.addEventListener("pointerup", up); stage.addEventListener("pointercancel", up); stage.addEventListener("keydown", keyboard);
  stage.addEventListener("wheel",wheel,{passive:false});
  document.addEventListener("click", controls);
  resize(); writeHash(); frame = requestAnimationFrame(loop);
  home.cleanup = () => { cancelAnimationFrame(frame); clearTimeout(urlTimer); observer.disconnect(); document.removeEventListener("click", controls); };
}
