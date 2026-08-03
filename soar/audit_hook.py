"""Platform-level наблюдаемость egress/файлов/подпроцессов + deny-policy на
приватные адреса — sys.addaudithook (PEP 578), устанавливается до загрузки
любого контента. Видит любую библиотеку, которой контент это сделал —
httpx, requests, paramiko, ldap3, raw socket — независимо от того, звал ли
код http_client. Хук нельзя снять (sys.removeaudithook не существует) — это
и есть разница со сегодняшним SSRF-guard внутри soar/tools/http_client.py,
который наблюдает только то, что прошло через LoggingHttpClient/CachingHttpClient.
_validate_external_url там остаётся как pre-flight (быстрый отказ до
открытия сокета, с понятным ValueError) — хук не заменяет его, а
гарантирует то же самое там, где pre-flight-проверки нет и быть не может
(paramiko, ldap3, pymssql — не HTTP). См. docs/concepts/ENTITY-MODEL.md,
решение 2."""

import ipaddress
import socket
import sys
from typing import Any

from loguru import logger as _log

_WATCHED = {
    "socket.connect", "socket.getaddrinfo", "open",
    "subprocess.Popen", "exec", "ctypes.dlopen",
}

_events: list[dict[str, Any]] = []


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        return False


def _handle(event: str, args: tuple) -> None:
    if event == "socket.connect":
        sock, address = args[0], args[1]
        family = getattr(sock, "family", None)
        if family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple) and address:
            host = address[0]
            if _is_private_ip(str(host)):
                _events.append({"event": "socket.connect.blocked", "address": str(host)})
                raise PermissionError(f"egress to private address {host} blocked by audit hook")
        _events.append({"event": event, "address": str(address)})
    elif event == "subprocess.Popen":
        _events.append({"event": event, "executable": str(args[0])})
    elif event == "open":
        _events.append({"event": event, "path": str(args[0])})
    elif event in ("exec", "ctypes.dlopen"):
        _events.append({"event": event})
    # socket.getaddrinfo — записывается, не блокируется: блокировка на
    # резолве не закрывает ничего, чего не закрывает блокировка на connect,
    # а резолвится DNS чаще, чем реально коннектится (retries, IPv4+IPv6).


def flush() -> None:
    """Batched write — вызывается из soar/runner.py::main() в finally, не на
    каждое событие (иначе на частый socket.connect дорого, см. ENTITY-MODEL
    решение 2: 'внутри только проверка членства в множестве, ... запись
    батчами')."""
    if not _events:
        return
    for e in _events:
        _log.bind(audit=True).info(f"audit: {e}")
    _events.clear()


def install() -> None:
    def hook(event: str, args: tuple) -> None:
        if event in _WATCHED:
            _handle(event, args)
    sys.addaudithook(hook)
