"""Ponto de entrada do executável (pen drive): sobe o app só nesta máquina e abre o navegador.

Padrões do executável: modo isolado (nenhuma conexão sai do computador), endereços e ruas pelo pacote de
mapa offline, sem IA. Fechar a janela encerra o app e apaga da memória tudo o que foi carregado.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser

DEFAULTS = {"OFFLINE": "1", "GEOCODER": "local", "MATRIX": "local", "LLM_PROVIDER": "none"}
PORTS = range(8765, 8785)


def _free_port() -> int | None:
    for p in PORTS:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return None


def main() -> None:
    for k, v in DEFAULTS.items():
        os.environ.setdefault(k, v)
    import uvicorn

    from app.main import app

    port = _free_port()
    if port is None:
        print("Nenhuma porta livre entre 8765 e 8784. Feche outras cópias do app e tente de novo.")
        input("Enter para sair.")
        return
    url = f"http://127.0.0.1:{port}/"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False))

    def open_browser():
        while not server.started:
            time.sleep(0.1)
        webbrowser.open(url)

    if os.environ.get("NO_BROWSER") != "1":      # testes automatizados: não abre o navegador
        threading.Thread(target=open_browser, daemon=True).start()
    print("Distribuidor de rotas")
    print(f"  Aberto em {url} (só neste computador).")
    print("  Modo isolado: nenhuma conexão sai daqui, exceto a busca de atualização do mapa,")
    print("  feita ao abrir e antes de carregar qualquer lista (pode ser desligada na tela).")
    print("  Feche esta janela para encerrar. Os dados da sessão ficam só na memória e somem ao fechar.")
    try:
        server.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
