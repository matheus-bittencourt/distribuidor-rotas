"""Divide as paradas entre N entregadores e ordena cada rota.

Problema: cada entregador sai do PRÓPRIO ponto de partida e todos terminam no MESMO ponto final; o custo é
tempo de deslocamento + tempo parado. O que se quer igualar entre os entregadores é a CARGA: km rodados,
entregas e tempo ao mesmo tempo (o critério escolhido ganha peso maior).

Etapas:
  1. Setores: as paradas são agrupadas em "fatias de pizza" a partir do ponto de partida (k-means balanceado
     num anel em torno dele), de modo que cada fatia tenha paradas perto e longe. Zonas da cidade puxam as
     paradas para o centro da zona com peso pequeno (no máximo MAX_ZONE_WEIGHT).
  2. Capacidade: a largura de cada fatia é ajustada por uma medida combinada de km, entregas e tempo.
  3. Cada fatia é ordenada como caminho aberto (partida -> paradas -> chegada) com OR-Tools.
  4. Redistribuição: paradas saem da rota mais sobrecarregada para as folgadas, avaliando o efeito real em km,
     entregas e tempo de cada rota, até a carga ficar equilibrada (ou acabar o orçamento de movimentos,
     proporcional ao parâmetro `balance`). Igualar custa km no total: quem moraria "perto" roda mais.
  5. Cada rota é reordenada.

Medido (1400 entregas reais de Porto Alegre, 14 entregadores, mesma partida): agrupar por manchas de bairro
deixava km 33-120, entregas 90-112 e tempo 5,3-8,7 h; igualar só km deixava entregas de 8 a 170. Esta
abordagem com km prioritário deixou km 74-85, entregas 98-102 e tempo 7,0-7,3 h, com ~45% mais km no total.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from scipy.optimize import linear_sum_assignment

from .matrix import estimated_dist_m

MODE_WEIGHTS = {            # pesos (km, entregas, tempo) usados para medir a carga e redistribuir
    "km": (6.0, 1.0, 1.0),
    "time": (1.0, 1.0, 4.0),
    "stops": (1.0, 4.0, 1.0),   # no modo "paradas" a medida de entregas conta paradas, não entregas
}
BALANCE_MODES = tuple(MODE_WEIGHTS)
BAND_WEIGHTS = (6.0, 1.0, 1.0)        # km em faixa: peso do desvio ALÉM da faixa, entregas, tempo
BAND_ADAPT_WEIGHTS = (0.25, 1.0, 1.0)  # na largura das fatias o km conta pouco
REFINE_STEPS = (1.0, 1.0, 1.0)  # passadas de redistribuição, cada uma seguida de reordenação das rotas (TSP)
ADAPT_POWER = 0.5           # expoente do ajuste de largura das fatias, x balance
ADAPT_ITERS = 12            # rodadas de ajuste da largura das fatias
POLAR_BETA = 0.25           # quanto da posição real (além do ângulo) entra no agrupamento em fatias
MAX_ZONE_WEIGHT = 0.15      # a zona nunca pesa mais que 15% (limite pedido: a carga vem antes)
KM_GROWTH_PEN = 6.0           # penalidade pelo aumento do km total, x (1 - balance): 100% = sem penalidade
ZONE_PEN_AT_MAX = 0.06      # penalidade por parada fora da zona de origem, no peso máximo de zona


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


def _rebalance(routes, k, n, depot, dist, travel, service, dels, weights, zone_idx=None, zone_pen=0.0,
               max_iters=1500, km_growth_pen=0.0, km_band=None):
    """Move paradas da rota mais sobrecarregada para as folgadas, medindo o efeito REAL (custo de remover e de
    inserir na melhor posição) em km, entregas e tempo de cada rota. Minimiza a soma dos desvios quadrados
    relativos de cada medida, ponderados por `weights` = (km, entregas, tempo) + uma penalidade pequena por
    parada fora da zona "de origem" do entregador."""
    wk, wd, wt = weights
    paths = [[n + v, *routes[v], depot] for v in range(k)]
    km = np.array([dist[p[:-1], p[1:]].sum() / 1000 for p in paths])
    km0 = max(km.sum(), 1e-9)   # km total antes de redistribuir: referência da penalidade de crescimento
    tr = np.array([travel[p[:-1], p[1:]].sum() for p in paths], dtype=float)
    tm = tr + np.array([service[routes[v]].sum() for v in range(k)])
    dl = np.array([dels[routes[v]].sum() for v in range(k)], dtype=float)
    if zone_idx is not None and zone_pen > 0:
        home = [np.bincount(zone_idx[routes[v]]).argmax() if routes[v] else -1 for v in range(k)]
        zm = np.array([(zone_idx[routes[v]] != home[v]).sum() for v in range(k)], dtype=float)
    else:
        home, zm = None, np.zeros(k)

    def fm(S1, S2):                       # soma de (m_v/média - 1)^2 a partir de S1 = soma e S2 = soma dos quadrados
        return k * k * S2 / np.maximum(S1 * S1, 1e-9) - k

    def pen_band(x, mu):                  # desvio relativo ALÉM da faixa permitida, ao quadrado
        return np.maximum(0.0, np.abs(x / mu - 1) - km_band) ** 2

    def km_term():
        if km_band is None:
            return fm(km.sum(), (km ** 2).sum())
        return pen_band(km, km.mean()).sum()

    def total():
        return (wk * km_term() + wd * fm(dl.sum(), (dl ** 2).sum())
                + wt * fm(tm.sum(), (tm ** 2).sum()) + zone_pen * zm.sum() / max(n, 1) * k
                + km_growth_pen * (km.sum() / km0 - 1))

    def load(v):
        kdev = km[v] / km.mean() - 1
        if km_band is not None:        # dentro da faixa o km não conta como sobrecarga
            kdev = np.sign(kdev) * max(0.0, abs(kdev) - km_band)
        return wk * kdev + wd * (dl[v] / dl.mean() - 1) + wt * (tm[v] / tm.mean() - 1)

    moves = 0
    for _ in range(max_iters):
        f0 = total()
        S = {"km": (km.sum(), (km ** 2).sum()), "dl": (dl.sum(), (dl ** 2).sum()), "tm": (tm.sum(), (tm ** 2).sum())}
        best = None
        for a in sorted(range(k), key=load, reverse=True)[: max(3, k // 3)]:
            seq = paths[a][1:-1]
            if len(seq) <= 1:
                continue
            st = np.array(seq)
            pa, qa = np.array(paths[a][:-2]), np.array(paths[a][2:])
            rem_km = (dist[pa, st] + dist[st, qa] - dist[pa, qa]) / 1000
            rem_tr = travel[pa, st] + travel[st, qa] - travel[pa, qa]
            for b in range(k):
                if b == a:
                    continue
                pb, qb = np.array(paths[b][:-1]), np.array(paths[b][1:])
                ins_tr = travel[pb][:, st] + travel[st][:, qb].T - travel[pb, qb][:, None]      # (posições, paradas)
                pos = ins_tr.argmin(0)
                cols = np.arange(len(st))
                ins_tr_best = ins_tr[pos, cols]
                ins_km = (dist[pb[pos], st] + dist[st, qb[pos]] - dist[pb[pos], qb[pos]]) / 1000
                ka, kb = km[a] - rem_km, km[b] + ins_km
                ta, tb = tm[a] - rem_tr - service[st], tm[b] + ins_tr_best + service[st]
                da, db = dl[a] - dels[st], dl[b] + dels[st]
                dk = ka + kb - km[a] - km[b]
                if km_band is None:
                    km_f = fm(S["km"][0] + dk, S["km"][1] - km[a] ** 2 - km[b] ** 2 + ka ** 2 + kb ** 2)
                else:
                    mu = km.mean()
                    km_f = (pen_band(km, mu).sum() - pen_band(km[a], mu) - pen_band(km[b], mu)
                            + pen_band(ka, mu) + pen_band(kb, mu))
                f = (wk * km_f
                     + wd * fm(S["dl"][0], S["dl"][1] - dl[a] ** 2 - dl[b] ** 2 + da ** 2 + db ** 2)
                     + wt * fm(S["tm"][0] + (ta + tb - tm[a] - tm[b]), S["tm"][1] - tm[a] ** 2 - tm[b] ** 2 + ta ** 2 + tb ** 2))
                f = f + km_growth_pen * ((S["km"][0] + dk) / km0 - 1)
                if home is not None:
                    mis_a = (zone_idx[st] != home[a]).astype(float)
                    mis_b = (zone_idx[st] != home[b]).astype(float)
                    f = f + zone_pen * (zm.sum() - mis_a + mis_b) / max(n, 1) * k
                else:
                    f = f + zone_pen * 0
                i = int(np.argmin(f))
                if best is None or f[i] < best[0]:
                    best = (float(f[i]), a, b, int(st[i]), int(pos[i]), float(ka[i]), float(kb[i]), float(ta[i]), float(tb[i]),
                            float(da[i]), float(db[i]))
        if best is None or best[0] >= f0 - 1e-6:
            break
        _, a, b, stop, pos, ka, kb, ta, tb, da, db = best
        paths[a].remove(stop)
        paths[b].insert(pos + 1, stop)
        km[a], km[b], tm[a], tm[b], dl[a], dl[b] = ka, kb, ta, tb, da, db
        if home is not None:
            zm[a] -= float(zone_idx[stop] != home[a]); zm[b] += float(zone_idx[stop] != home[b])
        moves += 1
    return [p[1:-1] for p in paths], moves


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
    balance_by: str = "km",
    stop_service: np.ndarray | None = None,
    stop_deliveries: np.ndarray | None = None,
    km_tolerance: float | None = None,
) -> SolveResult:
    """balance_by: critério que pesa mais ao igualar a carga — "km" (distância rodada), "time" (tempo de rota)
    ou "stops" (quantidade de paradas); os outros dois continuam entrando com peso menor. `balance` (0..1) é
    até onde ir: 0 = só agrupar por proximidade; 1 = redistribuir até igualar. `zone_weight` é limitado a
    MAX_ZONE_WEIGHT. stop_service: tempo parado em cada ponto (s). stop_deliveries: entregas em cada ponto."""
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
    service[:n] = service_seconds if stop_service is None else np.asarray(stop_service, dtype=np.int64)
    cost = travel + service[:, None]          # sair do nó i = viagem + parada em i
    np.fill_diagonal(cost, 0)

    balance = min(max(balance, 0.0), 1.0)
    zw = min(max(zone_weight, 0.0), MAX_ZONE_WEIGHT)
    weights = MODE_WEIGHTS[balance_by]
    if km_tolerance is not None:       # km em faixa: entregas e tempo são o alvo, o km só não pode passar da faixa
        weights = BAND_WEIGHTS
    dels = np.ones(n) if (balance_by == "stops" or stop_deliveries is None) else np.asarray(stop_deliveries, dtype=float)
    avg = n / k

    # 1) fatias a partir da partida (com um empurrão pequeno das zonas)
    origin = stop_latlon.mean(0)
    xy = _project(stop_latlon, origin)
    if zone_idx is not None and zone_centers is not None and zw > 0:
        xy = (1 - zw) * xy + zw * _project(zone_centers, origin)[zone_idx]
    rel = xy - _project(depot_latlon[None, :], origin)[0]
    r, th = np.hypot(rel[:, 0], rel[:, 1]), np.arctan2(rel[:, 1], rel[:, 0])
    ring = np.column_stack([np.median(r) * np.cos(th), np.median(r) * np.sin(th)])
    xy = ring + POLAR_BETA * rel
    labels, centers = _balanced(xy, k)
    groups = [np.flatnonzero(labels == j) for j in range(k)]
    match = np.zeros((k, k))
    for v in range(k):
        for j, g in enumerate(groups):
            match[v, j] = travel[n + v, g].mean() if len(g) else 0
    drivers, clusters = linear_sum_assignment(match)
    order = {int(v): int(c) for v, c in zip(drivers, clusters)}
    centers = np.array([centers[order[v]] for v in range(k)])
    assigned = {v: groups[order[v]] for v in range(k)}

    # 2) largura das fatias por uma medida combinada de km, entregas e tempo
    wk, wd, wt = weights if km_tolerance is None else BAND_ADAPT_WEIGHTS
    if k > 1 and balance > 0:
        caps = np.full(k, float(math.ceil(avg)))
        norm = lambda a: a / max(a.mean(), 1e-9)
        for _ in range(ADAPT_ITERS):
            km_v = np.array([_nn_cost(dist, n + v, assigned[v], depot) for v in range(k)], dtype=float)
            tm_v = np.array([_nn_cost(travel, n + v, assigned[v], depot) + service[assigned[v]].sum() for v in range(k)], dtype=float)
            dl_v = np.array([dels[assigned[v]].sum() for v in range(k)], dtype=float)
            score = (wk * norm(km_v) + wd * norm(dl_v) + wt * norm(tm_v)) / (wk + wd + wt)
            ratio = score.mean() / np.maximum(score, 1e-9)
            caps = np.clip(caps * ratio ** (ADAPT_POWER * balance), 0.1 * avg, 1.9 * avg)
            labels, centers = _balanced(xy, k, _fix_sum(caps, n), centers, iters=4)
            assigned = {v: np.flatnonzero(labels == v) for v in range(k)}

    # 3) ordem de cada fatia
    per_cluster = max(0.4, 0.2 * time_limit / k)
    routes = [_order_open_path(cost, n + v, [int(x) for x in assigned[v]], depot, per_cluster) for v in range(k)]

    # 4) redistribuição por carga real + 5) reordena
    status = "ok"
    if k > 1 and balance > 0:
        pen = ZONE_PEN_AT_MAX * zw / MAX_ZONE_WEIGHT
        moves = 0
        for mult in REFINE_STEPS:
            w = weights if km_tolerance is not None else (weights[0] * mult, weights[1], weights[2]) if balance_by == "km" else                 (weights[0], weights[1], weights[2] * mult) if balance_by == "time" else (weights[0], weights[1] * mult, weights[2])
            routes, m = _rebalance(routes, k, n, depot, dist, travel, service, dels, w, zone_idx, pen,
                                   max_iters=max(600, 2 * n), km_growth_pen=KM_GROWTH_PEN * (1 - balance),
                                   km_band=km_tolerance)
            moves += m
            # reordena a cada passada: o km "de verdade" depois do TSP é o que a próxima passada deve igualar
            routes = [_order_open_path(cost, n + v, [int(x) for x in routes[v]], depot, per_cluster) for v in range(k)]
        status = f"ok ({moves} paradas redistribuídas)"

    legs, meters, total = [], [], 0
    for v in range(k):
        path = [n + v, *routes[v], depot]
        leg = [int(travel[a, b]) for a, b in zip(path, path[1:])]
        legs.append(leg)
        meters.append([int(dist[a, b]) for a, b in zip(path, path[1:])])
        total += sum(leg) + (int(service[routes[v]].sum()) if routes[v] else 0)
    return SolveResult(routes, legs, total, status, meters)
