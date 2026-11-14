import numpy as np
import pytest

from app.matrix import estimated_dist_m, estimated_matrix
from app.solver import solve

DEPOT = np.array([-30.0262, -51.2062])


def _uneven_city():
    """Miolo denso perto da partida + uma região distante e esparsa: o caso em que a divisão por
    quantidade deixa um entregador rodando muito mais km que os outros."""
    rng = np.random.default_rng(11)
    near = DEPOT + rng.normal(0, 0.012, (240, 2))
    far = np.array([-30.19, -51.19]) + rng.normal(0, 0.020, (40, 2))
    return np.vstack([near, far])


def _run(mode, balance=0.9, k=5):
    pts = _uneven_city()
    r = solve(pts, np.tile(DEPOT, (k, 1)), DEPOT, lambda c: (estimated_matrix(c), estimated_dist_m(c)),
              120, balance, 8, balance_by=mode)
    assert sorted(i for x in r.routes for i in x) == list(range(len(pts)))  # toda parada atendida uma vez
    km = [sum(m) / 1000 for m in r.leg_meters]
    hours = [(sum(l) + 120 * len(s)) / 3600 for l, s in zip(r.leg_seconds, r.routes)]
    return r, km, hours


def test_km_mode_narrows_km_spread():
    _, km_stops, _ = _run("stops")
    _, km_km, _ = _run("km")
    assert max(km_km) - min(km_km) < max(km_stops) - min(km_stops)


def test_time_mode_narrows_time_spread():
    _, _, h_stops = _run("stops")
    _, _, h_time = _run("time")
    assert max(h_time) - min(h_time) < max(h_stops) - min(h_stops)


def test_legs_in_meters_match_matrix():
    r, _, _ = _run("km", k=3)
    assert all(len(m) == len(s) + 1 for m, s in zip(r.leg_meters, r.routes))


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        _run("peso")
