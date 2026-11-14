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
