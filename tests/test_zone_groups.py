"""Zonas desenhadas: cada uma vira um grupo de entregadores. A zona a pé do Centro vem sempre primeiro."""
import time
from urllib.parse import parse_qs, urlparse

import numpy as np
from fastapi.testclient import TestClient

from app import main, zonegroups
from test_pedestrian import INSIDE, OUTSIDE, _job_with

client = TestClient(main.app)

# retângulos [lat, lon]: LESTE pega OUTSIDE[0] e OUTSIDE[1]; NORTE pega OUTSIDE[3]; ambos fora da zona a pé
LESTE = [[-30.06, -51.21], [-30.06, -51.17], [-30.02, -51.17], [-30.02, -51.21]]
NORTE = [[-30.02, -51.17], [-30.02, -51.13], [-30.01, -51.13], [-30.01, -51.17]]
SOBREPOSTA = [[-30.06, -51.21], [-30.06, -51.19], [-30.02, -51.19], [-30.02, -51.21]]   # cobre só OUTSIDE[0]
DRIVERS = [{"label": "A"}, {"label": "B"}, {"label": "C"}]


def _solve(jid, zones, drivers=DRIVERS, **extra):
    body = {"depot": {"address": ""}, "drivers": drivers, "time_limit": 5, "zones": zones, **extra}
    r = client.post(f"/api/jobs/{jid}/solve", json=body)
    if r.status_code != 200:
        return r
    for _ in range(200):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["state"] in ("pronto", "erro"):
            break
        time.sleep(0.2)
    assert j["state"] == "pronto", j
    return client.get(f"/api/jobs/{jid}/result").json()


def _codes(driver):
    return {x["code"] for s in driver["stops"] for x in s["deliveries"]}


def test_zona_de_moto_so_com_o_grupo_dela():
    jid = _job_with(OUTSIDE)    # B0..B3: B0 e B1 no LESTE
    res = _solve(jid, [{"name": "Leste", "polygon": LESTE, "drivers": [1]}])
    a, b, c = res["drivers"][:3]
    assert _codes(b) == {"B0", "B1"} and b["group"] == "Leste" and b["mode"] == "moto"
    assert _codes(a) | _codes(c) == {"B2", "B3"} and _codes(a).isdisjoint(_codes(b)) and not a["group"]
    z = res["zones"][0]
    assert (z["name"], z["profile"], z["drivers"], z["deliveries"]) == ("Leste", "moto", [1], 2)
    assert z["polygon"] and not res["zone_warnings"]
    assert all(d["end"]["lat"] == res["depot"]["lat"] for d in (a, b, c))      # moto termina no ponto padrão


def test_dois_entregadores_na_mesma_zona_dividem_so_ela():
    pts = OUTSIDE[:2] + [(-30.0300, -51.1900), (-30.0400, -51.1800), (-30.0500, -51.1750)]   # 5 pontos no LESTE
    jid = _job_with(pts + [OUTSIDE[3]])
    res = _solve(jid, [{"name": "Leste", "polygon": LESTE, "drivers": [0, 1]}])
    a, b, c = res["drivers"][:3]
    assert a["count"] + b["count"] == 5 and a["count"] > 0 and b["count"] > 0
    assert a["group"] == b["group"] == "Leste" and _codes(c) == {"B5"}


def test_zona_a_pe_usa_rota_de_pedestre_e_volta_ao_ponto_dela():
    jid = _job_with(OUTSIDE)
    res = _solve(jid, [{"name": "Leste a pé", "polygon": LESTE, "profile": "pe", "drivers": [1],
                        "start": {"lat": -30.0300, "lon": -51.1900}}])
    b = res["drivers"][1]
    assert b["mode"] == "pe" and _codes(b) == {"B0", "B1"}
    assert (b["start"]["lat"], b["start"]["lon"]) == (b["end"]["lat"], b["end"]["lon"]) == (-30.03, -51.19)
    for link in b["links"]:
        assert parse_qs(urlparse(link["url"]).query)["travelmode"] == ["walking"]
    assert res["drivers"][0]["mode"] == "moto"


def test_zona_a_pe_sem_ponto_sai_da_parada_mais_central():
    res = _solve(_job_with(OUTSIDE), [{"name": "Leste a pé", "polygon": LESTE, "profile": "pe", "drivers": [1]}])
    b = res["drivers"][1]
    stops = {(s["lat"], s["lon"]) for s in b["stops"]}
    assert (b["start"]["lat"], b["start"]["lon"]) in stops


def test_zona_a_pe_do_centro_tem_precedencia_sobre_zona_desenhada():
    jid = _job_with(INSIDE + OUTSIDE)
    cobre_o_centro = [[-30.04, -51.25], [-30.04, -51.215], [-30.02, -51.215], [-30.02, -51.25]]
    res = _solve(jid, [{"name": "Sobre o Centro", "polygon": cobre_o_centro, "drivers": [1]}])
    walker = next(d for d in res["drivers"] if d["label"] == "A pé (Centro)")
    assert _codes(walker) == {f"B{i}" for i in range(len(INSIDE))}           # tudo do Centro fica com o a pé
    assert any("zona a pé do Centro" in w for w in res["zone_warnings"])
    assert res["zones"][0]["deliveries"] == 0


def test_parada_em_duas_zonas_fica_com_a_primeira_da_lista():
    jid = _job_with(OUTSIDE)
    res = _solve(jid, [{"name": "Primeira", "polygon": SOBREPOSTA, "drivers": [0]},
                       {"name": "Leste", "polygon": LESTE, "drivers": [1]}])
    assert _codes(res["drivers"][0]) == {"B0"} and _codes(res["drivers"][1]) == {"B1"}
    assert any("também estão em outra zona" in w for w in res["zone_warnings"])


def test_borda_da_zona_com_faixa():
    jid = _job_with([(-30.0300, -51.2105)])   # ~50 m a oeste do LESTE
    sem = _solve(jid, [{"name": "Leste", "polygon": LESTE, "drivers": [1]}])
    assert sem["drivers"][1]["count"] == 0
    jid = _job_with([(-30.0300, -51.2105)])
    com = _solve(jid, [{"name": "Leste", "polygon": LESTE, "drivers": [1], "edge_m": 120}])
    assert com["drivers"][1]["count"] == 1
    assert com["zones"][0]["near_border"] == 1


def test_validacoes():
    jid = _job_with(OUTSIDE)
    z = {"name": "Leste", "polygon": LESTE}
    assert _solve(jid, [{**z, "drivers": []}]).status_code == 400                       # sem entregador
    assert _solve(jid, [{**z, "drivers": [7]}]).status_code == 400                      # entregador inexistente
    assert _solve(jid, [{**z, "drivers": [1]}, {**z, "name": "Outra", "drivers": [1]}]).status_code == 400   # repetido
    assert _solve(jid, [{"name": "x", "polygon": LESTE[:2], "drivers": [0]}]).status_code == 422             # < 3 pontos


def test_sem_entregador_livre_para_o_resto_da_erro_claro():
    jid = _job_with(OUTSIDE)
    body = {"depot": {"address": ""}, "drivers": [{"label": "A"}], "time_limit": 5,
            "zones": [{"name": "Leste", "polygon": LESTE, "drivers": [0]}]}
    client.post(f"/api/jobs/{jid}/solve", json=body)
    for _ in range(100):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["state"] in ("pronto", "erro"):
            break
        time.sleep(0.1)
    assert j["state"] == "erro" and "entregador livre" in j["error"]


def test_todas_as_entregas_continuam_roteirizadas_uma_vez():
    jid = _job_with(INSIDE + OUTSIDE)
    res = _solve(jid, [{"name": "Leste", "polygon": LESTE, "drivers": [1]},
                       {"name": "Norte a pé", "polygon": NORTE, "profile": "pe", "drivers": [2]}])
    every = [c for d in res["drivers"] for c in _codes(d)]
    assert sorted(every) == sorted(f"B{i}" for i in range(len(INSIDE) + len(OUTSIDE)))
    assert res["deliveries"] == len(every)


def test_assign_unitario():
    xy = np.array([[-30.03, -51.19], [-30.015, -51.15], [-30.0296, -51.231]])
    z1 = zonegroups.ZoneSpec("L", np.array(LESTE), drivers=[0])
    z2 = zonegroups.ZoneSpec("N", np.array(NORTE), drivers=[1])
    labels, warns = zonegroups.assign(xy, np.array([False, False, True]), [z1, z2])
    assert labels.tolist() == [0, 1, zonegroups.BUILTIN] and not warns


# ---- zonas salvas no servidor (data/zonas.json): sobrevivem a fechar o app e a mudar de porta/navegador
def _saved(**kw):
    return {"name": "Centro-sul", "profile": "moto", "labels": ["Ana", "Beto"], "start": "", "edge": 0,
            "poly": [[-30.06, -51.21], [-30.05, -51.15], [-30.02, -51.17], [-30.03, -51.2], [-30.045, -51.19]], **kw}


def test_zonas_salvas_voltam_iguais_e_o_poligono_nao_vira_retangulo():
    assert client.get("/api/zonas").json() == {"zones": []}
    z = _saved()
    assert client.put("/api/zonas", json={"zones": [z, _saved(name="A pé", profile="pe", start="Praça X", edge=40)]}).json() == {"saved": 2}
    got = client.get("/api/zonas").json()["zones"]
    assert [g["name"] for g in got] == ["Centro-sul", "A pé"]
    assert got[0]["poly"] == z["poly"] and len(got[0]["poly"]) == 5          # os 5 vértices, na ordem
    assert (got[1]["profile"], got[1]["start"], got[1]["edge"]) == ("pe", "Praça X", 40)
    assert got[0]["labels"] == ["Ana", "Beto"]


def test_zonas_salvas_validacao():
    assert client.put("/api/zonas", json={"zones": [_saved(poly=[[-30, -51], [-30, -50]])]}).status_code == 422   # < 3 pontos
    assert client.put("/api/zonas", json={"zones": [_saved(profile="bike")]}).status_code == 422
    assert client.put("/api/zonas", json={"zones": [_saved()] * 51}).status_code == 422
    assert client.get("/api/zonas").json() == {"zones": []}                  # nada foi gravado pelos pedidos inválidos


def test_arquivo_de_zonas_corrompido_nao_derruba_o_app():
    from app import zonestore

    zonestore.PATH.write_text("{isso nao e json", encoding="utf-8")
    assert client.get("/api/zonas").json() == {"zones": []}
    assert client.put("/api/zonas", json={"zones": [_saved()]}).status_code == 200   # e a próxima gravação conserta
    assert len(client.get("/api/zonas").json()["zones"]) == 1


def test_poligono_irregular_decide_a_zona_e_nao_a_caixa_dele():
    """Um L: o ponto no vão do L está dentro da caixa do polígono, mas fora dele, e não pode entrar."""
    L_ = np.array([[-30.06, -51.21], [-30.06, -51.15], [-30.045, -51.15], [-30.045, -51.195], [-30.02, -51.195], [-30.02, -51.21]])
    xy = np.array([[-30.05, -51.20],     # braço de baixo: dentro
                   [-30.03, -51.205],    # braço da esquerda: dentro
                   [-30.03, -51.16]])    # no vão do L: fora, apesar de estar na caixa
    z = zonegroups.ZoneSpec("L", L_, drivers=[0])
    labels, _ = zonegroups.assign(xy, np.zeros(3, dtype=bool), [z])
    assert labels.tolist() == [0, 0, zonegroups.FREE]
