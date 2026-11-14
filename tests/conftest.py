import os
import sys
from pathlib import Path

os.environ["GEOCODER"] = "fake"
os.environ["MATRIX"] = "haversine"
os.environ["LLM_PROVIDER"] = "none"
os.environ["OFFLINE"] = "0"                       # o bloqueio de rede é testado à parte (test_offline.py)
os.environ["MAPDATA_DIR"] = str(Path(__file__).resolve().parent / "_sem_mapa")   # nenhum pacote real
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture(autouse=True)
def _isolated_templates(tmp_path, monkeypatch):
    """Cada teste usa seu próprio arquivo de modelos salvos."""
    from app import templates

    monkeypatch.setattr(templates, "PATH", tmp_path / "templates.json")
