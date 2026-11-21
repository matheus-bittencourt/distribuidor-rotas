"""Mede o ganho do ViaCEP na geocodificação (usa a rede: ViaCEP + Nominatim público, 1 req/s).

Uso:  python scripts/measure_viacep.py [N=120] [saida.csv]

Sorteia N consultas do geocache da amostra (a coordenada do cache é o centro do trecho da rua, usada como
referência), geocodifica cada uma SEM e COM o bairro do ViaCEP e compara:
  - achou / não achou, precisão (exato = veio com número da casa), cidade devolvida;
  - distância até o centro da rua de referência (mediana, p90 e quantas ficam a mais de 2 km).
Só o nome da rua sai da máquina. Nomes e códigos da amostra nem são lidos.
"""
import csv
import math
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.geocode import Nominatim, in_region, is_poa  # noqa: E402
from app.viacep import ViaCep, split_query  # noqa: E402

CACHE = Path("amostras/porto_alegre_1400.geocache.csv")


def km(a, b):
    p = math.pi / 180
    h = (math.sin((b[0] - a[0]) * p / 2) ** 2
         + math.cos(a[0] * p) * math.cos(b[0] * p) * math.sin((b[1] - a[1]) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def geo(nom, q):
    try:
        g = nom.geocode(q)
    except Exception as exc:
        return ("erro", type(exc).__name__)
    if not g:
        return None
    ok = is_poa(g.city) and in_region(g.lat, g.lon)
    return (g, ok)


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "amostras/viacep_medicao.csv")
    rows = list(csv.DictReader(open(CACHE, encoding="utf-8"), delimiter=";"))
    random.Random(7).shuffle(rows)
    rows = rows[:n]
    nom, via = Nominatim(), ViaCep()
    res = []
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        q, ref = r["query"], (float(r["lat"]), float(r["lon"]))
        better = via.enrich(q)
        a = geo(nom, q)
        b = geo(nom, better) if better != q else a      # sem bairro novo, a consulta é a mesma
        if better != q and b is None:                    # mesmo comportamento do app: volta à original
            b = a
        res.append((q, better, ref, a, b))
        if i % 10 == 0:
            print(f"{i}/{n} ({time.time() - t0:.0f}s) viacep_calls={via.calls}", flush=True)

    def ok(x):
        return x is not None and x[0] != "erro" and x[1]

    def dist(x, ref):
        return km((x[0].lat, x[0].lon), ref) if ok(x) else None

    enriched = [x for x in res if x[1] != x[0]]
    n_err = sum(1 for x in res if x[3] and x[3][0] == "erro")
    print(f"\n== ViaCEP: {len(res)} ruas consultadas, {len(enriched)} ganharam bairro ({pct(len(enriched), len(res))})")
    streets = [split_query(x[0])[0].lower() for x in res]
    notfound = [x[0] for x in res if x[1] == x[0] and not via.search(split_query(x[0])[0])]
    print(f"   rua não encontrada no ViaCEP: {len(notfound)} ({pct(len(notfound), len(res))})  ex.: {notfound[:3]}")
    print(f"   consultas reais ao ViaCEP nesta rodada: {via.calls} (as demais vieram do cache em disco)")

    for label, idx in (("TODAS as consultas", range(len(res))), ("só as que ganharam bairro", [i for i, x in enumerate(res) if x[1] != x[0]])):
        idx = list(idx)
        if not idx:
            continue
        print(f"\n== {label} (n={len(idx)})")
        for name, k in (("sem ViaCEP", 3), ("com ViaCEP", 4)):
            xs = [res[i][k] for i in idx]
            found = [x for x in xs if ok(x)]
            exact = [x for x in found if x[0].precision == "exato"]
            ds = sorted(dist(res[i][k], res[i][2]) for i in idx if ok(res[i][k]))
            med = statistics.median(ds) if ds else float("nan")
            p90 = ds[int(0.9 * (len(ds) - 1))] if ds else float("nan")
            far = sum(1 for d in ds if d > 2)
            print(f"  {name:11s}: achou {len(found)}/{len(idx)} ({pct(len(found), len(idx))}) | exato {len(exact)} "
                  f"({pct(len(exact), len(idx))}) | dist. ao centro da rua: mediana {med:.2f} km, p90 {p90:.2f} km, >2 km: {far}")
        changed = [i for i in idx if ok(res[i][3]) and ok(res[i][4])
                   and km((res[i][3][0].lat, res[i][3][0].lon), (res[i][4][0].lat, res[i][4][0].lon)) > 0.05]
        better = sum(1 for i in changed if dist(res[i][4], res[i][2]) < dist(res[i][3], res[i][2]) - 0.05)
        worse = sum(1 for i in changed if dist(res[i][4], res[i][2]) > dist(res[i][3], res[i][2]) + 0.05)
        gained = sum(1 for i in idx if not ok(res[i][3]) and ok(res[i][4]))
        lost = sum(1 for i in idx if ok(res[i][3]) and not ok(res[i][4]))
        print(f"  mudou de lugar (>50 m): {len(changed)} -> mais perto da rua de referência: {better}, mais longe: {worse}")
        print(f"  passou a achar: {gained} | deixou de achar: {lost}")
    if n_err:
        print(f"\n(aviso) {n_err} consultas ao Nominatim falharam sem bairro; resultados parciais.")

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["query", "com_bairro", "ref_lat", "ref_lon", "sem_lat", "sem_lon", "sem_prec", "com_lat", "com_lon", "com_prec"])
        for q, bq, ref, a, b in res:
            cells = lambda x: [round(x[0].lat, 6), round(x[0].lon, 6), x[0].precision] if ok(x) else ["", "", ""]
            w.writerow([q, bq, *ref, *cells(a), *cells(b)])
    print(f"\nDetalhes em {out}")


if __name__ == "__main__":
    main()
