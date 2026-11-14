"""Links do Google Maps para cada rota, fragmentados.

O Google Maps (URL de direções) aceita um número limitado de pontos intermediários por link
(documentado: 9 waypoints), longe das 50-170 paradas por entregador. A rota é então partida em
trechos encadeados: o destino de um link é a origem do próximo.

No primeiro link a origem é omitida de propósito: o Maps usa a LOCALIZAÇÃO ATUAL do celular de
quem abre, que é o ponto de partida do entregador.
"""
from __future__ import annotations

from urllib.parse import quote

Point = tuple[float, float]


def _fmt(p: Point) -> str:
    return f"{p[0]:.6f},{p[1]:.6f}"


def build_links(
    stops: list[Point], depot: Point, start: Point | None = None, per_link: int = 9,
) -> list[dict]:
    """stops em ordem de visita; o último destino é sempre o ponto final fixo (`depot`).

    Cada link cobre até per_link + 1 paradas (per_link intermediárias + o destino do trecho).
    Devolve [{url, first, last, count}] com índices (1-based) das paradas cobertas.
    """
    seq: list[Point] = [*stops, depot]
    links, origin, i = [], start, 0
    step = per_link + 1
    while i < len(seq):
        chunk = seq[i:i + step]
        dest, waypoints = chunk[-1], chunk[:-1]
        url = "https://www.google.com/maps/dir/?api=1&travelmode=driving"
        if origin is not None:
            url += f"&origin={_fmt(origin)}"
        url += f"&destination={_fmt(dest)}"
        if waypoints:
            url += "&waypoints=" + quote("|".join(_fmt(w) for w in waypoints), safe=",")
        is_last = i + step >= len(seq)
        links.append({
            "url": url,
            "first": i + 1,
            "last": min(i + step, len(stops)),
            "count": len(chunk),
            "ends_at_depot": is_last,
        })
        origin = dest
        i += step
    return links
