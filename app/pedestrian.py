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

from .config import SETTINGS

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


def inside(latlon: np.ndarray, edge_m: float | None = None) -> np.ndarray:
    """Quais pontos (lat, lon) são da zona: dentro do polígono (traçado de raio) OU a até `edge_m` metros do
    contorno (padrão: PEDESTRIAN_EDGE_M). A faixa mantém as ruas de borda dentro da zona."""
    edge_m = SETTINGS.pedestrian_edge_m if edge_m is None else edge_m
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
        # distância (m) do ponto ao segmento, com a longitude encolhida pelo cosseno da latitude
        kx, ky = 111320.0 * np.cos(np.radians(lat)), 111320.0
        ax, ay = (x1 - lon) * kx, (y1 - lat) * ky
        dx, dy = (x2 - x1) * kx, (y2 - y1) * ky
        seg2 = dx * dx + dy * dy
        t = np.clip(-(ax * dx + ay * dy) / seg2, 0, 1) if np.all(seg2 > 0) else np.zeros(len(pts))
        on_edge |= np.hypot(ax + t * dx, ay + t * dy) <= max(edge_m, 1.0)
    return res | on_edge
