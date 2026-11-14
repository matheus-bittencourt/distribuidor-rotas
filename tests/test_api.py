import time

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
CSV = ("ENDEREÇO;NOME;COD_RASTREIO\nRua dos Andradas, 100;Ana;B1\nRua Inexistente do Teste, 5;Bia;B2\n").encode()


def _job():
    r = client.post("/api/upload", files={"file": ("l.csv", CSV, "text/csv")})
    jid = r.json()["job_id"]
    for _ in range(50):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["state"] in ("revisao", "erro"):
            return jid, j
        time.sleep(0.1)
    raise AssertionError("ingestão não terminou")


def test_discard_and_restore_roundtrip():
    jid, j = _job()
    assert j["counts"] == {"ok": 1, "revisar": 1}
    sid = j["review"][0]["id"]
    assert client.patch(f"/api/jobs/{jid}/stops/{sid}", json={"discard": True}).json()["status"] == "descartado"
    assert client.get(f"/api/jobs/{jid}").json()["review"] == []
    back = client.patch(f"/api/jobs/{jid}/stops/{sid}", json={"restore": True}).json()
    assert back["status"] == "revisar"
    assert [s["id"] for s in client.get(f"/api/jobs/{jid}").json()["review"]] == [sid]


def test_balance_by_is_validated_and_km_reaches_result():
    jid, _ = _job()
    bad = client.post(f"/api/jobs/{jid}/solve", json={"depot": {"address": ""}, "drivers": [{"label": "A"}], "balance_by": "peso"})
    assert bad.status_code == 422
    ok = client.post(f"/api/jobs/{jid}/solve", json={"depot": {"address": ""}, "drivers": [{"label": "A"}, {"label": "B"}],
                                                     "balance_by": "km", "time_limit": 5})
    assert ok.status_code == 200
    for _ in range(100):
        if client.get(f"/api/jobs/{jid}").json()["state"] in ("pronto", "erro"):
            break
        time.sleep(0.2)
    res = client.get(f"/api/jobs/{jid}/result").json()
    assert res["balance_by"] == "km" and all("km" in d for d in res["drivers"])
    assert "distancia_trecho_km" in client.get(f"/api/jobs/{jid}/export.csv").text


def test_same_address_deliveries_become_one_stop():
    csv = ("ENDEREÇO;NOME;COD_RASTREIO\n"
           "Rua dos Andradas, 100, Bloco A, apto 11;Ana;B1\n"
           "Rua dos Andradas, 100, Bloco B, apto 22;Bia;B2\n"
           "Rua dos Andradas, 100, apto 33;Cris;B3\n"
           "Avenida Ipiranga, 5000;Davi;B4\n").encode()
    jid = client.post("/api/upload", files={"file": ("l.csv", csv, "text/csv")}).json()["job_id"]
    for _ in range(50):
        if client.get(f"/api/jobs/{jid}").json()["state"] == "revisao":
            break
        time.sleep(0.1)
    client.post(f"/api/jobs/{jid}/solve", json={"depot": {"address": ""}, "drivers": [{"label": "A"}], "time_limit": 5})
    for _ in range(100):
        if client.get(f"/api/jobs/{jid}").json()["state"] in ("pronto", "erro"):
            break
        time.sleep(0.2)
    res = client.get(f"/api/jobs/{jid}/result").json()
    assert (res["deliveries"], res["visits"]) == (4, 2)
    stops = res["drivers"][0]["stops"]
    assert sorted(s["n_deliveries"] for s in stops) == [1, 3]
    multi = next(s for s in stops if s["n_deliveries"] == 3)
    assert [x["code"] for x in multi["deliveries"]] and {x["name"] for x in multi["deliveries"]} == {"Ana", "Bia", "Cris"}
    assert len(res["drivers"][0]["links"][0]["url"].split("waypoints=")) <= 2  # sem ponto repetido nos links
    lines = [l for l in client.get(f"/api/jobs/{jid}/export.csv").text.splitlines() if l and not l.startswith("﻿entregador")]
    assert len(lines) == 4  # uma linha por entrega


def test_ui_files_are_revalidated_not_cached():
    for path in ("/", "/static/app.js", "/static/style.css"):
        assert client.get(path).headers["cache-control"] == "no-cache"


def _solve_total(jid, **extra):
    body = {"depot": {"address": ""}, "drivers": [{"label": "A"}], "time_limit": 5, "service_seconds": 120, **extra}
    client.post(f"/api/jobs/{jid}/solve", json=body)
    for _ in range(100):
        if client.get(f"/api/jobs/{jid}").json()["state"] in ("pronto", "erro"):
            break
        time.sleep(0.2)
    return client.get(f"/api/jobs/{jid}/result").json()


def test_tolerance_is_added_per_delivery():
    csv = ("ENDEREÇO;NOME;COD_RASTREIO\n"
           "Rua dos Andradas, 100, apto 1;Ana;T1\n"
           "Rua dos Andradas, 100, apto 2;Bia;T2\n"      # mesma parada: 2 entregas
           "Avenida Ipiranga, 5000;Davi;T3\n").encode()   # outra parada: 1 entrega
    jid = client.post("/api/upload", files={"file": ("l.csv", csv, "text/csv")}).json()["job_id"]
    for _ in range(50):
        if client.get(f"/api/jobs/{jid}").json()["state"] == "revisao":
            break
        time.sleep(0.1)
    base = _solve_total(jid, tolerance_seconds=0)
    ten = _solve_total(jid, tolerance_seconds=600)
    assert (base["tolerance_seconds"], ten["tolerance_seconds"]) == (0, 600)
    # 3 entregas x 10 min a mais na rota (a ordem das paradas não muda com 2 pontos)
    assert ten["drivers"][0]["total_min"] - base["drivers"][0]["total_min"] == 30
    # o padrão do servidor é 5 min por entrega
    assert client.get("/api/config").json()["delivery_tolerance_seconds"] == 300
    default = _solve_total(jid)
    assert default["tolerance_seconds"] == 300 and default["drivers"][0]["total_min"] - base["drivers"][0]["total_min"] == 15
