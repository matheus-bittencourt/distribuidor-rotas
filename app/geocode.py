"""Endereço -> coordenadas. Provedores: nominatim (OSM), google, fake (demo/testes offline).

Entregas só em Porto Alegre: o resultado precisa estar dentro da caixa do município E (quando o
provedor informa) ter Porto Alegre como cidade. Pontos de partida (casas) usam a caixa metropolitana.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

import httpx

from .config import POA_BBOX, RMPA_BBOX, SETTINGS
from .models import Stop
from .sanitize import strip_accents


@dataclass
class Geo:
    lat: float
    lon: float
    precision: str  # exato | aproximado
    city: str = ""


def _inside(lat: float, lon: float, box) -> bool:
    la0, la1, lo0, lo1 = box
    return la0 <= lat <= la1 and lo0 <= lon <= lo1


def in_region(lat: float, lon: float) -> bool:
    """Dentro da caixa de Porto Alegre (paradas de entrega)."""
    return _inside(lat, lon, POA_BBOX)


def in_metro(lat: float, lon: float) -> bool:
    return _inside(lat, lon, RMPA_BBOX)


def is_poa(city: str) -> bool:
    return not city or strip_accents(city).lower().strip() == "porto alegre"


def _variants(query: str) -> list[tuple[str, str]]:
    """Tentativas em ordem de precisão: completo, depois sem o número da casa."""
    out = [(query, "exato")]
    no_num = re.sub(r",?\s*\b\d+[a-zA-Z]?\b(?=\s*[,-]|\s*$)", "", query, count=1).strip(" ,")
    if no_num and no_num != query:
        out.append((no_num, "aproximado"))
    return out


class Nominatim:
    def __init__(self):
        self._lock = threading.Lock()
        self._last = 0.0
        self._client = httpx.Client(
            base_url=SETTINGS.nominatim_url,
            headers={"User-Agent": SETTINGS.nominatim_user_agent},
            timeout=20,
        )

    def _throttle(self) -> None:
        gap = 1.0 / max(SETTINGS.nominatim_rate, 0.01)
        with self._lock:
            wait = self._last + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _search(self, q: str, box) -> dict | None:
        la0, la1, lo0, lo1 = box
        self._throttle()
        r = self._client.get("/search", params={
            "q": q, "format": "jsonv2", "limit": 1, "countrycodes": "br", "addressdetails": 1,
            "viewbox": f"{lo0},{la1},{lo1},{la0}", "bounded": 1,
        })
        r.raise_for_status()
        data = r.json()
        return data[0] if data else None

    def geocode(self, query: str, wide: bool = False) -> Geo | None:
        for q, precision in _variants(query):
            hit = self._search(q, RMPA_BBOX if wide else POA_BBOX)
            if hit:
                a = hit.get("address", {})
                city = a.get("city") or a.get("town") or a.get("municipality") or a.get("village") or ""
                p = "exato" if (precision == "exato" and a.get("house_number")) else "aproximado"
                return Geo(float(hit["lat"]), float(hit["lon"]), p, city)
        return None


class Google:
    def __init__(self):
        if not SETTINGS.google_api_key:
            raise RuntimeError("GOOGLE_MAPS_API_KEY não definida")
        self._client = httpx.Client(timeout=20)

    def geocode(self, query: str, wide: bool = False) -> Geo | None:
        la0, la1, lo0, lo1 = RMPA_BBOX if wide else POA_BBOX
        r = self._client.get("https://maps.googleapis.com/maps/api/geocode/json", params={
            "address": query, "key": SETTINGS.google_api_key, "region": "br", "language": "pt-BR",
            "bounds": f"{la0},{lo0}|{la1},{lo1}",
        })
        r.raise_for_status()
        res = r.json().get("results") or []
        if not res:
            return None
        loc = res[0]["geometry"]["location"]
        kind = res[0]["geometry"].get("location_type", "")
        exact = kind in ("ROOFTOP", "RANGE_INTERPOLATED") and not res[0].get("partial_match")
        city = next((c["long_name"] for c in res[0].get("address_components", [])
                     if "administrative_area_level_2" in c["types"] or "locality" in c["types"]), "")
        return Geo(loc["lat"], loc["lng"], "exato" if exact else "aproximado", city)


class Fake:
    """Coordenadas determinísticas dentro de Porto Alegre. Só para demo/testes sem rede."""

    def geocode(self, query: str, wide: bool = False) -> Geo | None:
        if "inexistente" in query.lower():
            return None
        h = hashlib.sha256(query.lower().encode()).digest()
        lat = -30.15 + (int.from_bytes(h[:4], "big") / 2**32) * 0.17
        lon = -51.27 + (int.from_bytes(h[4:8], "big") / 2**32) * 0.17
        return Geo(lat, lon, "exato", "Porto Alegre")


class Cache:
    """Endereços já resolvidos num CSV local (`query;lat;lon;precisao`). Sem rede; ideal para demo e
    para reaproveitar endereços recorrentes. Consultas fora do arquivo ficam 'não encontradas'."""

    def __init__(self, path: str | None = None):
        import csv
        from pathlib import Path

        self._data: dict[str, Geo] = {}
        p = Path(path or SETTINGS.geocache)
        if not p.exists():
            raise RuntimeError(f"Arquivo de geocache não encontrado: {p}")
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter=";"):
                self._data[row["query"].strip().lower()] = Geo(
                    float(row["lat"]), float(row["lon"]), row.get("precisao") or "aproximado", "Porto Alegre")

    def geocode(self, query: str, wide: bool = False) -> Geo | None:
        return self._data.get(query.strip().lower())


def make_geocoder():
    name = SETTINGS.geocoder
    if name == "cache":
        return Cache()
    if name == "google":
        return Google()
    if name == "fake":
        return Fake()
    return Nominatim()


def geocode_stops(stops: list[Stop], progress: Callable[[int, int], None] = lambda a, b: None,
                  geocoder=None, retry: bool = False) -> None:
    """Preenche lat/lon/status das paradas 'pendente' (e 'revisar' se retry). Consultas iguais rodam uma vez."""
    geocoder = geocoder or make_geocoder()
    pending = [s for s in stops if s.status == "pendente" or (retry and s.status == "revisar")]
    unique: dict[str, Geo | None | Exception] = {}
    queries = list(dict.fromkeys(s.query for s in pending))
    done = 0

    def one(q: str):
        try:
            return q, geocoder.geocode(q)
        except Exception as exc:  # rede/limite
            return q, exc

    # Nominatim já é serializado pelo throttle; Google/Fake aproveitam o paralelismo.
    workers = 1 if SETTINGS.geocoder == "nominatim" and SETTINGS.nominatim_rate <= 2 else 8
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for q, res in pool.map(one, queries):
            unique[q] = res
            done += 1
            progress(done, len(queries))

    for s in pending:
        res = unique.get(s.query)
        s.lat = s.lon = None
        if isinstance(res, Exception):
            s.status, s.reason = "revisar", f"falha na consulta ({type(res).__name__}); tente de novo"
        elif res is None:
            s.status, s.reason = "revisar", "endereço não encontrado em Porto Alegre"
        elif not is_poa(res.city):
            s.status, s.reason = "revisar", f"fora de Porto Alegre ({res.city}): entregas só na capital"
        elif not in_region(res.lat, res.lon):
            s.status, s.reason = "revisar", "fora de Porto Alegre"
        else:
            s.status, s.reason = "ok", ""
            s.lat, s.lon, s.precision = res.lat, res.lon, res.precision
            if res.precision == "aproximado":
                s.reason = "posição aproximada (rua, sem o número)"
