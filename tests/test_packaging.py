"""O executável (PyInstaller) só leva os arquivos de dados listados no .spec: todo app/*.json precisa estar lá."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_app_json_is_bundled_in_the_spec():
    spec = (ROOT / "distribuidor.spec").read_text(encoding="utf-8")
    missing = [p.name for p in (ROOT / "app").glob("*.json") if f"app/{p.name}" not in spec]
    assert not missing, f"faltam no distribuidor.spec (datas): {missing}"
