"""Zonas desenhadas, salvas em data/zonas.json (ao lado do executável, então acompanham o pen drive).

Guarda contorno, nome, forma de atendimento e os nomes dos entregadores escolhidos para cada zona. Nenhum dado
de entrega (nome de cliente, endereço) vai para este arquivo.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .mapdata import base_dir

PATH = base_dir() / "data" / "zonas.json"
_LOCK = threading.Lock()
MAX_ZONES = 50


class SavedZone(BaseModel):
    name: str = Field("", max_length=60)
    profile: Literal["moto", "pe"] = "moto"
    labels: list[str] = Field(default_factory=list, max_length=40)     # nomes dos entregadores da zona
    start: str = Field("", max_length=200)                              # perfil a pé: ponto de saída (opcional)
    edge: float = Field(0.0, ge=0, le=500)
    poly: list[tuple[float, float]] = Field(min_length=3, max_length=500)   # [lat, lon]


class SavedZones(BaseModel):
    zones: list[SavedZone] = Field(default_factory=list, max_length=MAX_ZONES)


def load() -> SavedZones:
    try:
        return SavedZones.model_validate_json(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return SavedZones()


def save(data: SavedZones) -> None:
    with _LOCK:
        PATH.parent.mkdir(exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, PATH)       # troca inteira: um corte no meio da gravação não deixa o arquivo pela metade
