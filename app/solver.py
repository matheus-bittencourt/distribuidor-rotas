"""Divide as paradas entre N entregadores e ordena cada rota.

Problema: cada entregador sai do PRÓPRIO ponto de partida (a casa/localização atual) e todos
terminam no MESMO ponto final; o custo é tempo de deslocamento (+ tempo de parada).

Abordagem em três etapas (agrupar -> rotear -> polir):
  1. Agrupamento balanceado: k-means em que cada grupo tem o mesmo tamanho (± 1 parada),
     resolvido como problema de designação. Dá grupos compactos e equilibrados. Com zonas da
     cidade, as coordenadas são puxadas para o centro da zona (peso `zone_weight`) antes do k-means.
  2. Cada grupo é entregue a quem mora mais perto dele (designação k x k) e a rota do grupo
     é ordenada como caminho início -> paradas -> ponto final (TSP aberto, OR-Tools).
  3. Polimento global (OR-Tools VRP) partindo da solução anterior: paradas de fronteira podem
     trocar de entregador se isso reduzir o tempo, dentro de uma faixa de paradas por entregador
     que o parâmetro `balance` (0..1) estreita ou alarga, mais uma penalidade sobre a rota mais longa.

Por que não só o VRP do OR-Tools: partindo do zero ele deixava entregadores sem paradas
(mínimos de paradas não são alcançados por heurísticas de inserção). Medido com 800-2000 paradas.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from scipy.optimize import linear_sum_assignment

SPAN_WEIGHT = 20      # peso da rota mais longa no custo (x balance)
LOW_PENALTY = 600     # custo (s) por parada abaixo do piso de paradas de um entregador


@dataclass
class SolveResult:
    routes: list[list[int]]        # por entregador: índices de paradas na ordem de visita
    leg_seconds: list[list[int]]   # por entregador: tempo de cada trecho (len = paradas + 1)
    total_seconds: int
    status: str


def _project(latlon: np.ndarray, origin: np.ndarray | None = None) -> np.ndarray:
    lat0, lon0 = (latlon.mean(0) if origin is None else origin)
    x = (latlon[:, 1] - lon0) * math.cos(math.radians(lat0)) * 111.32
    y = (latlon[:, 0] - lat0) * 110.57
    return np.column_stack([x, y])


def balanced_clusters(xy: np.ndarray, k: int, iters: int = 15, seed: int = 0) -> np.ndarray:
    """k-means com grupos de tamanho igual (± 1). Devolve o rótulo (0..k-1) de cada ponto."""
    n = len(xy)
    cap = math.ceil(n / k)
    rng = np.random.default_rng(seed)
    centers = [xy[rng.integers(n)]]
    for _ in range(1, k):  # k-means++
        d2 = np.min([((xy - c) ** 2).sum(1) for c in centers], axis=0)
        p = d2 / d2.sum() if d2.sum() > 0 else None
        centers.append(xy[rng.choice(n, p=p)])
    centers = np.array(centers)
    labels = np.full(n, -1, dtype=int)
    for _ in range(iters):
        d2 = ((xy[:, None, :] - centers[None, :, :]) ** 2).sum(2)
        rows, cols = linear_sum_assignment(np.repeat(d2, cap, axis=1))
        new = np.empty(n, dtype=int)
        new[rows] = cols // cap
        if np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            m = labels == j
            if m.any():
                centers[j] = xy[m].mean(0)
    return labels


def _order_open_path(cost: np.ndarray, start: int, members: list[int], end: int, seconds: float) -> list[int]:
    """Ordena `members` num caminho start -> ... -> end (TSP aberto) com OR-Tools."""
    if len(members) <= 1:
        return list(members)
    nodes = [start, *members, end]
    sub = cost[np.ix_(nodes, nodes)]
    manager = pywrapcp.RoutingIndexManager(len(nodes), 1, [0], [len(nodes) - 1])
    routing = pywrapcp.RoutingModel(manager)
    cb = routing.RegisterTransitMatrix(sub.tolist())
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    p = pywrapcp.DefaultRoutingSearchParameters()
    p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    p.time_limit.FromMilliseconds(int(seconds * 1000))
    sol = routing.SolveWithParameters(p)
    if sol is None:
        return list(members)
    out, idx = [], routing.Start(0)
    while not routing.IsEnd(idx):
        idx = sol.Value(routing.NextVar(idx))
        node = manager.IndexToNode(idx)
        if 0 < node < len(nodes) - 1:
            out.append(members[node - 1])
    return out


def solve(
    stop_latlon: np.ndarray,
    starts_latlon: np.ndarray,
    depot_latlon: np.ndarray,
    matrix_fn,
    service_seconds: int = 120,
    balance: float = 0.7,
    time_limit: int = 30,
    zone_idx: np.ndarray | None = None,
    zone_centers: np.ndarray | None = None,
    zone_weight: float = 0.0,
) -> SolveResult:
    t0 = time.monotonic()
    n, k = len(stop_latlon), len(starts_latlon)
    if n == 0:
        return SolveResult([[] for _ in range(k)], [[0] for _ in range(k)], 0, "sem paradas")

    coords = np.vstack([stop_latlon, starts_latlon, depot_latlon[None, :]])
    travel = matrix_fn(coords)
    depot = n + k
    service = np.zeros(len(coords), dtype=np.int64)
    service[:n] = service_seconds
    cost = travel + service[:, None]          # sair do nó i = viagem + parada em i
    np.fill_diagonal(cost, 0)

    # 1) grupos balanceados e 2) quem mora mais perto de cada grupo
    # Prioridade por zonas: cada parada é "puxada" para o centro da sua zona antes de agrupar, então
    # paradas da mesma zona tendem a ficar juntas e só se dividem entre entregadores quando a zona é grande.
    origin = stop_latlon.mean(0)
    xy = _project(stop_latlon, origin)
    if zone_idx is not None and zone_centers is not None and zone_weight > 0:
        w = min(max(zone_weight, 0.0), 1.0)
        xy = (1 - w) * xy + w * _project(zone_centers, origin)[zone_idx]
    labels = balanced_clusters(xy, k)
    groups = [np.flatnonzero(labels == j) for j in range(k)]
    match = np.zeros((k, k))
    for v in range(k):
        for j, g in enumerate(groups):
            match[v, j] = travel[n + v, g].mean() if len(g) else 0
    drivers, clusters = linear_sum_assignment(match)
    assigned = {int(v): groups[int(c)] for v, c in zip(drivers, clusters)}

    per_cluster = max(0.5, 0.3 * time_limit / k)
    initial = [
        _order_open_path(cost, n + v, [int(x) for x in assigned[v]], depot, per_cluster)
        for v in range(k)
    ]

    # 3) polimento global
    balance = min(max(balance, 0.0), 1.0)
    avg = n / k
    spread = 0.9 - 0.75 * balance
    lo = math.floor(avg * (1 - spread))
    hi = max(math.ceil(avg * (1 + spread)), max(len(r) for r in initial))

    manager = pywrapcp.RoutingIndexManager(len(coords), k, [n + v for v in range(k)], [depot] * k)
    routing = pywrapcp.RoutingModel(manager)
    transit = routing.RegisterTransitMatrix(cost.tolist())
    routing.SetArcCostEvaluatorOfAllVehicles(transit)

    stops_cb = routing.RegisterUnaryTransitVector([1] * n + [0] * (k + 1))
    routing.AddDimension(stops_cb, 0, hi, True, "Paradas")            # teto rígido por entregador
    stops_dim = routing.GetDimensionOrDie("Paradas")
    for v in range(k):                                                # piso macio
        stops_dim.SetCumulVarSoftLowerBound(routing.End(v), lo, LOW_PENALTY)
    routing.AddDimension(transit, 0, 10**7, True, "Tempo")
    routing.GetDimensionOrDie("Tempo").SetGlobalSpanCostCoefficient(int(round(balance * SPAN_WEIGHT)))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    remaining = max(2.0, time_limit - (time.monotonic() - t0))
    params.time_limit.FromMilliseconds(int(remaining * 1000))
    routing.CloseModelWithParameters(params)
    start_sol = routing.ReadAssignmentFromRoutes(initial, True)
    solution = routing.SolveFromAssignmentWithParameters(start_sol, params) if start_sol else None
    status = "ok" if solution is not None else "ok (sem polimento)"

    routes, legs, total = [], [], 0
    for v in range(k):
        if solution is None:
            seq = initial[v]
            path = [n + v, *seq, depot]
            leg = [int(travel[a, b]) for a, b in zip(path, path[1:])]
        else:
            idx, seq, leg = routing.Start(v), [], []
            prev = manager.IndexToNode(idx)
            while not routing.IsEnd(idx):
                idx = solution.Value(routing.NextVar(idx))
                node = manager.IndexToNode(idx)
                leg.append(int(travel[prev, node]))
                if node < n:
                    seq.append(node)
                prev = node
        routes.append(seq)
        legs.append(leg)
        total += sum(leg) + service_seconds * len(seq)
    return SolveResult(routes, legs, total, status)
