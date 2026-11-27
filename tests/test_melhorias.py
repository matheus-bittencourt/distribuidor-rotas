"""Melhorias do dia: trânsito esperado (fator no tempo de deslocamento das motos)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_pedestrian import OUTSIDE, _job_with  # noqa: E402
from test_zone_groups import _solve  # noqa: E402


def test_transito_aumenta_so_o_tempo_de_deslocamento():
    jid = _job_with(OUTSIDE)
    base = _solve(jid, [])
    slow = _solve(jid, [], traffic=1.4)
    assert base["traffic"] == 1.0 and slow["traffic"] == 1.4
    b, s = base["drivers"], slow["drivers"]
    assert sum(d["travel_min"] for d in s) > sum(d["travel_min"] for d in b) * 1.2     # o deslocamento cresce
    assert sum(d["km"] for d in s) == sum(d["km"] for d in b)                          # os km não mudam
    assert sum(d["deliveries"] for d in s) == sum(d["deliveries"] for d in b)          # nem as paradas


def test_transito_fora_da_faixa_e_recusado():
    from test_zone_groups import client

    jid = _job_with(OUTSIDE)
    for bad in (0.5, 3):
        r = client.post(f"/api/jobs/{jid}/solve", json={"depot": {"address": ""}, "drivers": [{"label": "A"}], "traffic": bad})
        assert r.status_code == 422
