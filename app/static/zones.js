"use strict";
// Zonas desenhadas no mapa, cada uma com seu grupo de entregadores (regras em app/zonegroups.py).
// Ficam salvas no servidor, em data/zonas.json (ao lado do executável: acompanham o pen drive e não dependem da
// porta nem do navegador). Cópia em localStorage como reserva. Nenhum dado de entrega vai para lá.
const ZONES_KEY = "distribuidor.zonas.v1";
const ZCOLORS = ["#0f766e", "#b45309", "#1d4ed8", "#be185d", "#4d7c0f", "#7e22ce", "#b91c1c", "#0e7490"];
const zcolor = (i) => ZCOLORS[i % ZCOLORS.length];
const Z = { list: [], map: null, layers: [], stopLayer: null, builtin: null, pts: [], job: null, draft: null, edit: null, editMarkers: [] };

const zClean = (v) => (Array.isArray(v) ? v : []).filter((z) => z && Array.isArray(z.poly) && z.poly.length >= 3).map((z) => ({
  name: String(z.name || ""), profile: z.profile === "pe" ? "pe" : "moto", labels: Array.isArray(z.labels) ? z.labels.map(String) : [],
  start: String(z.start || ""), edge: Number(z.edge) || 0, poly: z.poly.map(([a, b]) => [+a, +b]),
}));
async function zLoad() {
  let fromServer = null;
  try { fromServer = zClean((await api("/api/zonas")).zones); } catch { /* servidor sem o arquivo: usa a reserva do navegador */ }
  let local = [];
  try { local = zClean(JSON.parse(localStorage.getItem(ZONES_KEY))); } catch {}
  if (fromServer && fromServer.length) Z.list = fromServer;
  else if (local.length) { Z.list = local; zSave(); }          // zonas da versão anterior (só no navegador): passam para o arquivo
}
let zTimer = null;
function zSave() {
  try { localStorage.setItem(ZONES_KEY, JSON.stringify(Z.list)); } catch {}
  clearTimeout(zTimer);
  zTimer = setTimeout(async () => {
    const note = $("z-save");
    try { await api("/api/zonas", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ zones: Z.list }) }); note.textContent = "Zonas salvas no arquivo data/zonas.json."; note.classList.remove("warnline"); }
    catch (e) { note.textContent = `Não consegui salvar no arquivo (${e.message}). As zonas ficam só neste navegador.`; note.classList.add("warnline"); }
  }, 500);
}

// ---- geometria (espelha app/pedestrian.py): dentro do polígono ou a até edgeM metros do contorno
function zEdgeDist(p, poly) {
  const kx = 111320 * Math.cos((p[0] * Math.PI) / 180), ky = 111320;
  let best = Infinity;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    const ax = (a[1] - p[1]) * kx, ay = (a[0] - p[0]) * ky, dx = (b[1] - a[1]) * kx, dy = (b[0] - a[0]) * ky, s2 = dx * dx + dy * dy;
    const t = s2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / s2)) : 0;
    best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
  }
  return best;
}
function zInside(p, poly, edgeM = 0) {
  let inside = false;
  for (let i = 0; i < poly.length; i++) {
    const [y1, x1] = poly[i], [y2, x2] = poly[(i + 1) % poly.length];
    if ((y1 > p[0]) !== (y2 > p[0]) && p[1] < x1 + ((p[0] - y1) * (x2 - x1)) / (y2 - y1)) inside = !inside;
  }
  return inside || zEdgeDist(p, poly) <= Math.max(edgeM, 1);
}

// ---- mapa
function zEnsureMap() {
  if (Z.map) return;
  Z.map = L.map("zmap", { preferCanvas: true, maxZoom: 18, doubleClickZoom: false });
  addBasemap(Z.map); touchGuard(Z.map, $("zmap"));
  Z.map.setView([-30.03, -51.2], 11);
  const bp = state.cfg.pedestrian_polygon;
  if (bp && bp.length) Z.builtin = L.polygon(bp, { color: "#7c3aed", weight: 2, dashArray: "6 6", fillOpacity: 0.06, interactive: false })
    .bindTooltip("Zona a pé do Centro (fixa)", { sticky: true }).addTo(Z.map);
  Z.map.on("click", zMapClick);
}
async function zLoadStops() {
  Z.job = state.job; Z.pts = [];
  if (Z.stopLayer) { Z.stopLayer.remove(); Z.stopLayer = null; }
  if (!state.job) return;
  try {
    const list = await api(`/api/jobs/${state.job}/stops`);
    Z.pts = list.filter((s) => s.status === "ok" && s.lat != null).map((s) => [s.lat, s.lon]);
  } catch { return; }
  if (!Z.map) return;
  Z.stopLayer = L.layerGroup(Z.pts.map((p) => L.circleMarker(p, { radius: 2.5, color: "#475569", weight: 1, fillOpacity: 0.7, interactive: false }))).addTo(Z.map);
  if (Z.pts.length && !Z.fitted) { Z.fitted = true; Z.map.fitBounds(L.latLngBounds(Z.pts), { padding: [20, 20] }); }
}
function zonesOnIngest() { Z.fitted = false; if ($("zones-box").open) zLoadStops().then(zRenderList); else Z.job = null; }

function zDrawPolygons() {
  Z.layers.forEach((l) => l.remove()); Z.layers = [];
  Z.list.forEach((z, i) => {
    const c = zcolor(i);
    Z.layers.push(L.polygon(z.poly, { color: c, weight: 2, dashArray: z.profile === "pe" ? "6 6" : null, fillOpacity: 0.1 })
      .bindTooltip(`${z.name || `Zona ${i + 1}`} · ${z.profile === "pe" ? "a pé" : "moto"}`, { sticky: true }).addTo(Z.map));
  });
}

// ---- desenhar
function zSetMode(drawing) {
  ["z-new", "z-view"].forEach((id) => show(id, !drawing));
  ["z-finish", "z-undo", "z-center", "z-cancel"].forEach((id) => show(id, drawing));
  $("zmap").classList.toggle("drawing", drawing);
  $("z-help").textContent = drawing
    ? "Clique no mapa para marcar os cantos da zona (no mínimo 3). Clique no primeiro ponto ou em Concluir para fechar. Só com o teclado: mova o mapa com as setas e use \"Adicionar ponto no centro do mapa\" (o círculo marca o centro)."
    : (Z.list.length ? "" : "Nenhuma zona ainda. Sem zonas, todos os entregadores dividem tudo, como sempre.");
}
function zDraftDraw() {
  const d = Z.draft; d.layers.forEach((l) => l.remove()); d.layers = [];
  if (d.pts.length > 1) d.layers.push(L.polyline(d.pts, { color: "#0f766e", weight: 2, dashArray: "4 4", interactive: false }).addTo(Z.map));
  d.pts.forEach((p, i) => d.layers.push(L.circleMarker(p, { radius: i === 0 ? 7 : 4, color: "#0f766e", fillColor: "#fff", fillOpacity: 1, weight: 2, interactive: false }).addTo(Z.map)));
}
function zStartDraw() {
  if (Z.edit != null) zStopEdit();
  zEnsureMap(); Z.draft = { pts: [], layers: [] }; zSetMode(true);
}
function zCancelDraw() { if (Z.draft) { Z.draft.layers.forEach((l) => l.remove()); Z.draft = null; } zSetMode(false); }
function zAddPoint(latlng) {
  if (!Z.draft) return;
  const p = [+latlng.lat.toFixed(6), +latlng.lng.toFixed(6)], d = Z.draft;
  if (d.pts.length >= 3) {
    const a = Z.map.latLngToContainerPoint(d.pts[0]), b = Z.map.latLngToContainerPoint(latlng);
    if (Math.hypot(a.x - b.x, a.y - b.y) < 14) return zFinishDraw();
  }
  d.pts.push(p); zDraftDraw();
  announce(`Ponto ${d.pts.length} marcado`);
}
function zMapClick(e) { zAddPoint(e.latlng); }
function zFinishDraw() {
  const d = Z.draft;
  if (!d || d.pts.length < 3) { $("z-help").textContent = "Marque pelo menos 3 pontos para fechar a zona."; return; }
  const poly = d.pts.slice(); zCancelDraw(); zAdd(poly);
}
function zAdd(poly) {
  Z.list.push({ name: `Zona ${Z.list.length + 1}`, profile: "moto", labels: [], start: "", edge: 0, poly });
  zSave(); zRender();
  const cards = $("zlist").querySelectorAll(".zcard"); cards[cards.length - 1]?.querySelector("input[type=text]")?.focus();
  announce("Zona criada. Escolha quem atende nela.");
}
function zFromView() {
  zEnsureMap(); const b = Z.map.getBounds(), r = (v) => +v.toFixed(6);
  zAdd([[r(b.getSouth()), r(b.getWest())], [r(b.getSouth()), r(b.getEast())], [r(b.getNorth()), r(b.getEast())], [r(b.getNorth()), r(b.getWest())]]);
}

// ---- editar o contorno: arraste os pontos; duplo clique em um ponto o remove (se sobrarem 3 ou mais)
function zStopEdit() {
  Z.editMarkers.forEach((m) => m.remove()); Z.editMarkers = []; Z.edit = null; zRender();
}
function zStartEdit(i) {
  if (Z.draft) zCancelDraw();
  if (Z.edit != null) zStopEdit();
  zEnsureMap(); Z.edit = i;
  const z = Z.list[i];
  z.poly.forEach((p, k) => {
    const m = L.marker(p, { draggable: true, icon: L.divIcon({ className: "", html: '<div class="zv"></div>', iconSize: [16, 16], iconAnchor: [8, 8] }), keyboard: false }).addTo(Z.map);
    m.on("drag", () => { const ll = m.getLatLng(); z.poly[k] = [+ll.lat.toFixed(6), +ll.lng.toFixed(6)]; Z.layers[i]?.setLatLngs(z.poly); });
    m.on("dragend", () => { zSave(); zRenderList(); });
    m.on("dblclick", () => { if (z.poly.length > 3) { z.poly.splice(k, 1); zSave(); zStartEdit(i); } });
    Z.editMarkers.push(m);
  });
  // o "+" no meio de cada lado cria um ponto novo ali (para dar a curva certa a uma rua ou divisa)
  z.poly.forEach((a, k) => {
    const b = z.poly[(k + 1) % z.poly.length];
    const mid = L.marker([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], { icon: L.divIcon({ className: "", html: '<div class="zm" title="Adicionar ponto aqui"></div>', iconSize: [14, 14], iconAnchor: [7, 7] }), keyboard: false }).addTo(Z.map);
    mid.on("click", (e) => { L.DomEvent.stopPropagation(e); const ll = mid.getLatLng(); z.poly.splice(k + 1, 0, [+ll.lat.toFixed(6), +ll.lng.toFixed(6)]); zSave(); zStartEdit(i); });
    Z.editMarkers.push(mid);
  });
  $("z-help").textContent = `Editando "${z.name}": arraste os círculos cheios para mover os pontos; clique num "+" para criar um ponto novo no meio daquele lado; duplo clique num ponto o remove.`;
  zRenderList();
}

// ---- lista de zonas
function zTaken(label, except) { return Z.list.findIndex((z, i) => i !== except && z.labels.includes(label)); }
function zCount(z) {
  let n = 0, ped = 0;
  const bp = state.cfg.pedestrian_polygon || [];
  for (const p of Z.pts) {
    if (!zInside(p, z.poly, z.edge)) continue;
    if (bp.length && zInside(p, bp, state.cfg.pedestrian_edge_m || 80)) ped++; else n++;
  }
  return { n, ped };
}
function zRenderList() {
  const names = parseDrivers().map((d) => d.label);
  const box = $("zlist"); box.replaceChildren();
  Z.list.forEach((z, i) => {
    const c = zcolor(i), id = `zc-${i}`;
    const name = el("input", { type: "text", id: `${id}-name`, value: z.name, maxlength: "60", "aria-label": `Nome da zona ${i + 1}` });
    name.addEventListener("input", () => { z.name = name.value; zSave(); zDrawPolygons(); zSummary(); });
    const profile = el("select", { id: `${id}-profile`, "aria-label": `Como atende ${z.name || `zona ${i + 1}`}` },
      el("option", { value: "moto" }, "Moto: sai do ponto padrão e volta a ele"), el("option", { value: "pe" }, "A pé: sai e volta ao mesmo ponto"));
    profile.value = z.profile;
    profile.addEventListener("change", () => { z.profile = profile.value; zSave(); zRender(); });
    const start = el("input", { type: "text", id: `${id}-start`, value: z.start, placeholder: "Padrão: a parada mais central da zona", autocomplete: "off" });
    start.addEventListener("input", () => { z.start = start.value; zSave(); });
    const edge = el("input", { type: "number", id: `${id}-edge`, min: "0", max: "500", step: "10", value: String(z.edge || 0) });
    edge.addEventListener("input", () => { z.edge = Math.max(0, Math.min(500, parseFloat(edge.value) || 0)); zSave(); zFillInfo(); });
    // quem atende: chips dos escolhidos (tocar tira) e uma lista para adicionar, em vez de uma caixa por entregador
    const who = el("fieldset", { class: "zwho" }, el("legend", {}, "Quem atende nesta zona"));
    const chosen = z.labels.filter((l) => names.includes(l));
    const free = names.filter((nm) => zTaken(nm, i) < 0 && !z.labels.includes(nm));
    if (!names.length) who.append(el("p", { class: "hint" }, "Cadastre os entregadores acima para escolher."));
    else {
      who.append(el("div", { class: "zchips" }, ...chosen.map((label) => {
        const chip = el("button", { type: "button", class: "zchip", "aria-label": `Tirar ${label} desta zona` }, label, " ×");
        chip.addEventListener("click", () => { z.labels = z.labels.filter((l) => l !== label); zSave(); zRender(); });
        return chip;
      })));
      const add = el("select", { id: `${id}-add`, "aria-label": `Adicionar entregador a ${z.name || `zona ${i + 1}`}` },
        el("option", { value: "" }, free.length ? "Adicionar entregador…" : "Nenhum entregador livre"), ...free.map((nm) => el("option", { value: nm }, nm)));
      add.disabled = !free.length;
      add.addEventListener("change", () => {
        if (!add.value) return;
        z.labels = [...z.labels, add.value]; zSave(); zRender();
        document.getElementById(`${id}-add`)?.focus();
      });
      who.append(add, el("p", { class: "hint" }, "Quem já está em outra zona não aparece na lista."));
    }
    const missing = z.labels.filter((l) => !names.includes(l));
    if (missing.length) who.append(el("p", { class: "hint warnline" }, `Fora da lista de entregadores: ${missing.join(", ")}. Não serão usados.`));
    const info = el("p", { class: "zinfo hint", id: `${id}-info`, role: "status" });
    const del = el("button", { type: "button", class: "ghost danger" }, "Remover zona");
    twoStep(del, "Confirmar: remover", () => { if (Z.edit != null) zStopEdit(); Z.list.splice(i, 1); zSave(); zRender(); announce("Zona removida"); });
    box.append(el("article", { class: "zcard", style: `--zc:${c}`, "data-i": String(i) },
      el("div", { class: "zhead" }, el("span", { class: "zsw", "aria-hidden": "true" }), name),
      el("div", { class: "zgrid" },
        el("div", { class: "field" }, el("label", { for: `${id}-profile` }, "Como atende"), profile),
        ...(z.profile === "pe" ? [el("div", { class: "field" }, el("label", { for: `${id}-start` }, "Ponto de saída e chegada (opcional)"), start)] : [])),
      who,
      el("details", { class: "zadv" }, el("summary", {}, "Avançado"),
        el("div", { class: "field" }, el("label", { for: `${id}-edge` }, "Faixa de borda (m)"), edge,
          el("span", { class: "hint" }, "Entregas até essa distância do contorno também entram na zona. Útil porque o endereço é a rua, e a rua pode ficar do outro lado da linha. 0 = só o que está dentro."))),
      info,
      el("div", { class: "actions tight" },
        el("button", { type: "button", class: "ghost", onclick: () => { zEnsureMap(); Z.map.fitBounds(L.polygon(z.poly).getBounds(), { padding: [20, 20] }); } }, "Ver no mapa"),
        el("button", { type: "button", class: "ghost", "aria-pressed": String(Z.edit === i), onclick: () => (Z.edit === i ? zStopEdit() : zStartEdit(i)) }, Z.edit === i ? "Concluir edição" : "Editar contorno"),
        del)));
  });
  zFillInfo(); zSummary();
}
function zFillInfo() {
  Z.list.forEach((z, i) => {
    const info = document.getElementById(`zc-${i}-info`); if (!info) return;
    const parts = [];
    if (!z.labels.length) parts.push("Escolha ao menos um entregador: sem isso o cálculo não roda.");
    if (Z.pts.length) {
      const { n, ped } = zCount(z);
      parts.push(`${n} entrega${n === 1 ? "" : "s"} da lista de hoje dentro desta zona` + (z.labels.length > 1 ? `, divididas entre ${z.labels.length} entregadores` : ""));
      if (ped) parts.push(`${ped} delas estão na zona a pé do Centro e ficam com o entregador a pé`);
      if (n && n / Math.max(z.labels.length, 1) > 90) parts.push("muita entrega por entregador: considere mais gente nesta zona");
    } else parts.push("Carregue a lista do dia para ver quantas entregas caem aqui.");
    info.textContent = parts.join(" · ") + ".";
    info.classList.toggle("warnline", !z.labels.length);
  });
}
// Zonas sem nenhum entregador (da lista atual): enquanto houver, o cálculo fica bloqueado e a tela diz qual é.
function zonesIncomplete() {
  const names = parseDrivers().map((d) => d.label);
  return Z.list.filter((zz) => !zz.labels.some((l) => names.includes(l))).map((zz) => zz.name.trim() || "sem nome");
}
function zSummary() {
  const n = Z.list.length, k = new Set(Z.list.flatMap((z) => z.labels)).size;
  $("zones-summary").textContent = n ? `${n} zona${n > 1 ? "s" : ""} · ${k} entregador${k === 1 ? "" : "es"} nelas` : "nenhuma";
  if (typeof updatePlan === "function" && state.cfg) updatePlan();
}
function zRender() { if (Z.map) zDrawPolygons(); zRenderList(); if (!Z.draft) zSetMode(false); }

// ---- usado por app.js
function zonesPayload() {
  const names = parseDrivers().map((d) => d.label);
  return Z.list.map((z, i) => {
    const m = z.start.trim().match(/^(-?\d{1,2}[.,]\d+)\s*[,; ]\s*(-?\d{1,3}[.,]\d+)$/);
    const start = z.profile !== "pe" || !z.start.trim() ? {} : m ? { lat: parseFloat(m[1].replace(",", ".")), lon: parseFloat(m[2].replace(",", ".")) } : { address: z.start.trim() };
    return { name: z.name.trim() || `Zona ${i + 1}`, polygon: z.poly, profile: z.profile, drivers: z.labels.map((l) => names.indexOf(l)).filter((k) => k >= 0), start, edge_m: z.edge || 0 };
  });
}

async function zonesInit() {
  await zLoad();
  const box = $("zones-box");
  zSetMode(false); zRenderList();
  box.addEventListener("toggle", () => {
    if (!box.open) return;
    zEnsureMap(); zDrawPolygons();
    setTimeout(() => { Z.map.invalidateSize(); if (Z.job !== state.job) zLoadStops().then(zRenderList); else if (Z.pts.length && !Z.fitted) { Z.fitted = true; Z.map.fitBounds(L.latLngBounds(Z.pts), { padding: [20, 20] }); } }, 50);
  });
  $("z-new").addEventListener("click", zStartDraw);
  $("z-view").addEventListener("click", zFromView);
  $("z-finish").addEventListener("click", zFinishDraw);
  $("z-center").addEventListener("click", () => zAddPoint(Z.map.getCenter()));
  $("z-cancel").addEventListener("click", zCancelDraw);
  $("z-undo").addEventListener("click", () => { if (Z.draft && Z.draft.pts.length) { Z.draft.pts.pop(); zDraftDraw(); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && Z.draft) zCancelDraw(); });
  let t; $("drivers").addEventListener("input", () => { clearTimeout(t); t = setTimeout(zRenderList, 400); });   // nomes mudaram: refaz as escolhas
  if (Z.list.length) box.open = false;
}
