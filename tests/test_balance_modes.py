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


def test_stop_service_changes_route_time():
    pts = _uneven_city()[:60]
    starts = np.tile(DEPOT, (3, 1))
    svc = np.full(len(pts), 120)
    svc[:10] = 120 + 45 * 3          # dez pontos com 4 entregas cada
    a = solve(pts, starts, DEPOT, lambda c: (estimated_matrix(c), estimated_dist_m(c)), 120, 0.5, 4)
    b = solve(pts, starts, DEPOT, lambda c: (estimated_matrix(c), estimated_dist_m(c)), 120, 0.5, 4, stop_service=svc)
    assert b.total_seconds > a.total_seconds


def _loads(r, svc, dels):
    km = np.array([sum(m) / 1000 for m in r.leg_meters])
    dl = np.array([dels[x].sum() for x in r.routes])
    hr = np.array([(sum(l) + svc[x].sum()) / 3600 for l, x in zip(r.leg_seconds, r.routes)])
    return km, dl, hr


def _spread(a):
    return (a.max() - a.min()) / a.max()


def test_km_priority_balances_km_deliveries_and_time_together():
    """Cidade desigual (miolo denso + região distante) e paradas com 1 a 4 entregas: com km prioritário,
    os três (km, entregas, tempo) ficam equilibrados ao mesmo tempo, não só o km."""
    pts = _uneven_city()
    rng = np.random.default_rng(4)
    dels = rng.integers(1, 5, len(pts))
    svc = 120 + 45 * (dels - 1) + 60 * dels
    r = solve(pts, np.tile(DEPOT, (5, 1)), DEPOT, lambda c: (estimated_matrix(c), estimated_dist_m(c)),
              120, 1.0, 10, balance_by="km", stop_service=svc, stop_deliveries=dels)
    assert sorted(i for x in r.routes for i in x) == list(range(len(pts)))
    km, dl, hr = _loads(r, svc, dels)
    assert _spread(km) <= 0.30 and _spread(dl) <= 0.20 and _spread(hr) <= 0.20, (km, dl, hr)


def test_zone_weight_is_capped_at_15_percent():
    import app.solver as S
    assert S.MAX_ZONE_WEIGHT == 0.15
    pts = _uneven_city()[:60]
    zi = np.arange(len(pts)) % 3
    centers = np.array([[-30.0, -51.2], [-30.1, -51.2], [-30.05, -51.1]])
    r = solve(pts, np.tile(DEPOT, (3, 1)), DEPOT, estimated_matrix, 120, 0.5, 4,
              zone_idx=zi, zone_centers=centers, zone_weight=5.0)   # valor absurdo é limitado, não quebra
    assert sorted(i for x in r.routes for i in x) == list(range(len(pts)))


def test_km_tolerance_band_saves_km_and_keeps_deliveries_and_time_balanced():
    """Com tolerância de km, entregas e tempo seguem equilibrados e o total de km não sobe (costuma cair)."""
    pts = _uneven_city()
    dels = np.random.default_rng(4).integers(1, 5, len(pts))
    svc = 120 + 45 * (dels - 1) + 60 * dels
    run = lambda tol: solve(pts, np.tile(DEPOT, (5, 1)), DEPOT, lambda c: (estimated_matrix(c), estimated_dist_m(c)),
                            120, 1.0, 10, balance_by="km", stop_service=svc, stop_deliveries=dels, km_tolerance=tol)
    strict, band = run(None), run(0.30)
    assert sorted(i for x in band.routes for i in x) == list(range(len(pts)))
    km_s, _, _ = _loads(strict, svc, dels)
    km_b, dl_b, hr_b = _loads(band, svc, dels)
    assert km_b.sum() <= km_s.sum() * 1.05
    assert _spread(dl_b) <= 0.25 and _spread(hr_b) <= 0.25, (dl_b, hr_b)
