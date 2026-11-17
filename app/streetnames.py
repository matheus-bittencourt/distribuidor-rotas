"""Normalização de nomes de rua: a mesma regra no gerador do pacote de mapa e na busca do app."""
from __future__ import annotations

import re
import unicodedata

# abreviação -> palavra completa (sem acento, minúsculas). Vale para a consulta e para o nome no OSM.
ABBR = {
    "av": "avenida", "avda": "avenida", "r": "rua", "tv": "travessa", "trav": "travessa", "est": "estrada",
    "estr": "estrada", "al": "alameda", "pc": "praca", "pca": "praca", "pr": "praca", "lg": "largo",
    "rod": "rodovia", "vl": "vila", "bc": "beco", "acs": "acesso", "esc": "escadaria", "pq": "parque",
    "dr": "doutor", "dra": "doutora", "gen": "general", "cel": "coronel", "cor": "coronel","prof": "professor", "profa": "professora",
    "des": "desembargador", "eng": "engenheiro", "mal": "marechal", "pres": "presidente", "sen": "senador",
    "dep": "deputado", "ver": "vereador", "cap": "capitao", "ten": "tenente", "maj": "major", "alm": "almirante",
    "brig": "brigadeiro", "pe": "padre", "fr": "frei", "d": "dom", "sto": "santo", "sta": "santa", "s": "sao",
    "n": "nossa", "sra": "senhora", "nsa": "nossa", "gov": "governador", "min": "ministro", "arq": "arquiteto",
    "cond": "conde", "visc": "visconde", "bar": "barao", "duq": "duque", "imp": "imperador", "jor": "jornalista",
    "sgt": "sargento", "sarg": "sargento", "cmte": "comandante", "com": "comendador", "intend": "intendente",
}
TYPES = {"rua", "avenida", "travessa", "estrada", "alameda", "praca", "largo", "rodovia", "beco", "acesso",
         "viela", "passagem", "escadaria", "parque", "via", "viaduto", "ponte", "tunel", "servidao", "caminho"}
TITLES = {"doutor", "doutora", "general", "coronel", "professor", "professora", "desembargador", "engenheiro",
          "marechal", "presidente", "senador", "deputado", "vereador", "capitao", "tenente", "major", "almirante",
          "brigadeiro", "padre", "frei", "dom", "governador", "ministro", "arquiteto", "conde", "visconde",
          "barao", "duque", "imperador", "jornalista", "sargento", "comandante", "comendador", "intendente"}
STOP = {"de", "da", "do", "das", "dos", "e"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


_UNITS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
          "oito": 8, "nove": 9}
_TEENS = {"dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14, "quinze": 15,
          "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19}
_TENS = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
         "oitenta": 80, "noventa": 90}


def _numbers(ws: list[str]) -> list[str]:
    """Número por extenso vira algarismo: 'vinte e quatro de outubro' -> '24 de outubro'.
    Só quando vem antes de 'de' (datas: 'sete de setembro'), para não mexer em nomes como 'Dois Irmãos'."""
    out, i = [], 0
    while i < len(ws):
        w, n, j = ws[i], None, i + 1
        if w in _TENS:
            n = _TENS[w]
            if j + 1 < len(ws) and ws[j] == "e" and ws[j + 1] in _UNITS:
                n, j = n + _UNITS[ws[j + 1]], j + 2
        elif w in _TEENS or w in _UNITS:
            n = _TEENS.get(w) or _UNITS[w]
        if n is not None and j < len(ws) and ws[j] == "de":
            out.append(str(n))
            i = j
        else:
            out.append(w)
            i += 1
    return out


def words(name: str) -> list[str]:
    s = strip_accents(name).lower().replace("º", "").replace("ª", "")
    out = []
    for i, w in enumerate(re.findall(r"[a-z0-9]+", s)):
        # "R" só é "rua" no começo; no meio do nome é inicial ("Francisco R. Simch")
        out.append(w if (w == "r" and i > 0) else ABBR.get(w, w))
    return _numbers(out)


def full_key(name: str) -> str:
    """Nome completo normalizado: 'Av. Dr. Nilo Peçanha' -> 'avenida doutor nilo pecanha'."""
    return " ".join(words(name))


def core_key(name: str) -> str:
    """Só o miolo do nome, sem tipo, títulos e preposições: 'nilo pecanha'. Tolera 'Rua'/'Av.' trocados."""
    ws = words(name)
    if ws and ws[0] in TYPES:
        ws = ws[1:]
    core = [w for w in ws if w not in TITLES and w not in STOP]
    return " ".join(core) or " ".join(ws)


def street_type(name: str) -> str:
    ws = words(name)
    return ws[0] if ws and ws[0] in TYPES else ""


_NUM = re.compile(r"^\s*(\d{1,5})")


def house_number(s: str) -> int | None:
    m = _NUM.match(s or "")
    return int(m.group(1)) if m else None


def parse_query(query: str) -> tuple[str, int | None]:
    """'Rua X, 123, Bairro, Porto Alegre, RS' -> ('Rua X', 123). Aceita também 'Rua X 123, ...'."""
    parts = [p.strip() for p in query.split(",") if p.strip()]
    if not parts:
        return "", None
    street = parts[0]
    # "Acesso 2, 1727": o número da casa é a parte seguinte; o "2" é do nome da rua
    if len(parts) > 1:
        num = house_number(re.sub(r"^n[º°o.]?\s*", "", parts[1], flags=re.I))
        if num is not None:
            return street, num
    sp = split_number(street)
    if sp and re.search(r"\bn[º°o.]?\s*\d", street, re.I):   # "Rua X nº 123": sem dúvida é o número
        return sp
    return street, None


def split_number(street: str) -> tuple[str, int] | None:
    """'Rua X 123' -> ('Rua X', 123). Ambíguo ('Acesso 2' é nome de rua): quem chama confere no índice."""
    m = re.match(r"^(.*?\D)\s+(?:n[º°o.]?\s*)?(\d{1,5})\s*[a-zA-Z]?$", street, re.I)
    return (m.group(1).strip(), int(m.group(2))) if m else None


def neighbourhood_parts(query: str) -> list[str]:
    """Partes do endereço depois da rua e do número (bairro, cidade...), para desempatar ruas homônimas."""
    parts = [p.strip() for p in query.split(",") if p.strip()]
    return [p for p in parts[1:] if house_number(p) is None and not re.fullmatch(r"[A-Za-z]{2}", p)]
