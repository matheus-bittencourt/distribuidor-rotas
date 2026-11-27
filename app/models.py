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
    pages: list[int] = field(default_factory=list)  # páginas desta entrega no PDF original (intimações)
    src_query: str = ""     # consulta como veio da lista (a chave da memória de endereços corrigidos)
    src: int = 0            # de qual arquivo enviado veio (posição na lista de envio)
    file: str = ""          # nome desse arquivo

    def __post_init__(self):
        if not self.src_query:
            self.src_query = self.query

    def public(self) -> dict:
        return {
            "id": self.id, "name": self.name, "address": self.address, "code": self.code, "file": self.file,
            "status": self.status, "lat": self.lat, "lon": self.lon,
            "precision": self.precision, "reason": self.reason, "zone": self.zone,
            "pages": [p + 1 for p in self.pages],  # numeração do PDF original, começando em 1
        }


@dataclass
class RawEntry:
    name: str
    address: str
    complement: str = ""   # apto/bloco: só para exibição, não vai ao geocodificador
    code: str = ""
    pages: list[int] = field(default_factory=list)
    query: str = ""        # consulta para o mapa, quando difere do endereço (via interna de condomínio)


@dataclass
class ExtractReport:
    method: str = ""                      # tabela | modelo salvo | ia-local | ia-anthropic | heuristica
    rows_read: int = 0
    masked: dict[str, int] = field(default_factory=dict)
    dropped_columns: list[str] = field(default_factory=list)
    skipped_lines: int = 0
    notes: list[str] = field(default_factory=list)
