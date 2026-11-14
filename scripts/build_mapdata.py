"""Gera o PACOTE DE MAPA offline de Porto Alegre (usado pelo app sem internet).

Uso:
  python scripts/build_mapdata.py --pbf osrm-data/sul-latest.osm.pbf --out dist/mapa [--version 2026.11.14]
         [--no-basemap] [--basemap-maxzoom 15]

Saída (pasta --out):
  graph.npz        malha viária para carro (cruzamentos, trechos com tempo, distância e traçado)
  geoindex.json.gz ruas e números de casa para achar endereços sem internet
  basemap.pmtiles  fundo do mapa (recorte do mapa-múndi diário do Protomaps)
  info.json        versão, data dos dados e contagens

Dados © colaboradores do OpenStreetMap (ODbL). Requer: pip install osmium pmtiles numpy scipy httpx
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import POA_BBOX, RMPA_BBOX  # noqa: E402
from app.streetnames import core_key, full_key, house_number  # noqa: E402

# ------------------------------------------------------------------ perfil de carro
# Velocidade (km/h) por tipo de via, sem trânsito. Calibrada contra o OSRM (perfil carro) em Porto Alegre.
SPEED = {
    "motorway": 80, "trunk": 60, "primary": 45, "secondary": 38, "tertiary": 32, "unclassified": 28,
    "residential": 24, "living_street": 10, "service": 15, "road": 20,
    "motorway_link": 50, "trunk_link": 40, "primary_link": 35, "secondary_link": 30, "tertiary_link": 26,
}
SKIP_SERVICE = {"parking_aisle", "drive-through", "emergency_access"}
NO_ACCESS = {"no", "private", "agricultural", "forestry", "delivery", "destination_no"}
SPEED_FACTOR = 1.0   # ajuste fino global (ver --calibrate)


def car_profile(tags) -> tuple[float, int] | None:
    """(velocidade km/h, sentido) ou None se carro não passa. sentido: 0 duplo, 1 só ida, -1 só volta."""
    hw = tags.get("highway")
    if hw not in SPEED or tags.get("area") == "yes":
        return None
    if hw == "service" and tags.get("service") in SKIP_SERVICE:
        return None
    acc = tags.get("motorcar") or tags.get("motor_vehicle") or tags.get("vehicle") or tags.get("access")
    if acc in NO_ACCESS:
        return None
    speed = SPEED[hw]
    ms = tags.get("maxspeed", "")
    if ms.split(" ")[0].isdigit():
        speed = min(speed, int(ms.split(" ")[0]) * 0.85)
    ow = tags.get("oneway", "")
    if ow in ("yes", "true", "1"):
        d = 1
    elif ow == "-1":
        d = -1
    elif ow == "no":
        d = 0
    else:
        d = 1 if (tags.get("junction") in ("roundabout", "circular") or hw in ("motorway", "motorway_link")) else 0
    return speed * SPEED_FACTOR, d


def inside(lat, lon, box) -> bool:
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


def hav_m(la1, lo1, la2, lo2):
    la1, lo1, la2, lo2 = map(np.radians, (la1, lo1, la2, lo2))
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371008.8 * np.arcsin(np.sqrt(h))


# ------------------------------------------------------------------ leitura do OSM
def read_osm(pbf: Path):
    import osmium

    car_ways = []            # (refs, lats, lons, speed, dir)
    named = defaultdict(list)  # full_key -> [(display, refs, lats, lons)]
    addrs = []               # (street display, number, lat, lon, city)
    poa_rings = []           # contorno do município (anéis externos)
    hoods = {}               # bairro -> (lat, lon)
    t0 = time.time()
    fp = (osmium.FileProcessor(str(pbf)).with_locations()
          .with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
          .with_filter(osmium.filter.KeyFilter("highway", "addr:housenumber", "boundary", "place")))
    for o in fp:
        if o.is_area():
            t = o.tags
            if t.get("boundary") != "administrative":
                continue
            lvl, name = t.get("admin_level"), t.get("name", "")
            rings = [np.array([(n.lat, n.lon) for n in ring]) for ring in o.outer_rings()]
            if not rings:
                continue
            if lvl == "8" and name == "Porto Alegre":
                poa_rings += rings
            elif lvl in ("9", "10") and name:
                big = max(rings, key=len)
                la, lo = float(big[:, 0].mean()), float(big[:, 1].mean())
                if inside(la, lo, POA_BBOX):
                    hoods[name] = (la, lo)
            continue
        if o.is_node():
            t = o.tags
            if t.get("place") in ("suburb", "neighbourhood", "quarter") and "name" in t and o.location.valid():
                la, lo = o.location.lat, o.location.lon
                if inside(la, lo, POA_BBOX):
                    hoods.setdefault(t["name"], (la, lo))
            if "addr:housenumber" in t and "addr:street" in t and o.location.valid():
                la, lo = o.location.lat, o.location.lon
                if inside(la, lo, RMPA_BBOX):
                    addrs.append((t["addr:street"], t["addr:housenumber"], la, lo, t.get("addr:city", "")))
        elif o.is_way():
            t = o.tags
            try:
                pts = [(n.ref, n.lat, n.lon) for n in o.nodes]
            except osmium.InvalidLocationError:
                continue
            if len(pts) < 2:
                continue
            if not any(inside(la, lo, RMPA_BBOX) for _, la, lo in pts[:: max(1, len(pts) // 4)] + [pts[-1]]):
                continue
            refs = np.array([p[0] for p in pts], dtype=np.int64)
            lats = np.array([p[1] for p in pts]); lons = np.array([p[2] for p in pts])
            if "highway" in t:
                prof = car_profile(t)
                if prof:
                    car_ways.append((refs, lats, lons, prof[0], prof[1]))
                if "name" in t:
                    named[full_key(t["name"])].append((t["name"], refs, lats, lons))
            if "addr:housenumber" in t and "addr:street" in t:
                la, lo = float(lats.mean()), float(lons.mean())
                if inside(la, lo, RMPA_BBOX):
                    addrs.append((t["addr:street"], t["addr:housenumber"], la, lo, t.get("addr:city", "")))
    print(f"OSM lido em {time.time() - t0:.0f}s: {len(car_ways)} vias de carro, {len(named)} nomes de rua, "
          f"{len(addrs)} endereços com número, {len(hoods)} bairros, contorno de Porto Alegre: "
          f"{sum(len(r) for r in poa_rings)} pontos")
    if not poa_rings:
        raise SystemExit("Contorno de Porto Alegre não encontrado no arquivo OSM.")
    return car_ways, named, addrs, poa_rings, hoods


def in_rings(rings, lat, lon) -> np.ndarray:
    """Ponto dentro de algum dos anéis (regra do número de cruzamentos), vetorizado."""
    lat, lon = np.asarray(lat), np.asarray(lon)
    hit = np.zeros(lat.shape, bool)
    for ring in rings:
        y0, x0 = ring[:-1, 0], ring[:-1, 1]
        y1, x1 = ring[1:, 0], ring[1:, 1]
        for a in range(0, len(lat), 20000):
            la, lo = lat[a:a + 20000, None], lon[a:a + 20000, None]
            cross = ((y0 > la) != (y1 > la)) & (lo < (x1 - x0) * (la - y0) / (y1 - y0 + 1e-15) + x0)
            hit[a:a + 20000] ^= (cross.sum(1) % 2).astype(bool)
    return hit


def simplify(ring: np.ndarray, tol: float = 0.0004) -> np.ndarray:
    """Douglas-Peucker simples (graus); contorno do município com poucas centenas de pontos.
    Anel fechado (1º ponto = último): divide no ponto mais distante do início, senão a reta de
    referência teria comprimento zero e o anel viraria 2 pontos."""
    if len(ring) < 4:
        return ring
    far = int(np.hypot(*(ring - ring[0]).T).argmax())
    keep = np.zeros(len(ring), bool); keep[[0, far, -1]] = True
    stack = [(0, far), (far, len(ring) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        p, q = ring[i], ring[j]
        seg = q - p; L = np.hypot(*seg) or 1e-12
        rel = ring[i + 1:j] - p
        d = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / L
        k = int(d.argmax())
        if d[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return ring[keep]


# ------------------------------------------------------------------ malha viária
def build_graph(car_ways, out: Path) -> dict:
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    use = defaultdict(int)
    for refs, *_ in car_ways:
        for r in refs:
            use[int(r)] += 1
        use[int(refs[0])] += 1; use[int(refs[-1])] += 1   # pontas sempre viram cruzamento
    nid: dict[int, int] = {}
    nlat, nlon = [], []

    def node(ref, la, lo):
        k = nid.get(ref)
        if k is None:
            k = nid[ref] = len(nlat); nlat.append(la); nlon.append(lo)
        return k

    eu, ev, et, ed, gptr, glat, glon = [], [], [], [], [0], [], []

    def add(u, v, t, d, la, lo):
        eu.append(u); ev.append(v); et.append(t); ed.append(d)
        glat.extend(la); glon.extend(lo); gptr.append(len(glat))

    for refs, lats, lons, speed, direction in car_ways:
        cut = [0] + [i for i in range(1, len(refs) - 1) if use[int(refs[i])] > 1] + [len(refs) - 1]
        seg_m = hav_m(lats[:-1], lons[:-1], lats[1:], lons[1:])
        for a, b in zip(cut[:-1], cut[1:]):
            u, v = node(int(refs[a]), lats[a], lons[a]), node(int(refs[b]), lats[b], lons[b])
            if u == v:
                continue
            d = float(seg_m[a:b].sum()); t = d / (speed / 3.6)
            la, lo = lats[a:b + 1], lons[a:b + 1]
            if direction >= 0:
                add(u, v, t, d, la, lo)
            if direction <= 0:
                add(v, u, t, d, la[::-1], lo[::-1])

    n = len(nlat)
    eu, ev, et, ed = map(np.asarray, (eu, ev, et, ed))
    # trechos paralelos entre os mesmos cruzamentos: fica o mais rápido
    order = np.lexsort((et, ev, eu))
    keep = np.ones(len(order), bool)
    same = (eu[order][1:] == eu[order][:-1]) & (ev[order][1:] == ev[order][:-1])
    keep[1:] = ~same
    sel = order[keep]
    gptr = np.asarray(gptr)
    g_idx = np.concatenate([np.arange(gptr[i], gptr[i + 1]) for i in sel])
    new_ptr = np.concatenate([[0], np.cumsum(gptr[sel + 1] - gptr[sel])])
    glat = np.asarray(glat)[g_idx]; glon = np.asarray(glon)[g_idx]
    eu, ev, et, ed = eu[sel], ev[sel], et[sel], ed[sel]

    m = csr_matrix((np.ones(len(eu)), (eu, ev)), shape=(n, n))
    _, lab = connected_components(m, directed=True, connection="strong")
    main = lab == np.bincount(lab).argmax()     # só se encaixa parada no maior trecho conectado da malha
    np.savez_compressed(
        out / "graph.npz",
        node_lat=np.asarray(nlat, np.float64), node_lon=np.asarray(nlon, np.float64), snap=main,
        edge_u=eu.astype(np.int32), edge_v=ev.astype(np.int32),
        edge_t=et.astype(np.float32), edge_d=ed.astype(np.float32),
        geom_ptr=new_ptr.astype(np.int64),
        geom_lat=np.rint(glat * 1e6).astype(np.int32), geom_lon=np.rint(glon * 1e6).astype(np.int32),
    )
    print(f"malha: {n} cruzamentos ({main.sum()} no trecho principal), {len(eu)} trechos")
    return {"nodes": int(n), "edges": int(len(eu))}


# ------------------------------------------------------------------ índice de endereços
def _clusters(ways):
    """Agrupa vias de mesmo nome que se tocam (mesma rua); nomes repetidos longe viram ruas distintas."""
    parent = list(range(len(ways)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i

    owner: dict[int, int] = {}
    for i, (_, refs, *_r) in enumerate(ways):
        for r in (int(refs[0]), int(refs[-1]), *map(int, refs[1:-1:3])):
            j = owner.setdefault(r, i)
            if j != i:
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(len(ways)):
        groups[find(i)].append(ways[i])
    return list(groups.values())


def build_geoindex(named, addrs, poa_rings, hoods, out: Path) -> dict:
    from scipy.spatial import cKDTree

    rings = [simplify(r) for r in poa_rings]
    entries, samples = [], []
    for key, ways in named.items():
        for grp in _clusters(ways):
            lat = np.concatenate([w[2] for w in grp]); lon = np.concatenate([w[3] for w in grp])
            length = float(sum(hav_m(w[2][:-1], w[3][:-1], w[2][1:], w[3][1:]).sum() for w in grp))
            pts = np.unique(np.round(np.c_[lat, lon], 6), axis=0)
            if len(pts) > 160:
                pts = pts[np.linspace(0, len(pts) - 1, 160).astype(int)]
            c = pts.mean(0)
            center = pts[np.argmin(((pts - c) ** 2).sum(1))]
            names = sorted({w[0] for w in grp}, key=len, reverse=True)
            samples.append(pts[np.linspace(0, len(pts) - 1, min(len(pts), 7)).astype(int)])
            entries.append({"n": names[0], "k": key, "c": core_key(names[0]), "len": round(length),
                            "ctr": [round(float(center[0]), 6), round(float(center[1]), 6)],
                            "pts": pts.round(6).tolist(), "a": []})
    # dentro de Porto Alegre = a maioria dos pontos da rua dentro do contorno oficial do município
    flat = np.concatenate(samples); owner = np.repeat(np.arange(len(samples)), [len(s) for s in samples])
    inside_poa = in_rings(rings, flat[:, 0], flat[:, 1])
    share = np.bincount(owner, weights=inside_poa, minlength=len(samples)) / np.bincount(owner, minlength=len(samples))
    for e, s in zip(entries, share):
        e["poa"] = bool(s >= 0.5)
    # cada endereço vai para a rua de mesmo nome mais próxima (até 400 m)
    by_key = defaultdict(list)
    for i, e in enumerate(entries):
        by_key[e["k"]].append(i)
    trees = {}
    placed = 0
    for street, hn, la, lo, _city in addrs:
        num = house_number(hn)
        k = full_key(street)
        if num is None or k not in by_key:
            continue
        cand = by_key[k]
        best, bd = None, 1e9
        for i in cand:
            if i not in trees:
                trees[i] = cKDTree(np.radians(entries[i]["pts"]))
            d, _ = trees[i].query(np.radians([la, lo]))
            if d < bd:
                best, bd = i, d
        if best is not None and bd * 6371000 < 400:
            entries[best]["a"].append([num, round(la, 6), round(lo, 6)])
            placed += 1
    for e in entries:
        e["a"].sort()
    bairros = [{"n": n, "k": full_key(n), "lat": round(la, 6), "lon": round(lo, 6)} for n, (la, lo) in sorted(hoods.items())]
    with gzip.open(out / "geoindex.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"streets": entries, "bairros": bairros,
                   "poa": [r.round(5).tolist() for r in rings]}, f, ensure_ascii=False, separators=(",", ":"))
    with_num = sum(1 for e in entries if e["poa"] and e["a"])
    print(f"endereços: {len(entries)} ruas ({sum(e['poa'] for e in entries)} em Porto Alegre, "
          f"{with_num} com números), {placed} números posicionados")
    return {"streets": len(entries), "addresses": placed}


# ------------------------------------------------------------------ fundo do mapa (Protomaps)
def build_basemap(out: Path, maxzoom: int) -> dict:
    """Recorta o mapa-múndi vetorial diário do Protomaps para a região, por requisições parciais (HTTP Range)."""
    import functools

    import httpx
    from pmtiles.reader import Reader
    from pmtiles.tile import zxy_to_tileid
    from pmtiles.writer import Writer

    builds = httpx.get("https://build-metadata.protomaps.dev/builds.json", timeout=60).json()
    key = builds[-1]["key"]
    url = f"https://build.protomaps.com/{key}"
    client = httpx.Client(timeout=120, follow_redirects=True)

    @functools.lru_cache(maxsize=4096)   # cabeçalho e diretórios se repetem a cada bloco
    def get_bytes(offset, length):
        for attempt in range(5):
            try:
                r = client.get(url, headers={"Range": f"bytes={offset}-{offset + length - 1}"})
                r.raise_for_status()
                return r.content
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)

    reader = Reader(get_bytes)
    header = reader.header()
    meta = reader.metadata()

    def tiles_for(z, box):
        la0, la1, lo0, lo1 = box
        n = 2 ** z
        x0 = int((lo0 + 180) / 360 * n); x1 = int((lo1 + 180) / 360 * n)
        def ty(la):
            r = math.radians(la)
            return int((1 - math.asinh(math.tan(r)) / math.pi) / 2 * n)
        y0, y1 = ty(la1), ty(la0)
        return [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

    want = []
    for z in range(0, maxzoom + 1):
        want += tiles_for(z, RMPA_BBOX if z <= 12 else POA_BBOX)
    t0 = time.time()
    with ThreadPoolExecutor(16) as pool:
        datas = list(pool.map(lambda zxy: (zxy, reader.get(*zxy)), want))
    datas = [(zxy, d) for zxy, d in datas if d]
    datas.sort(key=lambda it: zxy_to_tileid(*it[0]))
    with open(out / "basemap.pmtiles", "wb") as f:
        w = Writer(f)
        for (z, x, y), d in datas:
            w.write_tile(zxy_to_tileid(z, x, y), d)
        la0, la1, lo0, lo1 = RMPA_BBOX
        w.finalize(dict(header) | {
            "min_lon_e7": int(lo0 * 1e7), "min_lat_e7": int(la0 * 1e7),
            "max_lon_e7": int(lo1 * 1e7), "max_lat_e7": int(la1 * 1e7),
            "center_zoom": 12, "center_lon_e7": int(-51.18 * 1e7), "center_lat_e7": int(-30.05 * 1e7),
        }, meta)
    size = (out / "basemap.pmtiles").stat().st_size
    print(f"fundo do mapa: {len(datas)} blocos até o zoom {maxzoom}, {size / 1e6:.1f} MB em {time.time() - t0:.0f}s "
          f"(Protomaps {key})")
    return {"tiles": len(datas), "protomaps_build": key, "basemap_maxzoom": maxzoom}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--version", default=date.today().strftime("%Y.%m.%d"))
    ap.add_argument("--no-basemap", action="store_true")
    ap.add_argument("--basemap-maxzoom", type=int, default=15)
    ap.add_argument("--basemap-from", type=Path, help="pasta de um pacote anterior com basemap.pmtiles")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    car_ways, named, addrs, poa_rings, hoods = read_osm(a.pbf)
    info = {"format": 1, "version": a.version, "built": date.today().isoformat(),
            "source": "© colaboradores do OpenStreetMap (ODbL)", "region": "Porto Alegre e região metropolitana"}
    info |= build_graph(car_ways, a.out)
    del car_ways
    info |= build_geoindex(named, addrs, poa_rings, hoods, a.out)
    if a.basemap_from:      # reaproveita um fundo já recortado (o mapa-múndi muda pouco de um dia para outro)
        import shutil
        shutil.copy(a.basemap_from / "basemap.pmtiles", a.out / "basemap.pmtiles")
        old = json.loads((a.basemap_from / "info.json").read_text(encoding="utf-8"))
        info |= {k: old[k] for k in ("tiles", "protomaps_build", "basemap_maxzoom") if k in old}
    elif not a.no_basemap:
        info |= build_basemap(a.out, a.basemap_maxzoom)
    (a.out / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
