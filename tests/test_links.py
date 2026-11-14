from urllib.parse import parse_qs, urlparse

from app.links import build_links

DEPOT = (-30.03, -51.23)


def _pts(n):
    return [(-30.0 - i * 0.001, -51.2 + i * 0.001) for i in range(n)]


def _q(link):
    return parse_qs(urlparse(link["url"]).query)


def test_chunks_chain_and_end_at_depot():
    links = build_links(_pts(25), DEPOT, per_link=9)
    assert len(links) == 3  # 26 pontos (25 + final) / 10 por link
    assert links[-1]["ends_at_depot"] and not links[0]["ends_at_depot"]
    for l in links:
        wps = _q(l)["waypoints"][0].split("|") if "waypoints" in _q(l) else []
        assert len(wps) <= 9
    # primeiro link sem origem (usa a localização atual); os demais partem do destino do anterior
    assert "origin" not in _q(links[0]) and _q(links[1])["origin"] == _q(links[0])["destination"]
    assert _q(links[-1])["destination"][0] == f"{DEPOT[0]:.6f},{DEPOT[1]:.6f}"


def test_every_stop_appears_once_in_order():
    stops = _pts(23)
    seen = []
    for l in build_links(stops, DEPOT, start=(-30.1, -51.1), per_link=9):
        q = _q(l)
        if "waypoints" in q:
            seen += q["waypoints"][0].split("|")
        seen.append(q["destination"][0])
    expected = [f"{a:.6f},{b:.6f}" for a, b in stops] + [f"{DEPOT[0]:.6f},{DEPOT[1]:.6f}"]
    assert seen == expected


def test_no_stops_goes_straight_to_depot():
    links = build_links([], DEPOT)
    assert len(links) == 1 and "waypoints" not in links[0]["url"]
