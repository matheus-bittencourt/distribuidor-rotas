"""Mascaramento local de dados sensíveis.

Roda ANTES de qualquer texto sair da máquina (LLM) e também sobre o que volta dele.
O objetivo é que só nome e endereço sobrevivam. CEP é preservado (faz parte do endereço).
"""
from __future__ import annotations

import re
import unicodedata

MASK = "[removido]"

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cnpj", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")),
    ("cpf", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("valor", re.compile(r"R\$\s*\d[\d.]*(?:,\d{1,2})?|\b\d{1,3}(?:\.\d{3})*,\d{2}\b", re.I)),
    ("data", re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")),
    ("telefone", re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-\d{4}\b|\b9?\d{4}-\d{4}\b|\(\d{2}\)\s?9?\d{8}\b")),
    # sequências longas de dígitos (contrato, protocolo, RG, conta...). CEP tem 8 dígitos e fica.
    ("numero_longo", re.compile(r"\b\d{9,}\b")),
]

# Cabeçalhos de coluna que indicam dado sensível: a coluna inteira é descartada.
_SENSITIVE_HEADER_WORDS = (
    "cpf", "cnpj", "rg", "documento", "valor", "divida", "debito", "saldo", "parcela",
    "juros", "multa", "vencimento", "nascimento", "telefone", "celular",
    "fone", "whats", "email", "e-mail", "contrato", "protocolo", "acordo", "titulo",
    "inscricao", "matricula", "conta", "banco", "mae", "pai", "renda", "score",
)


_LABEL_BEFORE_MASK = re.compile(
    r"(?:\b(?:cpf|cnpj|rg|tel|telefone|cel|celular|fone|whats(?:app)?|deve|devendo|valor|d[ií]vida|"
    r"d[eé]bito|contrato|e-?mail|nasc|venc\w*)\b[.:]*\s*)+(?:de\s+)?" + re.escape(MASK),
    re.I,
)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", strip_accents(str(h)).lower()).strip()


def is_sensitive_header(header: str) -> bool:
    words = norm_header(header).split()
    for w in _SENSITIVE_HEADER_WORDS:
        w = norm_header(w)
        if w in words or (len(w) > 4 and any(x.startswith(w) for x in words)):
            return True
    return False


def mask_text(text: str) -> tuple[str, dict[str, int]]:
    """Troca padrões sensíveis por [removido]. Devolve o texto e a contagem por tipo."""
    counts: dict[str, int] = {}
    for name, pat in _PATTERNS:
        text, n = pat.subn(MASK, text)
        if n:
            counts[name] = counts.get(name, 0) + n
    return text, counts


def clean_value(text: str) -> str:
    """Máscara + remove marcas e espaços duplicados (usado em campos que vão para a tela)."""
    masked, _ = mask_text(text)
    # some também o rótulo que acompanhava o dado ("CPF [removido]", "deve [removido]")
    masked = _LABEL_BEFORE_MASK.sub(" ", masked).replace(MASK, " ")
    return re.sub(r"\s+", " ", masked).strip(" ,;-")
