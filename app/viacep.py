"""ViaCEP: completa o endereço com o bairro antes de geocodificar (opcional, VIACEP=1).

A API devolve dados no nível da RUA (CEP, bairro, faixa de numeração); não tem latitude nem número da casa.
Por isso ela não substitui o geocodificador: só acrescenta o bairro à consulta quando a rua é inequívoca.
Sai da máquina apenas o NOME DA RUA (nunca nome do destinatário, número da casa ou código de rastreio).

Regras de segurança: se a rua não é achada, tem mais de um bairro sem faixa que decida, ou a API falha,
a consulta segue exatamente como estava. O resultado (inclusive "não achada") fica num cache em disco.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

import httpx

from .config import SETTINGS
from .sanitize import strip_accents


def split_query(query: str) -> tuple[str, int | None, str]:
    """('Rua X', 123, ', Porto Alegre, RS') a partir de 'Rua X, 123, Porto Alegre, RS'. Número pode ser None."""
    parts = [p.strip() for p in query.split(",")]
    street = parts[0] if parts else ""
    number = None
    rest_from = 1
    if len(parts) > 1:
        m = re.fullmatch(r"(\d+)[a-zA-Z]?", parts[1])
        if m:
            number, rest_from = int(m.group(1)), 2
    return street, number, ", ".join(parts[rest_from:])


def number_in(complemento: str, n: int) -> bool | None:
    """A faixa da API ('de 1 a 99 - lado ímpar', 'até 1000/1001', 'de 1001/1002 ao fim', 'lado par') inclui n?
    None = a descrição não diz nada que dê para checar."""
    c = strip_accents(complemento or "").lower()
    side = "par" if "lado par" in c else "impar" if "lado impar" in c else None
    if side and (n % 2 == 0) != (side == "par"):
        return False
    nums = [int(x) for x in re.findall(r"\d+", c)]
    if "ao fim" in c and nums:
        return n >= nums[0]
    if c.startswith("ate") and nums:
        return n <= nums[0]
    if re.match(r"de \d", c) and len(nums) >= 2 and " a " in c:
        return nums[0] <= n <= nums[1]
    return True if side else None


class ViaCep:
    def __init__(self, cache_path: str | None = None):
        self._lock = threading.Lock()
        self._last = 0.0
        self._path = Path(cache_path or SETTINGS.viacep_cache)
        self._cache: dict[str, list[dict]] = {}
        if self._path.exists():
            try:
                self._cache = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._cache = {}
        self._client = httpx.Client(timeout=15, headers={"User-Agent": SETTINGS.nominatim_user_agent})
        self.calls = 0

    def _throttle(self) -> None:
        gap = 1.0 / max(SETTINGS.viacep_rate, 0.01)
        with self._lock:
            wait = self._last + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def search(self, street: str) -> list[dict] | None:
        """CEPs de Porto Alegre para o nome da rua (None = falha de rede; não entra no cache)."""
        key = strip_accents(street).lower().strip()
        if len(key) < 3:
            return []
        if key in self._cache:
            return self._cache[key]
        self._throttle()
        url = f"{SETTINGS.viacep_url.rstrip('/')}/ws/RS/{quote(SETTINGS.default_city)}/{quote(street)}/json/"
        try:
            r = self._client.get(url)
            if r.status_code == 400:
                rows = []
            else:
                r.raise_for_status()
                data = r.json()
                rows = [{k: x.get(k, "") for k in ("cep", "logradouro", "complemento", "bairro")}
                        for x in data if isinstance(x, dict) and "erro" not in x
                        and strip_accents(x.get("localidade", "")).lower() == "porto alegre"]
        except (httpx.HTTPError, ValueError):
            return None
        self.calls += 1
        self._cache[key] = rows
        self._save()
        return rows

    def bairro_for(self, query: str) -> str | None:
        """Bairro da rua da consulta, se a API o determina sem ambiguidade."""
        street, number, _ = split_query(query)
        rows = self.search(street)
        if not rows:
            return None
        # a API faz busca aproximada: só vale linha cujo logradouro tem o mesmo nome (sem acento/caixa)
        want = strip_accents(street).lower()
        exact = [x for x in rows if strip_accents(x["logradouro"]).lower() == want] or []
        rows = exact or rows
        bairros = {x["bairro"] for x in rows if x["bairro"]}
        if len(bairros) == 1:
            return next(iter(bairros))
        if number is not None:
            fits = {x["bairro"] for x in rows if x["bairro"] and number_in(x["complemento"], number)}
            known = {x["bairro"] for x in rows if x["bairro"] and number_in(x["complemento"], number) is not None}
            if len(fits) == 1 and known:
                return next(iter(fits))
        return None

    def enrich(self, query: str) -> str:
        """'Rua X, 123, Porto Alegre, RS' -> 'Rua X, 123, Bairro, Porto Alegre, RS' (ou igual, se não der)."""
        bairro = self.bairro_for(query)
        if not bairro or strip_accents(bairro).lower() in strip_accents(query).lower():
            return query
        street, number, rest = split_query(query)
        head = f"{street}, {number}" if number is not None else street
        return f"{head}, {bairro}, {rest}" if rest else f"{head}, {bairro}"


class Enriched:
    """Envolve um geocodificador: tenta com o bairro e, se não achar, volta à consulta original."""

    def __init__(self, inner, viacep: ViaCep | None = None):
        self.inner, self.viacep = inner, viacep or ViaCep()

    def geocode(self, query: str, wide: bool = False):
        if not wide:  # pontos de partida (casas) ficam como estão
            better = self.viacep.enrich(query)
            if better != query:
                hit = self.inner.geocode(better, wide=wide)
                if hit:
                    return hit
        return self.inner.geocode(query, wide=wide)
