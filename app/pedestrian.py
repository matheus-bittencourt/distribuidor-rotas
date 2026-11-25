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
    """Quais pontos (lat, lon) são da zona a pé do Centro: dentro do polígono OU a até `edge_m` metros do
    contorno (padrão: PEDESTRIAN_EDGE_M). A faixa mantém as ruas de borda dentro da zona."""
    return inside_polygon(latlon, polygon(), SETTINGS.pedestrian_edge_m if edge_m is None else edge_m)


def inside_polygon(latlon: np.ndarray, poly: np.ndarray, edge_m: float = 0.0) -> np.ndarray:
    """Quais pontos (lat, lon) estão dentro de `poly` (traçado de raio) ou a até `edge_m` metros do contorno
    (no mínimo 1 m: entrega na própria rua que limita a zona fica dentro)."""
    pts = np.asarray(latlon, dtype=float).reshape(-1, 2)
    lat, lon = pts[:, 0], pts[:, 1]
    res = np.zeros(len(pts), dtype=bool)
    n = len(poly)
    for i in range(n):
        (y1, x1), (y2, x2) = poly[i], poly[(i + 1) % n]
        crosses = (y1 > lat) != (y2 > lat)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
        res ^= crosses & (lon < x_at)
    return res | (edge_distance_m(pts, poly) <= max(edge_m, 1.0))


def edge_distance_m(latlon: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Distância (m) de cada ponto ao contorno do polígono, dentro ou fora."""
    pts = np.asarray(latlon, dtype=float).reshape(-1, 2)
    lat, lon = pts[:, 0], pts[:, 1]
    best = np.full(len(pts), np.inf)
    kx, ky = 111320.0 * np.cos(np.radians(lat)), 111320.0   # longitude encolhida pelo cosseno da latitude
    n = len(poly)
    for i in range(n):
        (y1, x1), (y2, x2) = poly[i], poly[(i + 1) % n]
        ax, ay = (x1 - lon) * kx, (y1 - lat) * ky
        dx, dy = (x2 - x1) * kx, (y2 - y1) * ky
        seg2 = dx * dx + dy * dy
        t = np.clip(-(ax * dx + ay * dy) / np.where(seg2 > 0, seg2, 1), 0, 1)
        best = np.minimum(best, np.hypot(ax + t * dx, ay + t * dy))
    return best
