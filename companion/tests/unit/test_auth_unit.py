"""Pure auth helpers: scopes (risks.md D4/D5) and trusted proxies (D6)."""

from __future__ import annotations

import pytest

from app.auth import scope_allows, validate_scope
from app.proxies import client_ip, is_trusted_peer


@pytest.mark.parametrize("scope", ["all", "read", "log:coffee", "log:first_social_media"])
def test_valid_scopes(scope):
    assert validate_scope(scope) == scope


@pytest.mark.parametrize("scope", ["", "admin", "log:", "log:Coffee", "log:1x", "log:a;drop table x", "log:a b"])
def test_invalid_scopes_are_rejected(scope):
    with pytest.raises(ValueError):
        validate_scope(scope)


@pytest.mark.parametrize(
    ("scope", "needed", "allowed"),
    [
        ("all", "read", True),
        ("all", "log:coffee", True),
        ("read", "read", True),
        ("read", "log:coffee", False),
        ("log:coffee", "log:coffee", True),
        ("log:coffee", "log:tea", False),
        ("log:coffee", "read", False),
    ],
)
def test_scope_matrix(scope, needed, allowed):
    assert scope_allows(scope, needed) is allowed


def test_forwarded_for_only_from_trusted_peer():
    assert client_ip("172.18.0.2", "203.0.113.9, 172.18.0.2", "") == "203.0.113.9"
    assert client_ip("198.51.100.7", "203.0.113.9", "") == "198.51.100.7"  # public peer: header ignored
    assert client_ip("198.51.100.7", "203.0.113.9", "198.51.100.0/24") == "203.0.113.9"


def test_wildcard_and_garbage():
    assert is_trusted_peer("8.8.8.8", "*")
    assert not is_trusted_peer(None, "")
    assert not is_trusted_peer("not-an-ip", "")
