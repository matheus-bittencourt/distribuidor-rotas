import io
import json

import openpyxl
import pytest

from app import extract as ex
from app.extract import NeedMapping, extract, other_city, to_query

MODELO = (
    "ENDEREÇO;NOME;COD_RASTREIO\n"
    "Rua x, 1237;João Silva;BR123456POA\n"
    "Rua y, 543;Alberto Jota;BR00123POA\n"
)


def _xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_formato_modelo():
    stops, rep = extract("lista.csv", MODELO.encode("utf-8"), force_llm=False)
    assert rep.method == "tabela" and len(stops) == 2
    assert (stops[0].name, stops[0].address, stops[0].code) == ("João Silva", "Rua x, 1237", "BR123456POA")
    assert stops[0].query == "Rua x, 1237, Porto Alegre, RS"
    assert stops[1].code == "BR00123POA"


def test_coluna_protocolo_e_ignorada_e_codigo_repetido_descartado():
    csv = ("PROTOCOLO;ENDEREÇO;NOME;COD_RASTREIO\n"
           "998877665;Rua x, 1;Ana;BR1POA\n"
           "112233445;Rua y, 2;Bia;BR2POA\n"
           "556677889;Rua z, 3;Bia Copia;BR2POA\n")
    stops, rep = extract("a.csv", csv.encode(), force_llm=False)
    assert [s.code for s in stops] == ["BR1POA", "BR2POA"]
    assert "PROTOCOLO" in rep.dropped_columns
    assert any("repetido" in n for n in rep.notes)
    assert "998877665" not in json.dumps([s.__dict__ for s in stops])


def test_so_porto_alegre_outra_cidade_vai_para_revisao():
    csv = "ENDEREÇO;NOME;COD_RASTREIO\nRua A, 10, Canoas/RS;Ana;B1\nRua B, 20, Porto Alegre;Bia;B2\nRua Canoas, 5;Cris;B3\n"
    stops, _ = extract("a.csv", csv.encode(), force_llm=False)
    assert stops[0].status == "revisar" and "Canoas" in stops[0].reason
    assert stops[1].status == "pendente"
    assert stops[2].status == "pendente"  # "Rua Canoas" é nome de rua, não cidade
    assert other_city("Rua A, 10 - São Leopoldo") == "Sao Leopoldo"
    assert other_city("Rua dos Andradas, 100") is None


def test_formato_desconhecido_pede_mapeamento_e_lembra():
    csv = "Ponto;Quem;CPF;Etiqueta\nRua x, 12;Ana Lima;123.456.789-09;ZZ1\nRua y, 34;Beto Cruz;987.654.321-00;ZZ2\n"
    with pytest.raises(NeedMapping) as e:
        extract("novo.csv", csv.encode(), force_llm=False)
    assert e.value.headers[:2] == ["Ponto", "Quem"]
    assert "123.456" not in json.dumps(e.value.sample)  # amostra vem mascarada

    mapping = {"columns": {"addr": 0, "name": 1, "code": 3}, "header_row": True, "remember": True}
    stops, rep = extract("novo.csv", csv.encode(), force_llm=False, mapping=mapping)
    assert [(s.name, s.code) for s in stops] == [("Ana Lima", "ZZ1"), ("Beto Cruz", "ZZ2")]
    assert any("lembrado" in n for n in rep.notes)

    # segunda vez: formato salvo, sem perguntar
    stops2, rep2 = extract("novo-outro-dia.csv", csv.encode(), force_llm=False)
    assert rep2.method == "modelo salvo" and len(stops2) == 2


def test_xlsx_descarta_colunas_sensiveis():
    data = _xlsx([
        ["Nome", "CPF", "Logradouro", "Número", "Complemento", "Bairro", "Cidade", "Valor da dívida"],
        ["Ana Souza", "123.456.789-09", "Rua dos Andradas", 100, "apto 12", "Centro Histórico", "Porto Alegre", "R$ 900,00"],
    ])
    stops, rep = extract("lista.xlsx", data, force_llm=False)
    assert "Rua dos Andradas, 100" in stops[0].address and "apto 12" in stops[0].address
    assert "apto" not in stops[0].query
    assert set(rep.dropped_columns) == {"CPF", "Valor da dívida"}


def test_texto_livre_heuristica_mascara_tudo():
    csv = ("registro\n"
           "Carla Dias CPF 111.222.333-44 deve R$ 2.000,00 - Rua Sarmento Leite, 200, Centro Histórico - tel (51) 3333-4444\n")
    stops, rep = extract("livre.csv", csv.encode(), force_llm=False)
    assert rep.method == "heuristica" and len(stops) == 1
    s = stops[0]
    assert s.name == "Carla Dias" and s.address.startswith("Rua Sarmento Leite, 200")
    assert not any(x in f"{s.name}{s.address}" for x in ("111.222", "2.000", "3333"))


def test_street_names_starting_with_ap_survive():
    assert "Aparício" in to_query("Rua Aparício Mariense, 10, Porto Alegre")


def test_unsupported_format():
    with pytest.raises(ValueError):
        extract("x.docx", b"", force_llm=False)


# ---------------------------------------------------------------- IA local (Ollama) simulada

def _fake_ollama(monkeypatch, entries_by_call):
    calls = []

    def fake(numbered):
        calls.append(numbered)
        return json.dumps({"entradas": entries_by_call(numbered)})

    monkeypatch.setattr(ex, "_call_ollama", fake)
    monkeypatch.setattr(ex, "llm_provider", lambda enabled=None: "ollama" if enabled is not False else None)
    return calls


def test_ia_local_extrai_e_descarta_alucinacao(monkeypatch):
    lines = ("Maria Souza CPF 111.222.333-44 deve R$ 50,00 Rua das Flores, 10 Bairro Centro\n"
             "João Pedro Av. Ipiranga, 200 apto 3\n"
             "Zeca Rua Verde, 5\n")

    def answer(numbered):
        return [
            {"linha": 1, "nome": "Maria Souza", "endereco": "Rua das Flores, 10 Bairro Centro", "complemento": ""},
            {"linha": 2, "nome": "João Pedro", "endereco": "Av. Ipiranga, 200", "complemento": "apto 3"},
            # modelo inventou outro endereço para a linha 3 -> deve ser descartado e cair na heurística
            {"linha": 3, "nome": "Zeca", "endereco": "Rua Inventada dos Sonhos, 999", "complemento": ""},
        ]

    calls = _fake_ollama(monkeypatch, answer)
    stops, rep = extract("livre.txt", lines.encode(), force_llm=None)
    assert rep.method == "ia-local"
    assert [s.name for s in stops] == ["Maria Souza", "João Pedro", "Zeca"]
    assert stops[2].address == "Rua Verde, 5"  # heurística no lugar da invenção
    assert "João Pedro" in stops[1].name and "apto 3" in stops[1].address
    # o que foi enviado ao modelo já estava mascarado
    assert "111.222" not in calls[0] and "50,00" not in calls[0]


def test_ia_local_fora_do_ar_cai_na_heuristica(monkeypatch):
    def boom(_):
        raise ConnectionError("sem servidor")

    monkeypatch.setattr(ex, "_call_ollama", boom)
    monkeypatch.setattr(ex, "llm_provider", lambda enabled=None: "ollama")
    stops, rep = extract("livre.txt", b"Ana Lima Rua das Acacias, 77\n", force_llm=None)
    assert stops[0].address == "Rua das Acacias, 77"
    assert any("indisponível" in n for n in rep.notes)
