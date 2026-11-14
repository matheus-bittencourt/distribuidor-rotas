import httpx

from app import matrix
from app.matrix import osrm_paths


def test_paths_use_osrm_geometry_in_order(monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        return httpx.Response(200, json={"code": "Ok", "routes": [{"geometry": "abc"}]})

    real = httpx.Client
    monkeypatch.setattr(matrix.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    out = osrm_paths([[(-30.0, -51.2), (-30.1, -51.1)], []], base_url="http://osrm")
    assert out == ["abc", None]  # rota sem paradas: nada a traçar
    # OSRM recebe lon,lat na ordem da rota
    assert seen == ["/route/v1/driving/-51.200000,-30.000000;-51.100000,-30.100000"]


def test_paths_fall_back_to_none_when_osrm_fails(monkeypatch):
    real = httpx.Client
    monkeypatch.setattr(matrix.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw))
    assert osrm_paths([[(-30.0, -51.2), (-30.1, -51.1)]], base_url="http://osrm") == [None]
