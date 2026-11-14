"""Modelos de planilha salvos: "neste formato, a coluna X é o nome, a Y é o endereço".

Guarda só NOMES DE COLUNAS (nenhum dado de entrega), em data/templates.json.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .sanitize import norm_header

from .mapdata import base_dir  # noqa: E402

PATH = base_dir() / "data" / "templates.json"   # ao lado do executável no pen drive
_LOCK = threading.Lock()


def signature(header: list[str]) -> str:
    return "|".join(norm_header(h) for h in header)


def _load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def lookup(header: list[str]) -> dict | None:
    return _load().get(signature(header))


def save(header: list[str], columns: dict[str, int], header_row: bool = True) -> None:
    with _LOCK:
        data = _load()
        data[signature(header)] = {
            "columns": {k: int(v) for k, v in columns.items()},
            "header_row": header_row,
            "labels": {k: header[int(v)] for k, v in columns.items() if int(v) < len(header)},
        }
        PATH.parent.mkdir(exist_ok=True)
        PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def all_templates() -> dict:
    return _load()
