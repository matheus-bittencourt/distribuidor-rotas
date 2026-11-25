"""Zonas desenhadas no mapa: cada zona vira um GRUPO de entregadores que atende só as entregas dela.

Precedência (a regra do entregador a pé vem primeiro):
  1. zona a pé do Centro (pedestrian_zone.json): vai sempre para o entregador a pé;
  2. zonas desenhadas, na ordem da lista: a primeira que contém a parada fica com ela;
  3. o resto vai para os entregadores livres (os que não estão em nenhuma zona).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .pedestrian import edge_distance_m, inside_polygon

BUILTIN, FREE = -2, -1     # rótulos de parada: zona a pé do Centro, sem zona desenhada


@dataclass
class ZoneSpec:
    name: str
    polygon: np.ndarray                      # (n, 2) lat, lon
    profile: str = "moto"                    # moto | pe
    drivers: list[int] = field(default_factory=list)   # posições na lista de entregadores
    start: tuple[float, float] | None = None  # perfil "pe": ponto onde o grupo sai e volta
    edge_m: float = 0.0                      # faixa em volta do contorno que também conta como da zona


def assign(stop_xy: np.ndarray, in_builtin: np.ndarray, zones: list[ZoneSpec]) -> tuple[np.ndarray, list[str]]:
    """Zona de cada parada: BUILTIN, FREE ou o índice da zona desenhada. Devolve também os avisos de conflito."""
    n = len(stop_xy)
    labels = np.full(n, FREE, dtype=int)
    labels[in_builtin] = BUILTIN
    warnings: list[str] = []
    taken = in_builtin.copy()
    for zi, z in enumerate(zones):
        m = inside_polygon(stop_xy, z.polygon, z.edge_m) if n else np.zeros(0, dtype=bool)
        under_builtin = int((m & in_builtin).sum())
        overlap = int((m & ~in_builtin & taken).sum())
        if under_builtin:
            warnings.append(f"Zona \"{z.name}\": {under_builtin} parada(s) estão na zona a pé do Centro e ficam com o "
                            "entregador a pé (a regra do pedestre vem primeiro).")
        if overlap:
            warnings.append(f"Zona \"{z.name}\": {overlap} parada(s) também estão em outra zona acima dela na lista "
                            "e ficam com a primeira.")
        mine = m & ~taken
        labels[mine] = zi
        taken |= mine
    return labels, warnings


def near_border(stop_xy: np.ndarray, zones: list[ZoneSpec], meters: float = 80.0) -> list[int]:
    """Quantas paradas ficam a até `meters` do contorno de cada zona, dentro ou fora: vale conferir, porque o
    endereço (rua) pode estar do outro lado da linha."""
    if not len(stop_xy):
        return [0] * len(zones)
    return [int((edge_distance_m(stop_xy, z.polygon) <= meters).sum()) for z in zones]
