"""Pacote de mapa offline: onde fica, qual versão está ativa e carregamento (uma vez, com recarga após atualizar).

Estrutura da pasta (ao lado do executável, ou MAPDATA_DIR):
  mapa/atual.txt        nome da pasta da versão ativa
  mapa/2026.11.14/      graph.npz, geoindex.json.gz, basemap.pmtiles, info.json
Uma pasta com os arquivos direto dentro (sem atual.txt) também serve, para desenvolvimento.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from .config import SETTINGS

_lock = threading.Lock()
_cache: dict[str, object] = {}


def base_dir() -> Path:
    """Pasta do app: ao lado do executável (pen drive) ou a raiz do projeto."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def root() -> Path:
    return Path(SETTINGS.mapdata_dir) if SETTINGS.mapdata_dir else base_dir() / "mapa"


def active_dir() -> Path | None:
    r = root()
    if (r / "graph.npz").exists():
        return r
    cur = r / "atual.txt"
    if cur.exists():
        d = r / cur.read_text(encoding="utf-8").strip()
        if (d / "graph.npz").exists():
            return d
    return None


def info() -> dict | None:
    d = active_dir()
    if not d:
        return None
    try:
        return json.loads((d / "info.json").read_text(encoding="utf-8"))
    except Exception:
        return {"version": d.name}


def _get(name: str, factory):
    d = active_dir()
    if d is None:
        raise RuntimeError("Pacote de mapa não instalado: baixe o mapa na tela inicial ou copie a pasta 'mapa'.")
    key = f"{name}:{d}"
    with _lock:
        if key not in _cache:
            for k in [k for k in _cache if not k.endswith(f":{d}")]:
                del _cache[k]          # versão anterior do mapa: libera a memória
            _cache[key] = factory(d)
        return _cache[key]


def router():
    from .router import LocalRouter
    return _get("router", LocalRouter)


def geocoder():
    from .localgeo import LocalGeocoder
    return _get("geo", LocalGeocoder)


def basemap_path() -> Path | None:
    d = active_dir()
    p = d / "basemap.pmtiles" if d else None
    return p if p and p.exists() else None


def reset() -> None:
    """Esquece o que estava carregado (depois de instalar uma versão nova)."""
    with _lock:
        _cache.clear()
