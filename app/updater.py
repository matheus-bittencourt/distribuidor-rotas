"""Atualização do pacote de mapa: manifesto assinado nos releases do GitHub, download retomável e troca atômica.

Regras de isolamento:
- a verificação só acontece com NENHUMA lista na memória (antes de abrir o arquivo do dia);
- só o manifesto e o pacote trafegam: nenhum endereço, nome ou identificador sai do computador;
- o pacote só é usado se a assinatura do manifesto (Ed25519, chave pública embutida) e o SHA-256 conferem;
- a versão anterior fica guardada; "nunca verificar" desliga tudo (atualização manual copiando a pasta).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import threading
import zipfile
from pathlib import Path

import httpx

from . import jobs, mapdata, netguard
from .config import SETTINGS

# Chave pública de assinatura dos pacotes de mapa (a privada fica fora do repositório).
PUBLIC_KEY_B64 = "ZhdaLYB9bWRKQnA6AUBBRknN9/wfJEFkaDdSkfHAGEg="
REQUIRED = ("graph.npz", "geoindex.json.gz", "info.json")

_state: dict = {"state": "idle"}      # idle | checking | available | current | offline | off | busy | error
_dl: dict = {"state": "idle"}         # idle | downloading | verifying | installing | done | error
_lock = threading.Lock()


# ------------------------------------------------------------------ preferências (ao lado do app)
def _prefs_path() -> Path:
    return mapdata.base_dir() / "preferencias.json"


def prefs() -> dict:
    try:
        return {"verificar_mapa": True} | json.loads(_prefs_path().read_text(encoding="utf-8"))
    except Exception:
        return {"verificar_mapa": True}


def set_check(enabled: bool) -> dict:
    p = prefs() | {"verificar_mapa": bool(enabled)}
    _prefs_path().write_text(json.dumps(p), encoding="utf-8")
    return p


# ------------------------------------------------------------------ assinatura
def verify_signature(data: bytes, sig_b64: str, public_key_b64: str | None = None) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64 or PUBLIC_KEY_B64)).verify(
            base64.b64decode(sig_b64.strip()), data)
        return True
    except (InvalidSignature, ValueError):
        return False


def installed_version() -> str | None:
    i = mapdata.info()
    return i.get("version") if i else None


def _client() -> httpx.Client:
    # User-Agent genérico: nada que identifique quem usa
    return httpx.Client(timeout=httpx.Timeout(15, read=60), follow_redirects=True,
                        headers={"User-Agent": "distribuidor-rotas"})


# ------------------------------------------------------------------ verificação
def status() -> dict:
    with _lock:
        return {"check": dict(_state), "download": dict(_dl), "installed": mapdata.info(),
                "prefs": prefs(), "isolated": netguard.installed(), "blocked": len(netguard.blocked)}


def check(force: bool = False) -> dict:
    with _lock:
        if _state["state"] == "checking" or (_state["state"] not in ("idle", "error", "offline") and not force):
            return dict(_state)
        if not prefs()["verificar_mapa"]:
            _state.clear(); _state["state"] = "off"; return dict(_state)
        if jobs.count():
            _state.clear(); _state["state"] = "busy"; return dict(_state)
        _state.clear(); _state["state"] = "checking"
    try:
        with netguard.update_window(), _client() as c:
            r1 = c.get(SETTINGS.update_manifest_url); r1.raise_for_status()
            r2 = c.get(SETTINGS.update_manifest_url.rsplit("/", 1)[0] + "/manifest.sig"); r2.raise_for_status()
            raw, sig = r1.content, r2.text
        if not verify_signature(raw, sig):
            raise ValueError("assinatura do manifesto não confere")
        man = json.loads(raw)
        cur = installed_version()
        new = {"state": "available" if (cur is None or man["version"] > cur) else "current",
               "version": man["version"], "size": man["size"], "built": man.get("built", ""),
               "installed": cur, "manifest": man}
    except (httpx.HTTPError, OSError) as exc:
        new = {"state": "offline", "detail": type(exc).__name__}
    except Exception as exc:
        new = {"state": "error", "detail": str(exc)}
    with _lock:
        _state.clear(); _state.update(new)
        return {k: v for k, v in _state.items() if k != "manifest"}


# ------------------------------------------------------------------ download e instalação
def start_download() -> dict:
    with _lock:
        man = _state.get("manifest")
        if _state.get("state") != "available" or not man:
            raise RuntimeError("Nenhuma atualização disponível para baixar.")
        if _dl["state"] in ("downloading", "verifying", "installing"):
            return dict(_dl)
        _dl.clear(); _dl.update(state="downloading", done=0, total=man["size"], version=man["version"])
    threading.Thread(target=_download, args=(man,), daemon=True).start()
    return dict(_dl)


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for m in zf.infolist():
        target = (dest / m.filename).resolve()
        if dest != target and dest not in target.parents:
            raise ValueError(f"caminho inválido no pacote: {m.filename}")
    zf.extractall(dest)


def install_zip(zip_path: Path, version: str) -> Path:
    """Extrai, confere e ativa a versão; guarda só a anterior."""
    root = mapdata.root(); root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".{version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as zf:
        _safe_extract(zf, tmp)
    missing = [f for f in REQUIRED if not (tmp / f).exists()]
    if missing:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError(f"pacote incompleto: faltam {', '.join(missing)}")
    final = root / version
    if final.exists():
        shutil.rmtree(final)
    tmp.rename(final)
    prev = installed_version() if (root / "atual.txt").exists() else None
    tmp_cur = root / "atual.txt.tmp"
    tmp_cur.write_text(version, encoding="utf-8")
    os.replace(tmp_cur, root / "atual.txt")          # troca atômica: ou a versão velha, ou a nova
    for d in root.iterdir():
        if d.is_dir() and d.name not in (version, prev) and not d.name.startswith(".baixando"):
            shutil.rmtree(d, ignore_errors=True)
    mapdata.reset()
    return final


def _download(man: dict) -> None:
    root = mapdata.root()
    part_dir = root / ".baixando"; part_dir.mkdir(parents=True, exist_ok=True)
    part = part_dir / f"mapa-{man['version']}.zip.part"
    try:
        with netguard.update_window(), _client() as c:
            for _attempt in range(6):
                have = part.stat().st_size if part.exists() else 0
                if have >= man["size"]:
                    break
                try:
                    hdr = {"Range": f"bytes={have}-"} if have else {}
                    with c.stream("GET", man["url"], headers=hdr) as r:
                        r.raise_for_status()
                        mode = "ab" if (have and r.status_code == 206) else "wb"
                        if mode == "wb":
                            have = 0
                        with open(part, mode) as f:
                            for chunk in r.iter_bytes(1 << 16):
                                f.write(chunk); have += len(chunk)
                                with _lock:
                                    _dl["done"] = have
                except httpx.HTTPError:
                    continue          # queda de rede: retoma de onde parou
        with _lock:
            _dl["state"] = "verifying"
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if part.stat().st_size != man["size"] or h.hexdigest() != man["sha256"]:
            part.unlink(missing_ok=True)
            raise ValueError("o arquivo baixado não confere com o manifesto (baixe de novo)")
        with _lock:
            _dl["state"] = "installing"
        install_zip(part, man["version"])
        shutil.rmtree(part_dir, ignore_errors=True)
        with _lock:
            _dl["state"] = "done"
            _state.clear(); _state.update(state="current", version=man["version"], installed=man["version"])
    except Exception as exc:
        with _lock:
            _dl["state"] = "error"; _dl["detail"] = str(exc)
