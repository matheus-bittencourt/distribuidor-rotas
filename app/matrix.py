"""Matriz de tempos de deslocamento (segundos) entre pontos."""
from __future__ import annotations

import httpx
import numpy as np

from .config import SETTINGS


def haversine_km(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a: (n,2) lat/lon em graus, b: (m,2). Devolve (n,m) em km."""
    la1, lo1 = np.radians(a[:, 0])[:, None], np.radians(a[:, 1])[:, None]
    la2, lo2 = np.radians(b[:, 0])[None, :], np.radians(b[:, 1])[None, :]
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(h))


def estimated_matrix(coords: np.ndarray) -> np.ndarray:
    """Estimativa sem rede: linha reta x fator de desvio / velocidade média."""
    km = haversine_km(coords, coords) * SETTINGS.detour_factor
    return np.rint(km / SETTINGS.avg_speed_kmh * 3600).astype(np.int64)


def estimated_dist_m(coords: np.ndarray) -> np.ndarray:
    """Distância estimada em metros: linha reta x fator de desvio."""
    return np.rint(haversine_km(coords, coords) * SETTINGS.detour_factor * 1000).astype(np.int64)


def osrm_matrix(coords: np.ndarray, base_url: str | None = None, block: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Tempos (s) e distâncias (m) reais por ruas via OSRM (/table), em blocos para respeitar --max-table-size."""
    base_url = (base_url or SETTINGS.osrm_url).rstrip("/")
    block = block or SETTINGS.osrm_block
    n = len(coords)
    dur, dist = estimated_matrix(coords).copy(), estimated_dist_m(coords).copy()
    with httpx.Client(timeout=60) as client:
        for i0 in range(0, n, block):
            src = list(range(i0, min(i0 + block, n)))
            for j0 in range(0, n, block):
                dst = list(range(j0, min(j0 + block, n)))
                idx = src + [j for j in dst if j not in src]
                pos = {k: p for p, k in enumerate(idx)}
                path = ";".join(f"{coords[k][1]:.6f},{coords[k][0]:.6f}" for k in idx)
                params = {
                    "sources": ";".join(str(pos[k]) for k in src),
                    "destinations": ";".join(str(pos[k]) for k in dst),
                    "annotations": "duration,distance",
                }
                r = client.get(f"{base_url}/table/v1/driving/{path}", params=params)
                r.raise_for_status()
                body = r.json()
                for a, row_t, row_d in zip(src, body["durations"], body["distances"]):
                    for b, t, d in zip(dst, row_t, row_d):
                        if t is not None:  # sem rota: mantém a estimativa
                            dur[a, b] = int(round(t))
                        if d is not None:
                            dist[a, b] = int(round(d))
    return dur, dist


def build_matrix(coords: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
    """(tempos em s, distâncias em m, origem dos números)."""
    if SETTINGS.matrix == "osrm":
        try:
            t, d = osrm_matrix(coords)
            return t, d, "osrm"
        except Exception:
            return estimated_matrix(coords), estimated_dist_m(coords), "estimativa (OSRM indisponível)"
    return estimated_matrix(coords), estimated_dist_m(coords), "estimativa"
