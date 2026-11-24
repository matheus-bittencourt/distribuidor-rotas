"""Estado em memória de cada processamento. Nada de nomes/endereços vai para disco.

Cada job expira após JOB_TTL_MINUTES (e pode ser apagado na hora via DELETE).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from .config import SETTINGS
from .models import ExtractReport, Stop


@dataclass
class Job:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=time.time)
    state: str = "lendo"          # lendo | mapear | geocodificando | revisao | calculando | pronto | erro
    # Arquivos ainda não lidos, (posição, nome, bytes): o primeiro fica aqui enquanto espera o mapeamento de colunas.
    queue: list[tuple[int, str, bytes]] = field(default_factory=list)
    n_files: int = 1              # quantos arquivos vieram no envio
    files: list[dict] = field(default_factory=list)   # resultado por arquivo (nome, entregas, duplicadas, erro)
    parts: list[tuple[str, ExtractReport]] = field(default_factory=list)   # relatório de leitura de cada arquivo
    codes: set[str] = field(default_factory=set)      # códigos de rastreio já vistos (repetidos entre arquivos saem)
    mapping_info: dict | None = None
    message: str = ""
    progress: tuple[int, int] = (0, 0)
    error: str = ""
    stops: list[Stop] = field(default_factory=list)
    report: ExtractReport | None = None
    result: dict | None = None
    # PDFs de intimações: os originais ficam na memória enquanto o job existe (por posição no envio), para
    # montar o PDF de cada entregador com as páginas das entregas dele. Somem junto com o job.
    sources: dict[int, bytes] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def _purge() -> None:
    cutoff = time.time() - SETTINGS.job_ttl_minutes * 60
    for jid in [j for j, job in _JOBS.items() if job.created < cutoff]:
        _JOBS.pop(jid, None)


def create() -> Job:
    with _LOCK:
        _purge()
        job = Job()
        _JOBS[job.id] = job
        return job


def get(job_id: str) -> Job | None:
    with _LOCK:
        _purge()
        return _JOBS.get(job_id)


def count() -> int:
    """Quantos processamentos (com dados de entrega) estão na memória agora."""
    with _LOCK:
        _purge()
        return len(_JOBS)


def delete(job_id: str) -> bool:
    with _LOCK:
        return _JOBS.pop(job_id, None) is not None
