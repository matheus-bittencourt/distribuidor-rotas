"""Vários arquivos num envio só: viram uma lista, com origem de cada entrega, repetidas fora e erro isolado."""
import io
import time

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app import extract as ex
from app.main import app

from test_intimacoes import _intimacao

client = TestClient(app)


def _csv(*rows):
    return ("ENDEREÇO;NOME;COD_RASTREIO\n" + "".join(f"{r}\n" for r in rows)).encode()


def _send(*files):
    r = client.post("/api/upload", files=[("file", f) for f in files])
    assert r.status_code == 200, r.text
    return r.json()["job_id"]


def _wait(jid, states=("revisao", "mapear", "erro")):
    for _ in range(100):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["state"] in states:
            return j
        time.sleep(0.1)
    raise AssertionError(j)


def test_dois_csv_viram_uma_lista():
    jid = _send(("a.csv", _csv("Rua dos Andradas, 100;Ana;A1", "Av. Ipiranga, 200;Beto;A2"), "text/csv"),
                ("b.csv", _csv("Rua Voluntários da Pátria, 300;Cida;B1"), "text/csv"))
    j = _wait(jid)
    assert j["state"] == "revisao" and j["total"] == 3
    stops = client.get(f"/api/jobs/{jid}/stops").json()
    assert [s["id"] for s in stops] == [0, 1, 2]                      # ids seguidos, de todos os arquivos
    assert [s["file"] for s in stops] == ["a.csv", "a.csv", "b.csv"]
    assert [(f["name"], f["stops"]) for f in j["files"]] == [("a.csv", 2), ("b.csv", 1)]
    assert j["report"]["rows_read"] == 3


def test_codigo_repetido_entre_arquivos_fica_so_uma_vez():
    jid = _send(("a.csv", _csv("Rua dos Andradas, 100;Ana;X1", "Av. Ipiranga, 200;Beto;X2"), "text/csv"),
                ("b.csv", _csv("Rua dos Andradas, 100;Ana;X1", "Av. Borges de Medeiros, 5;Cida;X3"), "text/csv"))
    j = _wait(jid)
    assert j["total"] == 3
    assert [f["duplicates"] for f in j["files"]] == [0, 1]
    assert any("b.csv" in n and "já presente" in n for n in j["report"]["notes"])


def test_arquivo_ruim_nao_derruba_os_outros_mas_avisa():
    jid = _send(("a.csv", _csv("Rua dos Andradas, 100;Ana;A1"), "text/csv"),
                ("lista.docx", b"nao e suportado", "application/octet-stream"))
    j = _wait(jid)
    assert j["state"] == "revisao" and j["total"] == 1
    bad = next(f for f in j["files"] if f["name"] == "lista.docx")
    assert bad["error"] and bad["stops"] == 0
    assert any("lista.docx" in n and "NÃO foi lido" in n for n in j["report"]["notes"])


def test_todos_ruins_da_erro_com_os_nomes():
    j = _wait(_send(("x.docx", b"1", "application/octet-stream"), ("y.doc", b"2", "application/octet-stream")))
    assert j["state"] == "erro" and "x.docx" in j["error"] and "y.doc" in j["error"]


def test_um_arquivo_ruim_sozinho_continua_dando_erro():
    j = _wait(_send(("x.docx", b"1", "application/octet-stream")))
    assert j["state"] == "erro" and "Formato não suportado" in j["error"]


def test_mapeamento_de_colunas_so_do_arquivo_que_precisa():
    desconhecido = "Ponto;Quem;Etiqueta\nRua Sarmento Leite, 12;Dani;ZZ1\nRua Riachuelo, 34;Edu;ZZ2\n".encode()
    jid = _send(("a.csv", _csv("Rua dos Andradas, 100;Ana;A1"), "text/csv"),
                ("novo.csv", desconhecido, "text/csv"),
                ("c.csv", _csv("Av. Ipiranga, 200;Beto;C1"), "text/csv"))
    j = _wait(jid)
    assert j["state"] == "mapear"
    m = j["mapping"]
    assert (m["file"], m["file_index"], m["file_total"]) == ("novo.csv", 2, 3)
    r = client.post(f"/api/jobs/{jid}/mapping", json={"columns": {"addr": 0, "name": 1, "code": 2}, "remember": False})
    assert r.status_code == 200
    j = _wait(jid, ("revisao", "erro"))
    assert j["state"] == "revisao" and j["total"] == 4                  # o c.csv, depois do mapeado, também entrou
    names = [(s["file"], s["name"]) for s in client.get(f"/api/jobs/{jid}/stops").json()]
    assert names == [("a.csv", "Ana"), ("novo.csv", "Dani"), ("novo.csv", "Edu"), ("c.csv", "Beto")]


def test_limite_de_arquivos():
    files = [("file", (f"{i}.csv", _csv("Rua A, 1;Ana;K%d" % i), "text/csv")) for i in range(21)]
    r = client.post("/api/upload", files=files)
    assert r.status_code == 413


def _blank_pdf(n, base):
    w = PdfWriter()
    for i in range(n):
        w.add_blank_page(width=base + i, height=200)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


def test_pdfs_de_intimacao_de_dois_arquivos_cada_pagina_vem_do_seu_pdf(monkeypatch):
    pages_a = _intimacao("ANA LIMA", "CPF 000.000.000-00", "RUA DOS ANDRADAS 100   - CENTRO  - CEP 90020-000 - PORTO ALEGRE/RS", "AA000000000001BR")
    pages_b = _intimacao("BETO CRUZ", "CPF 000.000.000-00", "AVENIDA IPIRANGA 200   - PRAIA  - CEP 90610-000 - PORTO ALEGRE/RS", "BB000000000001BR")
    pdf_a, pdf_b = _blank_pdf(2, 100), _blank_pdf(2, 300)    # largura = 100 + página (A) ou 300 + página (B)
    by_data = {pdf_a: pages_a, pdf_b: pages_b}
    monkeypatch.setattr(ex, "_read_pdf_pages", lambda data: by_data[data])
    jid = _send(("a.pdf", pdf_a, "application/pdf"), ("b.pdf", pdf_b, "application/pdf"))
    assert _wait(jid)["total"] == 2
    client.post(f"/api/jobs/{jid}/solve", json={"depot": {"address": ""}, "drivers": [{"label": "A"}], "time_limit": 5})
    res = None
    for _ in range(100):
        if client.get(f"/api/jobs/{jid}").json()["state"] in ("pronto", "erro"):
            res = client.get(f"/api/jobs/{jid}/result").json()
            break
        time.sleep(0.2)
    assert res and res["has_pages"] is True

    def widths(url):
        r = client.get(url)
        assert r.status_code == 200
        return [int(p.mediabox.width) for p in PdfReader(io.BytesIO(r.content)).pages]

    stops = {s["code"]: s["id"] for s in client.get(f"/api/jobs/{jid}/stops").json()}
    assert widths(f"/api/jobs/{jid}/paginas.pdf?stop={stops['AA000000000001BR']}") == [100, 101]
    assert widths(f"/api/jobs/{jid}/paginas.pdf?stop={stops['BB000000000001BR']}") == [300, 301]
    assert sorted(widths(f"/api/jobs/{jid}/paginas.pdf")) == [100, 101, 300, 301]
