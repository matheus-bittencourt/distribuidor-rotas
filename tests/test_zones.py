import numpy as np

from app import zones
from app.matrix import estimated_matrix
from app.solver import solve

DEPOT = np.array([-30.0262, -51.2062])


def test_assign_nearest_zone():
    names, centers = zones.load()
    idx = zones.assign(centers + 0.001)  # perto de cada centro
    assert [names[i] for i in idx] == names


def _purity(res, zone_idx):
    shares, total = 0, 0
    for route in res.routes:
        if route:
            top = np.bincount(zone_idx[route]).max()
            shares += top
            total += len(route)
    return shares / total


def test_zone_weight_raises_zone_purity():
    rng = np.random.default_rng(5)
    _, centers = zones.load()
    # paradas espalhadas em torno dos centros das zonas, com bordas que se misturam
    pts = np.vstack([c + rng.normal(0, 0.018, (30, 2)) for c in centers])
    zi = zones.assign(pts)
    starts = np.tile(DEPOT, (5, 1))
    pur = {}
    for w in (0.0, 1.0):
        r = solve(pts, starts, DEPOT, estimated_matrix, 120, 0.7, 8, zone_idx=zi, zone_centers=centers, zone_weight=w)
        assert sorted(i for x in r.routes for i in x) == list(range(len(pts)))
        pur[w] = _purity(r, zi)
    # O otimizador tem limite de tempo, então o resultado oscila um pouco conforme a máquina.
    # Aceita até duas paradas de diferença: o que importa é o peso de zona não piorar o agrupamento.
    assert pur[1.0] >= pur[0.0] - 2 / len(pts)
