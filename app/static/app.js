"use strict";
const $ = (id) => document.getElementById(id);
const state = { job: null, cfg: null, map: null, routes: [], okCount: 0, result: null, texts: [], timers: {} };
const NS = "http://www.w3.org/2000/svg";
const PREF_KEY = "distribuidor.prefs.v1";

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
const fmtMin = (m) => `${Math.floor(m / 60)}h${String(Math.round(m % 60)).padStart(2, "0")}`;
const pct = (v) => `${Math.round(v * 100)}%`;
const show = (id, on = true) => { $(id).hidden = !on; };
const announce = (t) => { $("live").textContent = ""; setTimeout(() => ($("live").textContent = t), 30); };
// Matiz por ângulo áureo e duas luminosidades alternadas: 14+ rotas continuam distinguíveis.
const color = (i) => `hsl(${Math.round((i * 137.508) % 360)} 62% ${i % 2 ? 36 : 46}%)`;

function setStatus(id, text, kind = "") {
  const s = $(id); s.hidden = !text; s.textContent = text || ""; s.className = "status" + (kind ? ` ${kind}` : "");
}
function setStep(n) {
  document.querySelectorAll("#steps li").forEach((li) => {
    const k = +li.dataset.step;
    li.className = k < n ? "done" : k === n ? "current" : "";
    li.setAttribute("aria-current", k === n ? "step" : "false");
  });
}
function flash(btn, text, ms = 1800) {
  const old = btn.dataset.label || btn.textContent;
  btn.dataset.label = old; btn.textContent = text; clearTimeout(btn._t);
  btn._t = setTimeout(() => (btn.textContent = old), ms);
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
      balance: $("balance").value, zone: $("zone").value, depot: $("depot").value,
    }));
    show("saved-note");
  } catch { /* navegação privada: segue sem lembrar */ }
}
function forgetPrefs() { try { localStorage.removeItem(PREF_KEY); } catch {} $("drivers").value = ""; show("saved-note", false); updatePlan(); }

// ------------------------------------------------------------------ início
const BY_LABEL = { stops: "paradas", time: "tempo de rota", km: "km rodados" };
const BY_HELP = {
  stops: "Cada entregador recebe quase o mesmo número de entregas.",
  time: "Cada um termina a rota em tempo parecido; quem mora longe ou atende zona espalhada recebe menos paradas.",
  km: "Cada um roda uma distância parecida; a soma de km tende a subir e o número de paradas varia bastante.",
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
  if (p.by) $("balance-by").value = p.by;
  $("balance").value = p.balance ?? 0.7; $("zone").value = p.zone ?? state.cfg.zone_weight;
  const ai = state.cfg.llm.startsWith("nenhuma") ? "sem IA: regras simples, menos precisas" : state.cfg.llm;
  $("s1ai").textContent = `PDF e texto livre: ${ai}.`;

  ["balance", "zone", "balance-by", "drivers", "depot"].forEach((id) => $(id).addEventListener("input", updatePlan));
  twoStepGenerate();
  $("me").addEventListener("click", addMe);
  $("forget").addEventListener("click", forgetPrefs);
  $("map-go").addEventListener("click", sendMapping);
  $("solve").addEventListener("click", solve);
  $("copy-all").addEventListener("click", (e) => copyText(state.texts.join("\n\n———\n\n"), e.currentTarget, "Copiar todos os textos"));
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
  show("s1report", false); setStatus("undo", ""); setStatus("s2status", ""); setStep(1);
}

async function upload(file) {
  if (state.job) await api(`/api/jobs/${state.job}`, { method: "DELETE" }).catch(() => {});
  resetPanels(); setStatus("s1status", "Enviando…");
  const fd = new FormData(); fd.append("file", file);
  try {
    const { job_id } = await api("/api/upload", { method: "POST", body: fd });
    state.job = job_id; show("wipe");
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
  const bar = $("undo"); bar.className = "status"; bar.hidden = false; bar.replaceChildren(
    el("span", { class: "grow" }, `Descartado: ${s.name}.`),
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
function updatePlan() {
  const d = parseDrivers(), home = d.filter((x) => x.start.address || x.start.lat != null).length;
  const by = $("balance-by").value, b = parseFloat($("balance").value), z = parseFloat($("zone").value);
  $("balance-out").textContent = pct(b); $("zone-out").textContent = pct(z);
  $("balance").setAttribute("aria-valuetext", pct(b)); $("zone").setAttribute("aria-valuetext", pct(z));
  $("balance-help").textContent = BY_HELP[by];
  $("adv-summary").textContent = `igualar ${BY_LABEL[by]} · ${pct(b)} · zonas ${pct(z)}`;
  $("drivers-count").textContent = d.length ? `${d.length} entregador${d.length > 1 ? "es" : ""}${home ? ` · ${home} saem de casa` : ""}` : "";
  const stops = state.okCount ? `${state.okCount} paradas` : "paradas";
  $("plan").textContent = d.length ? `${stops} para ${d.length} entregador${d.length > 1 ? "es" : ""}, igualando ${BY_LABEL[by]} (${pct(b)}).` : "Informe pelo menos um entregador.";
  $("solve").disabled = !d.length || $("solve").dataset.busy === "1";
}
function addMe() {
  if (!navigator.geolocation) return setStatus("s2status", "Este navegador não oferece localização.", "err");
  navigator.geolocation.getCurrentPosition((p) => {
    const t = $("drivers"), n = parseDrivers().length + 1;
    t.value += `${t.value && !t.value.endsWith("\n") ? "\n" : ""}Entregador ${n}; ${p.coords.latitude.toFixed(6)}, ${p.coords.longitude.toFixed(6)}\n`;
    setStatus("s2status", ""); updatePlan();
  }, () => setStatus("s2status", "Não consegui obter a localização. Verifique a permissão do navegador.", "err"));
}

async function solve() {
  const drivers = parseDrivers();
  if (!drivers.length) return setStatus("s2status", "Informe pelo menos um entregador.", "err");
  savePrefs();
  const btn = $("solve"); btn.dataset.busy = "1"; btn.disabled = true; show("s3", false);
  const t0 = Date.now(), budget = (state.cfg.solver_seconds || 30) + 10;
  const tick = () => setStatus("s2status", `Calculando as rotas… ${Math.round((Date.now() - t0) / 1000)} s (costuma levar até ${budget} s)`);
  tick(); const timer = setInterval(tick, 1000);
  try {
    await post(`/api/jobs/${state.job}/solve`, {
      depot: { address: $("depot").value.trim() }, drivers, balance: parseFloat($("balance").value),
      balance_by: $("balance-by").value, zone_weight: parseFloat($("zone").value),
    });
    for (;;) {
      await sleep(1500);
      const j = await api(`/api/jobs/${state.job}`);
      if (j.state === "erro") throw new Error(j.error);
      if (j.state === "pronto") break;
    }
    setStatus("s2status", "");
    renderResult(await api(`/api/jobs/${state.job}/result`));
  } catch (e) { setStatus("s2status", e.message, "err"); }
  finally { clearInterval(timer); btn.dataset.busy = ""; updatePlan(); }
}

// ------------------------------------------------------------------ etapa 3: resultado
function whatsappText(d, depotAddr) {
  const lines = [`*${d.label}* — ${d.count} paradas (~${fmtMin(d.total_min)}, ~${Math.round(d.km)} km)`, ""];
  d.stops.forEach((s) => lines.push(`${s.order}. ${s.name} — ${s.address}${s.code ? ` [${s.code}]` : ""}`));
  lines.push("", `Chegada: ${depotAddr || "ponto de chegada"}`, "", "Mapas (siga na ordem):");
  d.links.forEach((l, i) => lines.push(`Trecho ${i + 1} (${l.first > l.last ? "última parada" : `paradas ${l.first}–${l.last}`}${l.ends_at_depot ? " → chegada" : ""}): ${l.url}`));
  return lines.join("\n");
}
async function copyText(text, btn, label) {
  try { await navigator.clipboard.writeText(text); flash(btn, "Copiado", 1800); announce("Texto copiado"); }
  catch { flash(btn, "Não foi possível copiar", 2500); }
  btn.dataset.label = label;
}
const range = (a) => (Math.min(...a) === Math.max(...a) ? `${Math.min(...a)}` : `${Math.min(...a)}–${Math.max(...a)}`);

function renderResult(r) {
  show("s3"); setStep(3);
  const n = r.drivers.length, dr = r.drivers;
  const counts = dr.map((d) => d.count), times = dr.map((d) => d.total_min), kms = dr.map((d) => d.km);
  const total = counts.reduce((a, b) => a + b, 0), all = dr.flatMap((d) => d.stops);
  const approxN = all.filter((s) => s.precision === "aproximado").length, mostApprox = all.length && approxN / all.length > 0.5;
  const estimated = r.matrix.startsWith("estimativa");

  const notes = [
    `Tempos e km ${estimated ? "estimados em linha reta (sem as ruas)" : "calculados pelas ruas"}`,
    `${pct(r.zone_purity)} das paradas ficam na zona principal do entregador`,
  ];
  if (mostApprox) notes.push(`${approxN} de ${all.length} posições são aproximadas (só a rua foi localizada)`);
  $("summary").replaceChildren(
    el("p", { class: "headline" }, `${total} paradas em ${n} rota${n > 1 ? "s" : ""}`),
    el("dl", { class: "ranges" },
      el("div", {}, el("dt", {}, "Paradas por entregador"), el("dd", {}, range(counts))),
      el("div", {}, el("dt", {}, "Tempo por rota"), el("dd", {}, Math.min(...times) === Math.max(...times) ? fmtMin(times[0]) : `${fmtMin(Math.min(...times))}–${fmtMin(Math.max(...times))}`)),
      el("div", {}, el("dt", {}, `Km por entregador (soma ${Math.round(kms.reduce((a, b) => a + b, 0))})`), el("dd", {}, `${Math.round(Math.min(...kms))}–${Math.round(Math.max(...kms))} km`)),
    ),
    el("p", { class: "note" }, notes.join(" · ") + "."),
    ...(r.unrouted.length ? [el("div", { class: "status warn" }, icon("alert"),
      el("span", {}, `${r.unrouted.length} entrega${r.unrouted.length > 1 ? "s ficaram" : " ficou"} de fora. Resolva em “Endereços para revisar” e calcule de novo.`))] : []),
  );
  $("legend").textContent = "Cada cor é uma rota e o número marca a primeira parada dela. Círculo grande = partida; pino azul = chegada. Linhas retas, não as ruas.";
  $("csv-all").href = `/api/jobs/${state.job}/export.csv`;
  state.texts = dr.map((d) => whatsappText(d, r.depot.address));
  drawMap(r);

  const maxTime = Math.max(...times, 1), box = $("drivers-out"); box.replaceChildren();
  dr.forEach((d, i) => {
    const body = el("div", { class: "body", hidden: "", id: `body-${i}` });
    const toggle = el("button", { class: "ghost", "aria-expanded": "false", "aria-controls": `body-${i}` }, "Paradas ", icon("chevron"));
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") === "true";
      if (!open && !body.childElementCount) fillBody(body, d, mostApprox);
      toggle.setAttribute("aria-expanded", String(!open)); body.hidden = open;
    });
    const copy = el("button", { class: "ghost" }, icon("copy"), " Copiar WhatsApp");
    copy.addEventListener("click", () => copyText(state.texts[i], copy, "Copiar WhatsApp"));
    const head = el("div", { class: "dhead" },
      el("span", { class: "swatch", style: `background:${color(i)}` }, String(i + 1)),
      el("div", { class: "dname" }, el("strong", {}, d.label), el("span", { class: "zone" }, d.zones[0] ? `${d.zones[0].name}${d.zones.length > 1 ? ` +${d.zones.length - 1}` : ""}` : "sem paradas")),
      el("div", { class: "dnums" }, el("span", {}, `${d.count} paradas`), el("span", {}, fmtMin(d.total_min)), el("span", {}, `${Math.round(d.km)} km`)),
      el("div", { class: "bar", role: "img", "aria-label": `Tempo de ${d.label} em relação à rota mais longa: ${Math.round((d.total_min / maxTime) * 100)}%`, style: `--bar:${color(i)}` }, el("i", { style: `width:${(d.total_min / maxTime) * 100}%` })),
      el("div", { class: "dact" }, copy, el("a", { class: "btn ghost", href: d.links[0].url, target: "_blank", rel: "noopener" }, icon("map"), " Maps 1"), toggle),
    );
    const row = el("article", { class: "driver" }, head, body);
    head.addEventListener("mouseenter", () => highlight(i)); head.addEventListener("mouseleave", () => highlight(null));
    head.addEventListener("focusin", () => highlight(i)); head.addEventListener("focusout", () => highlight(null));
    box.append(row);
  });
  $("s3").scrollIntoView({ behavior: "smooth", block: "start" });
}

function fillBody(body, d, mostApprox) {
  const links = el("div", { class: "links" }, ...d.links.map((l, k) =>
    el("a", { href: l.url, target: "_blank", rel: "noopener" },
      l.first > l.last ? `Maps trecho ${k + 1} · última parada → chegada` : `Maps trecho ${k + 1} · paradas ${l.first}–${l.last}${l.ends_at_depot ? " → chegada" : ""}`)));
  const rows = d.stops.map((s) => el("tr", {},
    el("td", { class: "num c-n" }, s.order), el("td", { class: "c-name" }, s.name),
    el("td", { class: "c-addr" }, s.address, !mostApprox && s.precision === "aproximado" ? el("span", { class: "approx" }, " ", icon("alert"), " aproximada") : ""),
    el("td", { class: "c-code" }, s.code),
    el("td", { class: "num c-leg" }, `+${Math.round(s.leg_min)} min · ${s.leg_km.toFixed(1)} km`),
    el("td", { class: "num c-eta" }, fmtMin(s.eta_min))));
  body.append(links, el("div", { class: "actions" }, el("a", { class: "btn ghost", href: `/api/jobs/${state.job}/export.csv?driver=${d.index}` }, icon("download"), " CSV desta rota")),
    el("table", { class: "stops" },
      el("thead", {}, el("tr", {}, ...["#", "Nome", "Endereço", "Rastreio", "Trecho", "Chega em"].map((h, k) => el("th", { class: [0, 4, 5].includes(k) ? "num" : "" }, h)))),
      el("tbody", {}, rows)));
}

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
  requestAnimationFrame(() => { state.map.invalidateSize(); state.map.fitBounds(all, { padding: [20, 20] }); });
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
  state.job = null; state.okCount = 0; state.result = null; state.texts = [];
  state.routes.forEach((o) => o.layers.forEach((l) => l.remove())); state.routes = [];
  resetPanels(); show("wipe", false);
  setStatus("s1status", "Pronto: lista, nomes, endereços e rotas foram apagados da memória. O elenco salvo neste navegador não foi tocado.", "ok");
  announce("Dados da sessão apagados");
}

init().catch((e) => setStatus("s1status", e.message, "err"));
