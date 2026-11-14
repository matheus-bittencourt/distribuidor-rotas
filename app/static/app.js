"use strict";
const $ = (id) => document.getElementById(id);
const state = { job: null, cfg: null, map: null, layers: [] };

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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmtMin = (m) => `${Math.floor(m / 60)}h${String(Math.round(m % 60)).padStart(2, "0")}`;
const color = (i, n) => `hsl(${Math.round((i * 360) / Math.max(n, 1) + (i % 2) * 18) % 360} 70% 45%)`;

function show(id, on = true) { $(id).hidden = !on; }
function setStatus(id, text, err = false) {
  const s = $(id); s.hidden = !text; s.textContent = text || ""; s.classList.toggle("err", err);
}

// ------------------------------------------------------------------ etapa 1: upload
async function init() {
  state.cfg = await api("/api/config");
  $("depot").value = state.cfg.default_depot;
  $("balance").value = 0.7; $("zone").value = state.cfg.zone_weight;
  $("s1ai").textContent = `Formato livre/PDF: ${state.cfg.llm}. Formatos salvos: ${state.cfg.saved_formats}.`;
  $("gen").addEventListener("click", () => {
    const n = Math.max(1, Math.min(40, parseInt($("n-drivers").value) || 1));
    $("drivers").value = Array.from({ length: n }, (_, i) => `Entregador ${i + 1}`).join("\n"); countDrivers();
  });
  $("map-go").addEventListener("click", sendMapping);
  const drop = $("drop");
  $("file").addEventListener("change", (e) => e.target.files[0] && upload(e.target.files[0]));
  ["dragover", "dragenter"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
  $("wipe").addEventListener("click", wipe);
  $("regeo").addEventListener("click", async () => {
    $("regeo").disabled = true;
    try { await api(`/api/jobs/${state.job}/regeocode`, { method: "POST" }); await refresh(); }
    finally { $("regeo").disabled = false; }
  });
  $("drivers").addEventListener("input", countDrivers);
  $("me").addEventListener("click", addMe);
  $("solve").addEventListener("click", solve);
}

async function upload(file) {
  if (state.job) await api(`/api/jobs/${state.job}`, { method: "DELETE" }).catch(() => {});
  ["review-card", "s2", "s3", "map-card"].forEach((i) => show(i, false));
  show("s1report", false);
  setStatus("s1status", "Enviando…");
  const fd = new FormData(); fd.append("file", file);
  try {
    const { job_id } = await api("/api/upload", { method: "POST", body: fd });
    state.job = job_id; show("wipe");
    await pollIngest();
  } catch (e) { setStatus("s1status", e.message, true); }
}

async function pollIngest() {
  for (;;) {
    const j = await api(`/api/jobs/${state.job}`);
    if (j.state === "erro") return setStatus("s1status", j.error, true);
    if (j.state === "mapear") { setStatus("s1status", ""); return renderMapping(j.mapping); }
    if (j.state === "revisao") { setStatus("s1status", ""); show("map-card", false); return renderIngest(j); }
    const [a, b] = j.progress;
    setStatus("s1status", j.state === "geocodificando" && b ? `${j.message} (${a}/${b})` : j.message || "Processando…");
    await sleep(1200);
  }
}

const GUESS = { name: /nome|cliente|destinat/i, addr: /endere|logradouro|rua/i, code: /rastre|codigo|cod/i };
function renderMapping(m) {
  show("map-card");
  const head = el("tr", {}, ...m.headers.map((h) => el("th", { class: h.sensitive ? "sens" : "" }, h.name || `col ${h.index + 1}`, h.sensitive ? " 🔒" : "")));
  const body = m.sample.map((r) => el("tr", {}, ...m.headers.map((h) => el("td", { class: h.sensitive ? "sens" : "" }, r[h.index] ?? ""))));
  $("map-table").replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
  const fields = $("map-fields"); fields.replaceChildren();
  for (const f of m.fields) {
    const sel = el("select", { "data-key": f.key }, el("option", { value: "" }, "— não usar —"),
      ...m.headers.filter((h) => !h.sensitive).map((h) => el("option", { value: h.index }, h.name || `coluna ${h.index + 1}`)));
    const guess = GUESS[f.key] && m.headers.find((h) => !h.sensitive && GUESS[f.key].test(h.name));
    if (guess) sel.value = guess.index;
    fields.append(el("label", {}, f.label + (f.key === "addr" ? " *" : ""), sel));
  }
  $("map-card").scrollIntoView({ behavior: "smooth" });
}
async function sendMapping() {
  const columns = {};
  document.querySelectorAll("#map-fields select").forEach((s) => (columns[s.dataset.key] = s.value === "" ? null : parseInt(s.value)));
  if (columns.addr == null) return alert("Escolha a coluna do endereço.");
  try {
    await api(`/api/jobs/${state.job}/mapping`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ columns, header_row: $("map-header").checked, remember: $("map-remember").checked }) });
    show("map-card", false); setStatus("s1status", "Lendo com as colunas indicadas…"); await pollIngest();
  } catch (e) { alert(e.message); }
}

function renderIngest(j) {
  const c = j.counts, r = j.report;
  const box = $("s1report"); box.replaceChildren(); show("s1report");
  const chips = el("div", { class: "chips" },
    el("span", { class: "chip ok" }, `${c.ok || 0} localizados`),
    el("span", { class: "chip" + (c.revisar ? " warn" : "") }, `${c.revisar || 0} para revisar`),
    el("span", { class: "chip" }, `método: ${r.method}`),
    ...Object.entries(r.masked).map(([k, v]) => el("span", { class: "chip" }, `${v} × ${k} removidos`)),
    ...r.dropped_columns.map((d) => el("span", { class: "chip" }, `coluna descartada: ${d}`)),
  );
  box.append(chips, ...r.notes.map((n) => el("p", { class: "hint" }, n)));
  renderReview(j.review); show("s2");
  if (!$("drivers").value) $("drivers").placeholder = "Ana; Rua Exemplo, 100, Bairro, Porto Alegre\nBruno; -30.0500, -51.1800\n…";
  countDrivers();
}

async function refresh() {
  const j = await api(`/api/jobs/${state.job}`);
  renderIngest(j);
}

function renderReview(list) {
  show("review-card", list.length > 0);
  $("review-count").textContent = `(${list.length})`;
  const box = $("review-list"); box.replaceChildren();
  for (const s of list) {
    const addr = el("input", { type: "text", value: s.address });
    const coords = el("input", { type: "text", placeholder: "lat, lon (Google Maps)" });
    const act = async (body) => {
      try { await api(`/api/jobs/${state.job}/stops/${s.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); await refresh(); }
      catch (e) { alert(e.message); }
    };
    box.append(el("div", { class: "row" },
      el("div", {}, el("div", { class: "who" }, s.name), el("div", { class: "why" }, s.reason)),
      addr, coords,
      el("div", { class: "btns" },
        el("button", { onclick: () => act({ address: addr.value }) }, "Buscar"),
        el("button", { onclick: () => coords.value && act({ coords: coords.value }) }, "Usar coords"),
        el("button", { class: "ghost danger", onclick: () => act({ discard: true }) }, "Descartar")),
    ));
  }
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
function countDrivers() {
  const n = parseDrivers().length;
  $("drivers-count").textContent = n ? `${n} entregador${n > 1 ? "es" : ""}` : "";
}
function addMe() {
  if (!navigator.geolocation) return alert("Este navegador não oferece localização.");
  navigator.geolocation.getCurrentPosition((p) => {
    const t = $("drivers"); const n = parseDrivers().length + 1;
    t.value += `${t.value && !t.value.endsWith("\n") ? "\n" : ""}Entregador ${n}; ${p.coords.latitude.toFixed(6)}, ${p.coords.longitude.toFixed(6)}\n`;
    countDrivers();
  }, () => alert("Não consegui obter a localização."));
}

async function solve() {
  const drivers = parseDrivers();
  if (!drivers.length) return setStatus("s2status", "Informe pelo menos um entregador.", true);
  $("solve").disabled = true; show("s3", false);
  setStatus("s2status", "Calculando… pode levar até um minuto.");
  try {
    await api(`/api/jobs/${state.job}/solve`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ depot: { address: $("depot").value.trim() }, drivers,
        balance: parseFloat($("balance").value), zone_weight: parseFloat($("zone").value) }),
    });
    for (;;) {
      await sleep(1500);
      const j = await api(`/api/jobs/${state.job}`);
      if (j.state === "erro") throw new Error(j.error);
      if (j.state === "pronto") break;
      setStatus("s2status", j.message || "Calculando…");
    }
    setStatus("s2status", "");
    renderResult(await api(`/api/jobs/${state.job}/result`));
  } catch (e) { setStatus("s2status", e.message, true); }
  finally { $("solve").disabled = false; }
}

// ------------------------------------------------------------------ etapa 3: resultado
function whatsappText(d, depotAddr) {
  const lines = [`*${d.label}* — ${d.count} paradas (~${fmtMin(d.total_min)})`, ""];
  d.stops.forEach((s) => lines.push(`${s.order}. ${s.name} — ${s.address}${s.code ? ` [${s.code}]` : ""}`));
  lines.push("", `Chegada: ${depotAddr || "ponto de chegada"}`, "", "Mapas (siga na ordem):");
  d.links.forEach((l, i) => lines.push(`Trecho ${i + 1} (paradas ${l.first}–${l.last}${l.ends_at_depot ? " + ponto final" : ""}): ${l.url}`));
  return lines.join("\n");
}

function renderResult(r) {
  show("s3");
  const n = r.drivers.length;
  const counts = r.drivers.map((d) => d.count), times = r.drivers.map((d) => d.total_min);
  const total = counts.reduce((a, b) => a + b, 0);
  $("summary").replaceChildren(
    stat(total, "paradas roteirizadas"), stat(n, "entregadores"),
    stat(`${Math.min(...counts)}–${Math.max(...counts)}`, "paradas por entregador"),
    stat(`${fmtMin(Math.min(...times))}–${fmtMin(Math.max(...times))}`, "tempo por rota (estimado)"),
    stat(`${Math.round(r.zone_purity * 100)}%`, "paradas na zona principal do entregador"),
    stat(r.unrouted.length, "fora do cálculo (revisar)"),
    stat(r.matrix, "tempos calculados por"),
  );
  $("csv-all").href = `/api/jobs/${state.job}/export.csv`;
  drawMap(r);

  const box = $("drivers-out"); box.replaceChildren();
  r.drivers.forEach((d, i) => {
    const body = el("div", { class: "body" });
    const links = el("div", { class: "links" }, ...d.links.map((l, k) =>
      el("a", { href: l.url, target: "_blank", rel: "noopener" }, `Maps trecho ${k + 1} · paradas ${l.first}–${l.last}${l.ends_at_depot ? " → final" : ""}`)));
    const copy = el("button", { onclick: async (ev) => {
      await navigator.clipboard.writeText(whatsappText(d, r.depot.address)); ev.target.textContent = "Copiado ✓";
      setTimeout(() => (ev.target.textContent = "Copiar para WhatsApp"), 1800);
    } }, "Copiar para WhatsApp");
    const csv = el("a", { class: "btn ghost", href: `/api/jobs/${state.job}/export.csv?driver=${d.index}` }, "CSV");
    const rows = d.stops.map((s) => el("tr", {},
      el("td", { class: "num" }, s.order), el("td", {}, s.name),
      el("td", { class: s.precision === "aproximado" ? "approx" : "" }, s.address, s.precision === "aproximado" ? " ⚠ posição aproximada" : ""),
      el("td", {}, s.code),
      el("td", { class: "num" }, `+${Math.round(s.leg_min)} min`), el("td", { class: "num" }, fmtMin(s.eta_min))));
    body.append(links, el("div", { class: "actions" }, copy, csv),
      el("table", {}, el("thead", {}, el("tr", {}, ...["#", "Nome", "Endereço", "Rastreio", "Trecho", "Chega em"].map((h) => el("th", {}, h)))), el("tbody", {}, rows)));
    box.append(el("details", { class: "driver" },
      el("summary", {}, el("span", { class: "swatch", style: `background:${color(i, n)}` }), el("strong", {}, d.label),
        el("span", { class: "meta" }, `${d.zones[0] ? d.zones[0].name + " · " : ""}${d.count} paradas · ${fmtMin(d.total_min)} · ${d.links.length} link(s) do Maps`)),
      body));
  });
  $("s3").scrollIntoView({ behavior: "smooth" });
}
const stat = (v, label) => el("div", { class: "stat" }, el("b", {}, String(v)), el("span", {}, label));

function drawMap(r) {
  if (!state.map) {
    state.map = L.map("map", { preferCanvas: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(state.map);
  }
  state.layers.forEach((l) => l.remove()); state.layers = [];
  const n = r.drivers.length, all = [[r.depot.lat, r.depot.lon]];
  r.drivers.forEach((d, i) => {
    const c = color(i, n), pts = [[d.start.lat, d.start.lon], ...d.stops.map((s) => [s.lat, s.lon]), [r.depot.lat, r.depot.lon]];
    state.layers.push(L.polyline(pts, { color: c, weight: 2, opacity: 0.6 }).addTo(state.map));
    d.stops.forEach((s) => state.layers.push(L.circleMarker([s.lat, s.lon], { radius: 4, color: c, fillColor: c, fillOpacity: 0.9, weight: 1 })
      .bindTooltip(`${d.label} · #${s.order}`).addTo(state.map)));
    state.layers.push(L.circleMarker(pts[0], { radius: 8, color: "#000", fillColor: c, fillOpacity: 1, weight: 2 }).bindTooltip(`Início: ${d.label}`).addTo(state.map));
    all.push(...pts);
  });
  state.layers.push(L.marker([r.depot.lat, r.depot.lon]).bindTooltip("Ponto final").addTo(state.map));
  // o cartão acabou de ficar visível: recalcula o tamanho antes de enquadrar
  requestAnimationFrame(() => { state.map.invalidateSize(); state.map.fitBounds(all, { padding: [20, 20] }); });
}

async function wipe() {
  if (!state.job || !confirm("Apagar nomes, endereços e rotas desta sessão?")) return;
  await api(`/api/jobs/${state.job}`, { method: "DELETE" }).catch(() => {});
  state.job = null; location.reload();
}

init().catch((e) => setStatus("s1status", e.message, true));
