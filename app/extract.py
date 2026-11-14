"""Leitura de planilhas/PDF e extração de NOME + ENDEREÇO (+ código de rastreio).

Caminhos, do mais para o menos privado/gratuito:
  1. Tabela com colunas conhecidas (modelo salvo ou nomes reconhecidos) -> leitura 100% local.
  2. Tabela de formato novo -> o app pede para você apontar as colunas e pode lembrar o formato.
  3. Texto livre / PDF -> mascara dados sensíveis localmente e usa IA LOCAL (Ollama, gratuita)
     ou, se houver chave, a API da Anthropic. Cada resposta da IA é conferida contra a linha original.
  4. Sem IA -> heurística local por regex (menos precisa).

O arquivo original nunca é gravado em disco: tudo acontece em memória.
"""
from __future__ import annotations

import csv
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx

from . import templates
from .config import RMPA_CITIES, SETTINGS
from .models import ExtractReport, RawEntry, Stop
from .sanitize import clean_value, is_sensitive_header, mask_text, norm_header, strip_accents

Progress = Callable[[str], None]

NAME_KEYS = {"nome", "cliente", "destinatario", "morador", "consumidor", "titular", "pessoa", "devedor"}
ADDR_KEYS = {"endereco", "logradouro", "rua", "avenida", "local", "destino"}
NUM_KEYS = {"numero", "num", "n", "nro", "no"}
COMPL_KEYS = {"complemento", "compl", "comp"}
BAIRRO_KEYS = {"bairro"}
CITY_KEYS = {"cidade", "municipio"}
UF_KEYS = {"uf", "estado"}
CEP_KEYS = {"cep"}
CODE_KEYS = {"rastreio", "rastreamento", "tracking", "codigo", "cod"}
COLUMN_LABELS = {  # para a tela de mapeamento
    "name": "Nome", "addr": "Endereço", "code": "Código de rastreio", "num": "Número",
    "compl": "Complemento", "bairro": "Bairro", "city": "Cidade", "uf": "UF", "cep": "CEP",
}


class NeedMapping(Exception):
    """Tabela com formato desconhecido: a tela precisa pedir o mapeamento das colunas."""

    def __init__(self, headers: list[str], sample: list[list[str]], total_rows: int):
        super().__init__("mapeamento de colunas necessário")
        self.headers, self.sample, self.total_rows = headers, sample, total_rows


# --------------------------------------------------------------------------- leitura

def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_csv(data: bytes) -> list[list[str]]:
    text = _decode(data)
    lines = [ln for ln in text.splitlines()[:50] if ln.strip()]
    best, best_score = "\x00", 0.0  # \x00: nenhum separador (texto livre em uma coluna)
    for d in (";", "\t", "|", ","):
        counts = [ln.count(d) for ln in lines]
        common = max(set(counts), key=counts.count) if counts else 0
        share = counts.count(common) / len(counts) if counts else 0
        if common >= 1 and share >= 0.8 and share * common > best_score:  # colunas consistentes
            best, best_score = d, share * common
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=best)]


def _read_xlsx(data: bytes) -> list[list[list[str]]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    tables = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v).strip() for v in r]
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def _read_pdf(data: bytes) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    lines: list[str] = []
    for page in reader.pages:
        for line in (page.extract_text() or "").splitlines():
            line = line.strip()
            if line:
                lines.append(line)
    return lines


# --------------------------------------------------------------------------- tabelas

def _map_columns(header: list[str]) -> dict[str, int]:
    cols: dict[str, int] = {}
    for i, h in enumerate(header):
        if not h or is_sensitive_header(h):
            continue
        words = set(norm_header(h).split())
        for key, vocab in (
            ("name", NAME_KEYS), ("addr", ADDR_KEYS), ("code", CODE_KEYS), ("num", NUM_KEYS),
            ("compl", COMPL_KEYS), ("bairro", BAIRRO_KEYS), ("city", CITY_KEYS), ("uf", UF_KEYS),
            ("cep", CEP_KEYS),
        ):
            if key not in cols and words & vocab:
                cols[key] = i
                break
    return cols


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(rows[:15]):
        if any(len(c) > 40 for c in row):  # cabeçalho tem rótulos curtos; dados/texto livre não
            continue
        cols = _map_columns(row)
        if "addr" in cols and (len(cols) >= 2 or sum(1 for c in row if c) <= 2):
            return i, cols
    return None


def _looks_tabular(rows: list[list[str]]) -> bool:
    return (len(rows) >= 2 and sum(1 for c in rows[0] if c) >= 2 and all(len(c) <= 40 for c in rows[0]))


def _cell(row: list[str], cols: dict[str, int], key: str) -> str:
    i = cols.get(key)
    if i is None or i >= len(row):
        return ""
    return clean_value(row[i])


def _entries_from_table(rows: list[list[str]], hdr_i: int, cols: dict[str, int], rep: ExtractReport) -> list[RawEntry]:
    if hdr_i >= 0:
        rep.dropped_columns += [h for h in rows[hdr_i] if h and is_sensitive_header(h)]
    out: list[RawEntry] = []
    for row in rows[hdr_i + 1:]:
        if not any(row):
            continue
        rep.rows_read += 1
        log = _cell(row, cols, "addr")
        if not log:
            rep.skipped_lines += 1
            continue
        num = _cell(row, cols, "num")
        bairro, city = _cell(row, cols, "bairro"), _cell(row, cols, "city")
        uf, cep = _cell(row, cols, "uf"), _cell(row, cols, "cep")
        street = log if (not num or re.search(r"\d", log)) else f"{log}, {num}"
        tail = [bairro, f"{city}/{uf}" if city and uf else city or uf]
        address = ", ".join(p for p in [street, *tail] if p)
        if cep:
            address += f" - CEP {cep}"
        code = _cell(row, cols, "code").replace(" ", "")
        out.append(RawEntry(_cell(row, cols, "name"), address, _cell(row, cols, "compl"), code))
    return out


# --------------------------------------------------------------------------- heurística

_STREET = re.compile(
    r"\b(rua|r\.|avenida|av\.?|travessa|tv\.?|estrada|est\.|alameda|al\.|rodovia|rod\.|largo|"
    r"pra[cç]a|p[cç]a\.?|beco|servid[aã]o|caminho|via)\s+[^|;\t]+",
    re.I,
)


def _looks_like_name(s: str) -> bool:
    s = s.strip(" |;,-")
    words = s.split()
    return 1 < len(words) <= 7 and not re.search(r"\d|\[removido\]", s) and not _STREET.search(s)


def _count_masks(counts: dict[str, int], rep: ExtractReport) -> None:
    for k, v in counts.items():
        rep.masked[k] = rep.masked.get(k, 0) + v


def _heuristic_line(raw: str, prev: str = "") -> RawEntry | None:
    masked, _ = mask_text(raw)
    m = _STREET.search(masked)
    if not m:
        return None
    address = clean_value(masked[m.start():])
    name = clean_value(masked[:m.start()].replace("|", " "))
    if not name and _looks_like_name(prev):
        name = clean_value(prev)
    return RawEntry(name, address)


def _heuristic_lines(lines: list[str], rep: ExtractReport) -> list[RawEntry]:
    out: list[RawEntry] = []
    prev = ""
    for raw in lines:
        masked, counts = mask_text(raw)
        _count_masks(counts, rep)
        rep.rows_read += 1
        e = _heuristic_line(masked, prev)
        if e is None:
            prev = masked
            rep.skipped_lines += 1
            continue
        out.append(e)
        prev = ""
    return out


# --------------------------------------------------------------------------- IA (Ollama / Anthropic)

_SYSTEM = (
    "Você recebe linhas de listas de entregas em formatos variados. Para cada linha que contenha um "
    "endereço de entrega, extraia SOMENTE: o nome da pessoa (ou empresa), o endereço completo "
    "(logradouro, número, bairro, cidade/UF e CEP quando existirem) e o complemento (apto/bloco/sala). "
    "Copie o texto exatamente como está na linha; não corrija, não complete e não invente nada. "
    "Nunca devolva CPF, valores, telefones, e-mails, datas ou números de contrato: marcações "
    "[removido] devem ser ignoradas. Se faltar o nome, devolva string vazia. Ignore cabeçalhos, totais "
    "e linhas sem endereço. 'linha' é o número que precede a linha de entrada."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "entradas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "linha": {"type": "integer"},
                    "nome": {"type": "string"},
                    "endereco": {"type": "string"},
                    "complemento": {"type": "string"},
                },
                "required": ["linha", "nome", "endereco", "complemento"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entradas"],
    "additionalProperties": False,
}


def _anthropic_client():
    import anthropic

    return anthropic.Anthropic()


def _anthropic_ready() -> bool:
    import os
    from pathlib import Path

    try:
        c = _anthropic_client()
    except Exception:
        return False
    return bool(c.api_key or getattr(c, "auth_token", None) or (Path.home() / ".config" / "anthropic").exists())


def _ollama_ready() -> bool:
    try:
        r = httpx.get(f"{SETTINGS.ollama_url}/api/tags", timeout=1.5)
        r.raise_for_status()
        wanted = SETTINGS.ollama_model.split(":")[0]
        return any(m.get("name", "").split(":")[0] == wanted for m in r.json().get("models", []))
    except Exception:
        return False


def llm_provider(enabled: bool | None = None) -> str | None:
    """'ollama' | 'anthropic' | None. enabled=False desliga (testes)."""
    if enabled is False:
        return None
    pref = SETTINGS.llm_provider.lower()
    if pref in ("none", "0", "off"):
        return None
    if pref in ("auto", "ollama") and _ollama_ready():
        return "ollama"
    if pref in ("auto", "anthropic") and _anthropic_ready():
        return "anthropic"
    return None


def _call_ollama(numbered: str) -> str:
    r = httpx.post(
        f"{SETTINGS.ollama_url}/api/chat",
        json={
            "model": SETTINGS.ollama_model, "stream": False, "format": _SCHEMA,
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": numbered}],
        },
        timeout=SETTINGS.ollama_timeout,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def _call_anthropic(numbered: str) -> str:
    resp = _anthropic_client().messages.create(
        model=SETTINGS.claude_model, max_tokens=16000, system=_SYSTEM,
        messages=[{"role": "user", "content": numbered}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("o modelo recusou o trecho")
    return next(b.text for b in resp.content if b.type == "text")


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{2,}", strip_accents(s).lower()))


def _grounded(value: str, line: str, minimum: float = 0.7) -> bool:
    """A resposta do modelo precisa estar na linha original (barra invenção de modelos pequenos)."""
    w = _words(value)
    return bool(w) and len(w & _words(line)) / len(w) >= minimum


def _llm_chunk(provider: str, lines: list[str], offset: int) -> dict[int, RawEntry]:
    numbered = "\n".join(f"{offset + i + 1}: {ln}" for i, ln in enumerate(lines))
    raw = _call_ollama(numbered) if provider == "ollama" else _call_anthropic(numbered)
    out: dict[int, RawEntry] = {}
    for e in json.loads(raw)["entradas"]:
        idx = int(e["linha"]) - 1 - offset
        if not 0 <= idx < len(lines):
            continue
        line = lines[idx]
        address = clean_value(e["endereco"])  # defesa extra: mascara também a saída
        if not address or not _grounded(address, line):
            continue
        name = clean_value(e["nome"])
        out[offset + idx] = RawEntry(name if name and _grounded(name, line, 0.99) else "", address,
                                     clean_value(e["complemento"]))
    return out


def _llm_lines(lines: list[str], rep: ExtractReport, progress: Progress, provider: str) -> list[RawEntry]:
    size = SETTINGS.ollama_chunk if provider == "ollama" else 60
    chunks = [(i, lines[i:i + size]) for i in range(0, len(lines), size)]
    done = 0

    def work(item):
        offset, chunk = item
        try:
            return offset, chunk, _llm_chunk(provider, chunk, offset), None
        except Exception as exc:  # modelo fora do ar/saída inválida: heurística só neste trecho
            return offset, chunk, {}, exc

    got: dict[int, RawEntry] = {}
    fallback = 0
    # IA local usa a máquina toda: um pedido por vez. API em nuvem aceita paralelismo.
    with ThreadPoolExecutor(max_workers=1 if provider == "ollama" else 4) as pool:
        for offset, chunk, res, exc in pool.map(work, chunks):
            if exc is not None:
                rep.notes.append(f"Linhas {offset + 1}-{offset + len(chunk)}: IA indisponível ({type(exc).__name__}); usada heurística local.")
            got.update(res)
            for i, ln in enumerate(chunk):  # cobre o que a IA deixou de fora ou inventou
                if offset + i not in got and _STREET.search(ln):
                    e = _heuristic_line(ln)
                    if e:
                        got[offset + i] = e
                        fallback += 1
            done += 1
            progress(f"Interpretando com IA ({done}/{len(chunks)} blocos)")
    if fallback:
        rep.notes.append(f"{fallback} linha(s) a IA não devolveu ou não bateu com o texto original; usada heurística.")
    rep.rows_read += len(lines)
    return [got[k] for k in sorted(got)]


# --------------------------------------------------------------------------- saída

_COMPL = re.compile(r"\b(?:apto?|apartamento|ap|bloco|bl|sala|casa|fundos|cj|conj|loja|andar|torre)\b\.?\s*\w*", re.I)
_OTHER_CITIES = [c for c in RMPA_CITIES if c != "porto alegre"]
_OTHER_CITY_RE = re.compile(
    r"[,/-]\s*(" + "|".join(re.escape(strip_accents(c)) for c in _OTHER_CITIES) + r")\b", re.I
)


def to_query(address: str) -> str:
    """Endereço limpo para o geocodificador: sem complemento, sempre em Porto Alegre/RS."""
    q = _COMPL.sub(" ", address.split(" - CEP")[0])
    q = re.sub(r"\s*(,\s*)+", ", ", q)           # vírgulas soltas que sobram ao tirar apto/bloco
    q = re.sub(r"\s+", " ", q).strip(" ,")
    if "porto alegre" not in strip_accents(q).lower():
        q += f", {SETTINGS.default_city}, RS"
    return q


def other_city(address: str) -> str | None:
    """Cidade (fora de Porto Alegre) citada como parte final do endereço, se houver."""
    m = _OTHER_CITY_RE.search(strip_accents(address))
    return m.group(1).title() if m else None


def _to_stops(entries: list[RawEntry], rep: ExtractReport) -> list[Stop]:
    stops: list[Stop] = []
    seen: set[str] = set()
    dup = 0
    for e in entries:
        if e.code:
            if e.code in seen:
                dup += 1
                continue
            seen.add(e.code)
        display = e.address + (f" ({e.complement})" if e.complement else "")
        s = Stop(id=len(stops), name=e.name or "(sem nome)", address=display,
                 query=to_query(e.address), code=e.code)
        city = other_city(e.address)
        if city:
            s.status, s.reason = "revisar", f"fora de Porto Alegre ({city}): entregas só na capital"
        stops.append(s)
    if dup:
        rep.notes.append(f"{dup} linha(s) com código de rastreio repetido foram ignoradas (códigos devem ser únicos).")
    return stops


def extract(filename: str, data: bytes, progress: Progress = lambda _m: None,
            force_llm: bool | None = None, mapping: dict | None = None) -> tuple[list[Stop], ExtractReport]:
    """`mapping` = resposta da tela de mapeamento: {"columns": {"name": 1, "addr": 0, ...},
    "header_row": true, "remember": true}. Sem ele, formato desconhecido levanta NeedMapping."""
    rep = ExtractReport()
    name = filename.lower()
    entries: list[RawEntry] = []

    raw_csv_lines: list[str] = []
    if name.endswith((".csv", ".txt")):
        tables = [_read_csv(data)] if name.endswith(".csv") else []
        lines = [] if tables else [ln.strip() for ln in _decode(data).splitlines() if ln.strip()]
        if tables:  # sem cabeçalho reconhecível, o texto original da linha é mais fiel que as células
            raw_csv_lines = [ln.strip() for ln in _decode(data).splitlines() if ln.strip()]
    elif name.endswith((".xlsx", ".xlsm")):
        tables, lines = _read_xlsx(data), []
    elif name.endswith(".xls"):
        raise ValueError("Formato .xls antigo não é suportado: salve como .xlsx ou .csv.")
    elif name.endswith(".pdf"):
        tables, lines = [], _read_pdf(data)
        if not lines:
            raise ValueError("O PDF não tem texto selecionável (parece escaneado). OCR ainda não está na POC.")
    else:
        raise ValueError("Formato não suportado. Envie .xlsx, .csv ou .pdf.")

    progress("Lendo o arquivo")
    free_lines: list[str] = list(lines)
    methods: set[str] = set()
    mapping_used = False
    for rows in tables:
        got: list[RawEntry] | None = None
        tpl = templates.lookup(rows[0]) if rows else None
        if tpl:
            got = _entries_from_table(rows, 0 if tpl.get("header_row", True) else -1, tpl["columns"], rep)
            if got:
                methods.add("modelo salvo")
        if not got:
            found = _find_header(rows)
            if found:
                got = _entries_from_table(rows, found[0], found[1], rep) or None
                if got:
                    methods.add("tabela")
        if not got and mapping and not mapping_used and _looks_tabular(rows):
            mapping_used = True
            cols = {k: int(v) for k, v in mapping["columns"].items() if v is not None and v != ""}
            if "addr" not in cols:
                raise ValueError("Indique qual coluna é o endereço.")
            header_row = bool(mapping.get("header_row", True))
            got = _entries_from_table(rows, 0 if header_row else -1, cols, rep)
            methods.add("colunas indicadas")
            if mapping.get("remember") and header_row:
                templates.save(rows[0], cols)
                rep.notes.append("Formato lembrado: na próxima vez as colunas serão reconhecidas sozinhas.")
        if got:
            entries += got
        elif _looks_tabular(rows) and mapping is None:
            raise NeedMapping(rows[0], [[clean_value(c)[:40] for c in r] for r in rows[1:5]], len(rows) - 1)
        elif raw_csv_lines:
            free_lines += raw_csv_lines
        else:
            free_lines += _table_to_lines(rows, rep)

    if free_lines:
        provider = llm_provider(force_llm)
        masked = []
        for ln in free_lines:
            m, counts = mask_text(ln)
            _count_masks(counts, rep)
            masked.append(m)
        if provider:
            progress("Mascarando dados sensíveis")
            entries += _llm_lines(masked, rep, progress, provider)
            methods.add("ia-local" if provider == "ollama" else "ia-anthropic")
        else:
            rep.notes.append("Nenhuma IA disponível (instale o Ollama: veja o README): usada heurística local, menos precisa.")
            entries += _heuristic_lines(masked, rep)
            methods.add("heuristica")

    rep.method = "+".join(sorted(methods)) or "nenhum"
    if not entries:
        raise ValueError("Nenhum endereço foi encontrado no arquivo.")
    return _to_stops(entries, rep), rep


def _table_to_lines(rows: list[list[str]], rep: ExtractReport) -> list[str]:
    """Linhas de texto de uma tabela sem colunas reconhecidas, sem as colunas de cabeçalho sensível."""
    drop: set[int] = set()
    if rows:
        for i, h in enumerate(rows[0]):
            if h and is_sensitive_header(h):
                drop.add(i)
                rep.dropped_columns.append(h)
    lines = []
    for row in rows:
        cells = [c for i, c in enumerate(row) if i not in drop and c]
        if cells:
            lines.append(", ".join(cells))
    return lines
