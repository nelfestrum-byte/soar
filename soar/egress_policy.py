"""Egress policy: `config.yaml`'s `egress` section, shared by
`soar/audit_hook.py` (layer 2, deny on `socket.connect`) and
`soar/tools/_net.py` (pre-flight for `http_client`) — one parse, two
enforcement points, per docs/compose/specs/2026-08-06-egress-policy-design.md
[S2]. `allow` is a set of exceptions carved out of deny-private, not a
replacement for the whole policy: public addresses stay allowed regardless
of `allow`, matching the deny-private behavior this policy defaults to when
`egress` is absent from config (upgrade never silently opens anything)."""

import ipaddress
from dataclasses import dataclass, field

_VALID_MODES = ("allowlist", "observe")


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        return False


@dataclass
class EgressPolicy:
    mode: str = "allowlist"
    allow: list = field(default_factory=list)

    def is_allowed(self, ip_str: str) -> bool:
        if self.mode == "observe":
            return True
        if not _is_private_ip(ip_str):
            return True
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        return any(ip in net for net in self.allow)


def parse(cfg: dict) -> EgressPolicy:
    cfg = cfg or {}
    mode = cfg.get("mode", "allowlist")
    if mode not in _VALID_MODES:
        raise ValueError(f"Unknown egress.mode: {mode!r} (expected one of {_VALID_MODES})")

    allow = []
    for entry in cfg.get("allow", []):
        try:
            allow.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as e:
            raise ValueError(f"Invalid egress.allow entry: {entry!r}") from e

    return EgressPolicy(mode=mode, allow=allow)
