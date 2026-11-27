"""API + interface web do distribuidor de rotas (POC).

Rodar:  .venv\\Scripts\\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import csv
import io
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import jobs, pedestrian, templates, zonegroups, zonestore, zones
from .config import FALLBACK_DEPOT, RMPA_CITIES, SETTINGS
from .extract import COLUMN_LABELS, NeedMapping, extract, llm_provider, to_query
from .geocode import geocode_stops, in_metro, in_region, make_geocoder
from .links import build_links
from .models import ExtractReport
from starlette.formparsers import MultiPartParser

from . import mapdata, netguard, updater
from .matrix import build_matrix, build_walk_matrix, osrm_paths
from .sanitize import is_sensitive_header, strip_accents
from .solver import solve

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 25 * 1024 * 1024          # por arquivo
MAX_UPLOAD_TOTAL = 100 * 1024 * 1024   # todos os arquivos de um envio
MAX_FILES = 20

app = FastAPI(title="Distribuidor de rotas (POC)")

if SETTINGS.offline:
    netguard.install()   # modo isolado: nenhuma conexão sai deste computador

# Arquivo enviado fica só na memória (o padrão do Starlette grava em disco acima de 1 MB).
MultiPartParser.spool_max_size = MAX_UPLOAD + 1024 * 1024


@app.middleware("http")
async def no_store(request, call_next):
    """Respostas com dados de entrega não ficam no cache do navegador."""
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


class FreshStatic(StaticFiles):
    """Arquivos da interface sempre revalidados: quem testa e edita não fica preso a uma versão antiga."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", FreshStatic(directory=STATIC), name="static")


# ------------------------------------------------------------------ esquemas

class PointIn(BaseModel):
    address: str | None = None
    lat: float | None = None
    lon: float | None = None


class DriverIn(BaseModel):
    label: str = ""
    start: PointIn = PointIn()   # vazio = sai do ponto padrão


class PedestrianIn(BaseModel):
    enabled: bool = True              # entregas da zona do Centro vão todas para um entregador a pé
    start: PointIn = PointIn()        # vazio = ponto padrão dentro da zona (Praça da Alfândega)


class ZoneIn(BaseModel):
    name: str = Field("", max_length=60)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=500)   # [lat, lon]
    profile: Literal["moto", "pe"] = "moto"
    drivers: list[int] = Field(default_factory=list, max_length=40)           # posições na lista de entregadores
    start: PointIn = PointIn()                                                # perfil "pe": onde o grupo sai e volta
    edge_m: float = Field(0.0, ge=0, le=500)                                  # faixa em volta do contorno


class SolveIn(BaseModel):
    depot: PointIn
    drivers: list[DriverIn] = Field(min_length=1, max_length=40)
    balance: float = Field(1.0, ge=0, le=1)       # até onde redistribuir para igualar a carga
    balance_by: Literal["stops", "time", "km"] = "km"   # critério prioritário ao igualar a carga
    zone_weight: float | None = Field(None, ge=0, le=1)
    # faixa de km em torno da média (0,15 = ±15%, o padrão); null = tentar igualar os km
    km_tolerance: float | None = Field(SETTINGS.km_tolerance or None, ge=0, le=1)
    time_limit: int | None = Field(None, ge=5, le=300)
    service_seconds: int | None = Field(None, ge=0, le=1800)
    tolerance_seconds: int | None = Field(None, ge=0, le=1800)   # folga por entrega (padrão: 5 min)
    traffic: float = Field(1.0, ge=1.0, le=2.0)   # trânsito esperado: multiplica o tempo de deslocamento das motos (1 = rua livre)
    pedestrian: PedestrianIn = PedestrianIn()
    zones: list[ZoneIn] = Field(default_factory=list, max_length=12)


class MoveIn(BaseModel):
    stop: int                 # id de uma entrega da parada que vai mudar de rota (vão todas as do mesmo ponto)
    to: int                   # posição do entregador que recebe
    preview: bool = True      # True: só calcula antes/depois; False: aplica


class StopPatch(BaseModel):
    name: str | None = None
    address: str | None = None
    coords: str | None = None   # "lat, lon" colado do Google Maps
    discard: bool | None = None
    restore: bool | None = None   # desfaz um descarte


class MappingIn(BaseModel):
    columns: dict[str, int | None]
    header_row: bool = True
    remember: bool = False


# ------------------------------------------------------------------ páginas

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/config")
def config():
    prov = llm_provider()
    return {
        "default_depot": SETTINGS.default_depot,
        "geocoder": SETTINGS.geocoder,
        "pedestrian": SETTINGS.pedestrian,
        "pedestrian_edge_m": SETTINGS.pedestrian_edge_m,
        "pedestrian_polygon": pedestrian.polygon().tolist() if SETTINGS.pedestrian else [],
        "matrix": SETTINGS.matrix,
        "llm": {"ollama": "IA local (Ollama)", "anthropic": "API Anthropic"}.get(prov, "nenhuma (heurística)"),
        "service_seconds": SETTINGS.service_seconds,
        "extra_delivery_seconds": SETTINGS.extra_delivery_seconds,
        "delivery_tolerance_seconds": SETTINGS.delivery_tolerance_seconds,
        "solver_seconds": SETTINGS.solver_seconds,
        "zone_weight": SETTINGS.zone_weight,
        "zone_weight_max": SETTINGS.zone_weight_max,
        "km_tolerance": SETTINGS.km_tolerance or None,
        "maps_waypoints_per_link": SETTINGS.maps_waypoints_per_link,
        "job_ttl_minutes": SETTINGS.job_ttl_minutes,
        "saved_formats": len(templates.all_templates()),
        "column_labels": COLUMN_LABELS,
        "offline": SETTINGS.offline,
        "basemap": mapdata.basemap_path() is not None,
    }


@app.get("/api/zonas")
def zones_saved():
    return zonestore.load()


@app.put("/api/zonas")
def zones_save(body: zonestore.SavedZones):
    zonestore.save(body)
    return {"saved": len(body.zones)}


# ------------------------------------------------------------------ pacote de mapa e atualização

class MapPrefIn(BaseModel):
    verificar: bool


@app.get("/api/mapa")
def map_status():
    return updater.status()


@app.post("/api/mapa/verificar")
def map_check(force: bool = False):
    return updater.check(force=force)


@app.post("/api/mapa/baixar")
def map_download():
    try:
        return updater.start_download()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/mapa/preferencia")
def map_pref(body: MapPrefIn):
    return updater.set_check(body.verificar)


@app.get("/mapa/basemap.pmtiles")
def basemap():
    p = mapdata.basemap_path()
    if not p:
        raise HTTPException(404, "Fundo do mapa não instalado.")
    return FileResponse(p, media_type="application/octet-stream", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ ingestão

def _add_file(job: jobs.Job, idx: int, filename: str, data: bytes, stops: list, rep) -> None:
    """Junta as entregas de um arquivo às do job: renumera, marca a origem e tira código de rastreio já visto."""
    dup = 0
    kept = 0
    for s in stops:
        if s.code and s.code in job.codes:
            dup += 1
            continue
        if s.code:
            job.codes.add(s.code)
        s.id, s.src, s.file = len(job.stops), idx, filename
        job.stops.append(s)
        kept += 1
    if any(s.pages for s in job.stops if s.src == idx):
        job.sources[idx] = data     # PDF de intimações: o original fica para o PDF de cada entregador
    job.parts.append((filename, rep))
    job.files.append({"name": filename, "stops": kept, "rows_read": rep.rows_read, "duplicates": dup,
                      "method": rep.method, "error": ""})


def _combined_report(job: jobs.Job) -> ExtractReport:
    """Um relatório só: com um arquivo, o dele; com vários, somado e com as notas ao lado do nome do arquivo."""
    if len(job.parts) == 1 and job.n_files == 1:
        return job.parts[0][1]
    out = ExtractReport()
    methods: set[str] = set()
    for name, rep in job.parts:
        methods |= {m for m in rep.method.split("+") if m}
        out.rows_read += rep.rows_read
        out.skipped_lines += rep.skipped_lines
        out.dropped_columns += rep.dropped_columns
        for k, v in rep.masked.items():
            out.masked[k] = out.masked.get(k, 0) + v
        out.notes += [f"{name}: {n}" for n in rep.notes]
    for f in job.files:
        if f["error"]:
            out.notes.append(f"{f['name']}: NÃO foi lido ({f['error']}). As entregas desse arquivo não estão na lista.")
        elif f["duplicates"]:
            out.notes.append(f"{f['name']}: {f['duplicates']} entrega(s) com código de rastreio já presente em "
                             "arquivo anterior foram ignoradas.")
    out.method = "+".join(sorted(methods)) or "nenhum"
    return out


def _ingest(job: jobs.Job, mapping: dict | None = None) -> None:
    """Lê os arquivos da fila, um por vez, e geocodifica tudo junto. Se um deles tem colunas que não reconheço,
    para em 'mapear' com esse arquivo na frente da fila; set_mapping chama de novo e a leitura continua dali."""
    try:
        multi = job.n_files > 1
        while job.queue:
            idx, filename, data = job.queue[0]
            where = f"Arquivo {idx + 1} de {job.n_files} ({filename}): " if multi else ""
            job.state, job.message = "lendo", (f"Lendo {filename} ({idx + 1} de {job.n_files})" if multi else "Lendo o arquivo")

            def prog(msg: str, _w=where):
                job.message = _w + msg

            try:
                stops, report = extract(filename, data, prog, mapping=mapping)
            except NeedMapping as nm:
                job.mapping_info = {
                    "headers": [{"index": i, "name": h, "sensitive": bool(h and is_sensitive_header(h))}
                                for i, h in enumerate(nm.headers)],
                    "sample": nm.sample, "total_rows": nm.total_rows,
                    "fields": [{"key": k, "label": v} for k, v in COLUMN_LABELS.items()],
                    "file": filename, "file_index": idx + 1, "file_total": job.n_files,
                }
                job.state, job.message = "mapear", ""
                return
            except Exception as exc:
                if not multi:
                    raise
                # um arquivo ruim não derruba os outros, mas o aviso fica visível no relatório
                job.files.append({"name": filename, "stops": 0, "rows_read": 0, "duplicates": 0, "method": "", "error": str(exc)})
                job.queue.pop(0)
                mapping = None
                continue
            mapping = None
            job.queue.pop(0)          # o arquivo original sai da memória (só o PDF de intimações fica, em job.sources)
            _add_file(job, idx, filename, data, stops, report)
            del data
        job.mapping_info = None
        if not job.stops:
            errs = "; ".join(f"{f['name']}: {f['error']}" for f in job.files if f["error"])
            raise ValueError(errs or "Nenhum endereço foi encontrado nos arquivos.")
        job.report = _combined_report(job)
        job.state, job.message = "geocodificando", "Localizando endereços no mapa"
        geocode_stops(job.stops, lambda a, b: setattr(job, "progress", (a, b)))
        job.state, job.message = "revisao", ""
    except Exception as exc:
        job.state, job.error = "erro", str(exc)


@app.post("/api/upload")
async def upload(file: list[UploadFile] = File(...)):
    """Um ou mais arquivos (o campo `file` repetido): viram uma lista só."""
    if len(file) > MAX_FILES:
        raise HTTPException(413, f"Arquivos demais (limite de {MAX_FILES} por envio).")
    blobs: list[tuple[str, bytes]] = []
    total = 0
    for f in file:
        data = await f.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, f"{f.filename or 'Arquivo'}: grande demais (limite de 25 MB por arquivo).")
        total += len(data)
        if total > MAX_UPLOAD_TOTAL:
            raise HTTPException(413, "Os arquivos juntos passam do limite de 100 MB.")
        blobs.append((f.filename or "", data))
    job = jobs.create()
    job.n_files = len(blobs)
    job.queue = [(i, n, d) for i, (n, d) in enumerate(blobs)]
    del blobs
    threading.Thread(target=_ingest, args=(job,), daemon=True).start()
    return {"job_id": job.id}


@app.post("/api/jobs/{job_id}/mapping")
def set_mapping(job_id: str, body: MappingIn):
    job = _job(job_id)
    if job.state != "mapear" or not job.queue:
        raise HTTPException(409, "Este processamento não está esperando o mapeamento de colunas.")
    if body.columns.get("addr") is None:
        raise HTTPException(400, "Indique qual coluna é o endereço.")
    job.state = "lendo"
    threading.Thread(target=_ingest, args=(job, body.model_dump()), daemon=True).start()
    return _summary(job)


def _job(job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Processamento não encontrado ou expirado.")
    return job


def _summary(job: jobs.Job) -> dict:
    counts: dict[str, int] = {}
    for s in job.stops:
        counts[s.status] = counts.get(s.status, 0) + 1
    rep = job.report
    return {
        "id": job.id, "state": job.state, "message": job.message, "error": job.error,
        "progress": list(job.progress), "counts": counts, "total": len(job.stops),
        "mapping": job.mapping_info, "files": job.files,
        "report": None if rep is None else {
            "method": rep.method, "rows_read": rep.rows_read, "masked": rep.masked,
            "dropped_columns": sorted(set(rep.dropped_columns)), "skipped_lines": rep.skipped_lines,
            "notes": rep.notes,
        },
    }


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = _job(job_id)
    out = _summary(job)
    out["review"] = [s.public() for s in job.stops if s.status == "revisar"]
    return out


@app.get("/api/jobs/{job_id}/stops")
def job_stops(job_id: str):
    return [s.public() for s in _job(job_id).stops]


@app.delete("/api/jobs/{job_id}")
def job_delete(job_id: str):
    return {"deleted": jobs.delete(job_id)}


# ------------------------------------------------------------------ revisão

_COORDS = re.compile(r"(-?\d{1,2}[.,]\d+)\s*[,; ]\s*(-?\d{1,3}[.,]\d+)")


@app.patch("/api/jobs/{job_id}/stops/{stop_id}")
def patch_stop(job_id: str, stop_id: int, body: StopPatch):
    job = _job(job_id)
    stop = next((s for s in job.stops if s.id == stop_id), None)
    if not stop:
        raise HTTPException(404, "Parada não encontrada.")
    if body.name is not None:
        stop.name = body.name.strip() or stop.name
    if body.restore:
        stop.status, stop.reason = "revisar", "restaurada: corrija o endereço ou use coordenadas"
    elif body.discard:
        stop.status, stop.reason = "descartado", "descartado na revisão"
    elif body.coords:
        m = _COORDS.search(body.coords)
        if not m:
            raise HTTPException(400, "Coordenadas no formato 'lat, lon' (ex.: -30.0346, -51.2177).")
        lat, lon = float(m[1].replace(",", ".")), float(m[2].replace(",", "."))
        if not in_region(lat, lon):
            raise HTTPException(400, "Coordenadas fora de Porto Alegre.")
        stop.lat, stop.lon, stop.status, stop.precision, stop.reason = lat, lon, "ok", "manual", ""
    elif body.address is not None:
        stop.address, stop.query, stop.status = body.address.strip(), to_query(body.address), "pendente"
        geocode_stops([stop])
    return stop.public()


@app.post("/api/jobs/{job_id}/regeocode")
def regeocode(job_id: str):
    job = _job(job_id)
    geocode_stops(job.stops, retry=True)
    return _summary(job)


# ------------------------------------------------------------------ cálculo

_CITY_WORDS = [strip_accents(c) for c in RMPA_CITIES]


def _start_query(address: str) -> str:
    """Casa de entregador pode ficar na região metropolitana: só acrescenta Porto Alegre se não houver cidade."""
    low = strip_accents(address).lower()
    if any(c in low for c in _CITY_WORDS) or re.search(r"\brs\b", low):
        return address
    return f"{address}, {SETTINGS.default_city}, RS"


def _resolve(point: PointIn, geocoder, fallback: tuple[float, float] | None = None):
    if point.lat is not None and point.lon is not None:
        return point.lat, point.lon
    if point.address:
        geo = geocoder.geocode(_start_query(point.address), wide=True)
        if geo and in_metro(geo.lat, geo.lon):
            return geo.lat, geo.lon
    return fallback


def _zone_specs(req: SolveIn, geocoder=None) -> list[zonegroups.ZoneSpec]:
    """Zonas desenhadas do pedido, validadas. Com `geocoder`, também localiza o ponto de saída dos grupos a pé."""
    k = len(req.drivers)
    out, used = [], set()
    for n, z in enumerate(req.zones, start=1):
        name = z.name.strip() or f"Zona {n}"
        if any(not (-90 <= la <= 90 and -180 <= lo <= 180) for la, lo in z.polygon):
            raise ValueError(f"Zona \"{name}\": contorno com coordenadas inválidas.")
        if not z.drivers:
            raise ValueError(f"Zona \"{name}\": escolha ao menos um entregador para ela.")
        for d in z.drivers:
            if not 0 <= d < k:
                raise ValueError(f"Zona \"{name}\": entregador inexistente na lista.")
            if d in used or z.drivers.count(d) > 1:
                raise ValueError(f"Zona \"{name}\": um entregador só pode estar em uma zona.")
            used.add(d)
        start = None
        if z.profile == "pe" and (z.start.address or z.start.lat is not None) and geocoder is not None:
            start = _resolve(z.start, geocoder)
            if start is None:
                raise ValueError(f"Zona \"{name}\": não foi possível localizar o ponto de saída.")
        out.append(zonegroups.ZoneSpec(name, np.array(z.polygon, dtype=float), z.profile, list(z.drivers), start, z.edge_m))
    return out


def _run_solve(job: jobs.Job, req: SolveIn) -> None:
    try:
        geocoder = make_geocoder()
        job.message = "Localizando ponto padrão e pontos de partida"
        is_default = req.depot.address in (None, "", SETTINGS.default_depot)
        depot = _resolve(req.depot, geocoder, FALLBACK_DEPOT if is_default else None)
        if depot is None:
            raise ValueError("Não foi possível localizar o ponto de partida/chegada informado.")
        starts, bad = [], []
        for i, d in enumerate(req.drivers):
            if not d.start.address and d.start.lat is None:
                starts.append(depot)  # sem endereço próprio: sai do ponto padrão
                continue
            p = _resolve(d.start, geocoder)
            if p is None:
                bad.append(d.label or f"Entregador {i + 1}")
            starts.append(p)
        if bad:
            raise ValueError("Ponto de partida não localizado para: " + ", ".join(bad)
                             + ". Informe o endereço completo ou as coordenadas.")

        ok = [s for s in job.stops if s.status == "ok"]
        if not ok:
            raise ValueError("Não há endereços localizados para roteirizar.")
        job.state, job.message = "calculando", "Calculando tempos de deslocamento e rotas"

        # Várias entregas no mesmo ponto (casa ou condomínio) viram UMA parada: o entregador para uma vez.
        by_point: dict[tuple[float, float], list] = {}
        for s in ok:
            by_point.setdefault((round(s.lat, 6), round(s.lon, 6)), []).append(s)
        visits = list(by_point.values())

        zone_names, zone_centers = zones.load()
        stop_xy = np.array([[v[0].lat, v[0].lon] for v in visits])
        zone_idx = zones.assign(stop_xy)
        for v, z in zip(visits, zone_idx):
            for s in v:
                s.zone = zone_names[z]

        method = {"v": "", "w": ""}

        def matrix_fn(coords):
            t, d, method["v"] = build_matrix(coords)
            if req.traffic != 1.0:      # o mapa não conhece o trânsito do dia: o tempo de deslocamento cresce pelo fator
                t = np.rint(t * req.traffic).astype(t.dtype)
            return t, d

        def walk_matrix_fn(coords):
            t, d, method["w"] = build_walk_matrix(coords)
            return t, d

        service = SETTINGS.service_seconds if req.service_seconds is None else req.service_seconds
        zw = SETTINGS.zone_weight if req.zone_weight is None else req.zone_weight
        extra = SETTINGS.extra_delivery_seconds
        tol = SETTINGS.delivery_tolerance_seconds if req.tolerance_seconds is None else req.tolerance_seconds
        # tempo parado = base da parada + extra por entrega adicional + tolerância de CADA entrega
        visit_service = np.array([service + extra * (len(v) - 1) + tol * len(v) for v in visits], dtype=np.int64)
        time_limit = req.time_limit or SETTINGS.solver_seconds

        # Zonas: a zona a pé do Centro vem primeiro; depois as zonas desenhadas (cada uma com seu grupo de
        # entregadores); o resto vai para os entregadores livres (os que não estão em nenhuma zona).
        ped_on = SETTINGS.pedestrian and req.pedestrian.enabled
        in_zone = pedestrian.inside(stop_xy) if ped_on else np.zeros(len(visits), dtype=bool)
        specs = _zone_specs(req, geocoder)
        labels, zone_warnings = zonegroups.assign(stop_xy, in_zone, specs)
        for zi, z in enumerate(specs):
            for j in np.flatnonzero(labels == zi):
                for s in visits[j]:
                    s.zone = z.name
        walk_idx, rest_idx = np.flatnonzero(labels == zonegroups.BUILTIN), np.flatnonzero(labels == zonegroups.FREE)
        zoned = {d for z in specs for d in z.drivers}
        free_drivers = [i for i in range(len(req.drivers)) if i not in zoned]
        if rest_idx.size and not free_drivers:
            raise ValueError("Há entregas fora das zonas e todos os entregadores estão em zonas. "
                             "Deixe ao menos um entregador livre ou desenhe uma zona para o resto.")
        walk_start, walk_addr = None, ""
        if walk_idx.size:
            ps = req.pedestrian.start
            if ps.address or ps.lat is not None:
                walk_start, walk_addr = _resolve(ps, geocoder), ps.address or ""
                if walk_start is None:
                    raise ValueError("Não foi possível localizar o ponto de saída do entregador a pé.")
            else:
                dlat, dlon, walk_addr = pedestrian.default_start()
                walk_start = (dlat, dlon)

        def sub(idx):
            return dict(stop_service=visit_service[idx], stop_deliveries=np.array([len(visits[j]) for j in idx]))

        res = solve(
            stop_xy[rest_idx].reshape(-1, 2), np.array([starts[i] for i in free_drivers]).reshape(-1, 2),
            np.array(depot), matrix_fn,
            service_seconds=service, balance=req.balance, time_limit=time_limit,
            zone_idx=zone_idx[rest_idx], zone_centers=zone_centers, zone_weight=zw, balance_by=req.balance_by,
            km_tolerance=req.km_tolerance, **sub(rest_idx),
        )
        total_seconds = res.total_seconds
        wres = None
        if walk_idx.size:   # uma só rota, de pedestre, que sai e volta ao ponto dele; sem equilibrar com as motos
            wres = solve(
                stop_xy[walk_idx], np.array([walk_start]), np.array(walk_start), walk_matrix_fn,
                service_seconds=service, balance=0.0, time_limit=min(time_limit, 15), **sub(walk_idx),
            )
            total_seconds += wres.total_seconds
        zone_runs = []      # (zona, paradas, resultado, ponto de saída do grupo a pé)

        def zlimit(idx):    # grupo pequeno não precisa do tempo todo
            return max(3, min(time_limit, 15, 2 + len(idx) // 20))

        for zi, z in enumerate(specs):
            idx = np.flatnonzero(labels == zi)
            zstart = None
            if z.profile == "pe":
                zstart = z.start or (tuple(stop_xy[idx][np.argmin(((stop_xy[idx] - z.polygon.mean(0)) ** 2).sum(1))])
                                     if idx.size else tuple(z.polygon.mean(0)))
                zsol = solve(
                    stop_xy[idx].reshape(-1, 2), np.array([zstart] * len(z.drivers)), np.array(zstart), walk_matrix_fn,
                    service_seconds=service, balance=req.balance if len(z.drivers) > 1 else 0.0,
                    time_limit=zlimit(idx), balance_by=req.balance_by, **sub(idx),
                )
            else:
                zsol = solve(
                    stop_xy[idx].reshape(-1, 2), np.array([starts[d] for d in z.drivers]), np.array(depot), matrix_fn,
                    service_seconds=service, balance=req.balance, time_limit=zlimit(idx),
                    balance_by=req.balance_by, km_tolerance=req.km_tolerance, **sub(idx),
                )
            total_seconds += zsol.total_seconds
            zone_runs.append((z, idx, zsol, zstart))
        if not method["v"]:
            method["v"] = method["w"] or "estimativa"

        route_of: dict[int, list[int]] = {}     # paradas (visitas) de cada rota, na ordem: base de "mover parada"

        def make_driver(i, label, start, start_addr, idxs, legs, meters, end, end_addr, mode):
            route_of[i] = [int(x) for x in idxs]
            seq = [visits[j] for j in idxs]
            svc = [int(visit_service[j]) for j in idxs]
            t, rows = 0, []
            for order, (v, leg, leg_m, sv) in enumerate(zip(seq, legs, meters, svc), start=1):
                t += leg
                s = v[0]
                rows.append({
                    "order": order, "id": s.id, "name": s.name, "address": s.address, "code": s.code,
                    "n_deliveries": len(v),
                    "deliveries": [{"id": x.id, "name": x.name, "address": x.address, "code": x.code} for x in v],
                    "zone": s.zone, "lat": s.lat, "lon": s.lon, "leg_min": round(leg / 60, 1), "leg_km": round(leg_m / 1000, 1),
                    "eta_min": round(t / 60), "precision": s.precision,
                })
                t += sv
            travel = sum(legs)
            zc = Counter(v[0].zone for v in seq).most_common()
            return {
                "index": i, "label": label, "mode": mode,
                "start": {"lat": start[0], "lon": start[1], "address": start_addr},
                "end": {"lat": end[0], "lon": end[1], "address": end_addr},
                "count": len(seq), "deliveries": sum(len(v) for v in seq), "stops": rows,
                "travel_min": round(travel / 60), "total_min": round((travel + sum(svc)) / 60),
                "last_leg_min": round(legs[-1] / 60, 1) if legs else 0,
                "km": round(sum(meters) / 1000, 1),
                "zones": [{"name": n, "count": c} for n, c in zc],
                "main_zone_share": round(zc[0][1] / len(seq), 2) if seq else 0,
                # sem origem no 1º link: o Maps parte da localização atual de quem abre o link
                "links": build_links([(v[0].lat, v[0].lon) for v in seq], end,
                                     per_link=SETTINGS.maps_waypoints_per_link,
                                     mode="walking" if mode == "pe" else "driving"),
            }

        built: dict[int, dict] = {}
        for j, i in enumerate(free_drivers):
            d = req.drivers[i]
            idxs = [int(rest_idx[x]) for x in res.routes[j]]
            built[i] = make_driver(
                i, d.label or f"Entregador {i + 1}", starts[i], d.start.address or "", idxs,
                res.leg_seconds[j], res.leg_meters[j], depot, req.depot.address or "", "moto")
            built[i]["group"] = ""
        for z, idx, zsol, zstart in zone_runs:
            for j, g in enumerate(z.drivers):
                d = req.drivers[g]
                idxs = [int(idx[x]) for x in zsol.routes[j]]
                label = d.label or f"Entregador {g + 1}"
                if z.profile == "pe":
                    built[g] = make_driver(g, label, zstart, "", idxs, zsol.leg_seconds[j], zsol.leg_meters[j],
                                           zstart, "", "pe")
                else:
                    built[g] = make_driver(g, label, starts[g], d.start.address or "", idxs, zsol.leg_seconds[j],
                                           zsol.leg_meters[j], depot, req.depot.address or "", "moto")
                built[g]["group"] = z.name
        drivers_out = [built[i] for i in range(len(req.drivers))]
        walker = None
        if wres is not None:
            idxs = [int(walk_idx[j]) for j in wres.routes[0]]
            walker = make_driver(len(req.drivers), pedestrian.LABEL, walk_start, walk_addr, idxs,
                                 wres.leg_seconds[0], wres.leg_meters[0], walk_start, walk_addr, "pe")
            walker["group"] = ""

        # Trajeto por ruas para o mapa (OSRM ou malha offline; na estimativa, linhas retas entre as paradas).
        def route_pts(d):
            return ([(d["start"]["lat"], d["start"]["lon"]), *((s["lat"], s["lon"]) for s in d["stops"]),
                     (d["end"]["lat"], d["end"]["lon"])] if d["stops"] else [])

        all_out = drivers_out + ([walker] if walker else [])
        for d in all_out:
            d["path"] = None
        moto_out = [d for d in all_out if d["mode"] == "moto"]
        if method["v"] in ("osrm", "ruas") and any(d["stops"] for d in moto_out):
            job.message = "Traçando o trajeto por ruas"
            pts = [route_pts(d) for d in moto_out]
            try:
                paths = osrm_paths(pts) if method["v"] == "osrm" else mapdata.router().paths(pts)
            except Exception:
                paths = [None] * len(pts)
            for d, p in zip(moto_out, paths):
                d["path"] = p
        foot_out = [d for d in all_out if d["mode"] == "pe" and d["stops"]]
        if foot_out and method["w"] == "osrm":
            try:
                for d, p in zip(foot_out, osrm_paths([route_pts(d) for d in foot_out],
                                                     base_url=SETTINGS.osrm_foot_url, profile="walking")):
                    d["path"] = p
            except Exception:
                pass

        shares = [(d["main_zone_share"], d["count"]) for d in drivers_out if d["count"] and not d["group"]]
        pedestrian_out = {"enabled": bool(ped_on), "active": walker is not None,
                          "polygon": pedestrian.polygon().tolist() if ped_on else [],
                          "matrix": method["w"], "warning": ""}
        if walker and walker["total_min"] > SETTINGS.pedestrian_max_hours * 60:
            pedestrian_out["warning"] = (
                f"A rota a pé tem {walker['deliveries']} entregas e leva cerca de {round(walker['total_min'] / 60, 1)} h, "
                f"acima de {SETTINGS.pedestrian_max_hours:g} h. Considere dividir a zona do Centro com outro entregador.")
        free_min = [d["total_min"] for d in drivers_out if not d["group"] and d["stops"]]
        near = zonegroups.near_border(stop_xy, specs)
        zones_out = []
        for zi, z in enumerate(specs):
            members = [drivers_out[g] for g in z.drivers]
            longest = max((m["total_min"] for m in members), default=0)
            warn = ""
            if z.profile == "pe" and longest > SETTINGS.pedestrian_max_hours * 60:
                warn = (f"A rota mais longa a pé leva cerca de {round(longest / 60, 1)} h, acima de "
                        f"{SETTINGS.pedestrian_max_hours:g} h. Coloque mais entregadores nesta zona.")
            elif z.profile == "moto" and free_min and longest > 1.3 * (sum(free_min) / len(free_min)):
                warn = (f"As rotas desta zona levam até {round(longest / 60, 1)} h, bem mais que as "
                        f"{round(sum(free_min) / len(free_min) / 60, 1)} h médias dos entregadores livres. "
                        "Considere mais entregadores nela.")
            zones_out.append({
                "name": z.name, "profile": z.profile, "polygon": z.polygon.tolist(), "drivers": z.drivers,
                "visits": int((labels == zi).sum()), "deliveries": sum(m["deliveries"] for m in members),
                "near_border": near[zi], "warning": warn,
            })
        job.result = {
            "depot": {"lat": depot[0], "lon": depot[1], "address": req.depot.address or ""},
            "balance": req.balance, "balance_by": req.balance_by, "km_tolerance": req.km_tolerance, "zone_weight": zw, "matrix": method["v"], "service_seconds": service,
            "total_min": round(total_seconds / 60), "status": res.status,
            "deliveries": len(ok), "visits": len(visits), "extra_delivery_seconds": extra, "tolerance_seconds": tol, "traffic": req.traffic,
            "zone_purity": round(sum(a * b for a, b in shares) / max(sum(b for _, b in shares), 1), 2),
            "drivers": all_out, "pedestrian": pedestrian_out, "zones": zones_out, "zone_warnings": zone_warnings,
            "has_pages": bool(job.sources),
            "unrouted": [s.public() for s in job.stops if s.status == "revisar"],
        }

        def move(stop_id: int, to: int, preview: bool) -> dict:
            """Passa uma parada (e as entregas do mesmo ponto) de uma rota de moto para outra e reordena só essas duas.
            Com preview=True só devolve antes e depois; a mesma conta é reaproveitada se logo em seguida vier a aplicação."""
            res_ = job.result
            by_idx = {d["index"]: d for d in res_["drivers"]}
            vi = next((j for j, v in enumerate(visits) if any(x.id == stop_id for x in v)), None)
            if vi is None:
                raise HTTPException(404, "Entrega não encontrada nas rotas.")
            src = next((i for i, ix in route_of.items() if vi in ix), None)
            if src is None:
                raise HTTPException(404, "Esta entrega não está em nenhuma rota.")
            if to not in by_idx:
                raise HTTPException(404, "Entregador não encontrado.")
            if to == src:
                raise HTTPException(400, "A parada já está na rota deste entregador.")
            if by_idx[src]["mode"] != "moto" or by_idx[to]["mode"] != "moto":
                raise HTTPException(400, "Só dá para mover paradas entre rotas de moto (a rota a pé tem outro cálculo).")
            key = (stop_id, to)
            pend = job.pending_move
            if pend and pend["key"] == key:
                nsrc, nto, new_routes = pend["src"], pend["to"], pend["routes"]
            else:
                saved = {src: list(route_of[src]), to: list(route_of[to])}

                def rebuild(i, idxs):
                    d = by_idx[i]
                    start = (d["start"]["lat"], d["start"]["lon"])
                    order, legs, meters = [], [], []
                    if idxs:
                        ix = np.array(idxs)
                        sol = solve(stop_xy[ix].reshape(-1, 2), np.array([start]), np.array(depot), matrix_fn,
                                    service_seconds=service, balance=0.0, time_limit=2,
                                    stop_service=visit_service[ix], stop_deliveries=np.array([len(visits[j]) for j in idxs]))
                        order, legs, meters = [idxs[x] for x in sol.routes[0]], sol.leg_seconds[0], sol.leg_meters[0]
                    nd = make_driver(i, d["label"], start, d["start"]["address"], order, legs, meters, depot,
                                     req.depot.address or "", "moto")
                    nd["group"], nd["path"] = d["group"], None
                    if method["v"] in ("osrm", "ruas") and nd["stops"]:
                        try:
                            nd["path"] = (osrm_paths([route_pts(nd)]) if method["v"] == "osrm" else mapdata.router().paths([route_pts(nd)]))[0]
                        except Exception:
                            nd["path"] = None
                    return nd, order

                try:
                    nsrc, o_src = rebuild(src, [j for j in saved[src] if j != vi])
                    nto, o_to = rebuild(to, saved[to] + [vi])
                finally:
                    route_of[src], route_of[to] = saved[src], saved[to]    # a prévia não muda nada
                new_routes = {src: o_src, to: o_to}
                job.pending_move = {"key": key, "src": nsrc, "to": nto, "routes": new_routes}

            def brief(d):
                return {"deliveries": d["deliveries"], "count": d["count"], "total_min": d["total_min"], "km": d["km"]}

            out = {
                "preview": preview, "stop": stop_id, "from": src, "to": to,
                "from_label": by_idx[src]["label"], "to_label": by_idx[to]["label"],
                "deliveries": len(visits[vi]), "address": visits[vi][0].address,
                "before": {"from": brief(by_idx[src]), "to": brief(by_idx[to])},
                "after": {"from": brief(nsrc), "to": brief(nto)},
            }
            if preview:
                return out
            route_of.update(new_routes)
            old_total = by_idx[src]["total_min"] + by_idx[to]["total_min"]
            res_["drivers"] = [nsrc if d["index"] == src else nto if d["index"] == to else d for d in res_["drivers"]]
            res_["total_min"] += nsrc["total_min"] + nto["total_min"] - old_total
            by2 = {d["index"]: d for d in res_["drivers"]}
            for z in res_["zones"]:
                z["deliveries"] = sum(by2[g]["deliveries"] for g in z["drivers"])
            sh = [(d["main_zone_share"], d["count"]) for d in res_["drivers"] if d["index"] < len(req.drivers) and d["count"] and not d["group"]]
            res_["zone_purity"] = round(sum(a * b for a, b in sh) / max(sum(b for _, b in sh), 1), 2)
            res_["manual_moves"] = res_.get("manual_moves", 0) + 1
            job.pending_move = None
            return out

        job.mover, job.pending_move = move, None
        job.state, job.message = "pronto", ""
    except Exception as exc:
        job.state, job.error = "erro", str(exc)


@app.post("/api/jobs/{job_id}/move")
def move_stop(job_id: str, body: MoveIn):
    """Mover uma parada de um entregador de moto para outro, antes de enviar as rotas (preview=True mostra o antes e depois)."""
    job = _job(job_id)
    if job.state != "pronto" or job.result is None or job.mover is None:
        raise HTTPException(409, "Calcule as rotas antes de mover paradas.")
    with job.lock:
        return job.mover(body.stop, body.to, body.preview)


@app.post("/api/jobs/{job_id}/solve")
def start_solve(job_id: str, req: SolveIn):
    job = _job(job_id)
    if job.state in ("lendo", "mapear", "geocodificando", "calculando"):
        raise HTTPException(409, "Este processamento ainda está em andamento.")
    try:
        _zone_specs(req)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    job.state, job.error, job.result = "calculando", "", None
    job.mover = job.pending_move = None
    threading.Thread(target=_run_solve, args=(job, req), daemon=True).start()
    return _summary(job)


@app.get("/api/jobs/{job_id}/result")
def result(job_id: str):
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, "Resultado ainda não disponível.")
    return job.result


@app.get("/api/jobs/{job_id}/paginas.pdf")
def pages_pdf(job_id: str, driver: int | None = None, stop: int | None = None):
    """Páginas das intimações de um entregador (ou de todos, um após o outro), na ordem da rota; com
    `stop`, só as de uma entrega (para conferir o original na revisão). Abre no navegador, que já
    oferece imprimir e salvar."""
    from pypdf import PdfReader, PdfWriter

    job = _job(job_id)
    if not job.sources:
        raise HTTPException(404, "Esta lista não veio de um PDF de intimações.")
    if stop is not None:
        if not 0 <= stop < len(job.stops):
            raise HTTPException(404, "Entrega não encontrada.")
        ids = [stop]
    else:
        if job.result is None:
            raise HTTPException(409, "Resultado ainda não disponível.")
        drivers = [d for d in job.result["drivers"] if driver is None or d["index"] == driver]
        if not drivers:
            raise HTTPException(404, "Entregador não encontrado.")
        ids = [x["id"] for d in drivers for r in d["stops"] for x in r["deliveries"]]
    readers: dict[int, PdfReader] = {}     # um por PDF de origem (a lista pode vir de vários)
    writer = PdfWriter()
    for i in ids:
        s = job.stops[i]
        if s.src not in job.sources:
            continue
        if s.src not in readers:
            readers[s.src] = PdfReader(io.BytesIO(job.sources[s.src]))
        for p in s.pages:
            writer.add_page(readers[s.src].pages[p])
    if not writer.pages:
        raise HTTPException(404, "Nenhuma página para este entregador.")
    buf = io.BytesIO()
    writer.write(buf)
    name = (f"intimacao-pagina-{job.stops[stop].pages[0] + 1}" if stop is not None
            else "intimacoes" if driver is None else f"intimacoes-rota-{driver + 1}")
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@app.get("/api/jobs/{job_id}/export.csv")
def export_csv(job_id: str, driver: int | None = None):
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, "Resultado ainda não disponível.")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["entregador", "ordem", "nome", "endereco", "codigo_rastreio", "zona", "latitude", "longitude",
                "chegada_estimada_min", "distancia_trecho_km"])
    for d in job.result["drivers"]:
        if driver is not None and d["index"] != driver:
            continue
        for r in d["stops"]:
            for x in r["deliveries"]:  # uma linha por entrega; a ordem se repete nas entregas da mesma parada
                w.writerow([d["label"], r["order"], x["name"], x["address"], x["code"], r["zone"],
                            r["lat"], r["lon"], r["eta_min"], r["leg_km"]])
    return Response(
        ("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rotas.csv"'},
    )
