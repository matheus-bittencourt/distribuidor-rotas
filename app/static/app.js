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
// Cores das rotas: 14 famílias diferentes escolhidas à mão (nada de três verdes seguidos), em ordem que
// afasta as parecidas (azul, marinho e anil ficam longe um do outro). Todas com texto branco ≥4,5:1.
// Acima de 14 entregadores: matiz por ângulo áureo, escurecida até o branco passar de 4,5:1.
const PALETTE = ["#1d4ed8", "#c2410c", "#15803d", "#7e22ce", "#b91c1c", "#0e7490", "#a21caf",
  "#78350f", "#be185d", "#4d7c0f", "#1e3a8a", "#475569", "#0f766e", "#4338ca"];
const _colors = [];
const _lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const _hsl = (h, s, l) => { s /= 100; l /= 100; const k = (n) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l), f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1))); return [f(0), f(8), f(4)].map((x) => Math.round(x * 255)); };
function color(i) {
  if (i < PALETTE.length) return PALETTE[i];
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
    a.setAttribute("aria-disabled", k > n ? "true" : "false");
    // etapa ainda fechada: diz o que falta, em vez de só aparecer apagada
    a.title = k > n ? (k === 2 ? "Disponível depois de carregar a lista do dia" : "Disponível depois de calcular as rotas") : "";
  });
}
function flash(btn, text, ms = 1800) {
  if (!btn._orig) btn._orig = [...btn.childNodes].map((n) => n.cloneNode(true));
  btn.textContent = text; clearTimeout(btn._t);
  btn._t = setTimeout(() => btn.replaceChildren(...btn._orig.map((n) => n.cloneNode(true))), ms);
}
// Confirmação em duas etapas, no próprio botão (sem alert/confirm nativos). O 2º toque só vale depois de 0,6 s
// (dois toques seguidos não confirmam) e o botão volta ao normal sozinho em 6 s; também desarma ao sair do botão
// ou com Esc. O estado é anunciado para leitores de tela.
function twoStep(btn, armedText, action, armedHint = "Clique de novo para confirmar (vale por 6 segundos), ou Esc para cancelar.") {
  const disarm = () => { clearTimeout(btn._t); if (!btn.classList.contains("armed")) return; btn.classList.remove("armed"); btn.textContent = btn.dataset.label; };
  btn.addEventListener("click", () => {
    if (btn.classList.contains("armed")) {
      if (Date.now() - btn._armedAt < 600) return;
      disarm(); return action();
    }
    btn.dataset.label = btn.textContent; btn.textContent = armedText; btn.classList.add("armed");
    btn._armedAt = Date.now(); btn._t = setTimeout(disarm, 6000);
    announce(`${armedText}. ${armedHint}`);
  });
  btn.addEventListener("blur", () => setTimeout(disarm, 150));
  btn.addEventListener("keydown", (e) => { if (e.key === "Escape") disarm(); });
  btn._disarm = disarm;
}

// ------------------------------------------------------------------ preferências do operador (só neste navegador)
function loadPrefs() { try { return JSON.parse(localStorage.getItem(PREF_KEY)) || {}; } catch { return {}; } }
function savePrefs() {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify({
      drivers: $("drivers").value, n: $("n-drivers").value, by: $("balance-by").value,
      balance: $("balance").value, zone: $("zone").value, depot: $("depot").value, v: 4, kmtol: $("km-tol").value, ped: $("ped-on").checked, pedstart: $("ped-start").value.trim(), traffic: $("traffic").value,
      tol: toleranceMin() === defaultToleranceMin() ? null : $("tolerance").value,
    }));
    show("saved-note");
  } catch { /* navegação privada: segue sem lembrar */ }
}
// Depois do primeiro envio completo (todos com rota e links), as dicas de primeiro uso recolhem.
// A ajuda continua a um clique: "Como usar", "Como ler esta tela" e os resumos curtos.
const SEASON_KEY = "distribuidor.experiente.v1";
function seasoned() { try { return localStorage.getItem(SEASON_KEY) === "1"; } catch { return false; } }
function markSeasoned() {
  if (seasoned()) return;
  try { localStorage.setItem(SEASON_KEY, "1"); } catch {}
  document.body.classList.add("seasoned");
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
  try { history.scrollRestoration = "manual"; } catch {}   // o app decide onde a tela começa (ex.: nas rotas)
  if (matchMedia("(pointer: coarse)").matches) document.querySelector("#drop strong").textContent = "Escolha o arquivo";   // no celular não se arrasta
  document.body.classList.toggle("seasoned", seasoned());
  state.cfg = await api("/api/config");
  const p = loadPrefs();
  $("depot").value = p.depot || state.cfg.default_depot;
  $("ped-field").hidden = state.cfg.pedestrian === false;
  $("ped-on").checked = p.ped !== false; $("ped-start").value = p.pedstart || ""; $("traffic").value = ["1", "1.2", "1.4"].includes(p.traffic) ? p.traffic : "1";
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
  $("s1ai").textContent = state.cfg.llm.startsWith("nenhuma")
    ? "PDF de intimações é lido pelo modelo fixo. Outros PDFs e texto livre são lidos por regras simples, sem IA: confira os nomes."
    : `PDF de intimações é lido pelo modelo fixo. Outros PDFs e texto livre são lidos com ${state.cfg.llm}.`;

  ["balance", "zone", "balance-by"].forEach((id) => $(id).addEventListener("input", () => { state.fromPrefs = false; }));
  ["balance", "zone", "balance-by", "drivers", "depot", "tolerance", "km-tol", "ped-on", "ped-start", "traffic"].forEach((id) => $(id).addEventListener("input", updatePlan));
  $("drivers").addEventListener("change", refreshPhones);
  // menu "Mais" fecha ao clicar fora ou com Esc
  document.addEventListener("click", (e) => document.querySelectorAll("details.more[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; }));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.querySelectorAll("details.more[open]").forEach((d) => { d.open = false; d.querySelector("summary").focus(); }); });
  document.querySelectorAll("#steps a").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); if (a.getAttribute("aria-disabled") !== "true") $(a.hash.slice(1)).scrollIntoView({ behavior: "smooth", block: "start" }); }));
  twoStepGenerate();
  $("me").addEventListener("click", addMe);
  $("forget").addEventListener("click", forgetPrefs);
  $("map-go").addEventListener("click", sendMapping);
  $("solve").addEventListener("click", solveClick);
  $("solve").addEventListener("blur", () => setTimeout(disarmSolve, 150));
  $("solve").addEventListener("keydown", (e) => { if (e.key === "Escape") disarmSolve(); });
  $("copy-all-routes").addEventListener("click", (e) => copyAll("rota", e.currentTarget, "Todas as rotas copiadas"));
  $("copy-all-links").addEventListener("click", (e) => copyAll("links", e.currentTarget, "Todos os links copiados"));
  $("print-all").addEventListener("click", () => { $("bulk").open = false; printSheets(state.result.drivers, "Rotas do dia"); });
  $("copy-next").addEventListener("click", copyNext);
  twoStep($("wipe"), "Confirmar: apagar tudo", wipe);
  twoStep($("wipe-end"), "Confirmar: apagar tudo", wipe);
  initPresets();
  $("regeo").addEventListener("click", async () => {
    $("regeo").disabled = true;
    try { await post(`/api/jobs/${state.job}/regeocode`, {}); await refresh(); } finally { $("regeo").disabled = false; }
  });
  $("copy-fallback").addEventListener("close", (e) => {
    const dlg = e.target, fn = dlg._onPasted; dlg._onPasted = null;
    if (dlg.returnValue === "done" && fn) fn();
    dlg.returnValue = "";
  });
  fabInit();
  // etapa ainda fechada: focável e anunciada como indisponível, mas sem levar a lugar nenhum
  $("steps").addEventListener("click", (e) => { const a = e.target.closest("a"); if (a && a.getAttribute("aria-disabled") === "true") e.preventDefault(); });
  const drop = $("drop");
  $("file").addEventListener("change", (e) => { const fs = [...e.target.files]; e.target.value = ""; if (fs.length) upload(fs); });
  ["dragover", "dragenter"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files.length && upload([...e.dataTransfer.files]));
  updatePlan();
  const saved = (() => { try { return sessionStorage.getItem(JOB_KEY); } catch { return null; } })();
  if (saved) await restore(saved);
  guideInit();
  mapInit();
  zonesInit();
}

// ------------------------------------------------------------------ tutorial "Como usar"
// Aberto na primeira visita; depois fica como a pessoa deixou (só neste navegador).
const GUIDE_KEY = "distribuidor.guia.v1";
const SAMPLE_CSV = [
  "ENDEREÇO;NOME;COD_RASTREIO",
  "Rua dos Andradas, 1000, Centro Histórico;Cliente Exemplo 1;BR000000001BR",
  "Av. Ipiranga, 6681, Partenon;Cliente Exemplo 2;BR000000002BR",
  "Av. Protásio Alves, 2000, Petrópolis;Cliente Exemplo 3;BR000000003BR",
  "Rua Padre Chagas, 300 apto 402, Moinhos de Vento;Cliente Exemplo 4;BR000000004BR",
].join("\r\n");

// Onde fica o tutorial: em tela larga e sem resultado, é o conteúdo da coluna da direita (ao lado da área
// de envio); no celular, ou com rotas na tela, fica recolhido no topo e abre pelo botão "Como usar".
const WIDE = matchMedia("(min-width: 1180px)");
function placeGuide() {
  const g = $("guide"); if (!g || !g.dataset.ready) return;
  // só sem lista aberta: com lista, a coluna larga é da revisão e dos entregadores
  const home = WIDE.matches && !document.body.classList.contains("has-result") && !document.body.classList.contains("has-job");
  const where = home ? $("guide-home") : $("guide-top");
  if (g.parentElement !== where.parentElement || g.previousElementSibling !== where) where.after(g);
  g.classList.toggle("in-home", home);
  const closed = (() => { try { return localStorage.getItem(GUIDE_KEY) === "fechado"; } catch { return false; } })();
  state.placing = true; g.open = home ? !closed : false; state.placing = false;
}

function guideInit() {
  const g = $("guide");
  g.dataset.ready = "1";
  g.addEventListener("toggle", () => {
    if (!state.placing && g.classList.contains("in-home")) { try { localStorage.setItem(GUIDE_KEY, g.open ? "aberto" : "fechado"); } catch {} }
  });
  WIDE.addEventListener("change", placeGuide);
  placeGuide();
  g.querySelectorAll("[data-go]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); $(a.dataset.go).scrollIntoView({ behavior: "smooth", block: "start" }); }));
  $("guide-depot").textContent = `o ponto padrão (${state.cfg.default_depot.split(",").slice(0, 2).join(",")})`;
  const local = ["local", "cache", "fake"].includes(state.cfg.geocoder);
  const ttl = `${Math.round(state.cfg.job_ttl_minutes / 60)} h`;
  $("guide-privacy").textContent = state.cfg.offline
    ? `Modo isolado: a lista fica só na memória deste computador e some ao fechar o app (ou depois de ${ttl}). Nenhuma conexão sai daqui; a única exceção é a busca de atualização do mapa, feita ao abrir e antes de qualquer lista.`
    : `A lista fica só na memória deste computador e some ao apagar os dados ou depois de ${ttl}. ${local ? "Os endereços são localizados aqui mesmo, sem internet." : "Neste modo, os endereços (sem nomes) são consultados no OpenStreetMap pela internet; para não enviar nada, use o executável do pen drive."}`;
  $("guide-sample").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob(["﻿" + SAMPLE_CSV], { type: "text/csv;charset=utf-8" }));
    const a = el("a", { href: url, download: "modelo-entregas.csv" }); document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    announce("Modelo de planilha baixado");
  });
}

// ------------------------------------------------------------------ pacote de mapa: versão e atualização
// A verificação só acontece sem lista aberta e só baixa o manifesto: nenhum dado de entrega sai daqui.
const fmtMB = (b) => `${Math.max(1, Math.round(b / 1e6))} MB`;
const fmtVer = (v) => { const m = /^(\d{4})\.(\d{2})\.(\d{2})/.exec(v || ""); return m ? `${m[3]}/${m[2]}/${m[1]}` : v || ""; };
const LATER_KEY = "distribuidor.mapa.depois";

function renderFoot(s) {
  const i = s.installed;
  $("foot-map").textContent = i ? `Mapa offline: dados de ${fmtVer(i.version)} · © colaboradores do OpenStreetMap` : "Mapa offline não instalado";
  const net = $("foot-net"); net.replaceChildren();
  if (s.isolated) net.append(el("span", { class: "on" }, "Modo isolado ativo"), ": nenhuma conexão sai deste computador");
  else net.append("Modo de desenvolvimento: conexões externas permitidas");
  $("map-check").checked = !!s.prefs.verificar_mapa;
}

function banner({ title, detail = "", kind = "", go = null, goLabel = "Baixar", later = true, meter = null }) {
  const b = $("map-update");
  b.className = "banner" + (kind ? ` ${kind}` : "");
  $("map-update-title").textContent = title; $("map-update-detail").textContent = detail;
  $("map-update-go").hidden = !go; $("map-update-go").lastChild.textContent = ` ${goLabel}`; $("map-update-go").onclick = go;
  $("map-update-later").hidden = !later;
  $("map-update-meter").hidden = meter == null;
  if (meter != null) $("map-update-meter").firstElementChild.style.width = `${Math.round(meter * 100)}%`;
  b.hidden = false;
}

async function mapInit() {
  $("map-update-later").addEventListener("click", () => { $("map-update").hidden = true; try { sessionStorage.setItem(LATER_KEY, "1"); } catch {} });
  $("map-check").addEventListener("change", async (e) => {
    await post("/api/mapa/preferencia", { verificar: e.target.checked }).catch(() => {});
    announce(e.target.checked ? "O app vai procurar atualização do mapa ao abrir" : "O app não vai mais procurar atualização do mapa");
  });
  let s;
  try { s = await api("/api/mapa"); } catch { return; }
  renderFoot(s);
  const later = (() => { try { return sessionStorage.getItem(LATER_KEY); } catch { return null; } })();
  if (!s.installed && (!s.prefs.verificar_mapa || state.job)) {
    return banner({ title: "Mapa offline não instalado", kind: "err", later: false,
      detail: "Sem ele, ruas e endereços não são encontrados. Ative “Procurar atualização do mapa ao abrir” e reabra o app com internet, ou copie a pasta “mapa” de outro computador." });
  }
  if (state.job || !s.prefs.verificar_mapa || later) return;
  const c = await post("/api/mapa/verificar", {}).catch(() => null);
  if (!c) return;
  if (c.state === "available") {
    const first = !s.installed;
    banner({
      title: first ? "Baixe o mapa offline para começar" : "Existe uma atualização do mapa disponível",
      detail: first ? `Ruas e endereços de Porto Alegre, ${fmtMB(c.size)}. Depois disso o app funciona sem internet.`
        : `Dados de ${fmtVer(c.version)}, ${fmtMB(c.size)}. O mapa atual (${fmtVer(c.installed)}) continua valendo até terminar.`,
      go: downloadMap, goLabel: first ? "Baixar mapa" : "Baixar", later: !first,
    });
  } else if (!s.installed) {
    banner({ title: "Mapa offline não instalado", kind: "err", later: false,
      detail: c.state === "offline" ? "Sem conexão para baixar agora. Conecte à internet e reabra o app, ou copie a pasta “mapa” de outro computador."
        : `Não foi possível conferir o mapa disponível (${c.detail || c.state}). Tente reabrir o app.` });
  }
}

async function downloadMap() {
  $("map-update-go").disabled = true;
  try { await post("/api/mapa/baixar", {}); } catch (e) {
    $("map-update-go").disabled = false;
    return banner({ title: "Não foi possível baixar o mapa", detail: e.message, kind: "err", go: downloadMap, goLabel: "Tentar de novo" });
  }
  for (;;) {
    const s = await api("/api/mapa").catch(() => null);
    const d = s?.download || {};
    if (d.state === "downloading") {
      const f = d.total ? d.done / d.total : 0;
      banner({ title: "Baixando o mapa…", detail: `${fmtMB(d.done)} de ${fmtMB(d.total)}. Pode continuar usando o app.`, meter: f, later: false });
    } else if (d.state === "verifying" || d.state === "installing") {
      banner({ title: "Conferindo a assinatura e instalando…", detail: "O mapa só é usado se a assinatura e o conteúdo conferem.", meter: 1, later: false });
    } else if (d.state === "done") {
      renderFoot(s); $("map-update-go").disabled = false;
      banner({ title: `Mapa atualizado: dados de ${fmtVer(d.version)}`, kind: "ok", later: false,
        detail: "As próximas rotas já usam o mapa novo. A versão anterior fica guardada." });
      announce("Mapa atualizado");
      if (state.cfg) state.cfg.basemap = true;
      setTimeout(() => { $("map-update").hidden = true; }, 8000);
      return;
    } else if (d.state === "error") {
      $("map-update-go").disabled = false;
      return banner({ title: "O download do mapa falhou", detail: `${d.detail || "Erro desconhecido"}. O mapa atual continua valendo.`, kind: "err", go: downloadMap, goLabel: "Tentar de novo" });
    }
    await sleep(700);
  }
}

// Recarregar a página não perde o resultado: o servidor guarda o processamento por até 2 h.
async function restore(id) {
  try {
    const j = await api(`/api/jobs/${id}`);
    state.job = id; show("wipe"); setHasJob(true);
    if (j.state === "mapear") return renderMapping(j.mapping);
    if (j.state === "lendo" || j.state === "geocodificando") return pollIngest();
    if (j.state === "erro") { setStatus("s1status", j.error, "err"); return; }
    renderIngest(j);
    if (j.state === "calculando") return awaitResult();
    if (j.state === "pronto") renderResult(await api(`/api/jobs/${id}/result`));
  } catch { state.job = null; setHasJob(false); show("wipe", false); try { sessionStorage.removeItem(JOB_KEY); } catch {} }
}

// Mesmo comportamento das outras confirmações (twoStep): sem prazo; desarma ao sair do botão ou com Esc.
// Com a lista vazia não há o que perder, então gera direto.
function twoStepGenerate() {
  const nb = $("gen");
  const disarm = () => { if (nb.classList.contains("armed")) { nb.classList.remove("armed"); nb.textContent = "Gerar lista"; } };
  nb.addEventListener("click", () => {
    if (!$("drivers").value.trim() || nb.classList.contains("armed")) { disarm(); return generateList(); }
    nb.classList.add("armed"); nb.textContent = "Substituir a lista atual?";
    announce("Substituir a lista atual? Clique de novo para confirmar, ou Esc para cancelar.");
  });
  nb.addEventListener("blur", () => setTimeout(disarm, 150));
  nb.addEventListener("keydown", (e) => { if (e.key === "Escape") disarm(); });
}

function generateList() {
  const n = Math.max(1, Math.min(40, parseInt($("n-drivers").value) || 1));
  $("drivers").value = Array.from({ length: n }, (_, i) => `Entregador ${i + 1}`).join("\n");
  updatePlan();
}

// ------------------------------------------------------------------ etapa 1: arquivo
// Com uma lista aberta, a área de envio encolhe para uma linha (trocar o arquivo) e a tela larga
// passa a ser do trabalho: revisão e entregadores, sem o tutorial ao lado.
function setHasJob(on) {
  document.body.classList.toggle("has-job", on);
  const coarse = matchMedia("(pointer: coarse)").matches;
  document.querySelector("#drop strong").textContent = on ? "Trocar o arquivo" : coarse ? "Escolha o arquivo" : "Escolha ou arraste o arquivo";
  placeGuide();
}
function resetPanels() {
  state.result = null; state.sent = []; document.body.classList.remove("has-result"); placeGuide();
  ["review-card", "s2", "s3", "map-card"].forEach((i) => show(i, false));
  show("s1report", false); state.lastDiscard = null; $("empty-busy").hidden = true; setStatus("s2status", ""); setStep(1);
}

async function upload(files) {
  if (state.job) await api(`/api/jobs/${state.job}`, { method: "DELETE" }).catch(() => {});
  resetPanels(); setStatus("s1status", files.length > 1 ? `Enviando ${files.length} arquivos…` : "Enviando…");
  const fd = new FormData(); files.forEach((f) => fd.append("file", f));
  try {
    const { job_id } = await api("/api/upload", { method: "POST", body: fd });
    state.job = job_id; show("wipe"); setHasJob(true);
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

// Envio com vários arquivos: quanto veio de cada um, o que foi repetido e o que não deu para ler.
function filesList(files) {
  return el("ul", { class: "files" }, ...files.map((f) => el("li", { class: f.error ? "bad" : "" },
    el("strong", {}, f.name), " · ",
    f.error ? `não lido: ${f.error}`
      : `${f.stops} entrega${f.stops === 1 ? "" : "s"}${f.duplicates ? ` (${f.duplicates} repetida${f.duplicates === 1 ? "" : "s"} de outro arquivo, ignorada${f.duplicates === 1 ? "" : "s"})` : ""}`)));
}

function renderIngest(j) {
  const c = j.counts, r = j.report;
  state.okCount = c.ok || 0;
  state.multiFile = (j.files || []).length > 1;
  const box = $("s1report"); box.replaceChildren(); show("s1report");
  box.append(
    el("div", { class: "chips" },
      chip(`${c.ok || 0} localizados`, "ok"),
      ...(c.revisar ? [chip(`${c.revisar} para revisar`, "warn")] : []),
      chip(`leitura: ${r.method.split("+").map((m) => METHOD[m] || m).join(" + ")}`),
      ...r.dropped_columns.map((d) => chip(`coluna ignorada: ${d}`)),
      ...Object.entries(r.masked).map(([k, v]) => chip(`${v} ${MASKED[k] || k} removidos do texto`)),
    ),
    ...(state.multiFile ? [filesList(j.files)] : []),
    ...r.notes.map((n) => el("p", { class: "hint" }, n)),
  );
  renderReview(j.review);
  show("s2"); setStep(2); zonesOnIngest();
  if (!$("drivers").value.trim()) generateList();
  updatePlan();
}

async function refresh() { renderIngest(await api(`/api/jobs/${state.job}`)); }

function renderReview(list) {
  const undo = state.lastDiscard;
  show("review-card", list.length > 0 || !!undo);
  $("review-count").textContent = `(${list.length})`;
  const box = $("review-list"); box.replaceChildren();
  list.forEach((s, idx) => {
    if (undo && undo.index === idx) box.append(undoRow(undo));
    const addr = el("input", { type: "text", value: s.address, "aria-label": `Endereço de ${s.name}` });
    const coords = el("input", { type: "text", placeholder: "lat, lon do Google Maps", "aria-label": `Coordenadas de ${s.name}` });
    const err = el("div", { class: "err", role: "alert", hidden: "" });
    // Depois de cada ação a lista é refeita: o foco vai para a próxima entrega (ou para o que sobrar),
    // em vez de cair no começo da página.
    const act = async (body, msg, discard) => {
      try {
        await api(`/api/jobs/${state.job}/stops/${s.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        state.lastDiscard = discard ? { s, index: idx } : null;
        await refresh();
        focusReview(idx, discard);
        announce(msg);
      } catch (e) { err.textContent = e.message; err.hidden = false; }   // o foco fica no botão usado
    };
    // Lista vinda do PDF de intimações: em que página está e um atalho para ver o original
    const pg = s.pages && s.pages.length ? el("div", { class: "where" },
      `${state.multiFile && s.file ? s.file : "PDF"}: página ${s.pages[0]}${s.pages.length > 1 ? `–${s.pages[s.pages.length - 1]}` : ""}`,
      s.code ? ` · ${s.code}` : "", " · ",
      el("a", { href: `/api/jobs/${state.job}/paginas.pdf?stop=${s.id}`, target: "_blank", rel: "noopener" }, "ver no PDF (nova aba)")) : null;
    box.append(el("div", { class: "row", "data-id": String(s.id) },
      el("div", {}, el("div", { class: "who" }, s.name), el("div", { class: "why" }, s.reason), ...(pg ? [pg] : [])),
      addr, coords,
      el("div", { class: "btns" },
        el("button", { onclick: () => act({ address: addr.value }, `Endereço de ${s.name} procurado de novo`) }, "Buscar"),
        el("button", { onclick: () => (coords.value.trim() ? act({ coords: coords.value }, `Coordenadas de ${s.name} usadas`) : ((err.textContent = "Cole as coordenadas no formato lat, lon."), (err.hidden = false), coords.focus())) }, "Usar coords"),
        el("button", { class: "ghost danger", onclick: () => act({ discard: true }, `${s.name} descartado. O botão Desfazer está no lugar da entrega.`, true) }, "Descartar")),
      err,
    ));
  });
  if (undo && undo.index >= list.length) box.append(undoRow(undo));
}

// O desfazer fica no lugar da entrega descartada até a próxima ação na lista (sem prazo).
function undoRow(u) {
  return el("div", { class: "row undone" },
    el("span", {}, `Descartado: ${u.s.name}.`),
    el("button", { class: "link", onclick: async () => {
      await api(`/api/jobs/${state.job}/stops/${u.s.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ restore: true }) });
      state.lastDiscard = null; await refresh();
      $("review-list").querySelector(`.row[data-id="${u.s.id}"] input`)?.focus();
      announce(`${u.s.name} voltou para a revisão`);
    } }, "Desfazer"));
}
function focusReview(idx, discarded) {
  const rows = [...$("review-list").querySelectorAll(".row:not(.undone)")];
  const target = discarded ? $("review-list").querySelector(".row.undone button")
    : rows[Math.min(idx, rows.length - 1)]?.querySelector("input");
  (target || $("s2").querySelector("h2"))?.focus({ preventScroll: false });
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
  const mf = $("map-file");
  mf.hidden = !(m.file_total > 1);
  mf.textContent = m.file_total > 1 ? `Arquivo ${m.file_index} de ${m.file_total}: ${m.file}` : "";
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
// Telefone do entregador (opcional): só dígitos com DDI 55. Fica no navegador; nunca vai ao servidor.
function phoneOf(part) {
  if (!/^\+?[\d\s().-]+$/.test(part)) return null;
  let d = part.replace(/\D/g, "");
  if (d.length === 10 || d.length === 11) d = "55" + d;
  return d.length >= 12 && d.length <= 13 ? d : null;
}
function parseDrivers() {
  return $("drivers").value.split("\n").map((l) => l.trim()).filter(Boolean).map((line, i) => {
    // "Nome" sozinho = sai do ponto padrão; "Nome; endereço ou lat, lon; telefone" (cada parte opcional)
    const [label, ...rest] = line.split(";").map((s) => s.trim());
    let phone = null;
    const parts = rest.filter((p) => { const ph = p && phoneOf(p); if (ph && !phone) { phone = ph; return false; } return !!p; });
    const where = parts.join("; ");
    const m = where.match(/^(-?\d{1,2}[.,]\d+)\s*[,; ]\s*(-?\d{1,3}[.,]\d+)$/);
    const start = !where ? {} : m ? { lat: parseFloat(m[1].replace(",", ".")), lon: parseFloat(m[2].replace(",", ".")) } : { address: where };
    return { label: label || `Entregador ${i + 1}`, start, phone };
  });
}
// Telefones por nome, lidos da lista atual (vale também para um resultado restaurado).
const phoneByLabel = () => Object.fromEntries(parseDrivers().filter((d) => d.phone).map((d) => [d.label, d.phone]));
const waUrl = (phone, text) => `https://wa.me/${phone}?text=${encodeURIComponent(text)}`;
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
// ---- predefinições da divisão: duas escolhas com nome cobrem o uso diário; "Personalizado" abre os controles
const PRESETS = {
  carga: { label: "Carga parecida", by: "km", balance: 1, kmtol: "15", zone: 0.1 },
  km: { label: "Menos km no total", by: "km", balance: 0.3, kmtol: "30", zone: 0.1 },
};
function currentPreset() {
  for (const [k, p] of Object.entries(PRESETS)) {
    if ($("balance-by").value === p.by && Math.abs(parseFloat($("balance").value) - p.balance) < 1e-6
      && String($("km-tol").value) === p.kmtol && Math.abs(parseFloat($("zone").value) - p.zone) < 1e-6) return k;
  }
  return "custom";
}
function applyPreset(name) {
  const p = PRESETS[name];
  if (p) { $("balance-by").value = p.by; $("balance").value = p.balance; $("km-tol").value = p.kmtol; $("zone").value = p.zone; }
  $("custom").hidden = name !== "custom";
  document.querySelectorAll('input[name="preset"]').forEach((r) => (r.checked = r.value === name));
  updatePlan();
}
function initPresets() {
  document.querySelectorAll('input[name="preset"]').forEach((r) => r.addEventListener("change", () => { state.fromPrefs = false; applyPreset(r.value); }));
  applyPreset(currentPreset());
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
  // Com margem de km, igualar "km" quer dizer: km dentro da faixa, e entregas e tempo igualados dentro dela.
  // O texto do seletor e o da margem dizem a mesma coisa, sem se contradizer.
  if (by === "km" && kt !== null) $("balance-help").textContent = `Com a margem de km preenchida, o km de cada rota só precisa ficar a ±${Math.round(kt * 100)}% da média; dentro dela, o app iguala entregas e tempo.`;
  $("km-tol-help").textContent = kt === null
    ? "Vazio: o app tenta deixar os km parecidos entre os entregadores. Com um valor (ex.: 30), o km só precisa ficar dentro de ±30% da média e entregas e tempo passam a ser igualados: o total de km cai, mas os km deixam de ser parecidos."
    : `Cada rota pode ter km até ${Math.round(kt * 100)}% acima ou abaixo da média sem penalidade.`;
  const preset = PRESETS[document.querySelector('input[name="preset"]:checked')?.value];
  const how = preset ? preset.label : `igualar ${BY_LABEL[by]} · ${pct(b)} · zonas ${pct(z)}${kt !== null ? ` · km ±${Math.round(kt * 100)}%` : ""}`;
  $("adv-summary").textContent = `${how} · folga ${tol} min${state.fromPrefs && !seasoned() ? " · da última vez" : ""}`;
  const tel = d.filter((x) => x.phone).length;
  $("drivers-count").textContent = d.length ? `${d.length} entregador${d.length > 1 ? "es" : ""}${home ? ` · ${home} ${home > 1 ? "saem" : "sai"} de casa` : ""}${tel ? ` · ${tel} com WhatsApp` : ""}${$("ped-on").checked && state.cfg.pedestrian ? " · mais 1 a pé no Centro" : ""}` : "";
  const stops = state.okCount ? `${state.okCount} entregas` : "entregas";
  const idle = state.okCount && d.length > state.okCount ? d.length - state.okCount : 0;
  $("plan").textContent = !state.okCount ? "Nenhuma entrega localizada ainda: resolva os endereços para revisar."
    : !d.length ? "Informe pelo menos um entregador."
    : `${stops} para ${d.length} entregador${d.length > 1 ? "es" : ""} · ${preset ? preset.label.toLowerCase() : `igualando ${BY_LABEL[by]} (${pct(b)})`} · ${tol} min de folga por entrega.`
      + (idle ? ` Mais entregadores que entregas: ${idle} ficaria${idle > 1 ? "m" : ""} sem rota.` : "");
  $("plan").classList.toggle("warn", !!idle);
  const bad = typeof zonesIncomplete === "function" ? zonesIncomplete() : [];
  if (bad.length) {
    $("plan").textContent = `A zona "${bad[0]}" ainda não tem entregador${bad.length > 1 ? ` (e mais ${bad.length - 1})` : ""}: escolha quem atende nela ou remova a zona.`;
    $("plan").classList.add("warn");
  }
  $("solve").disabled = !d.length || !state.okCount || bad.length > 0 || $("solve").dataset.busy === "1";
  if (!$("solve").classList.contains("armed")) $("solve").textContent = state.result ? "Recalcular rotas" : "Calcular rotas";
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

// Recalcular troca as rotas: as marcações de "copiado" deixam de valer. Se já houver envios, pede confirmação.
function disarmSolve() { const b = $("solve"); clearTimeout(b._t); if (b.classList.contains("armed")) { b.classList.remove("armed"); updatePlan(); } }
function solveClick() {
  const b = $("solve"), n = state.sent.filter((s) => s.rota || s.links).length;
  if (state.result && n && !b.classList.contains("armed")) {
    b.classList.add("armed"); b._armedAt = Date.now(); b._t = setTimeout(disarmSolve, 8000);
    b.textContent = `Recalcular? ${n} já ${n > 1 ? "receberam" : "recebeu"} a rota atual`;
    announce(`${b.textContent}. Recalcular troca as rotas: o que já foi enviado deixa de valer e as marcações de envio são apagadas. Clique de novo para confirmar (vale por 8 segundos), ou Esc para cancelar.`);
    return;
  }
  if (b.classList.contains("armed") && Date.now() - (b._armedAt || 0) < 600) return;
  clearTimeout(b._t); b.classList.remove("armed");
  clearSent();
  solve();
}

async function solve() {
  const drivers = parseDrivers();
  if (!drivers.length) return setStatus("s2status", "Informe pelo menos um entregador.", "err");
  savePrefs(); setStep(2);
  const btn = $("solve"); btn.dataset.busy = "1"; btn.disabled = true; show("s3", false);
  document.body.classList.remove("has-result"); placeGuide();
  const t0 = Date.now(), budget = (state.cfg.solver_seconds || 30) + 15 + 10 * Z.list.length;
  // O contador muda a cada segundo na tela; o leitor de tela ouve só o início e o fim.
  ["s2status", "empty-busy"].forEach((id) => $(id).setAttribute("aria-live", "off"));
  announce(`Calculando as rotas. Costuma levar até ${budget} segundos.`);
  const tick = () => {
    const msg = `Calculando as rotas… ${Math.round((Date.now() - t0) / 1000)} s (costuma levar até ~${budget} s)`;
    setStatus("s2status", msg); const b = $("empty-busy"); b.hidden = false; b.textContent = msg;
  };
  tick(); const timer = setInterval(tick, 1000);
  try {
    await post(`/api/jobs/${state.job}/solve`, {
      // o telefone fica só no navegador: o servidor recebe nome e partida
      depot: { address: $("depot").value.trim() }, drivers: drivers.map(({ label, start }) => ({ label, start })), balance: parseFloat($("balance").value),
      balance_by: $("balance-by").value, zone_weight: parseFloat($("zone").value),
      tolerance_seconds: toleranceMin() * 60, km_tolerance: kmTolerance(), traffic: parseFloat($("traffic").value) || 1,
      pedestrian: { enabled: $("ped-on").checked && state.cfg.pedestrian !== false, start: { address: $("ped-start").value.trim() } },
      zones: zonesPayload(),
    });
    try {   // lembra com qual predefinição este cálculo foi feito (para o veredito e para um recarregamento)
      const m = JSON.parse(sessionStorage.getItem(PRESET_KEY) || "{}");
      m[state.job] = document.querySelector('input[name="preset"]:checked')?.value || "custom";
      sessionStorage.setItem(PRESET_KEY, JSON.stringify(m));
    } catch {}
    await awaitResult();
    setStatus("s2status", "");
    announce("Rotas prontas");
  } catch (e) { $("s2status").removeAttribute("aria-live"); setStatus("s2status", e.message, "err"); announce(e.message); }
  finally {
    clearInterval(timer); $("empty-busy").hidden = true; btn.dataset.busy = ""; updatePlan();
    ["s2status", "empty-busy"].forEach((id) => $(id).removeAttribute("aria-live"));
  }
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
async function copyText(text, what = "Texto copiado", onPasted = null) {
  try { await navigator.clipboard.writeText(text); announce(what); return true; }
  catch { showCopyFallback(text, onPasted); return false; }
}
// Sem acesso à área de transferência (ex.: o app aberto por IP na rede), o texto vai para um diálogo. "Já colei e
// enviei" marca como enviado, como se a cópia tivesse funcionado; fechar de outro jeito não marca nada.
function showCopyFallback(text, onPasted) {
  const dlg = $("copy-fallback"), ta = $("copy-fallback-text");
  dlg._onPasted = onPasted || null; $("cf-done").hidden = !onPasted;
  ta.value = text; dlg.showModal(); ta.focus(); ta.select();
}
function markCopied(btn, label) {
  btn.classList.add("done");
  btn.replaceChildren(icon("check"), " ", label, ...(btn.dataset.who ? [el("span", { class: "sr" }, ` de ${btn.dataset.who}`)] : []));
}
function unmarkCopied(btn, label, ico = "copy") {
  btn.classList.remove("done");
  btn.replaceChildren(icon(ico), " ", label, el("span", { class: "sr" }, ` de ${btn.dataset.who}`));
}
// Rótulos dependem de haver telefone: "WhatsApp: rota" abre a conversa; "Copiar rota" só copia.
function refreshSent(i) {
  const row = document.querySelector(`.driver[data-i="${i}"]`); if (!row) return;
  const st = state.sent[i], chip = row.querySelector(".chip.sent"), wa = !!state.phones?.[state.result.drivers[i].label];
  const ms = row.querySelector(".mark-sent");
  if (ms) ms.replaceChildren(icon("check"), st.rota && st.links ? " Desmarcar envio" : " Marcar como enviado, sem copiar");
  st.rota ? markCopied(row.querySelector(".copy-rota"), wa ? "Rota aberta" : "Rota copiada")
    : unmarkCopied(row.querySelector(".copy-rota"), wa ? "WhatsApp: rota" : "Copiar rota", wa ? "chat" : "copy");
  st.links ? markCopied(row.querySelector(".copy-links"), wa ? "Links abertos" : "Links copiados")
    : unmarkCopied(row.querySelector(".copy-links"), wa ? "WhatsApp: links" : "Copiar links", wa ? "chat" : "copy");
  chip.hidden = !(st.rota && st.links);
}

// ---- marcações de "copiado" sobrevivem a um recarregamento (só nesta aba; somem ao apagar ou recalcular)
const SENT_KEY = "distribuidor.copiados.v1";
const PRESET_KEY = "distribuidor.predefinicao.v1";
const resultSig = (r) => [state.job, r.deliveries, r.total_min, ...r.drivers.map((d) => d.stops[0]?.id ?? "")].join("|");
function saveSent() { try { sessionStorage.setItem(SENT_KEY, JSON.stringify({ sig: state.sig, sent: state.sent })); } catch {} }
function loadSent(r) {
  try {
    const s = JSON.parse(sessionStorage.getItem(SENT_KEY));
    if (s && s.sig === state.sig && s.sent.length === r.drivers.length) return s.sent;
  } catch {}
  return null;
}
function clearSent() { try { sessionStorage.removeItem(SENT_KEY); } catch {} }

const KIND = { rota: ["Rota", "copiada"], links: ["Links", "copiados"] };
function showLastCopy(i, kind) {
  const who = state.result.drivers[i].label, [what, done] = KIND[kind];
  state.lastCopy = { i, kind };
  const msg = state.phones?.[who]
    ? ` ${what} de ${who} aberta no WhatsApp: confira e toque em enviar. Se o texto chegar cortado, cole (também foi copiado). `
    : ` ${what} de ${who} ${done}. Cole na conversa de ${who}. `;
  $("sent-last").replaceChildren(icon("check"), msg, el("button", { class: "link", onclick: undoLastCopy }, "Desfazer"));
}
function undoLastCopy() {
  const lc = state.lastCopy; if (!lc) return;
  state.sent[lc.i][lc.kind] = false; state.lastCopy = null;
  refreshSent(lc.i); updateSendbar(); saveSent();
  $("sent-last").textContent = `Marcação desfeita: ${KIND[lc.kind][0].toLowerCase()} de ${state.result.drivers[lc.i].label} volta para a fila.`;
  announce($("sent-last").textContent);
}
// Com telefone: abre a conversa do entregador no WhatsApp já com a mensagem (e copia também, caso o
// WhatsApp corte um texto longo). Sem telefone: só copia, para colar.
function markSent(i, kind) {
  state.sentOneByOne = true;
  state.sent[i][kind] = true; refreshSent(i); updateSendbar(); saveSent(); showLastCopy(i, kind);
}
// Marca (ou desmarca) rota e links de um entregador como enviados sem copiar nada: para quem já mandou por outro
// meio, ou para pular quem não responde sem travar a fila.
function toggleSent(i) {
  const st = state.sent[i], was = st.rota && st.links, who = state.result.drivers[i].label;
  st.rota = st.links = !was; state.lastCopy = null;
  refreshSent(i); updateSendbar(); saveSent();
  $("sent-last").textContent = was ? `Envio de ${who} desmarcado: volta para a fila.` : `${who} marcado como enviado, sem copiar.`;
  announce($("sent-last").textContent);
}
async function copyKind(i, kind) {
  const [what, done] = KIND[kind], who = state.result.drivers[i].label, phone = state.phones?.[who], text = state.texts[i][kind];
  if (phone) {
    window.open(waUrl(phone, text), "_blank", "noopener");   // dentro do clique: o navegador não bloqueia
    try { await navigator.clipboard.writeText(text); } catch {}
    announce(`${what} de ${who} aberta no WhatsApp`);
  } else if (!(await copyText(text, `${what} de ${who} ${done}`, () => markSent(i, kind)))) return;
  markSent(i, kind);
}
// "Copiar todas" serve para mandar tudo de uma vez (ex.: num grupo). Marca todos, mas dá para desfazer:
// se o texto não chegou a ser colado, as marcações voltam como estavam.
async function copyAll(kind, btn, doneLabel) {
  $("bulk").open = false;
  if (!(await copyText(state.texts.map((t) => t[kind]).join(SEP), doneLabel, () => applyCopyAll(kind, btn, doneLabel)))) return;
  applyCopyAll(kind, btn, doneLabel);
}
function applyCopyAll(kind, btn, doneLabel) {
  const before = state.sent.map((st) => st[kind]);
  state.sent.forEach((st, i) => { st[kind] = true; refreshSent(i); });
  markCopied(btn, doneLabel); updateSendbar(); saveSent();
  state.lastCopy = null;
  $("sent-last").replaceChildren(icon("check"), ` ${doneLabel}: ${KIND[kind][0].toLowerCase()} de todos os entregadores numa mensagem só, e todos marcados. `,
    el("button", { class: "link", onclick: () => {
      state.sent.forEach((st, i) => { st[kind] = before[i]; refreshSent(i); });
      btn.classList.remove("done"); btn.replaceChildren(icon("copy"), " ", btn.id === "copy-all-routes" ? "Copiar todas as rotas" : "Copiar todos os links");
      updateSendbar(); saveSent();
      $("sent-last").textContent = "Marcações desfeitas: a fila voltou como estava.";
      announce($("sent-last").textContent);
    } }, "Desfazer"));
}

// ---- impressão: lista completa, sem blocos de 10
// Sai de casa (endereço ou coordenadas próprias) em vez do ponto padrão?
const ownStart = (d, r) => !!d.start.address || Math.hypot(d.start.lat - r.depot.lat, d.start.lon - r.depot.lon) > 1e-5;
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
    el("p", { class: "meta" }, d.mode === "pe"
      ? `A pé · Saída e chegada: ${d.start.address || `${d.start.lat.toFixed(5)}, ${d.start.lon.toFixed(5)}`}`
      : ownStart(d, r)
      ? `Partida: ${d.start.address || `${d.start.lat.toFixed(5)}, ${d.start.lon.toFixed(5)}`} · Chegada: ${r.depot.address || "ponto padrão"}`
      : `Partida e chegada: ${r.depot.address || "ponto padrão"}`),
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

// Veredito desigual: diz quem destoa no critério mais desigual e oferece o próximo passo, em vez de só alertar.
function outliers(dr, spreads, kt, usedPreset) {
  const crit = [["entregas", (d) => d.deliveries, (v) => `${v} entrega${v === 1 ? "" : "s"}`],
    ["tempo", (d) => d.total_min, fmtMin], ...(kt ? [] : [["km", (d) => d.km, (v) => `${Math.round(v)} km`]])]
    .sort((a, b) => spreads[b[0]] - spreads[a[0]])[0];
  const [, val, fmt] = crit;
  const idx = dr.map((_, i) => i).filter((i) => dr[i].count);
  const hi = idx.reduce((a, i) => (val(dr[i]) > val(dr[a]) ? i : a), idx[0]);
  const lo = idx.reduce((a, i) => (val(dr[i]) < val(dr[a]) ? i : a), idx[0]);
  const who = (i) => el("button", { class: "link", onclick: () => focusRoute(i), "aria-label": `Destacar a rota de ${dr[i].label} no mapa` }, dr[i].label);
  const p = el("p", { class: "outliers" }, "Mais carregado: ", who(hi), ` (${fmt(val(dr[hi]))}) · mais leve: `, who(lo), ` (${fmt(val(dr[lo]))}).`);
  if (usedPreset && usedPreset !== "carga") {
    // com mensagens já enviadas, o botão Calcular pede confirmação: leva a pessoa até ele
    p.append(" ", el("button", { class: "link", onclick: () => { applyPreset("carga"); state.fromPrefs = false; $("calcbar").scrollIntoView({ behavior: "smooth", block: "nearest" }); solveClick(); } }, "Recalcular com carga parecida"));
  } else {
    p.append(" Escolha um nome para ver a rota no mapa.");
  }
  return p;
}
// Destaca uma rota (como a legenda) e leva o mapa à vista.
function focusRoute(i) {
  const b = $("map-legend").querySelectorAll(".lg")[i];
  if (b && b.getAttribute("aria-pressed") !== "true") b.click();
  $("s3-map").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

const range = (a) => !a.length ? "–" : (Math.min(...a) === Math.max(...a) ? `${Math.min(...a)}` : `${Math.min(...a)}–${Math.max(...a)}`);
const CRIT = { stops: "paradas", time: "tempo de rota", km: "km rodados" };

function renderResult(r) {
  show("s3"); setStep(3);
  const n = r.drivers.length, dr = r.drivers, by = r.balance_by || "stops";
  // O entregador a pé (Centro) e os grupos de zona ficam fora do equilíbrio: faixas, veredito e barras comparam só os livres.
  const eq = dr.filter((d) => d.mode !== "pe" && !d.group), walker = dr.find((d) => d.mode === "pe" && !d.group);
  const zones = r.zones || [];
  const counts = eq.map((d) => d.count), times = eq.map((d) => d.total_min), kms = eq.map((d) => d.km);
  const total = dr.reduce((a, d) => a + d.count, 0), all = dr.flatMap((d) => d.stops);   // paradas de todas as rotas
  const approxN = all.filter((s) => s.precision === "aproximado").length, mostApprox = all.length && approxN / all.length > 0.5;
  const estimated = r.matrix.startsWith("estimativa");
  const metric = (d) => (by === "km" ? d.km : by === "stops" ? d.count : d.total_min);
  const eqm = eq.map(metric), mx = eqm.length ? Math.max(...eqm) : 0, mn = eqm.length ? Math.min(...eqm) : 0;
  const diff = mx ? Math.round(((mx - mn) / mx) * 100) : 0;
  const dsp = (arr) => { if (!arr.length) return 0; const m = Math.max(...arr), l = Math.min(...arr); return m ? Math.round(((m - l) / m) * 100) : 0; };
  const spreads = { km: dsp(kms), entregas: dsp(eq.map((d) => d.deliveries)), tempo: dsp(times) };
  // Com tolerância de km, o km é avaliado contra a faixa (±t da média permite até 2t/(1+t) entre menor e maior).
  const kt = r.km_tolerance, kmAllowed = kt ? Math.round(((2 * kt) / (1 + kt)) * 100) : null;
  const worst = Math.max(kt ? 0 : spreads.km, spreads.entregas, spreads.tempo);
  // A margem de km só vira alerta quando o operador a escolheu (em "Personalizado"); nas predefinições
  // ela é um ajuste interno do cálculo, e passar dela é informação, não problema.
  const usedPreset = (() => { try { return JSON.parse(sessionStorage.getItem(PRESET_KEY))?.[state.job] || null; } catch { return null; } })();
  const chosenMargin = usedPreset === "custom";
  const kmOut = kt != null && spreads.km > kmAllowed && chosenMargin;
  // A cor segue o pior critério: nada de verde ao lado de "fora da faixa".
  const verdictWord = worst <= 15 ? "bem equilibradas" : worst <= 30 ? "razoavelmente equilibradas" : "bem desiguais";
  const verdictKind = worst > 30 || kmOut ? "warn" : "ok";

  const notes = [
    `Tempos e km ${estimated ? "estimados em linha reta (sem as ruas)" : "calculados pelas ruas"}`,
    `tempos com ${Math.round((r.tolerance_seconds ?? 0) / 60)} min de folga por entrega`,
    ...((r.traffic || 1) > 1 ? [`deslocamento das motos com +${Math.round((r.traffic - 1) * 100)}% de trânsito`] : []),
    `${pct(r.zone_purity)} das paradas ficam na zona principal do entregador`,
  ];
  const outside = n - eq.length, zoneRoutes = dr.filter((d) => d.group).length;
  const outsideDriver = (d) => !!d.group || d.mode === "pe";
  const plate = (d) => { const k = dr.indexOf(d); return el("span", { class: "swatch mini", style: `background:${color(k)}`, title: d.label }, String(k + 1)); };
  const multi = all.filter((s) => s.n_deliveries > 1).length;
  if (multi) notes.push(`${multi} paradas reúnem várias entregas no mesmo endereço (casa ou condomínio)`);
  if (zones.length) notes.push(`${zones.length} zona${zones.length > 1 ? "s" : ""} desenhada${zones.length > 1 ? "s" : ""}: cada uma é dividida só entre os entregadores dela`);
  if (walker) notes.push("as entregas da zona do Centro (contorno tracejado no mapa) vão para o entregador a pé, que não entra no equilíbrio");
  if (mostApprox) notes.push(`${approxN} de ${all.length} posições são aproximadas (só a rua foi localizada; a ordem das paradas continua valendo)`);
  const fmtRange = (a, f) => !a.length ? "–" : (Math.min(...a) === Math.max(...a) ? f(a[0]) : `${f(Math.min(...a))}–${f(Math.max(...a))}`);
  const reviewBtn = el("button", { class: "link", onclick: () => $("review-card").scrollIntoView({ behavior: "smooth", block: "start" }) }, "Revisar endereços");
  $("summary").replaceChildren(
    el("p", { class: "headline" }, `${n} rota${n > 1 ? "s" : ""} pront${n > 1 ? "as" : "a"}`
      + (outside ? ` (${[`${eq.length} livre${eq.length === 1 ? "" : "s"}`, ...(zoneRoutes ? [`${zoneRoutes} de zona`] : []), ...(walker ? ["1 a pé"] : [])].join(" + ")})` : "")
      + ` · ${r.deliveries} entregas em ${total} paradas`),
    el("dl", { class: "ranges" },
      el("div", {}, el("dt", {}, "Entregas"), el("dd", {}, range(eq.map((d) => d.deliveries)))),
      el("div", {}, el("dt", {}, "Tempo"), el("dd", {}, fmtRange(times, fmtMin))),
      el("div", {}, el("dt", {}, "Km"), el("dd", {}, `${fmtRange(kms, Math.round)} km`)),
      el("div", {}, el("dt", {}, "Paradas"), el("dd", {}, range(counts))),
    ),
    ...(outside ? [el("p", { class: "ranges-cap" }, `Faixas e veredito: só as ${eq.length} rotas livres. O que está fora do equilíbrio aparece abaixo.`)] : []),
    ...(outside ? [el("ul", { class: "outside" },
      ...zones.map((z) => {
        const ds = dr.filter((d) => d.group === z.name);
        return el("li", {}, el("span", { class: "plates" }, ...ds.map(plate)),
          el("span", {}, el("strong", {}, z.name), ` · ${z.deliveries} entrega${z.deliveries === 1 ? "" : "s"} · ${z.profile === "pe" ? "a pé" : "moto"} · ${fmtRange(ds.map((d) => d.total_min), fmtMin)} por entregador`,
            z.near_border ? ` · ${z.near_border} parada${z.near_border === 1 ? "" : "s"} a até 80 m do contorno (dentro ou fora): confira o lado` : ""));
      }),
      ...(walker ? [el("li", {}, el("span", { class: "plates" }, plate(walker)),
        el("span", {}, el("strong", {}, walker.label), ` · ${walker.deliveries} entrega${walker.deliveries === 1 ? "" : "s"} em ${walker.count} parada${walker.count === 1 ? "" : "s"} · a pé · ~${fmtMin(walker.total_min)} · ~${Math.round(walker.km)} km`))] : []))] : []),
    ...(() => {
      const alerts = [...(r.pedestrian?.warning ? [r.pedestrian.warning] : []), ...zones.filter((z) => z.warning).map((z) => `${z.name}: ${z.warning}`), ...(r.zone_warnings || [])];
      if (alerts.length > 1) return [el("details", { class: "alerts" }, el("summary", {}, icon("alert"), ` ${alerts.length} avisos sobre as zonas`, icon("chevron")), ...alerts.map((w) => el("p", { class: "alert-line" }, w)))];
      return alerts.map((w) => el("p", { class: "alert-line" }, icon("alert"), " ", w));
    })(),
    ...(eq.length > 1 ? [el("p", { class: `verdict ${verdictKind}` }, verdictKind === "ok" ? icon("check") : icon("alert"), " ",
      `Rotas ${outside ? "livres " : ""}${verdictWord}` + (kmOut ? `, mas o km passou da margem de ±${Math.round(kt * 100)}%` : "") +
      `. Diferença entre a menor e a maior: entregas ${spreads.entregas}% · tempo ${spreads.tempo}% · km ${spreads.km}%.`)] : []),
    ...(eq.length > 1 && worst > 15 ? [outliers(eq, spreads, kt, usedPreset)] : []),
    ...(r.unrouted.length ? [el("p", { class: "alert-line" }, icon("alert"), " ",
      `${r.unrouted.length} entrega${r.unrouted.length > 1 ? "s ficaram" : " ficou"} de fora destas rotas. `, reviewBtn)] : []),
  );
  $("calc-notes").textContent = notes.join(" · ") + ".";
  const byStreet = r.drivers.some((d) => d.path);
  $("legend").textContent = "Cada cor é uma rota e o número marca a primeira parada dela. Círculo grande = partida; pino azul = chegada. "
    + (byStreet ? "Linhas seguem as ruas." : "Linhas retas, não as ruas.") + (walker ? " Contorno tracejado = zona do entregador a pé." : "") + ((r.zones || []).length ? " Contornos coloridos = zonas que você desenhou." : "");
  $("csv-all").href = `/api/jobs/${state.job}/export.csv`;
  $("pdf-all").href = `/api/jobs/${state.job}/paginas.pdf`; $("pdf-all").hidden = !r.has_pages;
  state.texts = dr.map((d) => ({ rota: routeText(d, d.mode === "pe" ? d.end.address || "ponto de saída" : r.depot.address), links: linksText(d) }));
  state.result = r; state.sig = resultSig(r); state.lastCopy = null; state.phones = phoneByLabel();
  const resumed = loadSent(r);
  state.sent = resumed || dr.map(() => ({ rota: false, links: false }));
  for (const [id, label] of [["copy-all-routes", "Copiar todas as rotas"], ["copy-all-links", "Copiar todos os links"]]) {
    const b = $(id); b.classList.remove("done"); b.replaceChildren(icon("copy"), " ", label);
  }
  document.body.classList.add("has-result"); placeGuide();
  drawMap(r);
  renderLegend(r);

  const maxM = Math.max(...eqm, 1), box = $("drivers-out"); box.replaceChildren();
  dr.forEach((d, i) => {
    const body = el("div", { class: "body", hidden: "", id: `body-${i}` });
    const toggle = el("button", { class: "dtoggle", "aria-expanded": "false", "aria-controls": `body-${i}` }, d.label, icon("chevron"));
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") === "true";
      if (!open && !body.childElementCount) fillBody(body, d, mostApprox);
      toggle.setAttribute("aria-expanded", String(!open)); body.hidden = open;
    });
    // O nome acessível é o texto visível + o entregador (oculto): o estado "copiada" fica audível.
    const copyRoute = el("button", { class: "ghost copy-rota", "data-who": d.label }, icon("copy"), " Copiar rota", el("span", { class: "sr" }, ` de ${d.label}`));
    const copyLinks = el("button", { class: "ghost copy-links", "data-who": d.label }, icon("copy"), " Copiar links", el("span", { class: "sr" }, ` de ${d.label}`));
    copyRoute.addEventListener("click", () => copyKind(i, "rota"));
    copyLinks.addEventListener("click", () => copyKind(i, "links"));
    const more = el("details", { class: "more" },
      el("summary", { "aria-label": `Mais ações de ${d.label}` }, "Mais", icon("chevron")),
      el("div", { class: "menu" },
        el("button", { onclick: () => { more.open = false; printSheets([d], `Rota ${d.label}`); } }, icon("print"), " Imprimir lista completa"),
        el("button", { class: "mark-sent", onclick: () => { more.open = false; toggleSent(i); } }, icon("check"), " Marcar como enviado, sem copiar"),
        el("a", { href: d.links[0].url, target: "_blank", rel: "noopener", onclick: () => (more.open = false) }, icon("map"), " Abrir trecho 1 no Maps (nova aba)"),
        ...(r.has_pages ? [el("a", { href: `/api/jobs/${state.job}/paginas.pdf?driver=${d.index}`, target: "_blank", rel: "noopener", onclick: () => (more.open = false) },
          icon("print"), " Intimações desta rota (PDF, nova aba)")] : []),
        el("a", { href: `/api/jobs/${state.job}/export.csv?driver=${d.index}`, onclick: () => (more.open = false) }, icon("download"), " CSV desta rota")));
    const zoneTxt = d.group ? d.group : d.zones[0] ? `${d.zones[0].name}${d.zones.length > 1 ? ` +${d.zones.length - 1}` : ""}` : "sem paradas";
    const head = el("div", { class: "dhead" },
      el("span", { class: "swatch", style: `background:${color(i)}` }, String(i + 1)),
      el("div", { class: "dname" }, el("h3", { class: "dtitle" }, toggle), el("span", { class: "zone" }, zoneTxt, el("span", { class: "chip sent", hidden: "" }, icon("check"), " enviado"))),
      el("div", { class: "dnums" }, el("span", {}, `${d.count} paradas · ${d.deliveries} entregas`), el("span", {}, fmtMin(d.total_min)), el("span", {}, `${Math.round(d.km)} km`)),
      el("div", { class: "bar" + (outsideDriver(d) ? " hatch" : ""), role: "img", "aria-label": `${d.label}: ${CRIT[by]} em relação à maior rota livre, ${Math.round((metric(d) / maxM) * 100)}%${outsideDriver(d) ? " (fora do equilíbrio das livres)" : ""}`, style: `--bar:${color(i)}` }, el("i", { style: `width:${Math.min(100, (metric(d) / maxM) * 100)}%` })),
      el("div", { class: "dact" }, copyRoute, copyLinks, more),
    );
    const row = el("article", { class: "driver" + (outsideDriver(d) ? " outside" : ""), "data-i": String(i), style: `--d:${i}` }, head, body);
    head.addEventListener("mouseenter", () => highlight(i)); head.addEventListener("mouseleave", () => highlight(null));
    head.addEventListener("focusin", () => highlight(i)); head.addEventListener("focusout", () => highlight(null));
    box.append(row);
  });
  state.sent.forEach((_, i) => refreshSent(i));
  const resumedN = state.sent.filter((s) => s.rota || s.links).length;
  $("sent-last").textContent = resumedN ? `Retomando de onde parou: ${resumedN} entregador${resumedN > 1 ? "es" : ""} já marcado${resumedN > 1 ? "s" : ""} como enviado${resumedN > 1 ? "s" : ""}.` : "";
  updateSendbar(); updatePlan();   // "Calcular rotas" vira "Recalcular rotas"
  // espera o layout assentar e a restauração de rolagem do navegador (no recarregamento o painel acabou de aparecer)
  setTimeout(() => $("s3").scrollIntoView({ behavior: "smooth", block: "start" }), 300);
}

// ---- fila de envio: quantos já receberam as duas mensagens e qual é a próxima
function nextMessage() {
  for (let i = 0; i < state.sent.length; i++) {
    if (!state.sent[i].rota) return { i, kind: "rota" };
    if (!state.sent[i].links) return { i, kind: "links" };
  }
  return null;
}
function updateSendbar() {
  const n = state.sent.length, done = state.sent.filter((s) => s.rota && s.links).length, nx = nextMessage();
  const msgs = state.sent.reduce((a, s) => a + s.rota + s.links, 0);
  $("sent-count").textContent = done === n ? `Tudo enviado: rota e links dos ${n} entregadores` : `${done} de ${n} entregadores com rota e links enviados`;
  $("sendbar").classList.toggle("all-done", n > 0 && done === n);
  document.querySelector(".s3-end .hint").textContent = n > 0 && done === n
    ? "Tudo enviado. Se quiser, apague a lista, os nomes e os endereços da memória deste computador."
    : "Terminou de enviar? Apague a lista, os nomes e os endereços da memória deste computador.";
  if (n && done === n && state.sentOneByOne) markSeasoned();   // envio completo de verdade, não o "copiar todas"
  $("sent-meter").style.width = `${n ? (msgs / (2 * n)) * 100 : 0}%`;   // avança a cada mensagem, não só a cada entregador
  const btn = $("copy-next");
  btn.disabled = !nx;
  const who = nx && state.result.drivers[nx.i].label, wa = nx && state.phones?.[who];
  btn.querySelector("use").setAttribute("href", wa ? "#i-chat" : "#i-copy");
  $("copy-next-label").textContent = !nx ? "Tudo enviado"
    : wa ? `Abrir WhatsApp de ${who}: ${nx.kind === "rota" ? "rota" : "links"}`
    : `Copiar ${nx.kind === "rota" ? "rota" : "links"} de ${who}`;
  // no celular, a mesma ação fica fixa na base quando a fila sai da tela
  $("fab-label").textContent = $("copy-next-label").textContent;
  $("copy-next-fab").querySelector("use").setAttribute("href", !nx ? "#i-check" : wa ? "#i-chat" : "#i-copy");
  $("copy-next-fab").disabled = !nx;
  for (const id of ["next-plate", "next-plate-fab"]) {
    const pl = $(id); pl.hidden = !nx;
    if (nx) { pl.textContent = String(nx.i + 1); pl.style.background = color(nx.i); }
  }
  syncFab();
}
function syncFab() {
  const on = !!state.result && !$("s3").hidden && state.barVisible === false;
  $("fab").hidden = !on; document.body.classList.toggle("fab-on", on);
}
function fabInit() {
  $("copy-next-fab").addEventListener("click", copyNext);
  if (!("IntersectionObserver" in window)) return;
  new IntersectionObserver(([e]) => { state.barVisible = e.isIntersecting; syncFab(); }).observe($("sendbar"));
}
// Telefones editados na lista de entregadores valem na hora para a fila (sem recalcular).
function refreshPhones() {
  if (!state.result) return;
  state.phones = phoneByLabel();
  state.sent.forEach((_, i) => refreshSent(i)); updateSendbar();
}
// Clique duplo não pode copiar os links por cima da rota antes de ela ser colada.
async function copyNext() {
  const nx = nextMessage(); if (!nx || Date.now() - (state.lastNextAt || 0) < 700) return;
  state.lastNextAt = Date.now();
  await copyKind(nx.i, nx.kind);
}
// Atalho: tecla C copia a próxima mensagem. Só vale com o foco na tela de rotas (ou em nenhum lugar),
// nunca em campos, links ou botões de outras partes: uma tecla solta não dispara nada por acidente.
document.addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() !== "c" || e.ctrlKey || e.metaKey || e.altKey || !state.result || $("s3").hidden) return;
  const t = e.target;
  if (t.closest && t.closest("input, textarea, select, [contenteditable], dialog")) return;
  if (t !== document.body && !$("s3").contains(t)) return;
  e.preventDefault(); copyNext();
});

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
      el("td", { class: "num c-n" }, el("span", { class: "ord", style: `--rc:${color(d.index)}` }, String(s.order)), multi ? el("span", { class: "badge" }, `${s.n_deliveries}×`) : ""),
      cell("c-name", (x) => x.name, s.name), cell("c-addr", (x) => x.address, s.address), cell("c-code", (x) => x.code, s.code),
      el("td", { class: "num c-leg" }, `+${Math.round(s.leg_min)} min · ${s.leg_km.toFixed(1).replace(".", ",")} km`),
      el("td", { class: "num c-eta" }, fmtMin(s.eta_min)));
  });
  body.append(el("p", { class: "hint" }, "Links do Maps (abra na ordem):"), links,
    el("table", { class: "stops" },
      el("thead", {}, el("tr", {}, ...["#", "Nome", "Endereço", "Rastreio", "Trecho", "Chega em"].map((h, k) => el("th", { class: [0, 4, 5].includes(k) ? "num" : "" }, h)))),
      el("tbody", {}, rows)));
}

// Mapa expandido = janela: foco preso dentro, Esc fecha, enquadra a rota em destaque (ou todas).
function setMapExpanded(on) {
  const box = $("s3-map");
  box.classList.toggle("expanded", on);
  document.body.classList.toggle("map-open", on);
  if (on) { box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true"); }
  else { box.removeAttribute("role"); box.removeAttribute("aria-modal"); }
  const b = $("map-expand"); b.textContent = on ? "Fechar mapa (Esc)" : "Expandir mapa"; b.setAttribute("aria-pressed", on);
  b.focus();
  if (state.map) setTimeout(() => { state.map.invalidateSize(); fitRoute(state.focusRoute); }, 80);
}
function fitRoute(i) {
  const pts = i == null ? state.allPts : state.routes[i]?.pts;
  if (state.map && pts?.length) state.map.fitBounds(pts, { padding: [24, 24] });
}
$("map-expand").addEventListener("click", () => setMapExpanded(!$("s3-map").classList.contains("expanded")));
document.addEventListener("keydown", (e) => {
  if (!document.body.classList.contains("map-open")) return;
  if (e.key === "Escape") return setMapExpanded(false);
  if (e.key === "Tab") {
    const f = [...$("s3-map").querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])")].filter((x) => x.offsetParent);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  }
});

// Legenda: cor + número + nome; clicar destaca a rota no mapa e enquadra só ela (clicar de novo volta a todas).
function renderLegend(r) {
  state.focusRoute = null;
  $("map-legend").replaceChildren(...r.drivers.map((d, i) => {
    const b = el("button", { type: "button", class: "lg", "aria-pressed": "false" },
      el("span", { class: "swatch", style: `background:${color(i)}`, "aria-hidden": "true" }, String(i + 1)), el("span", { class: "lg-name" }, d.label));
    b.addEventListener("click", () => {
      state.focusRoute = state.focusRoute === i ? null : i;
      $("map-legend").querySelectorAll(".lg").forEach((x, k) => x.setAttribute("aria-pressed", String(k === state.focusRoute)));
      highlight(null); fitRoute(state.focusRoute);
    });
    return b;
  }));
}

// Polyline codificada (formato do Google, precisão 5) -> [[lat, lon], ...]
function decodePolyline(s) {
  const out = []; let i = 0, lat = 0, lon = 0;
  const next = () => { let r = 0, sh = 0, b; do { b = s.charCodeAt(i++) - 63; r |= (b & 31) << sh; sh += 5; } while (b >= 32); return r & 1 ? ~(r >> 1) : r >> 1; };
  while (i < s.length) { lat += next(); lon += next(); out.push([lat / 1e5, lon / 1e5]); }
  return out;
}

// No celular um dedo sobre o mapa faria pan e prenderia a rolagem da página: o arrastar fica desligado, com um botão
// para ligar. O pinch (dois dedos) continua dando zoom e toques continuam valendo (desenhar zona, ver dica).
function touchGuard(map, host) {
  if (!L.Browser.mobile) return;
  map.dragging.disable();
  const b = el("button", { type: "button", class: "ghost map-pan", "aria-pressed": "false" }, "Mover o mapa com um dedo");
  b.addEventListener("click", () => {
    const on = b.getAttribute("aria-pressed") !== "true";
    on ? map.dragging.enable() : map.dragging.disable();
    b.setAttribute("aria-pressed", String(on)); b.textContent = on ? "Parar de mover o mapa" : "Mover o mapa com um dedo";
  });
  host.insertAdjacentElement("afterend", b);
}
// Fundo do mapa: o do pacote offline; sem ele, o servidor do OSM (só fora do modo isolado).
function addBasemap(map) {
  const attribution = '© <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>';
  if (state.cfg.basemap && window.protomapsL) {
    protomapsL.leafletLayer({ url: "/mapa/basemap.pmtiles", flavor: "light", lang: "pt", maxDataZoom: 15, attribution: `${attribution} · Protomaps` }).addTo(map);
  } else if (!state.cfg.offline) {
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution }).addTo(map);
  }
}

function drawMap(r) {
  if (!state.map) {
    state.map = L.map("map", { preferCanvas: true, maxZoom: 18 });
    addBasemap(state.map); touchGuard(state.map, $("map"));
    $("map-toggle").addEventListener("click", () => {
      const box = $("s3-map"), on = !box.classList.contains("shown");
      box.classList.toggle("shown", on); $("map-toggle").setAttribute("aria-expanded", String(on));
      $("map-toggle").textContent = on ? "Ocultar o mapa" : "Ver o mapa das rotas";
      if (on) setTimeout(() => { state.map.invalidateSize(); if (state.allPts) state.map.fitBounds(state.allPts, { padding: [20, 20] }); }, 50);
    });
  }
  state.routes.forEach((o) => o.layers.forEach((l) => l.remove())); state.routes = [];
  if (state.zoneLayer) { state.zoneLayer.remove(); state.zoneLayer = null; }
  (state.zoneLayers || []).forEach((l) => l.remove()); state.zoneLayers = [];
  (r.zones || []).forEach((z, i) => state.zoneLayers.push(
    L.polygon(z.polygon, { color: zcolor(i), weight: 2, dashArray: z.profile === "pe" ? "6 6" : null, fillOpacity: 0.07 })
      .bindTooltip(`${z.name} · ${z.deliveries} entrega${z.deliveries === 1 ? "" : "s"}`, { sticky: true }).addTo(state.map)));
  if (r.pedestrian?.active && r.pedestrian.polygon?.length) {   // zona do entregador a pé
    state.zoneLayer = L.polygon(r.pedestrian.polygon, { color: "#7c3aed", weight: 2, dashArray: "6 6", fillOpacity: 0.06, interactive: false }).addTo(state.map);
  }
  const all = [[r.depot.lat, r.depot.lon]];
  r.drivers.forEach((d, i) => {
    const c = color(i), pts = [[d.start.lat, d.start.lon], ...d.stops.map((s) => [s.lat, s.lon]), [d.end.lat, d.end.lon]];
    // Com OSRM vem o trajeto por ruas; sem ele, liga as paradas em linha reta.
    const line = L.polyline(d.path ? decodePolyline(d.path) : pts, { color: c, weight: 2, opacity: 0.6, dashArray: d.mode === "pe" ? "6 6" : null }).addTo(state.map);
    const dots = d.stops.map((s) => L.circleMarker([s.lat, s.lon], { radius: 4, color: c, fillColor: c, fillOpacity: 0.9, weight: 1 })
      .bindTooltip(`${d.label} · #${s.order}`).addTo(state.map));
    const layers = [line, ...dots];
    if (d.stops[0]) {
      const pin = L.marker([d.stops[0].lat, d.stops[0].lon], { icon: L.divIcon({ className: "", html: `<div class="num-pin" style="background:${c}">${i + 1}</div>`, iconSize: [28, 22], iconAnchor: [14, 11] }) })
        .bindTooltip(`${d.label}: primeira parada`).addTo(state.map);
      layers.push(pin);
    }
    const start = L.circleMarker(pts[0], { radius: 8, color: "#000", fillColor: c, fillOpacity: 1, weight: 2 }).bindTooltip(`${d.mode === "pe" ? "Saída e chegada" : "Partida"}: ${d.label}`).addTo(state.map);
    layers.push(start);
    state.routes.push({ line, dots, layers, pts });
    all.push(...pts);
  });
  const end = L.marker([r.depot.lat, r.depot.lon], { alt: "Ponto de chegada", title: "Chegada", keyboard: false }).bindTooltip("Chegada").addTo(state.map);
  state.routes.push({ line: null, dots: [], layers: [end] });
  // Enquadra assim que o mapa tiver tamanho real (o painel acabou de aparecer e o layout ainda assenta).
  state.fitPending = all; state.allPts = all;
  const fit = () => {
    if (!state.fitPending || !$("map").clientWidth) return;
    state.map.invalidateSize(); state.map.fitBounds(state.fitPending, { padding: [20, 20] }); state.fitPending = null;
  };
  if (!state.mapObserver) { state.mapObserver = new ResizeObserver(fit); state.mapObserver.observe($("map")); }
  requestAnimationFrame(fit); setTimeout(fit, 300);
}
function highlight(i) {
  i = i ?? state.focusRoute ?? null;    // sem passar o mouse, volta à rota escolhida na legenda
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
  clearSent();
  state.routes.forEach((o) => o.layers.forEach((l) => l.remove())); state.routes = [];
  resetPanels(); show("wipe", false); setHasJob(false); state.lastDiscard = null; zonesOnIngest();
  setStatus("s1status", "Pronto: lista, nomes, endereços e rotas foram apagados da memória. O elenco salvo neste navegador não foi tocado.", "ok");
  announce("Dados da sessão apagados");
}

init().catch((e) => setStatus("s1status", e.message, "err"));
