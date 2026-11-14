"""Roteamento por ruas sem servidor: Dijkstra (scipy) sobre a malha viária do pacote de mapa.

Tempo é o critério do caminho e a distância é a do MESMO caminho. Os dois saem de uma única busca:
o peso de cada trecho é  décimos_de_segundo * 1e6 + metros. Como nenhuma rota passa de 1000 km, a parte
dos metros nunca transborda para a dos décimos: o menor peso é o caminho mais rápido (com empate
resolvido pelo mais curto), e tempo = peso // 1e6, distância = peso % 1e6, exatos em float64.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

ACCESS_KMH = 15.0      # trecho entre a parada e o cruzamento mais próximo (entrada, manobra)
CHUNK = 48             # origens por lote (memória: CHUNK x nº de cruzamentos)
SCALE = 1e6            # separa décimos de segundo (parte alta) de metros (parte baixa) no peso
WORKERS = 4            # lotes em paralelo (o Dijkstra do scipy libera o GIL)


def encode_polyline(pts) -> str:
    """[[lat, lon], ...] -> polyline codificada (formato do Google, precisão 5)."""
    out, plat, plon = [], 0, 0
    for la, lo in pts:
        ila, ilo = int(round(la * 1e5)), int(round(lo * 1e5))
        for v in (ila - plat, ilo - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63)); v >>= 5
            out.append(chr(v + 63))
        plat, plon = ila, ilo
    return "".join(out)


class LocalRouter:
    def __init__(self, folder: Path):
        z = np.load(Path(folder) / "graph.npz")
        self.lat, self.lon = z["node_lat"], z["node_lon"]
        n = self.n = len(self.lat)
        u, v = z["edge_u"].astype(np.int64), z["edge_v"].astype(np.int64)
        self.edge_t, self.edge_d = z["edge_t"].astype(np.float64), z["edge_d"].astype(np.float64)
        self.gptr, self.glat, self.glon = z["geom_ptr"], z["geom_lat"], z["geom_lon"]
        w = np.rint(self.edge_t * 10) * SCALE + np.maximum(self.edge_d, 0.01)
        self.G = csr_matrix((w, (u, v)), shape=(n, n))
        keys = u * n + v
        self.korder = np.argsort(keys)
        self.keys = keys[self.korder]
        snap = np.flatnonzero(z["snap"])
        self.snap_ids = snap
        self.lat0 = float(np.cos(np.radians(self.lat.mean())))
        self.tree = cKDTree(self._xy(self.lat[snap], self.lon[snap]))

    def _xy(self, lat, lon):
        return np.c_[np.asarray(lon) * 111320.0 * self.lat0, np.asarray(lat) * 110574.0]

    def _edge(self, a, b):
        """Índice do trecho a->b (vetorizado)."""
        k = a.astype(np.int64) * self.n + b
        return self.korder[np.searchsorted(self.keys, k)]

    def snap(self, coords: np.ndarray):
        d, i = self.tree.query(self._xy(coords[:, 0], coords[:, 1]))
        return self.snap_ids[i], d

    # -------------------------------------------------------------- matriz
    def matrix(self, coords: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(tempos s, distâncias m, alcançável) entre todos os pontos (lat, lon)."""
        from concurrent.futures import ThreadPoolExecutor

        nodes, acc_m = self.snap(np.asarray(coords, float))
        uniq, inv = np.unique(nodes, return_inverse=True)

        def run(c0):
            src = uniq[c0:c0 + CHUNK]
            return c0, dijkstra(self.G, directed=True, indices=src)[:, uniq]

        W = np.empty((len(uniq), len(uniq)))
        with ThreadPoolExecutor(WORKERS) as pool:
            for c0, block in pool.map(run, range(0, len(uniq), CHUNK)):
                W[c0:c0 + len(block)] = block
        with np.errstate(invalid="ignore"):
            tenths = np.floor(W / SCALE)
            T, D = tenths / 10, W - tenths * SCALE
        T, D = T[inv][:, inv], D[inv][:, inv]
        ok = np.isfinite(T)
        acc_t = acc_m / (ACCESS_KMH / 3.6)
        T = np.where(ok, T + acc_t[:, None] + acc_t[None, :], np.inf)
        D = np.where(ok, D + acc_m[:, None] + acc_m[None, :], np.inf)
        np.fill_diagonal(T, 0); np.fill_diagonal(D, 0); np.fill_diagonal(ok, True)
        return T, D, ok

    # -------------------------------------------------------------- traçado
    def _leg(self, a: int, b: int) -> list[int] | None:
        """Cruzamentos do caminho mais rápido a->b. A busca para num raio de custo que cabe o trecho
        (linha reta x 3 a 10 km/h); se não achar, refaz sem limite."""
        xy = self._xy(self.lat[[a, b]], self.lon[[a, b]])
        straight = float(np.hypot(*(xy[1] - xy[0])))
        for limit in ((straight * 3 + 500) / (10 / 3.6) * 10 * SCALE, np.inf):
            _, pred = dijkstra(self.G, directed=True, indices=a, return_predecessors=True, limit=limit)
            if pred[b] >= 0:
                seq = [b]
                while seq[-1] != a:
                    seq.append(int(pred[seq[-1]]))
                return seq[::-1]
        return None

    def paths(self, routes: list[list[tuple[float, float]]]) -> list[str | None]:
        out = []
        for pts in routes:
            if len(pts) < 2:
                out.append(None); continue
            arr = np.asarray(pts, float)
            nodes, _ = self.snap(arr)
            line: list[list[float]] = []
            for k in range(len(nodes) - 1):
                a, b = int(nodes[k]), int(nodes[k + 1])
                line.append([arr[k, 0], arr[k, 1]])
                if a == b:
                    continue
                seq = self._leg(a, b)
                if seq is None:       # sem caminho: liga em linha reta
                    continue
                for x, y in zip(seq[:-1], seq[1:]):
                    e = int(self._edge(np.array([x]), np.array([y]))[0])
                    s, t = self.gptr[e], self.gptr[e + 1]
                    line.extend(np.c_[self.glat[s:t], self.glon[s:t]] / 1e6)
            line.append([arr[-1, 0], arr[-1, 1]])
            out.append(encode_polyline(line))
        return out
