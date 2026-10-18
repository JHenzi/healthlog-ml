"""Trusted reverse proxies, with HealthLog's ``TRUSTED_PROXIES`` semantics (own code, not imported: design §8.4).

empty (default)  trust the private and loopback ranges;
explicit list    trust exactly those IPs/CIDRs;
``*``            trust every peer.

Only a trusted peer may set ``X-Forwarded-For``; the resolved client IP is
used for log lines, never for authorization.
"""

from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache

log = logging.getLogger("companion.proxies")

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network

_PRIVATE_DEFAULTS = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fe80::/10")


@lru_cache(maxsize=4)
def _parse(raw: str) -> tuple[_Network, ...] | None:
    raw = raw.strip()
    if raw == "*":
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()] if raw else list(_PRIVATE_DEFAULTS)
    networks: list[_Network] = []
    for part in parts:
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            log.warning("TRUSTED_PROXIES: invalid entry %r ignored", part)
    return tuple(networks)


def is_trusted_peer(peer: str | None, trusted: str) -> bool:
    networks = _parse(trusted)
    if networks is None:
        return True
    if not peer:
        return False
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(address in network for network in networks)


def client_ip(peer: str | None, forwarded_for: str | None, trusted: str) -> str | None:
    """The original client: the left-most ``X-Forwarded-For`` entry, but only from a trusted peer."""
    if forwarded_for and is_trusted_peer(peer, trusted):
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first
    return peer
