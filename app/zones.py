"""Zonas da cidade: cada parada pertence à zona de centro mais próximo (diagrama de Voronoi)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

_PATH = Path(__file__).parent / "zones.json"


def load() -> tuple[list[str], np.ndarray]:
    zones = json.loads(_PATH.read_text(encoding="utf-8"))["zones"]
    return [z["name"] for z in zones], np.array([[z["lat"], z["lon"]] for z in zones])


def _km(latlon: np.ndarray, lat0: float) -> np.ndarray:
    return np.column_stack([latlon[:, 1] * math.cos(math.radians(lat0)) * 111.32, latlon[:, 0] * 110.57])


def assign(latlon: np.ndarray) -> np.ndarray:
    """Índice da zona de cada ponto (n,)."""
    _, centers = load()
    lat0 = float(latlon[:, 0].mean())
    d2 = ((_km(latlon, lat0)[:, None, :] - _km(centers, lat0)[None, :, :]) ** 2).sum(2)
    return d2.argmin(1)
