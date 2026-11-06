"use strict";

// Presentation only: saved inputs, answers, verdicts and downloadable data are
// never translated. Text marked translate="no" is an explicit evidence boundary.
const i18n = (() => {
  const dictionary = window.OBSERVATORY_EN;
  const normalize = value => value === "en" ? "en" : value === "pt" || value === "pt-BR" ? "pt" : null;
  // The canonical URL always opens in Portuguese, regardless of browser locale
  // or a previous visit. An explicit choice is kept in the shareable URL.
  let language = normalize(new URL(location.href).searchParams.get("lang")) || "pt";
  const originals = new WeakMap();
  const ignored = 'script,style,pre,code,noscript,[translate="no"],[data-original]';
  const attributes = ["aria-label", "title", "placeholder", "label", "alt"];
  const escapeRegExp = text => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const patterns = dictionary.patterns.map(([source, translation, numeric]) => ({
    expression: new RegExp("^" + source.split(/\{\d+\}/).map(escapeRegExp).join(numeric ? "([\\d.,]+)" : "(.+?)") + "$"), translation,
  }));

  function translate(text, targetLanguage = language) {
    if (targetLanguage !== "en" || typeof text !== "string") return text;
    const value = text.trim();
    if (!value) return text;
    let result = Object.hasOwn(dictionary.messages, value) ? dictionary.messages[value] : undefined;
    if (result === undefined) {
      for (const {expression, translation} of patterns) {
        const match = value.match(expression);
        if (match) { result = translation.replace(/\{(\d+)\}/g, (_, n) => translate(match[Number(n) + 1], targetLanguage)); break; }
      }
    }
    // Joined category and metadata labels use the same vocabulary as controls.
    if (result === undefined && value.includes(" · ")) {
      const parts = value.split(" · ").map(part => translate(part, targetLanguage));
      if (parts.join(" · ") !== value) result = parts.join(" · ");
    }
    if (result === undefined && /[↗→↓↻:]$/.test(value)) {
      const prefix = value.slice(0, -1), translated = translate(prefix, targetLanguage);
      if (translated !== prefix) result = translated + value.slice(-1);
    }
    return result === undefined ? text : text.slice(0, text.indexOf(value)) + result + text.slice(text.indexOf(value) + value.length);
  }
  function update(node, key, value, write) {
    let source = originals.get(node);
    if (!source) { source = new Map(); originals.set(node, source); }
    const previous = source.get(key);
    const original = previous && previous.rendered === value ? previous.original : value;
    const rendered = translate(original);
    source.set(key, {original, rendered});
    if (rendered !== value) write(rendered);
  }
  function apply(root = document.body) {
    if (!root) return;
    const visit = node => {
      const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
      if (!element || element.closest(ignored)) return;
      if (node.nodeType === Node.TEXT_NODE) update(node, "text", node.data, value => { node.data = value; });
      else for (const name of attributes) if (node.hasAttribute(name)) {
        update(node, name, node.getAttribute(name), value => node.setAttribute(name, value));
      }
    };
    visit(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: node => node.nodeType === Node.ELEMENT_NODE && node.matches(ignored) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    while (walker.nextNode()) visit(walker.currentNode);
  }
  function syncDocument() {
    document.documentElement.lang = language === "en" ? "en" : "pt-BR";
    document.querySelector('meta[name="description"]').content = translate("Explore modelos, resultados e protocolos de avaliação da Maritaca.");
    document.querySelectorAll("[data-language]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.language === language)));
  }
  function setLanguage(value, {writeURL = true} = {}) {
    const next = normalize(value);
    if (!next || next === language) return;
    language = next;
    if (writeURL) {
      const url = new URL(location.href);
      url.searchParams.set("lang", language);
      history.replaceState(null, "", url);
    }
    syncDocument();
    window.dispatchEvent(new CustomEvent("observatory-languagechange"));
    apply();
  }
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-language]");
    if (button) setLanguage(button.dataset.language);
  });
  window.addEventListener("popstate", () => {
    setLanguage(normalize(new URL(location.href).searchParams.get("lang")) || "pt", {writeURL:false});
  });
  // Observe only content and accessible labels, never sky animation styles.
  const observer = new MutationObserver(mutations => {
    const roots = new Set();
    for (const mutation of mutations) {
      if (mutation.type === "childList") mutation.addedNodes.forEach(node => roots.add(node));
      else roots.add(mutation.target);
    }
    for (const root of roots) if (root.isConnected) apply(root);
  });
  syncDocument();
  document.title = translate(document.title);
  apply();
  observer.observe(document.body, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:attributes});
  return {get language() { return language; }, get locale() { return language === "en" ? "en-US" : "pt-BR"; }, t:translate, english:text=>translate(text,"en"), apply, setLanguage};
})();
