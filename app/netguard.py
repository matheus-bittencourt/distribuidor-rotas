"""Modo isolado: bloqueia, no nível do sistema, qualquer conexão para fora deste computador.

Atua em socket.getaddrinfo (resolução de nomes) e em socket.connect/sendto, então vale para qualquer
biblioteca (httpx, urllib, a IA, etc.), não só para o código do app. A única exceção é a janela de
atualização do mapa, aberta pelo atualizador para os domínios do GitHub, só na thread que baixa.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import threading
from contextlib import contextmanager

log = logging.getLogger("netguard")
UPDATE_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}

_ctx = threading.local()
_allowed_ips: set[str] = set()
_lock = threading.Lock()
_installed = False
blocked: list[str] = []          # tentativas bloqueadas (só o destino, para diagnóstico na tela)

_orig_getaddrinfo = socket.getaddrinfo
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_sendto = socket.socket.sendto


def _is_local_ip(h: str) -> bool:
    try:
        ip = ipaddress.ip_address(h.split("%")[0])
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


def _host_ok(host) -> bool:
    if host is None:
        return True
    h = host.decode() if isinstance(host, bytes) else str(host)
    h = h.strip("[]").lower()
    if h in ("localhost", "") or _is_local_ip(h):
        return True
    return bool(getattr(_ctx, "update", False)) and h in UPDATE_HOSTS


def _block(what: str):
    with _lock:
        if len(blocked) < 50:
            blocked.append(what)
    log.warning("modo isolado: conexão bloqueada para %s", what)


def _getaddrinfo(host, *a, **k):
    if not _host_ok(host):
        _block(str(host))
        raise socket.gaierror(socket.EAI_NONAME, f"modo isolado: {host} bloqueado")
    res = _orig_getaddrinfo(host, *a, **k)
    if getattr(_ctx, "update", False) and not _is_local_ip(str(host)):
        with _lock:
            _allowed_ips.update(r[4][0] for r in res)
    return res


def _addr_ok(sock, address) -> bool:
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return True
    ip = str(address[0])
    if _is_local_ip(ip):
        return True
    return bool(getattr(_ctx, "update", False)) and ip in _allowed_ips


def _connect(self, address):
    if not _addr_ok(self, address):
        _block(str(address[0]))
        raise ConnectionRefusedError(f"modo isolado: {address[0]} bloqueado")
    return _orig_connect(self, address)


def _connect_ex(self, address):
    if not _addr_ok(self, address):
        _block(str(address[0]))
        return 111
    return _orig_connect_ex(self, address)


def _sendto(self, data, *args):
    address = args[-1]
    if isinstance(address, tuple) and not _addr_ok(self, address):
        _block(str(address[0]))
        raise ConnectionRefusedError(f"modo isolado: {address[0]} bloqueado")
    return _orig_sendto(self, data, *args)


def install() -> None:
    global _installed
    if _installed:
        return
    socket.getaddrinfo = _getaddrinfo
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    socket.socket.sendto = _sendto
    _installed = True


def uninstall() -> None:
    """Só para testes."""
    global _installed
    socket.getaddrinfo = _orig_getaddrinfo
    socket.socket.connect = _orig_connect
    socket.socket.connect_ex = _orig_connect_ex
    socket.socket.sendto = _orig_sendto
    _installed = False


def installed() -> bool:
    return _installed


@contextmanager
def update_window():
    """Libera os domínios do GitHub só nesta thread, enquanto o atualizador baixa o mapa."""
    _ctx.update = True
    try:
        yield
    finally:
        _ctx.update = False
