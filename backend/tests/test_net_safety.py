"""Endpoint safety for registered graph databases (server-side request forgery controls)."""

import socket
from typing import Any

import pytest

from app.core.net_safety import (
    EndpointError,
    assert_reachable_target,
    assert_url_reachable_target,
    check_bolt_uri,
    check_http_url,
    classify_host,
)


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", "loopback"),
        ("localhost", "loopback"),
        ("db.localhost", "loopback"),
        ("::1", "loopback"),
        ("10.1.2.3", "private"),
        ("192.168.0.9", "private"),
        ("172.16.5.5", "private"),
        ("8.8.8.8", "public"),
        ("169.254.169.254", "blocked"),
        ("::ffff:169.254.169.254", "blocked"),
        ("fd00:ec2::254", "blocked"),
        ("100.100.100.200", "blocked"),
        ("0.0.0.0", "blocked"),
        ("224.0.0.1", "blocked"),
        ("example.com", None),
    ],
)
def test_host_classification(host: str, expected: str | None) -> None:
    assert classify_host(host) == expected


def test_http_urls_require_tls_for_public_hosts_and_reject_unsafe_forms() -> None:
    assert check_http_url("http://localhost:3030/ds/query", field="q", allow_private=True)
    assert check_http_url("http://10.0.0.5:7200/repositories/r", field="q", allow_private=True)
    assert check_http_url("https://graphdb.example.com/repositories/r", field="q", allow_private=True)
    for url, reason in [
        ("http://graphdb.example.com/sparql", "HTTPS"),
        ("https://user:pw@example.com/sparql", "credentials"),
        ("https://169.254.169.254/latest", "not allowed"),
        ("https://example.com/sparql#frag", "fragment"),
        ("ftp://example.com/x", "http"),
        ("https://example.com:70000/x", "port"),
        ("http://", "http"),
    ]:
        with pytest.raises(EndpointError, match=reason):
            check_http_url(url, field="q", allow_private=True)


def test_private_networks_can_be_forbidden_by_policy() -> None:
    for url in ("http://localhost:3030/q", "http://10.0.0.5/q", "http://127.0.0.1/q"):
        with pytest.raises(EndpointError, match="private and loopback"):
            check_http_url(url, field="q", allow_private=False)
    check_http_url("https://example.com/q", field="q", allow_private=False)
    with pytest.raises(EndpointError, match="private and loopback"):
        check_bolt_uri("bolt://localhost:7687", field="u", allow_private=False)


def test_bolt_uris() -> None:
    assert check_bolt_uri("neo4j+s://abc.databases.neo4j.io", field="u", allow_private=True) == (
        "neo4j+s", "abc.databases.neo4j.io", 7687,
    )
    assert check_bolt_uri("bolt://localhost:7688", field="u", allow_private=True)[2] == 7688
    assert check_bolt_uri("bolt+ssc://10.0.0.4", field="u", allow_private=True)[0] == "bolt+ssc"
    for uri, reason in [
        ("bolt://db.example.com", "encrypted"),
        ("neo4j://db.example.com", "encrypted"),
        ("neo4j+ssc://db.example.com", "self-signed"),
        ("https://db.example.com", "neo4j"),
        ("neo4j+s://u:p@db.example.com", "credentials"),
        ("neo4j+s://db.example.com/neo4j", "path"),
        ("neo4j+s://169.254.169.254", "not allowed"),
    ]:
        with pytest.raises(EndpointError, match=reason):
            check_bolt_uri(uri, field="u", allow_private=True)


def test_connection_time_dns_check_blocks_names_resolving_to_metadata_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolves_to(address: str) -> Any:
        def fake(host: str, port: int, **_: Any) -> list[Any]:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            return [(family, socket.SOCK_STREAM, 6, "", (address, port))]

        return fake

    monkeypatch.setattr(socket, "getaddrinfo", resolves_to("169.254.169.254"))
    with pytest.raises(EndpointError, match="resolves to an address that is not allowed"):
        assert_reachable_target("innocent.example.com", 443, allow_private=True)
    with pytest.raises(EndpointError, match="resolves to an address"):
        assert_url_reachable_target("https://innocent.example.com/sparql", allow_private=True)

    monkeypatch.setattr(socket, "getaddrinfo", resolves_to("10.0.0.7"))
    assert_reachable_target("internal.example.com", 443, allow_private=True)
    with pytest.raises(EndpointError, match="resolves to an address"):
        assert_reachable_target("internal.example.com", 443, allow_private=False)

    monkeypatch.setattr(socket, "getaddrinfo", resolves_to("93.184.216.34"))
    assert_reachable_target("example.com", 443, allow_private=False)

    def unresolvable(*_: Any, **__: Any) -> Any:
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", unresolvable)
    with pytest.raises(EndpointError, match="could not be resolved"):
        assert_reachable_target("nowhere.invalid", 443, allow_private=True)
