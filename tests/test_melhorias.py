"""Melhorias do dia: trânsito esperado (fator no tempo de deslocamento das motos)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_pedestrian import OUTSIDE, _job_with  # noqa: E402
from test_zone_groups import _solve  # noqa: E402


def test_transito_aumenta_so_o_tempo_de_deslocamento():
    jid = _job_with(OUTSIDE)
    base = _solve(jid, [])
    slow = _solve(jid, [], traffic=1.4)
    assert base["traffic"] == 1.0 and slow["traffic"] == 1.4
    b, s = base["drivers"], slow["drivers"]
    assert sum(d["travel_min"] for d in s) > sum(d["travel_min"] for d in b) * 1.2     # o deslocamento cresce
    assert sum(d["km"] for d in s) == sum(d["km"] for d in b)                          # os km não mudam
    assert sum(d["deliveries"] for d in s) == sum(d["deliveries"] for d in b)          # nem as paradas


def test_transito_fora_da_faixa_e_recusado():
    from test_zone_groups import client

    jid = _job_with(OUTSIDE)
    for bad in (0.5, 3):
        r = client.post(f"/api/jobs/{jid}/solve", json={"depot": {"address": ""}, "drivers": [{"label": "A"}], "traffic": bad})
        assert r.status_code == 422


# ---- mover parada entre entregadores (antes de enviar)
from test_pedestrian import INSIDE  # noqa: E402
from test_zone_groups import LESTE, client  # noqa: E402

PONTOS = OUTSIDE + [(-30.0100, -51.1500), (-30.0600, -51.1900), (-30.0700, -51.2000), (-30.0350, -51.1600)]


def _ids(res):
    return [x["id"] for d in res["drivers"] for s in d["stops"] for x in s["deliveries"]]


def test_mover_parada_previa_nao_muda_nada_e_aplicar_troca_so_as_duas_rotas():
    jid = _job_with(PONTOS)
    res = _solve(jid, [], drivers=[{"label": "A"}, {"label": "B"}, {"label": "C"}])
    a, b, c = res["drivers"][:3]
    stop = a["stops"][0]["deliveries"][0]["id"]
    pv = client.post(f"/api/jobs/{jid}/move", json={"stop": stop, "to": 1, "preview": True}).json()
    assert pv["preview"] and (pv["from"], pv["to"]) == (0, 1)
    assert pv["after"]["from"]["deliveries"] == pv["before"]["from"]["deliveries"] - 1
    assert pv["after"]["to"]["deliveries"] == pv["before"]["to"]["deliveries"] + 1
    assert client.get(f"/api/jobs/{jid}/result").json()["drivers"][0]["deliveries"] == a["deliveries"]   # prévia não aplica

    done = client.post(f"/api/jobs/{jid}/move", json={"stop": stop, "to": 1, "preview": False}).json()
    assert not done["preview"]
    new = client.get(f"/api/jobs/{jid}/result").json()
    na, nb, nc = new["drivers"][:3]
    assert stop not in [x["id"] for s in na["stops"] for x in s["deliveries"]]
    assert stop in [x["id"] for s in nb["stops"] for x in s["deliveries"]]
    assert sorted(_ids(new)) == sorted(_ids(res))                      # todas as entregas, uma vez cada
    assert (nc["deliveries"], nc["total_min"]) == (c["deliveries"], c["total_min"])   # a terceira rota não mexeu
    assert na["deliveries"] == a["deliveries"] - 1 and nb["deliveries"] == b["deliveries"] + 1
    assert new["manual_moves"] == 1
    assert new["total_min"] == res["total_min"] + (na["total_min"] + nb["total_min"]) - (a["total_min"] + b["total_min"])
    # as ordens das duas rotas seguem 1..n e o ETA cresce
    for d in (na, nb):
        assert [s["order"] for s in d["stops"]] == list(range(1, len(d["stops"]) + 1))
        assert [s["eta_min"] for s in d["stops"]] == sorted(s["eta_min"] for s in d["stops"])


def test_mover_parada_da_zona_atualiza_a_contagem_da_zona():
    jid = _job_with(OUTSIDE + [(-30.0300, -51.2000)])
    res = _solve(jid, [{"name": "Leste", "polygon": LESTE, "drivers": [1]}], drivers=[{"label": "A"}, {"label": "B"}, {"label": "C"}])
    z0 = res["zones"][0]["deliveries"]
    assert z0 >= 1
    stop = res["drivers"][1]["stops"][0]["deliveries"][0]["id"]
    client.post(f"/api/jobs/{jid}/move", json={"stop": stop, "to": 0, "preview": False})
    assert client.get(f"/api/jobs/{jid}/result").json()["zones"][0]["deliveries"] == z0 - 1


def test_mover_parada_erros():
    jid = _job_with(PONTOS)
    assert client.post(f"/api/jobs/{jid}/move", json={"stop": 0, "to": 1}).status_code == 409        # antes de calcular
    res = _solve(jid, [], drivers=[{"label": "A"}, {"label": "B"}])
    stop = res["drivers"][0]["stops"][0]["deliveries"][0]["id"]
    assert client.post(f"/api/jobs/{jid}/move", json={"stop": stop, "to": 0}).status_code == 400    # já está nela
    assert client.post(f"/api/jobs/{jid}/move", json={"stop": 9999, "to": 1}).status_code == 404    # entrega inexistente
    assert client.post(f"/api/jobs/{jid}/move", json={"stop": stop, "to": 9}).status_code == 404     # entregador inexistente


def test_nao_move_de_ou_para_a_rota_a_pe():
    jid = _job_with(INSIDE + PONTOS)
    res = _solve(jid, [], drivers=[{"label": "A"}, {"label": "B"}])
    walker = next(d for d in res["drivers"] if d["mode"] == "pe")
    moto_stop = res["drivers"][0]["stops"][0]["deliveries"][0]["id"]
    walk_stop = walker["stops"][0]["deliveries"][0]["id"]
    assert client.post(f"/api/jobs/{jid}/move", json={"stop": moto_stop, "to": walker["index"]}).status_code == 400
    assert client.post(f"/api/jobs/{jid}/move", json={"stop": walk_stop, "to": 0}).status_code == 400
