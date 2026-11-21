"""ViaCEP: bairro só entra na consulta quando a rua é inequívoca; nada de rede nos testes (cache pré-carregado)."""
import json

from app.geocode import Geo
from app.viacep import Enriched, ViaCep, number_in, split_query


def _viacep(tmp_path, data):
    p = tmp_path / "viacep.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return ViaCep(str(p))


def _row(logradouro, bairro, compl=""):
    return {"cep": "90000-000", "logradouro": logradouro, "complemento": compl, "bairro": bairro}


def test_split_query():
    assert split_query("Rua Dom João VI, 146, Porto Alegre, RS") == ("Rua Dom João VI", 146, "Porto Alegre, RS")
    assert split_query("Rua A, Porto Alegre, RS") == ("Rua A", None, "Porto Alegre, RS")


def test_number_in_ranges():
    assert number_in("de 1 a 99 - lado ímpar", 51) is True
    assert number_in("de 1 a 99 - lado ímpar", 50) is False
    assert number_in("de 1 a 99", 150) is False
    assert number_in("até 1000/1001", 500) is True
    assert number_in("de 1001/1002 ao fim", 900) is False
    assert number_in("lado par", 10) is True and number_in("lado par", 11) is False
    assert number_in("", 10) is None


def test_single_bairro_is_added(tmp_path):
    v = _viacep(tmp_path, {"rua dom joao vi": [_row("Rua Dom João VI", "Medianeira")]})
    assert v.enrich("Rua Dom João VI, 146, Porto Alegre, RS") == "Rua Dom João VI, 146, Medianeira, Porto Alegre, RS"


def test_ambiguous_bairros_resolved_by_number_range(tmp_path):
    rows = [_row("Avenida X", "Centro", "de 1 a 999"), _row("Avenida X", "Navegantes", "de 1000 ao fim")]
    v = _viacep(tmp_path, {"avenida x": rows})
    assert "Centro" in v.enrich("Avenida X, 500, Porto Alegre, RS")
    assert "Navegantes" in v.enrich("Avenida X, 1500, Porto Alegre, RS")


def test_ambiguous_without_range_stays_unchanged(tmp_path):
    rows = [_row("Rua Y", "A"), _row("Rua Y", "B")]
    v = _viacep(tmp_path, {"rua y": rows})
    q = "Rua Y, 10, Porto Alegre, RS"
    assert v.enrich(q) == q


def test_not_found_and_fuzzy_matches_leave_query_alone(tmp_path):
    v = _viacep(tmp_path, {"rua nova": [], "rua z": [_row("Rua Z Prolongada", "Lami")]})
    assert v.enrich("Rua Nova, 5, Porto Alegre, RS") == "Rua Nova, 5, Porto Alegre, RS"
    # a API aproxima o nome; sem logradouro idêntico ainda usa o único bairro encontrado
    assert "Lami" in v.enrich("Rua Z, 5, Porto Alegre, RS")


def test_network_failure_does_not_break(tmp_path, monkeypatch):
    v = _viacep(tmp_path, {})
    monkeypatch.setattr(v, "search", lambda street: None)
    q = "Rua Q, 5, Porto Alegre, RS"
    assert v.enrich(q) == q


class _Inner:
    def __init__(self):
        self.seen = []

    def geocode(self, query, wide=False):
        self.seen.append(query)
        return Geo(-30.0, -51.2, "exato", "Porto Alegre") if "Medianeira" not in query else None


def test_enriched_falls_back_to_original_query(tmp_path):
    v = _viacep(tmp_path, {"rua dom joao vi": [_row("Rua Dom João VI", "Medianeira")]})
    inner = _Inner()
    hit = Enriched(inner, v).geocode("Rua Dom João VI, 146, Porto Alegre, RS")
    assert hit is not None
    assert inner.seen == ["Rua Dom João VI, 146, Medianeira, Porto Alegre, RS", "Rua Dom João VI, 146, Porto Alegre, RS"]


def test_enriched_leaves_start_points_alone(tmp_path):
    inner = _Inner()
    Enriched(inner, _viacep(tmp_path, {})).geocode("Rua R, 1, Porto Alegre, RS", wide=True)
    assert inner.seen == ["Rua R, 1, Porto Alegre, RS"]
