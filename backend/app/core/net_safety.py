"""Endpoint safety for outbound connections to registered databases.

Registered graph databases are reached by the backend, so a configurable endpoint is a potential
server-side request forgery vector. Rules:

* link-local, unspecified, multicast and reserved addresses and well-known cloud metadata
  addresses are always refused (static check on registration, DNS-resolved check on every connection);
* loopback and private addresses are allowed only while ``allow_private`` is set (self-hosted
  databases on a developer machine or private network are an expected use);
* hosts that are not private must be reached over TLS.

Messages never include credentials and name only the offending host or field.
"""

import ipaddress
import re
import socket
from typing import Any, Literal
from urllib.parse import urlsplit

HostClass = Literal["loopback", "private", "public", "blocked"]

_HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9_]([A-Za-z0-9_-]{0,62}[A-Za-z0-9_])?(\.[A-Za-z0-9_]([A-Za-z0-9_-]{0,62}[A-Za-z0-9_])?)*$")
_METADATA = {
    ipaddress.ip_address(a)
    for a in ("169.254.169.254", "100.100.100.200", "168.63.129.16", "fd00:ec2::254", "192.0.0.192")
}
BOLT_SCHEMES = ("bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc")
_TLS_BOLT = ("bolt+s", "bolt+ssc", "neo4j+s", "neo4j+ssc")


class EndpointError(ValueError):
    """The endpoint is malformed or unsafe. The message is safe to show to users."""


def _address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        address = ipaddress.ip_address(value.strip("[]").split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def classify_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> HostClass:
    if address in _METADATA or address.is_link_local or address.is_unspecified or address.is_multicast:
        return "blocked"
    if address.is_loopback:  # before is_reserved: ::1 lies inside the reserved ::/8 block
        return "loopback"
    if address.is_reserved:
        return "blocked"
    return "public" if address.is_global else "private"


def classify_host(host: str) -> HostClass | None:
    """Classification of a host that needs no DNS lookup; ``None`` for a name that must be resolved."""
    address = _address(host)
    if address is not None:
        return classify_address(address)
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return "loopback"
    return None


def check_host(host: str, *, field: str, allow_private: bool) -> HostClass | None:
    """Static host validation; returns the class when it is known without DNS."""
    if not host or (_address(host) is None and not _HOSTNAME.match(host)):
        raise EndpointError(f"{field}: '{host[:80]}' is not a valid host name.")
    host_class = classify_host(host)
    if host_class == "blocked":
        raise EndpointError(f"{field}: link-local, metadata and reserved addresses are not allowed.")
    if host_class in ("loopback", "private") and not allow_private:
        raise EndpointError(f"{field}: private and loopback addresses are not allowed by this server's policy.")
    return host_class


def check_port(port: int | None, *, field: str) -> None:
    if port is not None and not 1 <= port <= 65535:
        raise EndpointError(f"{field}: the port must be between 1 and 65535.")


def check_http_url(url: str, *, field: str, allow_private: bool) -> str:
    """Validate an HTTP(S) endpoint; public hosts must use HTTPS. Returns the URL without trailing slash noise."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as error:
        raise EndpointError(f"{field}: not a valid URL (check the host and port).") from error
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise EndpointError(f"{field}: must be an absolute http:// or https:// URL.")
    if parts.username or parts.password:
        raise EndpointError(f"{field}: credentials must not be embedded in the URL.")
    if parts.fragment:
        raise EndpointError(f"{field}: must not contain a fragment.")
    check_port(port, field=field)
    host_class = check_host(parts.hostname, field=field, allow_private=allow_private)
    if parts.scheme == "http" and host_class not in ("loopback", "private"):
        raise EndpointError(f"{field}: public hosts must be reached over HTTPS.")
    return url.strip()


def check_bolt_uri(uri: str, *, field: str, allow_private: bool) -> tuple[str, str, int]:
    """Validate a Bolt/Neo4j URI; returns (scheme, host, port)."""
    try:
        parts = urlsplit(uri.strip())
        port = parts.port
    except ValueError as error:
        raise EndpointError(f"{field}: not a valid URI (check the host and port).") from error
    if parts.scheme not in BOLT_SCHEMES or not parts.hostname:
        raise EndpointError(f"{field}: use one of {', '.join(f'{s}://' for s in BOLT_SCHEMES)}.")
    if parts.username or parts.password:
        raise EndpointError(f"{field}: credentials must not be embedded in the URI.")
    if parts.path not in ("", "/") or parts.fragment:
        raise EndpointError(f"{field}: must not contain a path or fragment; set the database separately.")
    check_port(port, field=field)
    host_class = check_host(parts.hostname, field=field, allow_private=allow_private)
    local = host_class in ("loopback", "private")
    if parts.scheme not in _TLS_BOLT and not local:
        raise EndpointError(f"{field}: public hosts require an encrypted scheme (neo4j+s:// or bolt+s://).")
    if parts.scheme.endswith("+ssc") and not local:
        raise EndpointError(f"{field}: self-signed certificates (+ssc) are only accepted for private hosts.")
    return parts.scheme, parts.hostname, port or 7687


def resolve_host(host: str, port: int) -> list[Any]:
    """DNS resolution seam (replaced in tests so they never depend on real name resolution)."""
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def assert_reachable_target(host: str, port: int, *, allow_private: bool) -> None:
    """Connection-time check: resolve ``host`` and refuse blocked (or, by policy, private) addresses."""
    static = classify_host(host)
    if static == "blocked" or (static in ("loopback", "private") and not allow_private):
        raise EndpointError("The endpoint address is not allowed by this server's network policy.")
    if static is not None:
        return
    try:
        infos = resolve_host(host, port)
    except socket.gaierror as error:
        raise EndpointError(f"The host '{host[:80]}' could not be resolved.") from error
    for info in infos:
        address = _address(info[4][0])
        if address is None:
            continue
        resolved = classify_address(address)
        if resolved == "blocked" or (resolved in ("loopback", "private") and not allow_private):
            raise EndpointError(f"The host '{host[:80]}' resolves to an address that is not allowed by network policy.")


def assert_url_reachable_target(url: str, *, allow_private: bool) -> None:
    parts = urlsplit(url)
    if not parts.hostname:
        raise EndpointError("The endpoint URL has no host.")
    default = 443 if parts.scheme == "https" else 80
    assert_reachable_target(parts.hostname, parts.port or default, allow_private=allow_private)
