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

from . import jobs, pedestrian, templates, zones
from .config import FALLBACK_DEPOT, RMPA_CITIES, SETTINGS
from .extract import COLUMN_LABELS, NeedMapping, extract, llm_provider, to_query
from .geocode import geocode_stops, in_metro, in_region, make_geocoder
from .links import build_links
from starlette.formparsers import MultiPartParser

from . import mapdata, netguard, updater
from .matrix import build_matrix, build_walk_matrix, osrm_paths
from .sanitize import is_sensitive_header, strip_accents
from .solver import solve

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 25 * 1024 * 1024

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
    pedestrian: PedestrianIn = PedestrianIn()


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

def _ingest(job: jobs.Job, filename: str, data: bytes, mapping: dict | None = None) -> None:
    try:
        job.state, job.message = "lendo", "Lendo o arquivo"

        def prog(msg: str):
            job.message = msg

        try:
            stops, report = extract(filename, data, prog, mapping=mapping)
        except NeedMapping as nm:
            job.pending = (filename, data)
            job.mapping_info = {
                "headers": [{"index": i, "name": h, "sensitive": bool(h and is_sensitive_header(h))}
                            for i, h in enumerate(nm.headers)],
                "sample": nm.sample, "total_rows": nm.total_rows,
                "fields": [{"key": k, "label": v} for k, v in COLUMN_LABELS.items()],
            }
            job.state, job.message = "mapear", ""
            return
        job.pending = job.mapping_info = None  # arquivo original sai da memória...
        if any(s.pages for s in stops):        # ...exceto o PDF de intimações, para o PDF de cada entregador
            job.source_pdf = data
        del data
        job.stops, job.report = stops, report
        job.state, job.message = "geocodificando", "Localizando endereços no mapa"
        geocode_stops(stops, lambda a, b: setattr(job, "progress", (a, b)))
        job.state, job.message = "revisao", ""
    except Exception as exc:
        job.state, job.error = "erro", str(exc)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Arquivo grande demais (limite de 25 MB).")
    job = jobs.create()
    threading.Thread(target=_ingest, args=(job, file.filename or "", data), daemon=True).start()
    return {"job_id": job.id}


@app.post("/api/jobs/{job_id}/mapping")
def set_mapping(job_id: str, body: MappingIn):
    job = _job(job_id)
    if job.state != "mapear" or not job.pending:
        raise HTTPException(409, "Este processamento não está esperando o mapeamento de colunas.")
    if body.columns.get("addr") is None:
        raise HTTPException(400, "Indique qual coluna é o endereço.")
    filename, data = job.pending
    job.state = "lendo"
    threading.Thread(target=_ingest, args=(job, filename, data, body.model_dump()), daemon=True).start()
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
        "mapping": job.mapping_info,
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

        # Entregador a pé: toda entrega dentro da zona do Centro vai para ele; o resto, para as motos.
        ped_on = SETTINGS.pedestrian and req.pedestrian.enabled
        in_zone = pedestrian.inside(stop_xy) if ped_on else np.zeros(len(visits), dtype=bool)
        walk_idx, rest_idx = np.flatnonzero(in_zone), np.flatnonzero(~in_zone)
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

        res = solve(
            stop_xy[rest_idx].reshape(-1, 2), np.array(starts), np.array(depot), matrix_fn,
            service_seconds=service, balance=req.balance, time_limit=time_limit,
            zone_idx=zone_idx[rest_idx], zone_centers=zone_centers, zone_weight=zw, balance_by=req.balance_by,
            stop_service=visit_service[rest_idx], stop_deliveries=np.array([len(visits[j]) for j in rest_idx]),
            km_tolerance=req.km_tolerance,
        )
        wres = None
        if walk_idx.size:   # uma só rota, de pedestre, que sai e volta ao ponto dele; sem equilibrar com as motos
            wres = solve(
                stop_xy[walk_idx], np.array([walk_start]), np.array(walk_start), walk_matrix_fn,
                service_seconds=service, balance=0.0, time_limit=min(time_limit, 15),
                stop_service=visit_service[walk_idx], stop_deliveries=np.array([len(visits[j]) for j in walk_idx]),
            )
        if not method["v"]:
            method["v"] = method["w"] or "estimativa"

        def make_driver(i, label, start, start_addr, idxs, legs, meters, end, end_addr, mode):
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

        drivers_out = []
        for i, d in enumerate(req.drivers):
            idxs = [int(rest_idx[j]) for j in res.routes[i]]
            drivers_out.append(make_driver(
                i, d.label or f"Entregador {i + 1}", starts[i], d.start.address or "", idxs,
                res.leg_seconds[i], res.leg_meters[i], depot, req.depot.address or "", "moto"))
        walker = None
        if wres is not None:
            idxs = [int(walk_idx[j]) for j in wres.routes[0]]
            walker = make_driver(len(req.drivers), pedestrian.LABEL, walk_start, walk_addr, idxs,
                                 wres.leg_seconds[0], wres.leg_meters[0], walk_start, walk_addr, "pe")

        # Trajeto por ruas para o mapa (OSRM ou malha offline; na estimativa, linhas retas entre as paradas).
        def route_pts(d):
            return ([(d["start"]["lat"], d["start"]["lon"]), *((s["lat"], s["lon"]) for s in d["stops"]),
                     (d["end"]["lat"], d["end"]["lon"])] if d["stops"] else [])

        for d in drivers_out + ([walker] if walker else []):
            d["path"] = None
        if method["v"] in ("osrm", "ruas") and rest_idx.size:
            job.message = "Traçando o trajeto por ruas"
            pts = [route_pts(d) for d in drivers_out]
            try:
                paths = osrm_paths(pts) if method["v"] == "osrm" else mapdata.router().paths(pts)
            except Exception:
                paths = [None] * len(pts)
            for d, p in zip(drivers_out, paths):
                d["path"] = p
        if walker and method["w"] == "osrm":
            walker["path"] = osrm_paths([route_pts(walker)], base_url=SETTINGS.osrm_foot_url, profile="walking")[0]

        shares = [(d["main_zone_share"], d["count"]) for d in drivers_out if d["count"]]
        pedestrian_out = {"enabled": bool(ped_on), "active": walker is not None,
                          "polygon": pedestrian.polygon().tolist() if ped_on else [],
                          "matrix": method["w"], "warning": ""}
        if walker and walker["total_min"] > SETTINGS.pedestrian_max_hours * 60:
            pedestrian_out["warning"] = (
                f"A rota a pé tem {walker['deliveries']} entregas e leva cerca de {round(walker['total_min'] / 60, 1)} h, "
                f"acima de {SETTINGS.pedestrian_max_hours:g} h. Considere dividir a zona do Centro com outro entregador.")
        job.result = {
            "depot": {"lat": depot[0], "lon": depot[1], "address": req.depot.address or ""},
            "balance": req.balance, "balance_by": req.balance_by, "km_tolerance": req.km_tolerance, "zone_weight": zw, "matrix": method["v"], "service_seconds": service,
            "total_min": round((res.total_seconds + (wres.total_seconds if wres else 0)) / 60), "status": res.status,
            "deliveries": len(ok), "visits": len(visits), "extra_delivery_seconds": extra, "tolerance_seconds": tol,
            "zone_purity": round(sum(a * b for a, b in shares) / max(sum(b for _, b in shares), 1), 2),
            "drivers": drivers_out + ([walker] if walker else []), "pedestrian": pedestrian_out,
            "has_pages": job.source_pdf is not None,
            "unrouted": [s.public() for s in job.stops if s.status == "revisar"],
        }
        job.state, job.message = "pronto", ""
    except Exception as exc:
        job.state, job.error = "erro", str(exc)


@app.post("/api/jobs/{job_id}/solve")
def start_solve(job_id: str, req: SolveIn):
    job = _job(job_id)
    if job.state in ("lendo", "mapear", "geocodificando", "calculando"):
        raise HTTPException(409, "Este processamento ainda está em andamento.")
    job.state, job.error, job.result = "calculando", "", None
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
    if job.source_pdf is None:
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
    reader = PdfReader(io.BytesIO(job.source_pdf))
    writer = PdfWriter()
    for i in ids:
        for p in job.stops[i].pages:
            writer.add_page(reader.pages[p])
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
