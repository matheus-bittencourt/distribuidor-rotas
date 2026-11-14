"use strict";
const $ = (id) => document.getElementById(id);
const state = { job: null, cfg: null, map: null, routes: [], okCount: 0, result: null, texts: [], sent: [], timers: {}, fromPrefs: false };
const NS = "http://www.w3.org/2000/svg";
const PREF_KEY = "distribuidor.prefs.v1";
const JOB_KEY = "distribuidor.job.v1";   // só o id do processamento, para sobreviver a um recarregamento da página

// ------------------------------------------------------------------ utilidades
function icon(name) {
  const s = document.createElementNS(NS, "svg"); s.setAttribute("class", "i");
  const u = document.createElementNS(NS, "use"); u.setAttribute("href", `#i-${name}`); s.append(u); return s;
}
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) e.append(kid instanceof Node ? kid : document.createTextNode(kid ?? ""));
  return e;
}
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
};
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Duração: "8 min" até uma hora, depois "2h32" (nunca "0h08", que parece horário de relógio).
const fmtMin = (m) => { m = Math.round(m); return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}`; };
const pct = (v) => `${Math.round(v * 100)}%`;
const show = (id, on = true) => { $(id).hidden = !on; };
const announce = (t) => { $("live").textContent = ""; setTimeout(() => ($("live").textContent = t), 30); };
// Matiz por ângulo áureo e luminosidade alternada; escurece até o texto branco passar de 4,5:1.
const _colors = [];
const _lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const _hsl = (h, s, l) => { s /= 100; l /= 100; const k = (n) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l), f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1))); return [f(0), f(8), f(4)].map((x) => Math.round(x * 255)); };
function color(i) {
  if (_colors[i]) return _colors[i];
  const h = Math.round((i * 137.508) % 360); let l = i % 2 ? 34 : 44;
  while (l > 16 && 1.05 / (_lum(_hsl(h, 62, l)) + 0.05) < 4.5) l -= 2;
  return (_colors[i] = `hsl(${h} 62% ${l}%)`);
}

function setStatus(id, text, kind = "") {
  const s = $(id); s.hidden = !text; s.textContent = text || ""; s.className = "status" + (kind ? ` ${kind}` : "");
}
function setStep(n) {
  document.querySelectorAll("#steps li").forEach((li) => {
    const k = +li.dataset.step, a = li.querySelector("a");
    li.className = k < n ? "done" : k === n ? "current" : "";
    a.setAttribute("aria-current", k === n ? "step" : "false");
    a.setAttribute("aria-disabled", k > n ? "true" : "false"); a.tabIndex = k > n ? -1 : 0;
  });
  document.querySelectorAll("#todo li").forEach((li) => { const k = +li.dataset.step; li.className = k < n ? "done" : k === n ? "current" : ""; });
}
function flash(btn, text, ms = 1800) {
  if (!btn._orig) btn._orig = [...btn.childNodes].map((n) => n.cloneNode(true));
  btn.textContent = text; clearTimeout(btn._t);
  btn._t = setTimeout(() => btn.replaceChildren(...btn._orig.map((n) => n.cloneNode(true))), ms);
}
// Confirmação em duas etapas, no próprio botão (sem alert/confirm nativos).
function twoStep(btn, armedText, action) {
  btn.addEventListener("click", () => {
    if (btn.classList.contains("armed")) { clearTimeout(btn._arm); btn.classList.remove("armed"); btn.textContent = btn.dataset.label; return action(); }
    btn.dataset.label = btn.textContent; btn.textContent = armedText; btn.classList.add("armed");
    btn._arm = setTimeout(() => { btn.classList.remove("armed"); btn.textContent = btn.dataset.label; }, 4000);
  });
}

// ------------------------------------------------------------------ preferências do operador (só neste navegador)
function loadPrefs() { try { return JSON.parse(localStorage.getItem(PREF_KEY)) || {}; } catch { return {}; } }
function savePrefs() {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify({
      drivers: $("drivers").value, n: $("n-drivers").value, by: $("balance-by").value,
      balance: $("balance").value, zone: $("zone").value, depot: $("depot").value, v: 4, kmtol: $("km-tol").value,
      tol: toleranceMin() === defaultToleranceMin() ? null : $("tolerance").value,
    }));
    show("saved-note");
  } catch { /* navegação privada: segue sem lembrar */ }
}
function forgetPrefs() { try { localStorage.removeItem(PREF_KEY); } catch {} $("drivers").value = ""; show("saved-note", false); updatePlan(); }

// ------------------------------------------------------------------ início
const BY_LABEL = { stops: "paradas", time: "tempo de rota", km: "km rodados" };
const BY_HELP = {
  km: "Prioriza igualar os km de cada entregador; entregas e tempo também são equilibrados, com peso menor. Igualar km aumenta o total rodado.",
  time: "Prioriza igualar o tempo de rota; km e entregas entram com peso menor.",
  stops: "Prioriza igualar a quantidade de paradas; km, entregas e tempo entram com peso menor.",
};
const METHOD = {
  "tabela": "local, sem IA", "modelo salvo": "formato salvo, sem IA", "colunas indicadas": "colunas indicadas por você",
  "ia-local": "IA local", "ia-anthropic": "IA (API)", "heuristica": "regras simples: confira os nomes",
};
const MASKED = { cpf: "CPF", cnpj: "CNPJ", valor: "valores", telefone: "telefones", email: "e-mails", data: "datas", numero_longo: "números longos" };

async function init() {
  state.cfg = await api("/api/config");
  const p = loadPrefs();
  $("depot").value = p.depot || state.cfg.default_depot;
  if (p.drivers) { $("drivers").value = p.drivers; show("saved-note"); }
  if (p.n) $("n-drivers").value = p.n;
  const fresh = p.v === 4;   // ajustes de divisão antigos (outra escala) não valem mais
  $("tolerance").value = fresh && p.tol != null ? p.tol : defaultToleranceMin();
  // vazio é uma escolha válida (igualar km); só vale se foi salvo nesta versão das preferências
  $("km-tol").value = fresh && p.kmtol !== undefined ? p.kmtol : Math.round((state.cfg.km_tolerance ?? 0) * 100) || "";
  if (fresh && p.by) $("balance-by").value = p.by;
  $("balance").value = fresh ? p.balance ?? 1 : 1;
  $("zone").value = Math.min(fresh ? p.zone ?? state.cfg.zone_weight : state.cfg.zone_weight, state.cfg.zone_weight_max ?? 0.15);
  state.fromPrefs = fresh && (p.by != null || p.balance != null);
  const ai = state.cfg.llm.startsWith("nenhuma") ? "sem IA: regras simples, menos precisas" : state.cfg.llm;
  $("s1ai").textContent = `PDF e texto livre: ${ai}.`;

  ["balance", "zone", "balance-by"].forEach((id) => $(id).addEventListener("input", () => { state.fromPrefs = false; }));
  ["balance", "zone", "balance-by", "drivers", "depot", "tolerance", "km-tol"].forEach((id) => $(id).addEventListener("input", updatePlan));
  // menu "Mais" fecha ao clicar fora ou com Esc
  document.addEventListener("click", (e) => document.querySelectorAll("details.more[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll("details.more[open]").forEach((d) => { d.open = false; d.querySelector("summary").focus(); }); });
  document.querySelectorAll("#steps a").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); if (a.getAttribute("aria-disabled") !== "true") $(a.hash.slice(1)).scrollIntoView({ behavior: "smooth", block: "start" }); }));
  twoStepGenerate();
  $("me").addEventListener("click", addMe);
  $("forget").addEventListener("click", forgetPrefs);
  $("map-go").addEventListener("click", sendMapping);
  $("solve").addEventListener("click", solve);
  $("copy-all-routes").addEventListener("click", (e) => copyAll("rota", e.currentTarget, "Todas as rotas copiadas"));
  $("copy-all-links").addEventListener("click", (e) => copyAll("links", e.currentTarget, "Todos os links copiados"));
  $("print-all").addEventListener("click", () => printSheets(state.result.drivers, "Rotas do dia"));
  twoStep($("wipe"), "Confirmar: apagar tudo", wipe);
  $("regeo").addEventListener("click", async () => {
    $("regeo").disabled = true;
    try { await post(`/api/jobs/${state.job}/regeocode`, {}); await refresh(); } finally { $("regeo").disabled = false; }
  });
  const drop = $("drop");
  $("file").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) upload(f); });
  ["dragover", "dragenter"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
  updatePlan();
  const saved = (() => { try { return sessionStorage.getItem(JOB_KEY); } catch { return null; } })();
  if (saved) await restore(saved);
}

// Recarregar a página não perde o resultado: o servidor guarda o processamento por até 2 h.
async function restore(id) {
  try {
    const j = await api(`/api/jobs/${id}`);
    state.job = id; show("wipe");
    if (j.state === "mapear") return renderMapping(j.mapping);
    if (j.state === "lendo" || j.state === "geocodificando") return pollIngest();
    if (j.state === "erro") { setStatus("s1status", j.error, "err"); return; }
    renderIngest(j);
    if (j.state === "calculando") return awaitResult();
    if (j.state === "pronto") renderResult(await api(`/api/jobs/${id}/result`));
  } catch { try { sessionStorage.removeItem(JOB_KEY); } catch {} }
}

function twoStepGenerate() {
  const nb = $("gen");
  nb.addEventListener("click", () => {
    if (!$("drivers").value.trim() || nb.classList.contains("armed")) {
      nb.classList.remove("armed"); nb.textContent = "Gerar lista"; return generateList();
    }
    nb.classList.add("armed"); nb.textContent = "Substituir a lista atual?";
    clearTimeout(nb._arm); nb._arm = setTimeout(() => { nb.classList.remove("armed"); nb.textContent = "Gerar lista"; }, 4000);
  });
}

function generateList() {
  const n = Math.max(1, Math.min(40, parseInt($("n-drivers").value) || 1));
  $("drivers").value = Array.from({ length: n }, (_, i) => `Entregador ${i + 1}`).join("\n");
  updatePlan();
}

// ------------------------------------------------------------------ etapa 1: arquivo
function resetPanels() {
  ["review-card", "s2", "s3", "map-card"].forEach((i) => show(i, false));
  show("s1report", false); $("undo").hidden = true; $("empty-busy").hidden = true; setStatus("s2status", ""); setStep(1);
}

async function upload(file) {
  if (state.job) await api(`/api/jobs/${state.job}`, { method: "DELETE" }).catch(() => {});
  resetPanels(); setStatus("s1status", "Enviando…");
  const fd = new FormData(); fd.append("file", file);
  try {
    const { job_id } = await api("/api/upload", { method: "POST", body: fd });
    state.job = job_id; show("wipe");
    try { sessionStorage.setItem(JOB_KEY, job_id); } catch {}
    await pollIngest();
  } catch (e) { setStatus("s1status", e.message, "err"); }
}

async function pollIngest() {
  for (;;) {
    const j = await api(`/api/jobs/${state.job}`);
    if (j.state === "erro") return setStatus("s1status", j.error, "err");
    if (j.state === "mapear") { setStatus("s1status", ""); return renderMapping(j.mapping); }
    if (j.state === "revisao") { setStatus("s1status", ""); show("map-card", false); return renderIngest(j); }
    const [a, b] = j.progress;
    setStatus("s1status", j.state === "geocodificando" && b ? `${j.message} (${a}/${b})` : j.message || "Processando…");
    await sleep(1200);
  }
}

function chip(text, kind = "") { return el("span", { class: "chip" + (kind ? ` ${kind}` : "") }, text); }

function renderIngest(j) {
  const c = j.counts, r = j.report;
  state.okCount = c.ok || 0;
  const box = $("s1report"); box.replaceChildren(); show("s1report");
  box.append(
    el("div", { class: "chips" },
      chip(`${c.ok || 0} localizados`, "ok"),
      chip(`${c.revisar || 0} para revisar`, c.revisar ? "warn" : ""),
      chip(`leitura: ${METHOD[r.method] || r.method}`),
      ...r.dropped_columns.map((d) => chip(`coluna ignorada: ${d}`)),
      ...Object.entries(r.masked).map(([k, v]) => chip(`${v} ${MASKED[k] || k} removidos do texto`)),
    ),
    ...r.notes.map((n) => el("p", { class: "hint" }, n)),
  );
  renderReview(j.review);
  show("s2"); setStep(2);
  if (!$("drivers").value.trim()) generateList();
  updatePlan();
}

async function refresh() { renderIngest(await api(`/api/jobs/${state.job}`)); }

function renderReview(list) {
  show("review-card", list.length > 0);
  $("review-count").textContent = `(${list.length})`;
  const box = $("review-list"); box.replaceChildren();
  for (const s of list) {
    const addr = el("input", { type: "text", value: s.address, "aria-label": `Endereço de ${s.name}` });
    const coords = el("input", { type: "text", placeholder: "lat, lon do Google Maps", "aria-label": `Coordenadas de ${s.name}` });
    const err = el("div", { class: "err", role: "alert", hidden: "" });
    const act = async (body, after) => {
      try { await api(`/api/jobs/${state.job}/stops/${s.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); if (after) after(); await refresh(); }
      catch (e) { err.textContent = e.message; err.hidden = false; }
    };
    box.append(el("div", { class: "row" },
      el("div", {}, el("div", { class: "who" }, s.name), el("div", { class: "why" }, s.reason)),
      addr, coords,
      el("div", { class: "btns" },
        el("button", { onclick: () => act({ address: addr.value }) }, "Buscar"),
        el("button", { onclick: () => (coords.value.trim() ? act({ coords: coords.value }) : ((err.textContent = "Cole as coordenadas no formato lat, lon."), (err.hidden = false))) }, "Usar coords"),
        el("button", { class: "ghost danger", onclick: () => act({ discard: true }, () => offerUndo(s)) }, "Descartar")),
      err,
    ));
  }
}

function offerUndo(s) {
  const bar = $("undo"); bar.hidden = false; bar.replaceChildren(
    el("span", {}, `Descartado: ${s.name}.`),
    el("button", { class: "link", onclick: async () => { clearTimeout(state.timers.undo); bar.hidden = true; await api(`/api/jobs/${state.job}/stops/${s.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ restore: true }) }); await refresh(); } }, "Desfazer"));
  clearTimeout(state.timers.undo); state.timers.undo = setTimeout(() => (bar.hidden = true), 10000);
}

// ------------------------------------------------------------------ mapeamento de colunas
const HEADER_GUESS = { name: /nome|cliente|destinat|quem|pessoa/i, addr: /endere|logradouro|rua|destino|local|ponto/i, code: /rastre|codigo|cod|etiqueta|objeto/i };
const CONTENT_GUESS = {
  addr: /\b(rua|r\.|av\.?|avenida|travessa|estrada|alameda|pra[cç]a|beco|rod\.?|rodovia)\b/i,
  name: /^[A-Za-zÀ-ÿ'.\- ]+\s[A-Za-zÀ-ÿ'.\- ]+$/,
  code: /^(?=.*\d)[A-Za-z0-9-]{5,}$/,
};
function guessColumns(m) {
  const usable = m.headers.filter((h) => !h.sensitive), used = new Set(), g = {};
  for (const k of ["addr", "name", "code"]) {
    const h = usable.find((h) => HEADER_GUESS[k].test(h.name) && !used.has(h.index));
    if (h) { g[k] = h.index; used.add(h.index); }
  }
  for (const k of ["addr", "name", "code"]) {
    if (g[k] != null) continue;
    let best = null, bestScore = 0.6;
    for (const h of usable) {
      if (used.has(h.index)) continue;
      const score = m.sample.filter((r) => CONTENT_GUESS[k].test((r[h.index] || "").trim())).length / Math.max(m.sample.length, 1);
      if (score >= bestScore) { best = h.index; bestScore = score; }
    }
    if (best != null) { g[k] = best; used.add(best); }
  }
  return g;
}
function renderMapping(m) {
  show("map-card"); setStatus("map-error", "");
  const head = el("tr", {}, ...m.headers.map((h) => el("th", { class: h.sensitive ? "sens" : "" }, h.sensitive ? icon("lock") : "", " ", h.name || `coluna ${h.index + 1}`)));
  const body = m.sample.map((r) => el("tr", {}, ...m.headers.map((h) => el("td", { class: h.sensitive ? "sens" : "" }, h.sensitive ? "oculto" : r[h.index] ?? ""))));
  $("map-table").replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
  const guess = guessColumns(m), main = ["addr", "name", "code"];
  for (const [boxId, keys] of [["map-main", main], ["map-extra", m.fields.map((f) => f.key).filter((k) => !main.includes(k))]]) {
    const box = $(boxId); box.replaceChildren();
    for (const key of keys) {
      const f = m.fields.find((x) => x.key === key);
      const sel = el("select", { id: `map-${key}`, "data-key": key }, el("option", { value: "" }, "não usar"),
        ...m.headers.filter((h) => !h.sensitive).map((h) => el("option", { value: h.index }, h.name || `coluna ${h.index + 1}`)));
      if (guess[key] != null) sel.value = guess[key];
      box.append(el("div", { class: "field" }, el("label", { for: `map-${key}` }, f.label + (key === "addr" ? " (obrigatório)" : "")), sel));
    }
  }
  $("map-card").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function sendMapping() {
  const columns = {};
  document.querySelectorAll("#map-card select[data-key]").forEach((s) => (columns[s.dataset.key] = s.value === "" ? null : parseInt(s.value)));
  if (columns.addr == null) return setStatus("map-error", "Escolha a coluna do endereço para continuar.", "err");
  try {
    await post(`/api/jobs/${state.job}/mapping`, { columns, header_row: $("map-header").checked, remember: $("map-remember").checked });
    show("map-card", false); setStatus("s1status", "Lendo com as colunas indicadas…"); await pollIngest();
  } catch (e) { setStatus("map-error", e.message, "err"); }
}

// ------------------------------------------------------------------ etapa 2: entregadores
function parseDrivers() {
  return $("drivers").value.split("\n").map((l) => l.trim()).filter(Boolean).map((line, i) => {
    const [label, ...rest] = line.split(";");   // "Nome" sozinho = sai do ponto padrão
    const where = rest.join(";").trim();
    const m = where.match(/^(-?\d{1,2}[.,]\d+)\s*[,; ]\s*(-?\d{1,3}[.,]\d+)$/);
    const start = !where ? {} : m ? { lat: parseFloat(m[1].replace(",", ".")), lon: parseFloat(m[2].replace(",", ".")) } : { address: where };
    return { label: label.trim() || `Entregador ${i + 1}`, start };
  });
}
// Tolerância por entrega, em minutos inteiros (0 a 30).
const defaultToleranceMin = () => Math.round((state.cfg.delivery_tolerance_seconds ?? 60) / 60);
const toleranceMin = () => Math.max(0, Math.min(30, Math.round(parseFloat($("tolerance").value) || 0)));
// Faixa de km em torno da média (fração) ou null = igualar os km.
const kmTolerance = () => { const v = parseFloat($("km-tol").value); return Number.isFinite(v) && v > 0 ? Math.min(v, 100) / 100 : null; };
const BY_WHAT = { stops: "o número de paradas", time: "o tempo de rota", km: "os km rodados" };
// O valor da barra é uma proporção entre dois objetivos que puxam em direções opostas.
function balanceScale(by) {
  return `0% = só agrupar por proximidade (menos km no total, carga desigual); 100% = redistribuir as paradas até igualar a carga, com prioridade para ${BY_WHAT[by]} (entregas e tempo também entram), mesmo que o total de km suba. Valores do meio aceitam alguma diferença para não subir tanto o total.`;
}
function balanceNow(b) {
  const now = b === 0 ? "sem equilíbrio: um entregador pode ficar com bem mais trabalho que outro."
    : b < 0.4 ? "equilíbrio leve: total de km baixo, mas a carga ainda varia bastante."
    : b < 0.75 ? "equilíbrio moderado."
    : "equilíbrio forte: carga bem parecida entre os entregadores, com mais km no total.";
  return `Agora (${pct(b)}): ${now}`;
}
const ZONE_SCALE = "A zona só desempata: com no máximo 15% de peso, a carga (km, entregas e tempo) vem antes. 0% ignora as zonas; 15% faz cada entregador preferir paradas da mesma zona quando isso não piora o equilíbrio.";
function zoneNow(z) {
  const now = z === 0 ? "as zonas são ignoradas."
    : z < 0.06 ? "zonas pesam pouco."
    : z < 0.11 ? "zonas pesam de forma moderada."
    : "peso máximo das zonas: ainda assim, a carga manda.";
  return `Agora (${pct(z)}): ${now}`;
}
function updatePlan() {
  const d = parseDrivers(), home = d.filter((x) => x.start.address || x.start.lat != null).length;
  const by = $("balance-by").value, b = parseFloat($("balance").value), z = parseFloat($("zone").value);
  $("balance-out").textContent = pct(b); $("zone-out").textContent = pct(z);
  $("balance").setAttribute("aria-valuetext", pct(b)); $("zone").setAttribute("aria-valuetext", pct(z));
  $("balance-help").textContent = BY_HELP[by];
  $("balance-now").textContent = balanceNow(b); $("balance-scale").textContent = balanceScale(by);
  $("zone-now").textContent = zoneNow(z); $("zone-scale").textContent = ZONE_SCALE;
  const tol = toleranceMin(), kt = kmTolerance();
  $("km-tol-help").textContent = kt === null
    ? "Vazio: o app tenta deixar os km parecidos entre os entregadores. Com um valor (ex.: 30), entregas e tempo viram o alvo e o km só não pode passar de ±30% da média: o total de km cai, mas os km deixam de ser parecidos."
    : `Entregas e tempo são o alvo; cada rota pode ter km até ${Math.round(kt * 100)}% acima ou abaixo da média sem penalidade.`;  $("adv-summary").textContent = `igualar ${BY_LABEL[by]} · ${pct(b)} · zonas ${pct(z)}${kt !== null ? ` · km ±${Math.round(kt * 100)}%` : ""} · tolerância ${tol} min${state.fromPrefs ? " · da última vez" : ""}`;
  $("drivers-count").textContent = d.length ? `${d.length} entregador${d.length > 1 ? "es" : ""}${home ? ` · ${home} saem de casa` : ""}` : "";
  const stops = state.okCount ? `${state.okCount} entregas` : "entregas";
  $("plan").textContent = !state.okCount ? "Nenhuma entrega localizada ainda: resolva os endereços para revisar."
    : !d.length ? "Informe pelo menos um entregador."
    : `${stops} para ${d.length} entregador${d.length > 1 ? "es" : ""}, igualando ${BY_LABEL[by]} (${pct(b)}), com ${tol} min de tolerância por entrega.`;
  $("solve").disabled = !d.length || !state.okCount || $("solve").dataset.busy === "1";
}
function addMe() {
  if (!navigator.geolocation) return setStatus("s2status", "Este navegador não oferece localização.", "err");
  navigator.geolocation.getCurrentPosition((p) => {
    const t = $("drivers"), n = parseDrivers().length + 1;
    t.value += `${t.value && !t.value.endsWith("\n") ? "\n" : ""}Entregador ${n}; ${p.coords.latitude.toFixed(6)}, ${p.coords.longitude.toFixed(6)}\n`;
    setStatus("s2status", ""); updatePlan();
  }, () => setStatus("s2status", "Não consegui obter a localização. Verifique a permissão do navegador.", "err"));
}

async function awaitResult() {
  for (;;) {
    await sleep(1500);
    const j = await api(`/api/jobs/${state.job}`);
    if (j.state === "erro") throw new Error(j.error);
    if (j.state === "pronto") break;
  }
  renderResult(await api(`/api/jobs/${state.job}/result`));
}

async function solve() {
  const drivers = parseDrivers();
  if (!drivers.length) return setStatus("s2status", "Informe pelo menos um entregador.", "err");
  savePrefs(); setStep(2);
  const btn = $("solve"); btn.dataset.busy = "1"; btn.disabled = true; show("s3", false);
  const t0 = Date.now(), budget = (state.cfg.solver_seconds || 30) + 15;
  const tick = () => {
    const msg = `Calculando as rotas… ${Math.round((Date.now() - t0) / 1000)} s (costuma levar até ~${budget} s)`;
    setStatus("s2status", msg); const b = $("empty-busy"); b.hidden = false; b.textContent = msg;
  };
  tick(); const timer = setInterval(tick, 1000);
  try {
    await post(`/api/jobs/${state.job}/solve`, {
      depot: { address: $("depot").value.trim() }, drivers, balance: parseFloat($("balance").value),
      balance_by: $("balance-by").value, zone_weight: parseFloat($("zone").value),
      tolerance_seconds: toleranceMin() * 60, km_tolerance: kmTolerance(),
    });
    await awaitResult();
    setStatus("s2status", "");
  } catch (e) { setStatus("s2status", e.message, "err"); }
  finally { clearInterval(timer); $("empty-busy").hidden = true; btn.dataset.busy = ""; updatePlan(); }
}

// ------------------------------------------------------------------ etapa 3: resultado
const SEP = "\n\n———\n\n";
// Mensagem 1: a rota (paradas na ordem). Mensagem 2: só os links do Maps. Enviadas em sequência.
function routeText(d, depotAddr) {
  const lines = [`*${d.label}* — ${d.count} paradas, ${d.deliveries} entregas (~${fmtMin(d.total_min)}, ~${Math.round(d.km)} km)`, ""];
  const one = (x) => `${x.name} — ${x.address}${x.code ? ` [${x.code}]` : ""}`;
  d.stops.forEach((s) => {
    if (s.n_deliveries > 1) { lines.push(`${s.order}. ${s.n_deliveries} entregas neste endereço:`); s.deliveries.forEach((x) => lines.push(`   • ${one(x)}`)); }
    else lines.push(`${s.order}. ${one(s)}`);
  });
  lines.push("", `Chegada: ${depotAddr || "ponto de chegada"}`, "", "Os links do Maps seguem na próxima mensagem.");
  return lines.join("\n");
}
function linksText(d) {
  const lines = [`*${d.label}* — links do Maps`, "Abra na ordem: o 1º parte da sua localização atual e cada seguinte começa onde o anterior terminou.", ""];
  d.links.forEach((l, i) => lines.push(`Trecho ${i + 1} (${l.first > l.last ? "última parada" : `paradas ${l.first}–${l.last}`}${l.ends_at_depot ? " → chegada" : ""}):`, l.url, ""));
  return lines.join("\n").trim();
}

// ---- cópia com estado persistente: o ✓ fica até recalcular, para o operador saber o que já mandou
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); announce("Texto copiado"); return true; }
  catch { showCopyFallback(text); return false; }
}
function showCopyFallback(text) {
  const dlg = $("copy-fallback"), ta = $("copy-fallback-text");
  ta.value = text; dlg.showModal(); ta.focus(); ta.select();
}
function markCopied(btn, label) { btn.classList.add("done"); btn.replaceChildren(icon("check"), " ", label); }
function refreshSent(i) {
  const row = document.querySelector(`.driver[data-i="${i}"]`); if (!row) return;
  const st = state.sent[i], chip = row.querySelector(".chip.sent");
  if (st.rota) markCopied(row.querySelector(".copy-rota"), "Rota copiada");
  if (st.links) markCopied(row.querySelector(".copy-links"), "Links copiados");
  chip.hidden = !(st.rota && st.links);
}
async function copyKind(i, kind) {
  if (await copyText(state.texts[i][kind])) { state.sent[i][kind] = true; refreshSent(i); }
}
async function copyAll(kind, btn, doneLabel) {
  if (!(await copyText(state.texts.map((t) => t[kind]).join(SEP)))) return;
  state.sent.forEach((st, i) => { st[kind] = true; refreshSent(i); });
  markCopied(btn, doneLabel);
}

// ---- impressão: lista completa, sem blocos de 10
function sheetFor(d, r) {
  const today = new Date().toLocaleDateString("pt-BR");
  const bodies = d.stops.map((s) => el("tbody", {}, ...s.deliveries.map((x, k) => el("tr", {},
    k === 0 ? el("td", { class: "c-n", rowspan: String(s.deliveries.length) }, String(s.order)) : "",
    el("td", {}, x.name), el("td", {}, x.address), el("td", {}, x.code),
    k === 0 ? el("td", { class: "c-eta", rowspan: String(s.deliveries.length) }, fmtMin(s.eta_min)) : "",
    el("td", { class: "c-ok" }, el("span", { class: "box" }))))));
  return el("section", { class: "sheet" },
    el("h1", {}, `Rota — ${d.label}`),
    el("p", { class: "meta" }, `${today} · ${d.count} paradas · ${d.deliveries} entregas · ~${fmtMin(d.total_min)} · ~${Math.round(d.km)} km`),
    el("p", { class: "meta" }, `Partida e chegada: ${r.depot.address || "ponto padrão"}`),
    el("table", {}, el("thead", {}, el("tr", {}, ...["#", "Nome", "Endereço", "Rastreio", "Chega em", "Entregue"].map((h) => el("th", {}, h)))), ...bodies),
    el("p", { class: "foot" }, "Tempos e km são estimativas. “Chega em” conta desde a saída."));
}
function printSheets(list, title) {
  const area = $("print-area"), oldTitle = document.title;
  area.replaceChildren(...list.map((d) => sheetFor(d, state.result)));
  document.title = title;
  const done = () => {
    area.replaceChildren(); document.title = oldTitle; window.removeEventListener("afterprint", done);
    if (state.map) setTimeout(() => state.map.invalidateSize(), 50);   // o mapa some durante a impressão
  };
  window.addEventListener("afterprint", done);
  window.print();
}

const range = (a) => (Math.min(...a) === Math.max(...a) ? `${Math.min(...a)}` : `${Math.min(...a)}–${Math.max(...a)}`);
const CRIT = { stops: "paradas", time: "tempo de rota", km: "km rodados" };

function renderResult(r) {
  show("s3"); setStep(3);
  const n = r.drivers.length, dr = r.drivers, by = r.balance_by || "stops";
  const counts = dr.map((d) => d.count), times = dr.map((d) => d.total_min), kms = dr.map((d) => d.km);
  const total = counts.reduce((a, b) => a + b, 0), all = dr.flatMap((d) => d.stops);
  const approxN = all.filter((s) => s.precision === "aproximado").length, mostApprox = all.length && approxN / all.length > 0.5;
  const estimated = r.matrix.startsWith("estimativa");
  const metric = (d) => (by === "km" ? d.km : by === "stops" ? d.count : d.total_min);
  const ms = dr.map(metric), mx = Math.max(...ms), mn = Math.min(...ms);
  const diff = mx ? Math.round(((mx - mn) / mx) * 100) : 0;
  const dsp = (arr) => { const m = Math.max(...arr), l = Math.min(...arr); return m ? Math.round(((m - l) / m) * 100) : 0; };
  const spreads = { km: dsp(kms), entregas: dsp(dr.map((d) => d.deliveries)), tempo: dsp(times) };
  // Com tolerância de km, o km é avaliado contra a faixa (±t da média permite até 2t/(1+t) entre menor e maior).
  const kt = r.km_tolerance, kmAllowed = kt ? Math.round(((2 * kt) / (1 + kt)) * 100) : null;
  const worst = Math.max(kt ? 0 : spreads.km, spreads.entregas, spreads.tempo);
  const verdictWord = worst <= 15 ? "bem equilibradas" : worst <= 30 ? "razoavelmente equilibradas" : "bem desiguais";

  const notes = [
    `Tempos e km ${estimated ? "estimados em linha reta (sem as ruas)" : "calculados pelas ruas"}`,
    `tempos com ${Math.round((r.tolerance_seconds ?? 0) / 60)} min de tolerância por entrega`,
    `${pct(r.zone_purity)} das paradas ficam na zona principal do entregador`,
  ];
  const multi = all.filter((s) => s.n_deliveries > 1).length;
  if (multi) notes.push(`${multi} paradas reúnem várias entregas no mesmo endereço (casa ou condomínio)`);
  $("summary").replaceChildren(
    el("p", { class: "headline" }, `${r.deliveries} entregas em ${total} paradas · ${n} rota${n > 1 ? "s" : ""}`),
    el("dl", { class: "ranges" },
      el("div", {}, el("dt", {}, "Paradas por entregador"), el("dd", {}, range(counts))),
      el("div", {}, el("dt", {}, "Entregas por entregador"), el("dd", {}, range(dr.map((d) => d.deliveries)))),
      el("div", {}, el("dt", {}, "Tempo por rota"), el("dd", {}, Math.min(...times) === Math.max(...times) ? fmtMin(times[0]) : `${fmtMin(Math.min(...times))}–${fmtMin(Math.max(...times))}`)),
      el("div", {}, el("dt", {}, `Km por entregador (soma ${Math.round(kms.reduce((a, b) => a + b, 0))})`), el("dd", {}, `${Math.round(Math.min(...kms))}–${Math.round(Math.max(...kms))} km`)),
    ),
    ...(n > 1 ? [el("p", { class: `verdict ${worst <= 30 ? "ok" : "warn"}` },
      `Rotas ${verdictWord}. Diferença entre a menor e a maior: km ${spreads.km}% · entregas ${spreads.entregas}% · tempo ${spreads.tempo}%.` +
      (kt ? ` O km tem tolerância de ±${Math.round(kt * 100)}%: ${spreads.km <= kmAllowed ? "dentro" : "fora"} da faixa (até ${kmAllowed}%).` : ""))] : []),
    el("p", { class: "note" }, notes.join(" · ") + "."),
    ...(mostApprox ? [el("div", { class: "status warn" }, icon("alert"),
      el("span", {}, `${approxN} de ${all.length} posições são aproximadas: só a rua foi localizada, então o ponto pode estar a algumas quadras. A ordem das paradas continua valendo.`))] : []),
    ...(r.unrouted.length ? [el("div", { class: "status warn" }, icon("alert"),
      el("span", {}, `${r.unrouted.length} entrega${r.unrouted.length > 1 ? "s ficaram" : " ficou"} de fora. Resolva em “Endereços para revisar” e calcule de novo.`))] : []),
  );
  $("legend").textContent = "Cada cor é uma rota e o número marca a primeira parada dela. Círculo grande = partida; pino azul = chegada. Linhas retas, não as ruas.";
  $("csv-all").href = `/api/jobs/${state.job}/export.csv`;
  state.texts = dr.map((d) => ({ rota: routeText(d, r.depot.address), links: linksText(d) }));
  state.sent = dr.map(() => ({ rota: false, links: false }));
  state.result = r;
  for (const [id, label] of [["copy-all-routes", "Copiar todas as rotas"], ["copy-all-links", "Copiar todos os links"]]) {
    const b = $(id); b.classList.remove("done"); b.replaceChildren(icon("copy"), " ", label);
  }
  drawMap(r);

  const maxM = Math.max(...ms, 1), box = $("drivers-out"); box.replaceChildren();
  dr.forEach((d, i) => {
    const body = el("div", { class: "body", hidden: "", id: `body-${i}` });
    const toggle = el("button", { class: "dtoggle", "aria-expanded": "false", "aria-controls": `body-${i}` }, el("strong", {}, d.label), icon("chevron"));
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") === "true";
      if (!open && !body.childElementCount) fillBody(body, d, mostApprox);
      toggle.setAttribute("aria-expanded", String(!open)); body.hidden = open;
    });
    const copyRoute = el("button", { class: "ghost copy-rota", "aria-label": `Copiar a mensagem da rota de ${d.label} para o WhatsApp` }, icon("copy"), " Copiar rota");
    const copyLinks = el("button", { class: "ghost copy-links", "aria-label": `Copiar a mensagem com os links do Maps de ${d.label} para o WhatsApp` }, icon("copy"), " Copiar links");
    copyRoute.addEventListener("click", () => copyKind(i, "rota"));
    copyLinks.addEventListener("click", () => copyKind(i, "links"));
    const more = el("details", { class: "more" },
      el("summary", { "aria-label": `Mais ações de ${d.label}` }, "Mais", icon("chevron")),
      el("div", { class: "menu" },
        el("button", { onclick: () => { more.open = false; printSheets([d], `Rota ${d.label}`); } }, icon("print"), " Imprimir lista completa"),
        el("a", { href: d.links[0].url, target: "_blank", rel: "noopener", onclick: () => (more.open = false) }, icon("map"), " Abrir trecho 1 no Maps (nova aba)"),
        el("a", { href: `/api/jobs/${state.job}/export.csv?driver=${d.index}`, onclick: () => (more.open = false) }, icon("download"), " CSV desta rota")));
    const zoneTxt = d.zones[0] ? `${d.zones[0].name}${d.zones.length > 1 ? ` +${d.zones.length - 1}` : ""}` : "sem paradas";
    const head = el("div", { class: "dhead" },
      el("span", { class: "swatch", style: `background:${color(i)}` }, String(i + 1)),
      el("div", { class: "dname" }, toggle, el("span", { class: "zone" }, zoneTxt, el("span", { class: "chip sent", hidden: "" }, "rota e links copiados"))),
      el("div", { class: "dnums" }, el("span", {}, `${d.count} paradas · ${d.deliveries} entregas`), el("span", {}, fmtMin(d.total_min)), el("span", {}, `${Math.round(d.km)} km`)),
      el("div", { class: "bar", role: "img", "aria-label": `${d.label}: ${CRIT[by]} em relação à maior rota, ${Math.round((metric(d) / maxM) * 100)}%`, style: `--bar:${color(i)}` }, el("i", { style: `width:${(metric(d) / maxM) * 100}%` })),
      el("div", { class: "dact" }, copyRoute, copyLinks, more),
    );
    const row = el("article", { class: "driver", "data-i": String(i) }, head, body);
    head.addEventListener("mouseenter", () => highlight(i)); head.addEventListener("mouseleave", () => highlight(null));
    head.addEventListener("focusin", () => highlight(i)); head.addEventListener("focusout", () => highlight(null));
    box.append(row);
  });
  $("s3").scrollIntoView({ behavior: "smooth", block: "start" });
}

function fillBody(body, d, mostApprox) {
  const links = el("div", { class: "links" }, ...d.links.map((l, k) =>
    el("a", { href: l.url, target: "_blank", rel: "noopener" },
      l.first > l.last ? `Trecho ${k + 1} · última parada → chegada` : `Trecho ${k + 1} · paradas ${l.first}–${l.last}${l.ends_at_depot ? " → chegada" : ""}`)));
  const rows = d.stops.map((s) => {
    const multi = s.n_deliveries > 1, approx = !mostApprox && s.precision === "aproximado";
    const mark = el("span", { class: "approx" }, " ", icon("alert"), " aproximada");
    // Várias entregas: cada uma é um bloco (nome, endereço, código) com linha própria no cartão do celular (--r).
    const cell = (cls, pick, single) => el("td", { class: cls },
      multi ? s.deliveries.map((x, j) => el("div", { class: "d", style: `--r:${3 * j}` }, pick(x), cls === "c-addr" && j === 0 && approx ? mark.cloneNode(true) : "")) : single,
      !multi && cls === "c-addr" && approx ? mark : "");
    return el("tr", multi ? { class: "multi", style: `--span:${3 * s.n_deliveries}` } : {},
      el("td", { class: "num c-n" }, s.order, multi ? el("span", { class: "badge" }, `${s.n_deliveries}×`) : ""),
      cell("c-name", (x) => x.name, s.name), cell("c-addr", (x) => x.address, s.address), cell("c-code", (x) => x.code, s.code),
      el("td", { class: "num c-leg" }, `+${Math.round(s.leg_min)} min · ${s.leg_km.toFixed(1)} km`),
      el("td", { class: "num c-eta" }, fmtMin(s.eta_min)));
  });
  body.append(el("p", { class: "hint" }, "Links do Maps (abra na ordem):"), links,
    el("table", { class: "stops" },
      el("thead", {}, el("tr", {}, ...["#", "Nome", "Endereço", "Rastreio", "Trecho", "Chega em"].map((h, k) => el("th", { class: [0, 4, 5].includes(k) ? "num" : "" }, h)))),
      el("tbody", {}, rows)));
}

function setMapExpanded(on) {
  document.querySelector(".s3-map").classList.toggle("expanded", on);
  document.body.classList.toggle("map-open", on);
  const b = $("map-expand"); b.textContent = on ? "Fechar mapa (Esc)" : "Expandir mapa"; b.setAttribute("aria-pressed", on);
  if (state.map) { setTimeout(() => state.map.invalidateSize(), 50); }
}
$("map-expand").addEventListener("click", () => setMapExpanded(!document.querySelector(".s3-map").classList.contains("expanded")));
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && document.body.classList.contains("map-open")) setMapExpanded(false); });

function drawMap(r) {
  if (!state.map) {
    state.map = L.map("map", { preferCanvas: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(state.map);
  }
  state.routes.forEach((o) => o.layers.forEach((l) => l.remove())); state.routes = [];
  const all = [[r.depot.lat, r.depot.lon]];
  r.drivers.forEach((d, i) => {
    const c = color(i), pts = [[d.start.lat, d.start.lon], ...d.stops.map((s) => [s.lat, s.lon]), [r.depot.lat, r.depot.lon]];
    const line = L.polyline(pts, { color: c, weight: 2, opacity: 0.6 }).addTo(state.map);
    const dots = d.stops.map((s) => L.circleMarker([s.lat, s.lon], { radius: 4, color: c, fillColor: c, fillOpacity: 0.9, weight: 1 })
      .bindTooltip(`${d.label} · #${s.order}`).addTo(state.map));
    const layers = [line, ...dots];
    if (d.stops[0]) {
      const pin = L.marker([d.stops[0].lat, d.stops[0].lon], { icon: L.divIcon({ className: "", html: `<div class="num-pin" style="background:${c}">${i + 1}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] }) })
        .bindTooltip(`${d.label}: primeira parada`).addTo(state.map);
      layers.push(pin);
    }
    const start = L.circleMarker(pts[0], { radius: 8, color: "#000", fillColor: c, fillOpacity: 1, weight: 2 }).bindTooltip(`Partida: ${d.label}`).addTo(state.map);
    layers.push(start);
    state.routes.push({ line, dots, layers });
    all.push(...pts);
  });
  const end = L.marker([r.depot.lat, r.depot.lon]).bindTooltip("Chegada").addTo(state.map);
  state.routes.push({ line: null, dots: [], layers: [end] });
  // Enquadra assim que o mapa tiver tamanho real (o painel acabou de aparecer e o layout ainda assenta).
  state.fitPending = all;
  const fit = () => {
    if (!state.fitPending || !$("map").clientWidth) return;
    state.map.invalidateSize(); state.map.fitBounds(state.fitPending, { padding: [20, 20] }); state.fitPending = null;
  };
  if (!state.mapObserver) { state.mapObserver = new ResizeObserver(fit); state.mapObserver.observe($("map")); }
  requestAnimationFrame(fit); setTimeout(fit, 300);
}
function highlight(i) {
  state.routes.forEach((o, k) => {
    if (!o.line) return;
    const on = i === null || i === k;
    o.line.setStyle({ opacity: on ? (i === k ? 0.95 : 0.6) : 0.08, weight: i === k ? 3.5 : 2 });
    o.dots.forEach((d) => d.setStyle({ opacity: on ? 1 : 0.1, fillOpacity: on ? 0.9 : 0.1 }));
  });
}

// ------------------------------------------------------------------ apagar
async function wipe() {
  if (!state.job) return;
  await api(`/api/jobs/${state.job}`, { method: "DELETE" }).catch(() => {});
  state.job = null; state.okCount = 0; state.result = null; state.texts = []; state.sent = [];
  try { sessionStorage.removeItem(JOB_KEY); } catch {}
  state.routes.forEach((o) => o.layers.forEach((l) => l.remove())); state.routes = [];
  resetPanels(); show("wipe", false);
  setStatus("s1status", "Pronto: lista, nomes, endereços e rotas foram apagados da memória. O elenco salvo neste navegador não foi tocado.", "ok");
  announce("Dados da sessão apagados");
}

init().catch((e) => setStatus("s1status", e.message, "err"));
