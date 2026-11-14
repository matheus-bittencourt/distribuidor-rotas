import numpy as np

from app.matrix import estimated_matrix
from app.solver import balanced_clusters, solve

DEPOT = np.array([-30.0306, -51.2288])


def _data(n, k, seed=3):
    rng = np.random.default_rng(seed)
    pts = rng.uniform([-30.13, -51.26], [-29.97, -51.11], size=(n, 2))
    starts = rng.uniform([-30.14, -51.27], [-29.95, -51.09], size=(k, 2))
    return pts, starts


def test_balanced_clusters_equal_sizes():
    xy = np.random.default_rng(0).normal(size=(103, 2))
    sizes = np.bincount(balanced_clusters(xy, 8), minlength=8)
    assert sizes.max() - sizes.min() <= 1


def test_every_stop_visited_once_and_no_empty_routes():
    pts, starts = _data(150, 6)
    r = solve(pts, starts, DEPOT, estimated_matrix, 120, 0.7, 6)
    assert sorted(i for route in r.routes for i in route) == list(range(150))
    counts = [len(x) for x in r.routes]
    assert min(counts) >= 10 and max(counts) <= 40  # média 25
    assert all(len(l) == len(s) + 1 for l, s in zip(r.leg_seconds, r.routes))


def test_route_is_open_path_from_start_to_depot():
    pts, starts = _data(40, 2)
    r = solve(pts, starts, DEPOT, estimated_matrix, 0, 0.7, 4)
    m = estimated_matrix(np.vstack([pts, starts, DEPOT[None, :]]))
    n = 40
    for v, route in enumerate(r.routes):
        path = [n + v, *route, n + 2]
        assert r.leg_seconds[v] == [int(m[a, b]) for a, b in zip(path, path[1:])]


def test_more_drivers_than_stops():
    pts, starts = _data(3, 5)
    r = solve(pts, starts, DEPOT, estimated_matrix, 60, 0.5, 3)
    assert sorted(i for route in r.routes for i in route) == [0, 1, 2]


def test_higher_balance_narrows_km_spread():
    pts, starts = _data(200, 8, seed=9)
    spread = {}
    for b in (0.0, 1.0):
        r = solve(pts, starts, DEPOT, estimated_matrix, 120, b, 8, balance_by="km")
        km = [sum(m) / 1000 for m in r.leg_meters]
        spread[b] = max(km) - min(km)
    assert spread[1.0] < spread[0.0]


def test_stops_mode_keeps_counts_tight():
    pts, starts = _data(200, 8, seed=9)
    r = solve(pts, starts, DEPOT, estimated_matrix, 120, 1.0, 8, balance_by="stops")
    c = [len(x) for x in r.routes]
    assert max(c) - min(c) <= 8   # média 25
