"""Memória de endereços corrigidos (opcional, desligada por padrão).

Quando o operador corrige um endereço na revisão (cola coordenadas ou ajusta o texto até o mapa achar), o texto
original da lista e as coordenadas ficam em data/enderecos.json, ao lado do executável. No dia seguinte, o mesmo
endereço sai localizado sozinho. O arquivo guarda SÓ o texto do endereço e a posição: nenhum nome, CPF, telefone ou
código de rastreio. Só grava se o operador ligar a opção; "Esquecer" apaga tudo.
"""
from __future__ import annotations

import json
import os
import re
import threading

from .mapdata import base_dir
from .sanitize import strip_accents

PATH = base_dir() / "data" / "enderecos.json"
MAX_ITEMS = 5000
_LOCK = threading.Lock()


def key(query: str) -> str:
    """Mesma rua escrita com outra caixa, acento ou espaçamento é o mesmo endereço."""
    return re.sub(r"\s+", " ", strip_accents(query or "")).strip().lower()


def _load() -> dict:
    try:
        d = json.loads(PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _write(d: dict) -> None:
    PATH.parent.mkdir(exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, PATH)


def enabled() -> bool:
    return bool(_load().get("enabled"))


def count() -> int:
    return len(_load().get("items", {}))


def set_enabled(on: bool) -> None:
    with _LOCK:
        d = _load()
        d["enabled"] = bool(on)
        d.setdefault("items", {})
        _write(d)


def get(query: str) -> tuple[float, float] | None:
    d = _load()
    if not d.get("enabled"):
        return None
    hit = d.get("items", {}).get(key(query))
    return (float(hit[0]), float(hit[1])) if hit else None


def remember(query: str, lat: float, lon: float) -> bool:
    """Guarda (só com a opção ligada). Devolve se gravou."""
    k = key(query)
    if not k:
        return False
    with _LOCK:
        d = _load()
        if not d.get("enabled"):
            return False
        items = d.setdefault("items", {})
        items.pop(k, None)
        items[k] = [round(lat, 6), round(lon, 6)]
        while len(items) > MAX_ITEMS:           # passou do limite: os mais antigos saem
            items.pop(next(iter(items)))
        _write(d)
        return True


def forget_all() -> int:
    with _LOCK:
        d = _load()
        n = len(d.get("items", {}))
        d["items"] = {}
        _write(d)
        return n
