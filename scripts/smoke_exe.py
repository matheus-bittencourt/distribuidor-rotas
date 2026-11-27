"""Teste de fumaça do executável: abre o .exe de verdade e confere que o pacote está inteiro.

Uso:  python scripts/smoke_exe.py dist/DistribuidorRotas          (pasta gerada pelo PyInstaller)
      python scripts/smoke_exe.py dist/DistribuidorRotas/DistribuidorRotas.exe

Por que existe: o executável só leva os arquivos de dados listados no distribuidor.spec. Um JSON esquecido não
aparece nos testes (que rodam sobre o código-fonte) e só estoura na mão do operador, como aconteceu com o
pedestrian_zone.json na v0.1.5. Aqui o app roda como ele sai do pacote.

Etapas (qualquer falha encerra com código 1 e mostra a saída do app):
  1. Todo app/*.json do projeto está dentro do pacote.
  2. O app sobe, responde /api/config (que lê a zona a pé) e serve a página e os arquivos estáticos.
  3. Envia uma lista pequena, calcula com uma zona desenhada e confere que todas as entregas foram roteirizadas.
  4. As zonas são gravadas em data/ ao lado do executável.
  5. Se o pacote traz o mapa offline: reabre com o geocodificador de verdade e confere que alguns endereços
     reais são localizados.

Roda numa CÓPIA da pasta, para não deixar data/ nem outros rastros no que vai para o zip.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTS = range(8765, 8785)
CSV = (
    "ENDEREÇO;NOME;COD_RASTREIO\n"
    + "".join(f"Rua Teste {i}, {100 + i};Pessoa {i};SMK{i:03d}\n" for i in range(12))
).encode("utf-8")
REAL = (
    "ENDEREÇO;NOME;COD_RASTREIO\n"
    "Avenida Mostardeiros, 322;Pessoa A;REAL001\n"
    "Rua dos Andradas, 1000;Pessoa B;REAL002\n"
    "Avenida Ipiranga, 6681;Pessoa C;REAL003\n"
).encode("utf-8")


class Fail(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Fail(msg)
    print(f"  ok  {msg}")


def find_exe(arg: str) -> Path:
    p = Path(arg).resolve()
    if p.is_file():
        return p
    for cand in (p / "DistribuidorRotas.exe", p / "DistribuidorRotas"):
        if cand.is_file():
            return cand
    raise Fail(f"executável não encontrado em {p}")


class App:
    """O executável rodando, com a saída guardada para mostrar se algo falhar."""

    def __init__(self, exe: Path, env_extra: dict[str, str]):
        self.log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False, encoding="utf-8", errors="replace")
        env = {**os.environ, "NO_BROWSER": "1", **env_extra}
        self.proc = subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.base = ""

    def wait_ready(self, timeout=120):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                raise Fail(f"o executável encerrou sozinho (código {self.proc.returncode})")
            for port in PORTS:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/config", timeout=2) as r:
                        if r.status == 200:
                            self.base = f"http://127.0.0.1:{port}"
                            return
                except urllib.error.HTTPError:
                    self.base = f"http://127.0.0.1:{port}"   # subiu, mas a rota falhou: o teste mostra o erro adiante
                    return
                except OSError:
                    continue
            time.sleep(1)
        raise Fail(f"o app não respondeu em {timeout} s")

    def request(self, method, path, body=None, raw=None, ctype="application/json", timeout=120):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": ctype})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()

    def json(self, method, path, body=None, **kw):
        status, data = self.request(method, path, body, **kw)
        return json.loads(data.decode("utf-8"))

    def upload(self, csv_bytes: bytes) -> str:
        b = uuid.uuid4().hex
        raw = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="lista.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()
               + csv_bytes + f"\r\n--{b}--\r\n".encode())
        return self.json("POST", "/api/upload", raw=raw, ctype=f"multipart/form-data; boundary={b}")["job_id"]

    def wait_state(self, job, states, timeout=120):
        t0 = time.time()
        while time.time() - t0 < timeout:
            j = self.json("GET", f"/api/jobs/{job}")
            if j["state"] in states:
                return j
            time.sleep(0.5)
        raise Fail(f"processamento não chegou a {states} em {timeout} s")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def output(self) -> str:
        self.log.flush()
        try:
            return Path(self.log.name).read_text(encoding="utf-8", errors="replace")[-3000:]
        except OSError:
            return ""


def step1_files(exe_dir: Path):
    print("1. arquivos de dados no pacote")
    want = sorted(p.name for p in (ROOT / "app").glob("*.json"))
    check(want, f"o projeto tem app/*.json ({', '.join(want)})")
    for name in want:
        found = [p for p in exe_dir.rglob(name) if p.parent.name == "app"]
        check(found, f"{name} está em app/ dentro do pacote")


def step2_to_4(exe: Path):
    exe_dir = exe.parent
    print("2. o app sobe e serve a interface (geocodificador de teste, sem rede)")
    app = App(exe, {"GEOCODER": "fake"})
    try:
        app.wait_ready()
        print(f"  ok  respondendo em {app.base}")
        cfg = app.json("GET", "/api/config")
        check(len(cfg.get("pedestrian_polygon", [])) > 50, "/api/config traz o contorno da zona a pé (pedestrian_zone.json)")
        status, page = app.request("GET", "/")
        check(status == 200 and b"Distribuidor de rotas" in page, "a página inicial abre")
        for path in ("/static/app.js", "/static/zones.js", "/static/style.css", "/static/vendor/leaflet/leaflet.js"):
            status, data = app.request("GET", path)
            check(status == 200 and len(data) > 500, f"{path} é servido")
        check(app.json("GET", "/api/mapa") is not None, "/api/mapa responde")

        print("3. lista pequena, uma zona desenhada e o cálculo")
        job = app.upload(CSV)
        j = app.wait_state(job, ("revisao", "erro"))
        check(j["state"] == "revisao", f"lista lida ({j.get('error') or str(j['total']) + ' entregas'})")
        zone = {"name": "Norte", "polygon": [[-30.05, -51.4], [-30.05, -50.9], [-29.8, -50.9], [-29.8, -51.4]],
                "profile": "moto", "drivers": [2], "start": {}, "edge_m": 0}
        app.json("POST", f"/api/jobs/{job}/solve", {"depot": {"address": ""}, "drivers": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
                                                    "time_limit": 5, "zones": [zone]})
        j = app.wait_state(job, ("pronto", "erro"))
        check(j["state"] == "pronto", f"cálculo concluído ({j.get('error') or 'ok'})")
        res = app.json("GET", f"/api/jobs/{job}/result")
        got = sum(d["deliveries"] for d in res["drivers"])
        check(got == res["deliveries"] == 12 and not res["unrouted"], f"as 12 entregas foram roteirizadas uma vez ({got})")
        check(len(res["zones"]) == 1 and res["zones"][0]["name"] == "Norte", "a zona desenhada aparece no resultado")
        app.request("DELETE", f"/api/jobs/{job}")

        print("4. zonas gravadas ao lado do executável")
        app.json("PUT", "/api/zonas", {"zones": [{"name": "Teste", "profile": "moto", "labels": ["A"], "start": "", "edge": 0,
                                                  "poly": [[-30.05, -51.2], [-30.05, -51.1], [-30.0, -51.15]]}]})
        check((exe_dir / "data" / "zonas.json").is_file(), "data/zonas.json foi criado ao lado do executável")
        check(len(app.json("GET", "/api/zonas")["zones"]) == 1, "as zonas voltam ao ler")
    except Exception:
        print("\n--- saída do app ---\n" + app.output())
        raise
    finally:
        app.stop()


def step5_real_geocoder(exe: Path):
    mapa = exe.parent / "mapa" / "atual.txt"
    if not mapa.is_file():
        print("5. mapa offline: não há pacote de mapa neste build, etapa ignorada")
        return
    print("5. mapa offline: geocodificador de verdade")
    app = App(exe, {})
    try:
        app.wait_ready()
        info = app.json("GET", "/api/mapa").get("installed")
        check(info, "o pacote de mapa foi reconhecido")
        job = app.upload(REAL)
        j = app.wait_state(job, ("revisao", "erro"))
        check(j["state"] == "revisao", f"lista lida ({j.get('error') or ''})")
        located = j["counts"].get("ok", 0)
        check(located >= 1, f"o geocodificador local localizou {located} de 3 endereços reais")
        app.request("DELETE", f"/api/jobs/{job}")
    except Exception:
        print("\n--- saída do app ---\n" + app.output())
        raise
    finally:
        app.stop()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    src = find_exe(sys.argv[1])
    tmp = Path(tempfile.mkdtemp(prefix="smoke_exe_"))
    try:
        print(f"copiando {src.parent} para uma pasta temporária...")
        shutil.copytree(src.parent, tmp / "app", ignore=shutil.ignore_patterns("data"))
        exe = tmp / "app" / src.name
        step1_files(exe.parent)
        step2_to_4(exe)
        step5_real_geocoder(exe)
        print("\nOK: o executável abre, serve a interface, calcula e grava as zonas.")
        return 0
    except Fail as e:
        print(f"\nFALHOU: {e}")
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:   # o app respondeu com erro ou não respondeu
        print(f"\nFALHOU: {type(e).__name__}: {e}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
