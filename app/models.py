from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Stop:
    id: int
    name: str
    address: str            # como será exibido ao entregador
    query: str              # o que vai para o geocodificador
    code: str = ""          # código de rastreio (único por entrega)
    status: str = "pendente"  # pendente | ok | revisar | descartado
    lat: float | None = None
    lon: float | None = None
    precision: str = ""     # exato | aproximado | manual
    reason: str = ""        # motivo quando status == revisar
    zone: str = ""

    def public(self) -> dict:
        return {
            "id": self.id, "name": self.name, "address": self.address, "code": self.code,
            "status": self.status, "lat": self.lat, "lon": self.lon,
            "precision": self.precision, "reason": self.reason, "zone": self.zone,
        }


@dataclass
class RawEntry:
    name: str
    address: str
    complement: str = ""   # apto/bloco: só para exibição, não vai ao geocodificador
    code: str = ""


@dataclass
class ExtractReport:
    method: str = ""                      # tabela | modelo salvo | ia-local | ia-anthropic | heuristica
    rows_read: int = 0
    masked: dict[str, int] = field(default_factory=dict)
    dropped_columns: list[str] = field(default_factory=list)
    skipped_lines: int = 0
    notes: list[str] = field(default_factory=list)
