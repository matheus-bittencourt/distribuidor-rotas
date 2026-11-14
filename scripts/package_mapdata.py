"""Empacota e assina o pacote de mapa para publicação (release do GitHub).

Uso:
  python scripts/package_mapdata.py dist/mapa --out dist/release [--url-base URL]

Gera em --out:
  mapa-<versão>.zip   arquivos do pacote
  manifest.json       versão, tamanho, SHA-256 e URL do zip
  manifest.sig        assinatura Ed25519 do manifest.json (base64)

A chave privada vem de MAPA_SIGNING_KEY (base64, 32 bytes) ou de ~/.distribuidor-rotas/mapa_assinatura.key.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import zipfile
from pathlib import Path

REPO = "matheus-bittencourt/distribuidor-rotas"


def load_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = os.environ.get("MAPA_SIGNING_KEY")
    if not raw:
        raw = (Path.home() / ".distribuidor-rotas" / "mapa_assinatura.key").read_text()
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw.strip()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--url-base", default=f"https://github.com/{REPO}/releases/download")
    a = ap.parse_args()
    info = json.loads((a.src / "info.json").read_text(encoding="utf-8"))
    ver = info["version"]
    a.out.mkdir(parents=True, exist_ok=True)
    z = a.out / f"mapa-{ver}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:   # já comprimidos: zip só agrupa
        for f in sorted(a.src.iterdir()):
            if f.is_file():
                zf.write(f, f.name)
    h = hashlib.sha256(z.read_bytes()).hexdigest()
    man = {"format": 1, "version": ver, "built": info.get("built", ""), "size": z.stat().st_size, "sha256": h,
           "url": f"{a.url_base}/mapa-{ver}/{z.name}", "source": info.get("source", "")}
    raw = json.dumps(man, ensure_ascii=False, indent=2).encode("utf-8")
    (a.out / "manifest.json").write_bytes(raw)
    (a.out / "manifest.sig").write_text(base64.b64encode(load_key().sign(raw)).decode())
    print(json.dumps(man, ensure_ascii=False))


if __name__ == "__main__":
    main()
