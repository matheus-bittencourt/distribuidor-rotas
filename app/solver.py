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

from .matrix import estimated_dist_m

SPAN_WEIGHT = 20       # equilíbrio por paradas: peso do tempo da rota mais longa (x balance)
TIME_SPAN_WEIGHT = 40  # equilíbrio por tempo: peso do tempo da rota mais longa (x balance)
KM_SPAN_WEIGHT = 500   # equilíbrio por km: peso por 100 m da rota mais longa (x balance); ~1 km = 129 s de viagem
ADAPT_ITERS = 12      # rodadas de ajuste de capacidade dos grupos (equilíbrio por tempo/km)
LOW_PENALTY = 600      # custo (s) por parada abaixo do piso de paradas de um entregador
BALANCE_MODES = ("stops", "time", "km")


@dataclass
class SolveResult:
    routes: list[list[int]]        # por entregador: índices de paradas na ordem de visita
    leg_seconds: list[list[int]]   # por entregador: tempo de cada trecho (len = paradas + 1)
    total_seconds: int
    status: str
    leg_meters: list[list[int]] | None = None  # por entregador: distância de cada trecho


def _project(latlon: np.ndarray, origin: np.ndarray | None = None) -> np.ndarray:
    lat0, lon0 = (latlon.mean(0) if origin is None else origin)
    x = (latlon[:, 1] - lon0) * math.cos(math.radians(lat0)) * 111.32
    y = (latlon[:, 0] - lat0) * 110.57
    return np.column_stack([x, y])


def _balanced(xy: np.ndarray, k: int, caps: np.ndarray | None = None, centers: np.ndarray | None = None,
              iters: int = 15, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """k-means com tamanho de grupo controlado: grupo j recebe no máximo caps[j] pontos (iguais por padrão,
    ± 1). Resolvido como designação; devolve (rótulos, centros)."""
    n = len(xy)
    caps = np.full(k, math.ceil(n / k)) if caps is None else np.asarray(caps, dtype=int)
    if centers is None:
        rng = np.random.default_rng(seed)
        cs = [xy[rng.integers(n)]]
        for _ in range(1, k):  # k-means++
            d2 = np.min([((xy - c) ** 2).sum(1) for c in cs], axis=0)
            p = d2 / d2.sum() if d2.sum() > 0 else None
            cs.append(xy[rng.choice(n, p=p)])
        centers = np.array(cs)
    centers = centers.copy()
    owner = np.repeat(np.arange(k), caps)  # um "espaço" por vaga de cada grupo
    labels = np.full(n, -1, dtype=int)
    for _ in range(iters):
        d2 = ((xy[:, None, :] - centers[None, :, :]) ** 2).sum(2)
        rows, cols = linear_sum_assignment(d2[:, owner])
        new = np.empty(n, dtype=int)
        new[rows] = owner[cols]
        if np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            m = labels == j
            if m.any():
                centers[j] = xy[m].mean(0)
    return labels, centers


def balanced_clusters(xy: np.ndarray, k: int, iters: int = 15, seed: int = 0) -> np.ndarray:
    """k-means com grupos de tamanho igual (± 1). Devolve o rótulo (0..k-1) de cada ponto."""
    return _balanced(xy, k, iters=iters, seed=seed)[0]


def _nn_cost(mat: np.ndarray, start: int, members: np.ndarray, end: int) -> float:
    """Custo aproximado de start -> members -> end: vizinho mais próximo + 2-opt. Serve só para comparar
    entregadores entre si (o vizinho mais próximo puro superestima grupos esparsos)."""
    if len(members) == 0:
        return float(mat[start, end])
    left, cur, path = list(members), start, [start]
    while left:
        j = min(range(len(left)), key=lambda i: mat[cur, left[i]])
        cur = left.pop(j)
        path.append(cur)
    path.append(end)
    p = np.array(path)
    m = len(p) - 2
    for _ in range(4):
        improved = False
        for i in range(1, m):
            js = np.arange(i + 1, m + 1)
            delta = (mat[p[i - 1], p[js]] + mat[p[i], p[js + 1]]
                     - mat[p[i - 1], p[i]] - mat[p[js], p[js + 1]])
            k = int(np.argmin(delta))
            if delta[k] < -1e-9:
                j = int(js[k])
                p[i:j + 1] = p[i:j + 1][::-1].copy()
                improved = True
        if not improved:
            break
    return float(mat[p[:-1], p[1:]].sum())


def _fix_sum(x: np.ndarray, n: int) -> np.ndarray:
    """Arredonda capacidades para inteiros >= 1 somando exatamente n."""
    x = np.maximum(x * n / x.sum(), 1.0)
    c = np.floor(x).astype(int)
    for i in np.argsort(-(x - c))[: max(n - c.sum(), 0)]:
        c[i] += 1
    while c.sum() > n:  # sobrou por causa do piso de 1
        c[int(np.argmax(c))] -= 1
    return c


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
    balance_by: str = "stops",
) -> SolveResult:
    """balance_by: o que o equilíbrio iguala entre entregadores — "stops" (quantidade de paradas),
    "time" (tempo de rota) ou "km" (distância rodada). `balance` (0..1) é a intensidade."""
    if balance_by not in BALANCE_MODES:
        raise ValueError(f"balance_by deve ser um de {BALANCE_MODES}")
    t0 = time.monotonic()
    n, k = len(stop_latlon), len(starts_latlon)
    if n == 0:
        return SolveResult([[] for _ in range(k)], [[0] for _ in range(k)], 0, "sem paradas",
                           [[0] for _ in range(k)])

    coords = np.vstack([stop_latlon, starts_latlon, depot_latlon[None, :]])
    got = matrix_fn(coords)
    travel, dist = got if isinstance(got, tuple) else (got, None)
    if dist is None:
        dist = estimated_dist_m(coords)
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
    labels, centers = _balanced(xy, k)
    groups = [np.flatnonzero(labels == j) for j in range(k)]
    match = np.zeros((k, k))
    for v in range(k):
        for j, g in enumerate(groups):
            match[v, j] = travel[n + v, g].mean() if len(g) else 0
    drivers, clusters = linear_sum_assignment(match)
    order = {int(v): int(c) for v, c in zip(drivers, clusters)}
    centers = np.array([centers[order[v]] for v in range(k)])        # centro do grupo de cada entregador
    assigned = {v: groups[order[v]] for v in range(k)}

    # Equilíbrio por tempo/km: entregadores cujas paradas "custam" mais (moram longe, zona espalhada)
    # recebem menos paradas. Ajusta as capacidades dos grupos e reagrupa algumas vezes.
    balance = min(max(balance, 0.0), 1.0)
    avg = n / k
    if balance_by in ("time", "km") and k > 1 and balance > 0:
        mat = travel if balance_by == "time" else dist          # simétricas: o 2-opt não depende do sentido
        per_stop = service_seconds if balance_by == "time" else 0
        caps = np.full(k, float(math.ceil(avg)))
        for _ in range(ADAPT_ITERS):
            metric = np.array([_nn_cost(mat, n + v, assigned[v], depot) + per_stop * len(assigned[v]) for v in range(k)], dtype=float)
            ratio = metric.mean() / np.maximum(metric, 1.0)
            caps = np.clip(caps * ratio ** (1.0 * balance), 0.1 * avg, 1.9 * avg)
            int_caps = _fix_sum(caps, n)
            labels, centers = _balanced(xy, k, int_caps, centers, iters=4)
            assigned = {v: np.flatnonzero(labels == v) for v in range(k)}

    per_cluster = max(0.5, 0.3 * time_limit / k)
    initial = [
        _order_open_path(cost, n + v, [int(x) for x in assigned[v]], depot, per_cluster)
        for v in range(k)
    ]

    # 3) polimento global
    if balance_by == "stops":      # iguala a quantidade (faixa estreita de paradas) e aperta o tempo máximo
        spread, time_w, km_w = 0.9 - 0.75 * balance, balance * SPAN_WEIGHT, 0
    elif balance_by == "time":     # iguala o tempo de rota; a quantidade de paradas pode variar mais
        spread, time_w, km_w = 0.9, balance * TIME_SPAN_WEIGHT, 0
    else:                          # iguala os km rodados
        spread, time_w, km_w = 0.9, 0, balance * KM_SPAN_WEIGHT
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
    if time_w > 0:
        routing.AddDimension(transit, 0, 10**7, True, "Tempo")
        routing.GetDimensionOrDie("Tempo").SetGlobalSpanCostCoefficient(int(round(time_w)))
    if km_w > 0:  # unidade da dimensão: 100 m
        km_cb = routing.RegisterTransitMatrix(np.rint(dist / 100).astype(np.int64).tolist())
        routing.AddDimension(km_cb, 0, 10**7, True, "Km")
        routing.GetDimensionOrDie("Km").SetGlobalSpanCostCoefficient(int(round(km_w)))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    remaining = max(2.0, time_limit - (time.monotonic() - t0))
    params.time_limit.FromMilliseconds(int(remaining * 1000))
    routing.CloseModelWithParameters(params)
    start_sol = routing.ReadAssignmentFromRoutes(initial, True)
    solution = routing.SolveFromAssignmentWithParameters(start_sol, params) if start_sol else None
    status = "ok" if solution is not None else "ok (sem polimento)"

    routes, legs, meters, total = [], [], [], 0
    for v in range(k):
        if solution is None:
            seq = initial[v]
        else:
            idx, seq = routing.Start(v), []
            while not routing.IsEnd(idx):
                idx = solution.Value(routing.NextVar(idx))
                node = manager.IndexToNode(idx)
                if node < n:
                    seq.append(node)
        path = [n + v, *seq, depot]
        leg = [int(travel[a, b]) for a, b in zip(path, path[1:])]
        routes.append(seq)
        legs.append(leg)
        meters.append([int(dist[a, b]) for a, b in zip(path, path[1:])])
        total += sum(leg) + service_seconds * len(seq)
    return SolveResult(routes, legs, total, status, meters)
