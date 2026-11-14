from app.geocode import Cache, geocode_stops
from app.models import Stop


def test_cache_geocoder(tmp_path):
    f = tmp_path / "g.csv"
    f.write_text("query;lat;lon;precisao\nRua A, 10, Porto Alegre, RS;-30.05;-51.2;aproximado\n", encoding="utf-8")
    stops = [Stop(0, "Ana", "Rua A, 10", "Rua A, 10, Porto Alegre, RS"),
             Stop(1, "Bia", "Rua B, 1", "Rua B, 1, Porto Alegre, RS")]
    geocode_stops(stops, geocoder=Cache(str(f)))
    assert stops[0].status == "ok" and (stops[0].lat, stops[0].precision) == (-30.05, "aproximado")
    assert stops[1].status == "revisar"
