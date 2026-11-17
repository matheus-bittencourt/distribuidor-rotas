"""Intimações de protesto em PDF. Textos fictícios no mesmo leiaute do arquivo real (duas páginas por intimação)."""
from app import extract as ex
from app import intimacoes


def _intimacao(nome, doc, endereco, protocolo, quebra=""):
    capa = (
        "3º TABELIONATO DE PROTESTOS\n"
        "Valor do Título\nR$ 304,16\n"
        f"{nome}  {doc}Pagador:\n"
        "PROTOCOLO\n5854911 - 16/11/2026\n"
        f"DEVEDOR/RESPONSÁVEL: {nome}\n"
        f"{doc}\n"
        f"{endereco}\n"
        f"{quebra}{protocolo}\n"
        "APRESENTANTE: BANCO FICTICIO\nCNPJ 00.000.000/0001-00\n"
        "RUA DO APRESENTANTE, 1 - - PORTO ALEGRE - RS - CEP: 90000-000\n"
    )
    ar = f"{nome}\nAVISO DE RECEBIMENTOAR\nDESTINATÁRIO {doc}\n{protocolo}\nPROTOCOLO: 5854911-16/11/2026\n"
    return [capa, ar]


PAGES = (
    _intimacao("FULANA DE TAL COMERCIO LTDA", "CNPJ 00.000.000/0001-91",
               "RUALUIGI SANTAGADA80   - MARIO QUINTA  - CEP 91250-121 - PORTO ALEGRE/RS", "AB000000000001BR")
    + _intimacao("BELTRANO DA SILVA", "CPF 000.000.000-00",
                 "RUA COR APARICIO BORGES 693   - PARTENON  - CEP 91510-115 - PORTO", "AB000000000002BR",
                 quebra="ALEGRE/RS\n")
    + _intimacao("12.345.678 CICLANO SOUZA", "CNPJ 12.345.678/0001-00",
                 "AVENIDA AVENIDA DOUTOR NILO PECANHA N. 3245 SALA 401   - VILA JARDIM  - CEP 91330-", "AB000000000003BR",
                 quebra="001 - PORTO ALEGRE/RS\n")
)


def test_reconhece_o_modelo():
    assert intimacoes.is_intimacao(PAGES)
    assert not intimacoes.is_intimacao(["Rua x, 10;João\n", "lista comum"])


def test_extrai_nome_endereco_e_protocolo():
    entries, failed = intimacoes.parse(PAGES)
    assert failed == 0 and len(entries) == 3
    a, b, c = entries
    assert (a.name, a.code) == ("FULANA DE TAL COMERCIO LTDA", "AB000000000001BR")
    assert a.address == "RUA LUIGI SANTAGADA, 80, MARIO QUINTA, PORTO ALEGRE/RS - CEP 91250-121"
    # cidade quebrada em duas linhas
    assert b.address == "RUA COR APARICIO BORGES, 693, PARTENON, PORTO ALEGRE/RS - CEP 91510-115"
    # CEP quebrado no meio, tipo repetido, "N." antes do número, raiz do CNPJ no nome do MEI
    assert c.name == "CICLANO SOUZA"
    assert c.address == "AVENIDA DOUTOR NILO PECANHA, 3245, VILA JARDIM, PORTO ALEGRE/RS - CEP 91330-001"
    assert c.complement == "SALA 401"


def test_nada_de_cpf_cnpj_ou_valor_na_saida():
    entries, _ = intimacoes.parse(PAGES)
    for e in entries:
        text = f"{e.name} {e.address} {e.code}"
        assert "CNPJ" not in text and "CPF" not in text and "R$" not in text and "000.000" not in text


def test_fix_street():
    assert intimacoes.fix_street("RUALUIGI SANTAGADA80") == "RUA LUIGI SANTAGADA, 80"
    assert intimacoes.fix_street("AVENIDA IPIRANGA 100") == "AVENIDA IPIRANGA, 100"   # não vira "AV ENIDA"
    assert intimacoes.fix_street("RUA 3 DE MAIO 100") == "RUA 3 DE MAIO, 100"           # número que é nome
    assert intimacoes.fix_street("NULL AV ASSIS BRASIL 6535 NULL") == "AV ASSIS BRASIL, 6535"
    assert intimacoes.fix_street("RUA CEL FEIJO NRO 52") == "RUA CEL FEIJO, 52"


def test_regras_de_limpeza_do_endereco():
    f = intimacoes.fix_street
    assert f("RUA ANITA GARIBALDI MONT SERRAT PORTO AL", "MONT SERRAT") == "RUA ANITA GARIBALDI"      # A
    assert f("RUA PADRE ALOIS KADES 210 PORTO ALEGRE") == "RUA PADRE ALOIS KADES, 210"                  # A
    assert f("AVENIDA DA CAVALHADA", "CAVALHADA") == "AVENIDA DA CAVALHADA"   # bairro com o nome da rua fica
    assert f("AVENIDA PLINIO BRASIL MILANO LADO PAR") == "AVENIDA PLINIO BRASIL MILANO"                 # D
    assert f("RUA SANTOS DUMONT SALA 1003 SALA 1004 15") == "RUA SANTOS DUMONT, 15"                     # E
    assert f("RGEN NETO71SALA 404 CXPST 203") == "R GEN NETO, 71"                                       # E
    assert f("A.J.RENNER 2185") == "A. J. RENNER, 2185"                                                 # F
    assert f("AV .JOSE BONIFACIO 95") == "AV JOSE BONIFACIO, 95"


def test_via_interna_busca_pela_via_de_acesso():
    pages = _intimacao("FULANO", "CPF 000.000.000-00",
                       "RUA DO LAGO 20 PROTASIO 12000   - VERDES CAMPOS  - CEP 91260-000 - PORTO ALEGRE/RS",
                       "AB000000000009BR")
    (e,), _ = intimacoes.parse(pages)
    assert e.address == "RUA DO LAGO, 20 PROTASIO 12000, VERDES CAMPOS, PORTO ALEGRE/RS - CEP 91260-000"
    assert e.query == "PROTASIO, 12000, VERDES CAMPOS, PORTO ALEGRE/RS"
    stops = ex._to_stops([e], ex.ExtractReport())
    assert stops[0].query.startswith("PROTASIO, 12000") and stops[0].public()["pages"] == [1, 2]


def test_extract_usa_o_leitor_de_intimacoes(monkeypatch):
    monkeypatch.setattr(ex, "_read_pdf_pages", lambda _data: PAGES)
    stops, rep = ex.extract("intimacoes.pdf", b"%PDF", force_llm=False)
    assert rep.method == "intimação de protesto" and len(stops) == 3
    assert [s.code for s in stops] == ["AB000000000001BR", "AB000000000002BR", "AB000000000003BR"]
    # a busca vai sem complemento e sem CEP; "COR" vira "coronel" no geocodificador
    assert stops[1].query == "RUA COR APARICIO BORGES, 693, PARTENON, PORTO ALEGRE/RS"
    assert stops[2].query == "AVENIDA DOUTOR NILO PECANHA, 3245, VILA JARDIM, PORTO ALEGRE/RS"
    assert all(s.status == "pendente" for s in stops)


def test_cada_intimacao_guarda_suas_paginas():
    entries, _ = intimacoes.parse(PAGES)
    assert [e.pages for e in entries] == [[0, 1], [2, 3], [4, 5]]


def _blank_pdf(n):
    """PDF de n páginas em branco; a largura de cada uma (100 + i) identifica a página de origem."""
    import io

    from pypdf import PdfWriter

    w = PdfWriter()
    for i in range(n):
        w.add_blank_page(width=100 + i, height=200)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


def test_pdf_de_cada_entregador_tem_as_paginas_das_entregas_dele(monkeypatch):
    import io
    import time

    from fastapi.testclient import TestClient
    from pypdf import PdfReader

    from app.main import app

    monkeypatch.setattr(ex, "_read_pdf_pages", lambda _data: PAGES)
    client = TestClient(app)
    jid = client.post("/api/upload", files={"file": ("int.pdf", _blank_pdf(len(PAGES)), "application/pdf")}).json()["job_id"]
    for _ in range(50):
        if client.get(f"/api/jobs/{jid}").json()["state"] in ("revisao", "erro"):
            break
        time.sleep(0.1)
    client.post(f"/api/jobs/{jid}/solve", json={"depot": {"address": ""}, "drivers": [{"label": "A"}, {"label": "B"}], "time_limit": 5})
    for _ in range(100):
        if client.get(f"/api/jobs/{jid}").json()["state"] in ("pronto", "erro"):
            break
        time.sleep(0.2)
    res = client.get(f"/api/jobs/{jid}/result").json()
    assert res["has_pages"] is True

    def widths(url):
        r = client.get(url)
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
        return [int(p.mediabox.width) - 100 for p in PdfReader(io.BytesIO(r.content)).pages]

    code_pages = {"AB000000000001BR": [0, 1], "AB000000000002BR": [2, 3], "AB000000000003BR": [4, 5]}
    every = []
    for d in res["drivers"]:
        expected = [p for s in d["stops"] for x in s["deliveries"] for p in code_pages[x["code"]]]
        every += expected
        if expected:
            assert widths(f"/api/jobs/{jid}/paginas.pdf?driver={d['index']}") == expected   # na ordem da rota
    assert sorted(every) == list(range(6))
    assert widths(f"/api/jobs/{jid}/paginas.pdf") == every                                 # todos, rota após rota

    # lista que não veio de PDF de intimações: sem o botão e sem o PDF
    csv = "ENDEREÇO;NOME;COD_RASTREIO\nRua dos Andradas, 100;Ana;B1\n".encode()
    jid2 = client.post("/api/upload", files={"file": ("l.csv", csv, "text/csv")}).json()["job_id"]
    for _ in range(50):
        if client.get(f"/api/jobs/{jid2}").json()["state"] in ("revisao", "erro"):
            break
        time.sleep(0.1)
    client.post(f"/api/jobs/{jid2}/solve", json={"depot": {"address": ""}, "drivers": [{"label": "A"}], "time_limit": 5})
    for _ in range(100):
        if client.get(f"/api/jobs/{jid2}").json()["state"] in ("pronto", "erro"):
            break
        time.sleep(0.2)
    assert client.get(f"/api/jobs/{jid2}/result").json()["has_pages"] is False
    assert client.get(f"/api/jobs/{jid2}/paginas.pdf").status_code == 404


def test_cor_e_coronel():
    from app.streetnames import words

    assert words("Rua Cor Aparicio Borges") == ["rua", "coronel", "aparicio", "borges"]
