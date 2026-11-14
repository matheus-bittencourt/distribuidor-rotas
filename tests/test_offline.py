"""Modo isolado, pacote de mapa (roteador e endereços locais) e atualização assinada."""
import base64
import gzip
import hashlib
import json
import socket
import zipfile

import numpy as np
import pytest
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import mapdata, netguard, updater
from app.localgeo import LocalGeocoder
from app.router import LocalRouter, encode_polyline
from app.streetnames import core_key, full_key, parse_query, split_number


# ------------------------------------------------------------------ nomes e consultas
def test_street_names_normalize_abbreviations():
    assert full_key("Av. Dr. Nilo Peçanha") == "avenida doutor nilo pecanha"
    assert core_key("Rua Gen. Lima e Silva") == core_key("Avenida General Lima e Silva") == "lima silva"
    assert parse_query("Rua Bento Balduino dos Santos, 1865, Porto Alegre, RS") == ("Rua Bento Balduino dos Santos", 1865)
    assert parse_query("Acesso 2, 1727, Porto Alegre, RS") == ("Acesso 2", 1727)     # o "2" é do nome
    assert parse_query("Rua X nº 45, Centro, Porto Alegre") == ("Rua X", 45)
    # "Av Mostardeiros 322": ambíguo sem o índice ("Acesso 2" também termina em número); o geocodificador decide
    assert parse_query("Av Mostardeiros 322, Moinhos de Vento, Porto Alegre") == ("Av Mostardeiros 322", None)
    assert split_number("Av Mostardeiros 322") == ("Av Mostardeiros", 322)
    assert parse_query("Rua Sem Número, Centro, Porto Alegre") == ("Rua Sem Número", None)


# ------------------------------------------------------------------ pacote de mapa sintético
def _graph(folder):
    """Três cruzamentos em linha (A - B - C, 1 km cada) + atalho só de ida A->C mais lento."""
    lat = np.array([-30.03, -30.03, -30.03]); lon = np.array([-51.23, -51.2196, -51.2092])
    eu = np.array([0, 1, 1, 2, 0], np.int32); ev = np.array([1, 0, 2, 1, 2], np.int32)
    d = np.array([1000, 1000, 1000, 1000, 1500], np.float32)
    t = np.array([100, 100, 100, 100, 400], np.float32)
    ptr, glat, glon = [0], [], []
    for a, b in zip(eu, ev):
        glat += [lat[a], lat[b]]; glon += [lon[a], lon[b]]; ptr.append(len(glat))
    np.savez_compressed(folder / "graph.npz", node_lat=lat, node_lon=lon, snap=np.ones(3, bool),
                        edge_u=eu, edge_v=ev, edge_t=t, edge_d=d, geom_ptr=np.array(ptr),
                        geom_lat=np.rint(np.array(glat) * 1e6).astype(np.int32),
                        geom_lon=np.rint(np.array(glon) * 1e6).astype(np.int32))


def _geoindex(folder):
    streets = [
        {"n": "Avenida Mostardeiros", "k": full_key("Avenida Mostardeiros"), "c": core_key("Avenida Mostardeiros"),
         "poa": True, "ctr": [-30.025, -51.205], "pts": [[-30.02, -51.205], [-30.03, -51.205]],
         "a": [[300, -30.0260, -51.2060], [400, -30.0270, -51.2070]]},
        {"n": "Rua São Paulo", "k": full_key("Rua São Paulo"), "c": core_key("Rua São Paulo"),
         "poa": False, "ctr": [-29.9, -51.1], "pts": [[-29.9, -51.1]], "a": []},
    ]
    with gzip.open(folder / "geoindex.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"streets": streets}, f)
    (folder / "info.json").write_text(json.dumps({"version": "2026.01.01"}))


def test_router_time_and_distance_follow_the_fastest_path(tmp_path):
    _graph(tmp_path)
    r = LocalRouter(tmp_path)
    pts = np.array([[-30.03, -51.23], [-30.03, -51.2092]])
    T, D, ok = r.matrix(pts)
    assert ok.all()
    # A->C: por B (200 s, 2 km) é mais rápido que o atalho (400 s, 1,5 km): a distância é a do caminho rápido
    assert T[0, 1] == pytest.approx(200, abs=1) and D[0, 1] == pytest.approx(2000, abs=1)
    assert T[1, 0] == pytest.approx(200, abs=1)
    line = r.paths([[(-30.03, -51.23), (-30.03, -51.2092)]])[0]
    assert line and isinstance(line, str)


def test_polyline_encoding_matches_reference():
    # exemplo da documentação do formato
    assert encode_polyline([[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"


def test_local_geocoder_exact_interpolated_and_street_level(tmp_path):
    _geoindex(tmp_path)
    g = LocalGeocoder(tmp_path)
    hit = g.geocode("Av. Mostardeiros, 300, Porto Alegre, RS")
    assert (hit.lat, hit.lon, hit.precision) == (-30.026, -51.206, "exato")
    mid = g.geocode("Avenida Mostardeiros, 350, Porto Alegre, RS")
    assert mid.precision == "exato" and mid.lat == pytest.approx(-30.0265)
    far = g.geocode("Mostardeiros, 3000, Porto Alegre, RS")
    assert far.precision == "aproximado" and [far.lat, far.lon] == [-30.025, -51.205]
    assert g.geocode("Rua São Paulo, 10, Porto Alegre, RS") is None          # só existe fora da capital
    assert g.geocode("Rua São Paulo, 10", wide=True) is not None             # partida pode ser na região
    assert g.geocode("Avenida Mostarderos, 300, Porto Alegre") is not None   # erro de digitação
    glued = g.geocode("Av Mostardeiros 300, Moinhos de Vento, Porto Alegre")  # número colado no nome
    assert glued and glued.precision == "exato" and glued.lat == -30.026


# ------------------------------------------------------------------ modo isolado
def test_netguard_blocks_outside_but_allows_localhost():
    netguard.install()
    try:
        with pytest.raises(socket.gaierror):
            socket.getaddrinfo("example.com", 443)
        with pytest.raises(OSError):
            socket.create_connection(("93.184.215.14", 443), timeout=1)
        s = socket.socket()
        with pytest.raises(ConnectionRefusedError):      # conexão direta por IP, sem resolver nome
            s.connect(("93.184.215.14", 443))
        s.close()
        assert socket.getaddrinfo("127.0.0.1", 80)
        # a janela de atualização libera só os domínios do GitHub, e só nesta thread
        with netguard.update_window():
            assert netguard._host_ok("github.com")
            assert not netguard._host_ok("example.com")
        assert not netguard._host_ok("github.com")
    finally:
        netguard.uninstall()


# ------------------------------------------------------------------ atualização
def _keys():
    k = Ed25519PrivateKey.generate()
    pub = base64.b64encode(k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)).decode()
    return k, pub


def test_signature_rejects_tampered_manifest():
    k, pub = _keys()
    raw = b'{"version": "2026.02.01"}'
    sig = base64.b64encode(k.sign(raw)).decode()
    assert updater.verify_signature(raw, sig, pub)
    assert not updater.verify_signature(raw.replace(b"02", b"03"), sig, pub)
    assert not updater.verify_signature(raw, sig, _keys()[1])     # outra chave


def test_install_zip_switches_version_and_keeps_previous(tmp_path, monkeypatch):
    monkeypatch.setattr(mapdata, "root", lambda: tmp_path / "mapa")
    for ver in ("2026.01.01", "2026.02.01", "2026.03.01"):
        src = tmp_path / f"src{ver}"; src.mkdir()
        _graph(src); _geoindex(src); (src / "info.json").write_text(json.dumps({"version": ver}))
        z = tmp_path / f"{ver}.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in src.iterdir():
                zf.write(f, f.name)
        updater.install_zip(z, ver)
        assert mapdata.info()["version"] == ver
    kept = sorted(d.name for d in (tmp_path / "mapa").iterdir() if d.is_dir())
    assert kept == ["2026.02.01", "2026.03.01"]     # a atual e a anterior


def test_install_zip_refuses_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(mapdata, "root", lambda: tmp_path / "mapa")
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../fora.txt", "x")
    with pytest.raises(ValueError):
        updater.install_zip(z, "2026.04.01")
    assert not (tmp_path / "fora.txt").exists()


def test_check_skips_network_while_a_list_is_open(monkeypatch):
    from app import jobs
    monkeypatch.setattr(updater, "prefs", lambda: {"verificar_mapa": True})
    monkeypatch.setattr(jobs, "count", lambda: 1)
    calls = []
    monkeypatch.setattr(updater, "_client", lambda: calls.append(1))
    updater._state.clear(); updater._state["state"] = "idle"
    assert updater.check()["state"] == "busy" and not calls


def test_check_reports_available_with_valid_signature(monkeypatch):
    import httpx
    from app import jobs
    k, pub = _keys()
    man = json.dumps({"version": "2099.01.01", "size": 10, "sha256": hashlib.sha256(b"").hexdigest(),
                      "url": "https://github.com/x/y/releases/download/mapa-2099.01.01/m.zip"}).encode()
    sig = base64.b64encode(k.sign(man)).decode()
    routes = {"manifest.json": man, "manifest.sig": sig.encode()}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=routes[req.url.path.rsplit("/", 1)[1]]))
    monkeypatch.setattr(updater, "_client", lambda: httpx.Client(transport=transport))
    monkeypatch.setattr(updater, "PUBLIC_KEY_B64", pub)
    monkeypatch.setattr(updater, "prefs", lambda: {"verificar_mapa": True})
    monkeypatch.setattr(jobs, "count", lambda: 0)
    updater._state.clear(); updater._state["state"] = "idle"
    out = updater.check()
    assert out["state"] == "available" and out["version"] == "2099.01.01"
    # assinatura de outra chave: recusa
    routes["manifest.sig"] = base64.b64encode(_keys()[0].sign(man))
    assert updater.check(force=True)["state"] == "error"
