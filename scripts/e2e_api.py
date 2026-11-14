"""Teste ponta a ponta contra um servidor local já rodando (GEOCODER=fake para não usar rede).

Uso:  python scripts/e2e_api.py amostras/amostra_colunas.xlsx [n_entregadores]
Confere: nenhum CPF/valor/telefone aparece em nenhuma resposta, todas as paradas são roteirizadas
uma única vez e os links do Maps respeitam o limite de pontos.
"""
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = "http://127.0.0.1:8000"
SENSITIVE = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|R\$|\(\d{2}\)\s?9?\d{4}-\d{4}")


def call(method, path, body=None, raw=None, ctype=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": ctype or "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.read().decode("utf-8")


def upload(path: Path) -> str:
    boundary = "----e2e"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return json.loads(call("POST", "/api/upload", raw=body, ctype=f"multipart/form-data; boundary={boundary}"))["job_id"]


def main():
    path = Path(sys.argv[1])
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    t0 = time.time()
    job = upload(path)
    while True:
        j = json.loads(call("GET", f"/api/jobs/{job}"))
        if j["state"] in ("revisao", "erro"):
            break
        time.sleep(0.5)
    assert j["state"] == "revisao", j
    print(f"ingestão {time.time() - t0:.1f}s | método={j['report']['method']} | contagem={j['counts']} | "
          f"mascarado={j['report']['masked']} | colunas descartadas={j['report']['dropped_columns']}")
    everything = [json.dumps(j), call("GET", f"/api/jobs/{job}/stops")]

    r = random.Random(7)
    # todos saem do ponto padrão (o mesmo da chegada); o último entregador tem "casa" própria
    drivers = [{"label": f"Entregador {i + 1}"} for i in range(k)]
    drivers[-1]["start"] = {"lat": r.uniform(-30.14, -29.95), "lon": r.uniform(-51.26, -51.08)}
    call("POST", f"/api/jobs/{job}/solve", {"depot": {"address": "Av. Mostardeiros, 322, Moinhos de Vento, Porto Alegre, RS"},
                                            "drivers": drivers, "balance": 0.7, "zone_weight": 0.5})
    t1 = time.time()
    while True:
        j = json.loads(call("GET", f"/api/jobs/{job}"))
        if j["state"] in ("pronto", "erro"):
            break
        time.sleep(1)
    assert j["state"] == "pronto", j
    res = json.loads(call("GET", f"/api/jobs/{job}/result"))
    csv_text = call("GET", f"/api/jobs/{job}/export.csv")
    everything += [json.dumps(res), csv_text]
    print(f"cálculo {time.time() - t1:.1f}s | total={res['total_min'] / 60:.1f}h | tempos por {res['matrix']}")
    if res["matrix"] == "osrm":  # com OSRM, cada rota com paradas traz o trajeto por ruas para o mapa
        com = [d for d in res["drivers"] if d["stops"]]
        sem = [d["label"] for d in com if not d.get("path")]
        print(f"trajeto por ruas: {len(com) - len(sem)}/{len(com)} rotas | {sum(len(d['path'] or '') for d in com) // 1024} KB")
        assert not sem, sem

    # entregas no mesmo endereço viram uma parada só: confere pelas entregas, não pelas paradas
    ids = [x["id"] for d in res["drivers"] for s in d["stops"] for x in s["deliveries"]]
    ok = j["counts"].get("ok", 0)
    assert len(ids) == len(set(ids)) == ok, (len(ids), len(set(ids)), ok)
    for d in res["drivers"]:
        for link in d["links"]:
            q = parse_qs(urlparse(link["url"]).query)
            wps = q["waypoints"][0].split("|") if "waypoints" in q else []
            assert len(wps) <= 9
        assert d["links"][-1]["ends_at_depot"]
    counts = [d["count"] for d in res["drivers"]]
    print(f"paradas por entregador: min={min(counts)} max={max(counts)} média={sum(counts) / len(counts):.1f}")
    print(f"pureza por zona: {res['zone_purity']:.0%} | zonas por entregador: {[len(d['zones']) for d in res['drivers']]}")
    assert all(s["code"] for d in res["drivers"] for s in d["stops"]) or "livre" in str(path)
    print("tempo por rota (h):", [round(d["total_min"] / 60, 1) for d in res["drivers"]])
    print(f"não roteirizadas (revisar): {len(res['unrouted'])} -> ex.: {[u['name'] + ' / ' + u['reason'] for u in res['unrouted'][:2]]}")

    leaked = [m.group(0) for blob in everything for m in SENSITIVE.finditer(blob)]
    assert not leaked, f"dado sensível vazou: {leaked[:3]}"
    print("OK: nenhum CPF / valor / telefone em nenhuma resposta da API.")
    call("DELETE", f"/api/jobs/{job}")
    try:
        call("GET", f"/api/jobs/{job}")
        raise SystemExit("job deveria ter sido apagado")
    except urllib.error.HTTPError as e:
        assert e.code == 404
    print("OK: job apagado da memória (404 depois do DELETE).")


if __name__ == "__main__":
    main()
