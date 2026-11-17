"""Intimações de protesto em PDF (modelo fixo do tabelionato): leitura direta, sem IA.

Cada intimação ocupa duas páginas: a intimação com o boleto e o aviso de recebimento (AR).
Da intimação saem só três campos; CPF/CNPJ, valores, credor e boleto são descartados aqui mesmo.

  NOME       linha "DEVEDOR/RESPONSÁVEL: ...", até onde começa o CNPJ/CPF.
  ENDEREÇO   linha logo abaixo do CNPJ/CPF: "rua nº - bairro - CEP 00000-000 - PORTO ALEGRE/RS".
             O texto vem com palavras grudadas ("RUALUIGI SANTAGADA80"), que são separadas aqui.
  PROTOCOLO  código "AB000000000000BR" junto ao código de barras. Impresso de cabeça para baixo,
             mas presente no texto do PDF como qualquer outro.
"""
from __future__ import annotations

import re

from .models import RawEntry
from .sanitize import clean_value

_DEVEDOR = re.compile(r"DEVEDOR\s*/\s*RESPONS.VEL\s*:\s*(.*)", re.I)
_DOC = re.compile(r"\s*\b(CNPJ|CPF)\b", re.I)
_CNPJ_RAIZ = re.compile(r"^\s*\d{2}\.?\d{3}\.?\d{3}\s+")
PROTOCOLO = re.compile(r"\b[A-Z]{2}\d{9,13}BR\b")
_ENDERECO = re.compile(
    r"^(?P<rua>.*?)\s+-\s+(?P<bairro>.*?)\s*-\s+CEP:?\s*(?P<cep>\d{5}-?\d{3})\s*-\s*(?P<cidade>[^/-]+?)\s*(?:/\s*(?P<uf>[A-Z]{2}))?\s*$",
    re.I,
)
# Tipos de logradouro que aparecem grudados no nome ("RUALUIGI", "AVBENTO"). Os mais longos primeiro,
# para "AVENIDA" não virar "AV ENIDA".
_TIPOS = ("AVENIDA", "TRAVESSA", "ESTRADA", "ALAMEDA", "RODOVIA", "ACESSO", "PRACA", "LARGO", "BECO", "RUA", "AV", "R")
_TIPO_JUNTO = re.compile(r"^(" + "|".join(_TIPOS) + r")(?=[A-Z]{3})")
_TIPO_SOLTO = re.compile(r"^(" + "|".join(_TIPOS) + r")\.?(\s|$)")


def is_intimacao(pages: list[str]) -> bool:
    """O PDF segue o modelo: tem devedor e protocolo na primeira página com conteúdo."""
    for text in pages[:4]:
        if _DEVEDOR.search(text):
            return bool(PROTOCOLO.search(text))
    return False


# Complemento escrito antes do número ("SANTOS DUMONT SALA 1003 15"): sai do nome e vai para o complemento.
_COMPL = re.compile(r"\b(?:SALAS?|SL|LOJAS?|LJS?|CONJ|CJ|APTO|AP|BLOCO|BL|ANDAR|PAVMTO|GALPAO|BOX|CX\s*PST|CAIXA POSTAL)\.?\s*-?\s*\d+[A-Z]?\b")
# Via interna de condomínio: "RUA DO LAGO 20 PROTASIO 12000" = Rua do Lago, 20, dentro do nº 12000 da
# Av. Protásio Alves. A busca vai pela via de acesso, que está no mapa.
_VIA_INTERNA = re.compile(r"^(?P<interna>.+?, \d+) (?P<acesso>[A-Z][A-Z ]{3,}?) (?P<num>\d{3,5})$")


def _clean_street(rua: str, bairro: str = "") -> tuple[str, str, str]:
    """(rua com número, complemento, via de acesso para a busca quando é via interna; "" se não é)."""
    rua = re.sub(r"\bNULL\b|\*+", " ", rua)                   # campo vazio do sistema de origem
    rua = re.sub(r"\s+", " ", rua).strip(" ,-")
    rua = re.sub(r"^(\w+\.?) \1\b", r"\1", rua)              # "RUA RUA X", "AVENIDA AVENIDA X"
    # A: cidade e bairro repetidos no fim do nome ("ANITA GARIBALDI MONT SERRAT PORTO AL")
    rua = re.sub(r"\s+PORTO\s+AL\w*\b", "", rua).strip()
    if bairro and rua.endswith(" " + bairro):
        rest = rua[: -len(bairro)].strip()
        # só se sobra um nome de verdade: em "AVENIDA DA CAVALHADA" (bairro Cavalhada) o bairro é o nome
        if len([w for w in rest.split()[1:] if w not in ("DA", "DE", "DO", "DAS", "DOS", "E")]) >= 2:
            rua = rest
    rua = re.sub(r"\s+LADO\s+(?:PAR|[IÍ]MPAR)\b", "", rua)   # D: observação, não endereço
    if not _TIPO_SOLTO.match(rua):
        rua = _TIPO_JUNTO.sub(r"\1 ", rua, count=1)
    rua = re.sub(r"(?<=[A-Z]{3})(?=\d)", " ", rua)            # "SANTAGADA80" -> "SANTAGADA 80"
    rua = re.sub(r"(?<=\d)(?=[A-Z]{3})", " ", rua)            # "71SALA" -> "71 SALA"
    rua = re.sub(r"\b([A-Z])\.\s*(?=[A-Z])", r"\1. ", rua)    # F: "A.J.RENNER" -> "A. J. RENNER"
    rua = re.sub(r"\s\.(?=[A-Z])", " ", rua)                  # "AV .JOSE" -> "AV JOSE"
    compl = " ".join(m.group(0) for m in _COMPL.finditer(rua))  # E: salas e lojas antes do número
    rua = re.sub(r"\s+", " ", _COMPL.sub(" ", rua)).strip()
    rua = re.sub(r"\s+(?:N|NO|NR|NRO|NUM|N[º°])\.?\s*(?=\d)", " ", rua)  # "X N. 3245", "X NRO 52"
    # vírgula antes do número da casa ("RUA X 865" -> "RUA X, 865"), que é como o geocodificador separa
    # nome e número. Número seguido de "DE" faz parte do nome ("RUA 3 DE MAIO 100").
    rua = re.sub(r"(?<=[A-Z.])\s+(\d+)(?!\s+D[EAO]S?\b)", r", \1", rua, count=1)
    m = _VIA_INTERNA.match(rua)
    acesso = f"{m['acesso']}, {m['num']}" if m else ""
    return rua, compl, acesso


def fix_street(rua: str, bairro: str = "") -> str:
    """Separa o que o PDF grudou: tipo + nome ("RUALUIGI" -> "RUA LUIGI") e nome + número
    ("SANTAGADA80" -> "SANTAGADA 80"). Abreviações como "COR" (coronel) ficam com o geocodificador."""
    return _clean_street(rua, bairro)[0]


def _address(lines: list[str]) -> tuple[str, str, str, str]:
    """(endereço para exibir, CEP, complemento, consulta para o mapa ou "" para a padrão). O endereço
    pode quebrar em duas linhas, às vezes no meio do CEP ("91360-" / "370")."""
    m = None
    # o endereço termina em "CIDADE/UF"; sem a UF, a cidade quebrou para a linha de baixo ("PORTO" / "ALEGRE/RS")
    for n, need_uf in ((1, True), (2, True), (1, False)):
        blob = re.sub(r"\s+", " ", " ".join(lines[:n])).strip()
        blob = re.sub(r"(\d{5}-)\s+(\d{3})", r"\1\2", blob)
        m = _ENDERECO.match(blob)
        if m and (m["uf"] or not need_uf):
            break
        m = None
    if not m:  # fora do padrão: a primeira linha como veio, só com as palavras separadas
        cep = re.search(r"CEP:?\s*(\d{5}-?\d{3})", blob)
        rua, compl, _ = _clean_street(lines[0])
        return clean_value(rua), (cep.group(1) if cep else ""), compl, ""
    bairro = m["bairro"].strip(" -")
    rua, compl, acesso = _clean_street(m["rua"], bairro)
    cidade = m["cidade"].strip() + (f"/{m['uf']}" if m["uf"] else "")
    cep = m["cep"] if "-" in m["cep"] else f"{m['cep'][:5]}-{m['cep'][5:]}"
    tail = ", ".join(p for p in (bairro, cidade) if p)
    query = f"{acesso}, {tail}" if acesso else ""
    return ", ".join(p for p in (rua, tail) if p) + f" - CEP {cep}", cep, compl, query


def parse(pages: list[str]) -> tuple[list[RawEntry], int]:
    """Entradas (nome, endereço, protocolo) e o número de intimações que não puderam ser lidas."""
    out: list[RawEntry] = []
    failed = 0
    # cada intimação vai da página do devedor até a página antes do próximo devedor (intimação + AR)
    starts = [p for p, text in enumerate(pages) if _DEVEDOR.search(text)]
    span = {p: list(range(p, min(nxt, p + 4))) for p, nxt in zip(starts, [*starts[1:], len(pages)])}
    for p, text in enumerate(pages):
        lines = [ln.strip() for ln in text.splitlines()]
        for j, line in enumerate(lines):
            m = _DEVEDOR.search(line)
            if not m:
                continue
            name = _DOC.split(m.group(1), maxsplit=1)[0]
            name = _CNPJ_RAIZ.sub("", name)  # MEI: "12.345.678 FULANO" leva a raiz do CNPJ no nome
            # o CNPJ/CPF fica na linha de baixo (ou na mesma); o endereço vem logo depois dele
            k = j + 1 if j + 1 < len(lines) and _DOC.match(lines[j + 1]) else j
            addr_lines = [ln for ln in lines[k + 1:k + 3] if ln]
            codes = PROTOCOLO.findall(text) or (PROTOCOLO.findall(pages[p + 1]) if p + 1 < len(pages) else [])
            if not addr_lines:
                failed += 1
                continue
            address, _cep, compl, query = _address(addr_lines)  # o CEP fica no texto, para a busca por CEP no futuro
            out.append(RawEntry(clean_value(name), address, complement=compl, code=codes[0] if codes else "",
                                pages=span.get(p, [p]), query=query))
    return out, failed
