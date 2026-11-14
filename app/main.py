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

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import jobs, templates, zones
from .config import FALLBACK_DEPOT, RMPA_CITIES, SETTINGS
from .extract import COLUMN_LABELS, NeedMapping, extract, llm_provider, to_query
from .geocode import geocode_stops, in_metro, in_region, make_geocoder
from .links import build_links
from .matrix import build_matrix
from .sanitize import is_sensitive_header, strip_accents
from .solver import solve

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 25 * 1024 * 1024

app = FastAPI(title="Distribuidor de rotas (POC)")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ------------------------------------------------------------------ esquemas

class PointIn(BaseModel):
    address: str | None = None
    lat: float | None = None
    lon: float | None = None


class DriverIn(BaseModel):
    label: str = ""
    start: PointIn = PointIn()   # vazio = sai do ponto padrão


class SolveIn(BaseModel):
    depot: PointIn
    drivers: list[DriverIn] = Field(min_length=1, max_length=40)
    balance: float = Field(0.7, ge=0, le=1)
    zone_weight: float | None = Field(None, ge=0, le=1)
    time_limit: int | None = Field(None, ge=5, le=300)
    service_seconds: int | None = Field(None, ge=0, le=1800)


class StopPatch(BaseModel):
    name: str | None = None
    address: str | None = None
    coords: str | None = None   # "lat, lon" colado do Google Maps
    discard: bool | None = None


class MappingIn(BaseModel):
    columns: dict[str, int | None]
    header_row: bool = True
    remember: bool = False


# ------------------------------------------------------------------ páginas

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config():
    prov = llm_provider()
    return {
        "default_depot": SETTINGS.default_depot,
        "geocoder": SETTINGS.geocoder,
        "matrix": SETTINGS.matrix,
        "llm": {"ollama": "IA local (Ollama)", "anthropic": "API Anthropic"}.get(prov, "nenhuma (heurística)"),
        "service_seconds": SETTINGS.service_seconds,
        "solver_seconds": SETTINGS.solver_seconds,
        "zone_weight": SETTINGS.zone_weight,
        "maps_waypoints_per_link": SETTINGS.maps_waypoints_per_link,
        "job_ttl_minutes": SETTINGS.job_ttl_minutes,
        "saved_formats": len(templates.all_templates()),
        "column_labels": COLUMN_LABELS,
    }


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
        job.pending = job.mapping_info = None  # arquivo original sai da memória
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
    if body.discard:
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

        zone_names, zone_centers = zones.load()
        stop_xy = np.array([[s.lat, s.lon] for s in ok])
        zone_idx = zones.assign(stop_xy)
        for s, z in zip(ok, zone_idx):
            s.zone = zone_names[z]

        method = {"v": ""}

        def matrix_fn(coords):
            m, method["v"] = build_matrix(coords)
            return m

        service = SETTINGS.service_seconds if req.service_seconds is None else req.service_seconds
        zw = SETTINGS.zone_weight if req.zone_weight is None else req.zone_weight
        res = solve(
            stop_xy, np.array(starts), np.array(depot), matrix_fn,
            service_seconds=service, balance=req.balance,
            time_limit=req.time_limit or SETTINGS.solver_seconds,
            zone_idx=zone_idx, zone_centers=zone_centers, zone_weight=zw,
        )

        drivers_out = []
        for i, d in enumerate(req.drivers):
            seq = [ok[j] for j in res.routes[i]]
            legs = res.leg_seconds[i]
            t, rows = 0, []
            for order, (s, leg) in enumerate(zip(seq, legs), start=1):
                t += leg
                rows.append({
                    "order": order, "id": s.id, "name": s.name, "address": s.address, "code": s.code,
                    "zone": s.zone, "lat": s.lat, "lon": s.lon, "leg_min": round(leg / 60, 1),
                    "eta_min": round(t / 60), "precision": s.precision,
                })
                t += service
            travel = sum(legs)
            zc = Counter(s.zone for s in seq).most_common()
            drivers_out.append({
                "index": i, "label": d.label or f"Entregador {i + 1}",
                "start": {"lat": starts[i][0], "lon": starts[i][1], "address": d.start.address or ""},
                "count": len(seq), "stops": rows,
                "travel_min": round(travel / 60), "total_min": round((travel + service * len(seq)) / 60),
                "last_leg_min": round(legs[-1] / 60, 1) if legs else 0,
                "zones": [{"name": n, "count": c} for n, c in zc],
                "main_zone_share": round(zc[0][1] / len(seq), 2) if seq else 0,
                # sem origem no 1º link: o Maps parte da localização atual de quem abre o link
                "links": build_links([(s.lat, s.lon) for s in seq], depot,
                                     per_link=SETTINGS.maps_waypoints_per_link),
            })
        shares = [(d["main_zone_share"], d["count"]) for d in drivers_out if d["count"]]
        job.result = {
            "depot": {"lat": depot[0], "lon": depot[1], "address": req.depot.address or ""},
            "balance": req.balance, "zone_weight": zw, "matrix": method["v"], "service_seconds": service,
            "total_min": round(res.total_seconds / 60), "status": res.status,
            "zone_purity": round(sum(a * b for a, b in shares) / max(sum(b for _, b in shares), 1), 2),
            "drivers": drivers_out,
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


@app.get("/api/jobs/{job_id}/export.csv")
def export_csv(job_id: str, driver: int | None = None):
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, "Resultado ainda não disponível.")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["entregador", "ordem", "nome", "endereco", "codigo_rastreio", "zona", "latitude", "longitude",
                "chegada_estimada_min"])
    for d in job.result["drivers"]:
        if driver is not None and d["index"] != driver:
            continue
        for r in d["stops"]:
            w.writerow([d["label"], r["order"], r["name"], r["address"], r["code"], r["zone"],
                        r["lat"], r["lon"], r["eta_min"]])
    return Response(
        ("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rotas.csv"'},
    )
