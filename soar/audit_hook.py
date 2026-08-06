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
решение 2.

Политика (soar/egress_policy.py) передаётся в install() замыканием, а не
читается из глобала модуля — хук снять нельзя, но глобал контент мог бы
перезаписать и расширить себе allowlist; захваченного в замыкание имени в
модуле не существует (docs/compose/specs/2026-08-06-egress-policy-design.md
[S2])."""

import socket
import sys
from typing import Any

from loguru import logger as _log

from soar.egress_policy import EgressPolicy
from soar.egress_policy import parse as parse_egress_policy

_WATCHED = {
    "socket.connect", "socket.getaddrinfo", "open",
    "subprocess.Popen", "exec", "ctypes.dlopen",
}

_events: list[dict[str, Any]] = []


def _handle(event: str, args: tuple, policy: EgressPolicy | None = None) -> None:
    policy = policy or parse_egress_policy({})
    if event == "socket.connect":
        sock, address = args[0], args[1]
        family = getattr(sock, "family", None)
        if family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple) and address:
            host = address[0]
            if not policy.is_allowed(str(host)):
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


def install(policy: EgressPolicy | None = None) -> None:
    policy = policy or parse_egress_policy({})

    def hook(event: str, args: tuple) -> None:
        if event in _WATCHED:
            _handle(event, args, policy)
    sys.addaudithook(hook)
