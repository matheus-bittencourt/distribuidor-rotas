"""Zona do Centro atendida por UM entregador a pé.

Todas as entregas dentro do polígono (app/pedestrian_zone.json) vão para esse entregador, que sai e volta
ao mesmo ponto dentro da zona; a rota dele é calculada para pedestre (OSRM com perfil de pé, ou estimativa
por linha reta). As demais entregas seguem para os entregadores de moto, como antes.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

ZONE_FILE = Path(__file__).with_name("pedestrian_zone.json")
LABEL = "A pé (Centro)"


@lru_cache(maxsize=1)
def zone() -> dict:
    return json.loads(ZONE_FILE.read_text(encoding="utf-8"))


def polygon() -> np.ndarray:
    return np.array(zone()["polygon"], dtype=float)


def default_start() -> tuple[float, float, str]:
    s = zone()["start"]
    return s["lat"], s["lon"], s.get("address", "")


def inside(latlon: np.ndarray) -> np.ndarray:
    """Quais pontos (lat, lon) estão dentro do polígono (traçado de raio; ponto na borda conta como dentro)."""
    pts = np.asarray(latlon, dtype=float).reshape(-1, 2)
    poly = polygon()
    lat, lon = pts[:, 0], pts[:, 1]
    res = np.zeros(len(pts), dtype=bool)
    on_edge = np.zeros(len(pts), dtype=bool)
    n = len(poly)
    for i in range(n):
        (y1, x1), (y2, x2) = poly[i], poly[(i + 1) % n]
        crosses = (y1 > lat) != (y2 > lat)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
        res ^= crosses & (lon < x_at)
        # ~1 m de tolerância: entrega na própria rua que limita a zona fica dentro
        dx, dy = x2 - x1, y2 - y1
        seg2 = dx * dx + dy * dy
        t = np.clip(((lon - x1) * dx + (lat - y1) * dy) / seg2, 0, 1) if seg2 else np.zeros(len(pts))
        d2 = (lon - (x1 + t * dx)) ** 2 + (lat - (y1 + t * dy)) ** 2
        on_edge |= d2 < (1e-5) ** 2
    return res | on_edge
