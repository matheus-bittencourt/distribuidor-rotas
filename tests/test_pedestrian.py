"""Zona do Centro: todas as entregas dentro dela vão para UM entregador a pé, com rota de pedestre."""
import time
from urllib.parse import parse_qs, urlparse

import numpy as np
from fastapi.testclient import TestClient

from app import main, pedestrian
from app.matrix import build_matrix, build_walk_matrix

client = TestClient(main.app)

INSIDE = [(-30.02959, -51.23102), (-30.0275, -51.2283), (-30.0300, -51.2250), (-30.0290, -51.2340)]  # Alfândega, Mercado, ...
OUTSIDE = [(-30.0262, -51.2062), (-30.0500, -51.1800), (-30.0450, -51.2200), (-30.0150, -51.1500)]


def test_zone_membership():
    pts = np.array(INSIDE + OUTSIDE)
    got = pedestrian.inside(pts)
    assert got[:4].all(), got
    assert not got[4:].any(), got


def test_default_start_is_inside_the_zone():
    lat, lon, _ = pedestrian.default_start()
    assert pedestrian.inside(np.array([[lat, lon]]))[0]


def test_walking_is_slower_than_driving():
    coords = np.array(INSIDE)
    t_walk, d_walk, _ = build_walk_matrix(coords)
    t_car, _, _ = build_matrix(coords)
    assert t_walk[0, 1] > t_car[0, 1] * 2
    assert d_walk[0, 1] > 0


def _job_with(points):
    rows = "".join(f"Rua Teste {i}, {i + 10};Pessoa {i};B{i}\n" for i in range(len(points)))
    csv = ("ENDEREÇO;NOME;COD_RASTREIO\n" + rows).encode()
    jid = client.post("/api/upload", files={"file": ("l.csv", csv, "text/csv")}).json()["job_id"]
    for _ in range(100):
        if client.get(f"/api/jobs/{jid}").json()["state"] == "revisao":
            break
        time.sleep(0.1)
    job = main._job(jid)
    for s, (la, lo) in zip(job.stops, points):   # posições escolhidas à mão (o geocodificador de teste é aleatório)
        s.lat, s.lon, s.status = la, lo, "ok"
    return jid


def _solve(jid, **extra):
    body = {"depot": {"address": ""}, "drivers": [{"label": "A"}, {"label": "B"}], "time_limit": 5, **extra}
    assert client.post(f"/api/jobs/{jid}/solve", json=body).status_code == 200
    for _ in range(200):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["state"] in ("pronto", "erro"):
            break
        time.sleep(0.2)
    assert j["state"] == "pronto", j
    return client.get(f"/api/jobs/{jid}/result").json()


def test_zone_deliveries_all_go_to_the_walker():
    jid = _job_with(INSIDE + OUTSIDE)
    res = _solve(jid)
    walkers = [d for d in res["drivers"] if d["mode"] == "pe"]
    assert len(walkers) == 1 and res["pedestrian"]["active"]
    w = walkers[0]
    assert w["label"] == pedestrian.LABEL and w["count"] == len(INSIDE)
    assert {s["code"] for s in w["stops"]} == {f"B{i}" for i in range(len(INSIDE))}
    motos = [d for d in res["drivers"] if d["mode"] == "moto"]
    assert len(motos) == 2 and sum(d["count"] for d in motos) == len(OUTSIDE)    # o a pé é um a mais
    assert not {s["code"] for d in motos for s in d["stops"]} & {s["code"] for s in w["stops"]}
    # sai e volta ao ponto dele, dentro da zona; links no modo "a pé"
    assert (w["start"]["lat"], w["start"]["lon"]) == (w["end"]["lat"], w["end"]["lon"])
    assert pedestrian.inside(np.array([[w["start"]["lat"], w["start"]["lon"]]]))[0]
    for link in w["links"]:
        assert parse_qs(urlparse(link["url"]).query)["travelmode"] == ["walking"]
    for d in motos:
        assert d["end"]["lat"] == res["depot"]["lat"]
        assert all(parse_qs(urlparse(l["url"]).query)["travelmode"] == ["driving"] for l in d["links"])
    assert res["pedestrian"]["polygon"]


def test_walker_can_be_turned_off():
    jid = _job_with(INSIDE + OUTSIDE)
    res = _solve(jid, pedestrian={"enabled": False})
    assert all(d["mode"] == "moto" for d in res["drivers"]) and not res["pedestrian"]["active"]
    assert sum(d["count"] for d in res["drivers"]) == len(INSIDE) + len(OUTSIDE)


def test_no_walker_without_deliveries_in_the_zone():
    res = _solve(_job_with(OUTSIDE))
    assert [d["mode"] for d in res["drivers"]] == ["moto", "moto"] and not res["pedestrian"]["active"]


def test_everything_inside_the_zone_leaves_motos_empty():
    res = _solve(_job_with(INSIDE))
    assert res["pedestrian"]["active"]
    assert [d["count"] for d in res["drivers"] if d["mode"] == "moto"] == [0, 0]
    assert sum(d["count"] for d in res["drivers"]) == len(INSIDE)


def test_custom_walker_start_is_used():
    jid = _job_with(INSIDE + OUTSIDE)
    res = _solve(jid, pedestrian={"enabled": True, "start": {"lat": -30.0275, "lon": -51.2283}})
    w = next(d for d in res["drivers"] if d["mode"] == "pe")
    assert (round(w["start"]["lat"], 4), round(w["start"]["lon"], 4)) == (-30.0275, -51.2283)
