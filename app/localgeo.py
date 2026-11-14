"""Geocodificador offline: acha o endereço no índice de ruas e números do pacote de mapa, sem internet.

Ordem: nome completo igual -> miolo do nome igual (sem 'Rua'/'Av.', títulos e preposições) -> nome
parecido. Com número: o mesmo número no índice, ou interpolado entre os vizinhos da mesma rua
('exato'); sem números por perto, o meio da rua ('aproximado').
"""
from __future__ import annotations

import difflib
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path

from .geocode import Geo
from .streetnames import core_key, full_key, neighbourhood_parts, parse_query, split_number, street_type

EXACT_GAP = 200      # vizinhos até 200 números de distância: interpolação confiável
NEAR_GAP = 300       # número mais próximo até 300 adiante/atrás: usa ele, como aproximado
FUZZY = 0.86


class LocalGeocoder:
    def __init__(self, folder: Path):
        with gzip.open(Path(folder) / "geoindex.json.gz", "rt", encoding="utf-8") as f:
            data = json.load(f)
        self.streets = data["streets"]
        self.hoods = {}
        for b in data.get("bairros", []):
            self.hoods[b["k"]] = (b["lat"], b["lon"])
            self.hoods.setdefault(core_key(b["n"]), (b["lat"], b["lon"]))
        self.by_full, self.by_core, self.by_word = defaultdict(list), defaultdict(list), defaultdict(set)
        for i, s in enumerate(self.streets):
            self.by_full[s["k"]].append(i)
            self.by_core[s["c"]].append(i)
            for w in s["c"].split():
                if len(w) > 2:
                    self.by_word[w[:4]].add(s["c"])   # início da palavra: tolera erro de digitação no fim

    def _candidates(self, street: str) -> tuple[list[int], bool]:
        """(índices de ruas, nome exato?)."""
        hit = self.by_full.get(full_key(street))
        if hit:
            return hit, True
        core = core_key(street)
        hit = self.by_core.get(core)
        if hit:
            t = street_type(street)
            same = [i for i in hit if not t or street_type(self.streets[i]["n"]) == t]
            return same or hit, True
        pool = set().union(*(self.by_word.get(w[:4], set()) for w in core.split() if len(w) > 2)) if core else set()
        near = difflib.get_close_matches(core, list(pool), n=3, cutoff=FUZZY)
        return [i for c in near for i in self.by_core[c]], False

    @staticmethod
    def _locate(s: dict, num: int | None) -> tuple[float, float, str]:
        a = s["a"]
        if num is not None and a:
            nums = [x[0] for x in a]
            for x in a:
                if x[0] == num:
                    return x[1], x[2], "exato"
            lo = max((x for x in a if x[0] < num), default=None, key=lambda x: x[0])
            hi = min((x for x in a if x[0] > num), default=None, key=lambda x: x[0])
            if lo and hi and hi[0] - lo[0] <= EXACT_GAP:
                f = (num - lo[0]) / (hi[0] - lo[0])
                return lo[1] + f * (hi[1] - lo[1]), lo[2] + f * (hi[2] - lo[2]), "exato"
            best = min(a, key=lambda x: abs(x[0] - num))
            if abs(best[0] - num) <= NEAR_GAP and nums:
                return best[1], best[2], "aproximado"
        return s["ctr"][0], s["ctr"][1], "aproximado"

    def geocode(self, query: str, wide: bool = False) -> Geo | None:
        street, num = parse_query(query)
        if not street:
            return None
        idx, exact_name = self._candidates(street)
        sp = split_number(street) if num is None else None
        if sp and not exact_name:          # "Rua X 123": só separa o número se "Rua X 123" não é nome de rua
            idx2, exact2 = self._candidates(sp[0])
            if idx2 and (exact2 or not idx):
                (street, num), idx = sp, idx2
        cands = [self.streets[i] for i in idx]
        if not wide:
            cands = [s for s in cands if s["poa"]]
        if not cands:
            return None
        hood = self._hood(query)

        # Ruas com o mesmo nome: 1) de Porto Alegre; 2) a mais perto do bairro informado; 3) a que tem
        # esse número no índice; 4) a que comporta o número (a numeração é métrica: o nº 2300 fica a
        # ~2,3 km do início da rua); 5) a com mais números conhecidos; 6) a maior.
        def score(s):
            near = 0.0
            if hood:
                pts = s["pts"]
                near = -min(math.hypot(p[0] - hood[0], (p[1] - hood[1]) * 0.866) for p in pts) * 111
                near = round(near * 2) / 2          # meio km: ruas na mesma vizinhança empatam
            has = num is not None and any(abs(x[0] - num) <= EXACT_GAP for x in s["a"])
            fits = num is None or s.get("len", 0) >= num * 0.6 - 100
            return (s["poa"], near, has, fits, len(s["a"]), s.get("len", len(s["pts"])))
        ranked = sorted(cands, key=score, reverse=True)
        best = ranked[0]
        lat, lon, precision = self._locate(best, num)
        # ainda empatado nos critérios fortes: não dá para afirmar que é esta rua
        if len(ranked) > 1 and score(ranked[1])[:4] == score(best)[:4] and precision == "exato":
            precision = "aproximado"
        return Geo(lat, lon, precision, "Porto Alegre" if best["poa"] else "")

    def _hood(self, query: str) -> tuple[float, float] | None:
        for part in neighbourhood_parts(query):
            k = full_key(part)
            if k in ("porto alegre", "rs"):
                continue
            hit = self.hoods.get(k) or self.hoods.get(core_key(part))
            if hit:
                return hit
        return None
