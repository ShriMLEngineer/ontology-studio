"""Graph database provider catalogue (Settings -> Graph Databases).

One :class:`TargetKind` per provider: what a user can register, which fields the registration form
shows, what the adapter can do (connect / deploy / read) and whether that was verified against a
live server. Adding a provider (for example TigerGraph) means adding a definition here, a
connection probe and, if it can store graphs, an adapter - the registry, API and Settings UI are
driven by this catalogue and need no redesign.

Capability flags are deliberately separate:

``available``            an adapter exists (connection test and, where flagged, deployment/read).
``deployment_supported`` the adapter can write and verify a build's projection.
``read_supported``       the Graph Explorer can read a deployment back from the target.
``live_tested``          the adapter was exercised against a real server of this provider (not only mocks).
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.errors import BusinessRuleError
from app.core.net_safety import (
    BOLT_SCHEMES,
    EndpointError,
    check_bolt_uri,
    check_host,
    check_http_url,
    check_port,
    classify_host,
)

GraphModel = Literal["rdf", "property-graph"]
FieldType = Literal["text", "url", "number", "integer", "select", "secret_ref"]
Family = Literal["local", "oxigraph", "sparql", "neo4j", "gremlin"]

AUTH_TYPES = ("none", "basic", "bearer", "gdb-token")
_AUTH_LABELS = {
    "none": "None",
    "basic": "Username and password (HTTP basic)",
    "bearer": "Bearer token",
    "gdb-token": "GraphDB token (Authorization: GDB)",
}


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    required: bool = False
    secret: bool = False
    placeholder: str = ""
    type: FieldType = "text"
    default: str = ""
    options: tuple[tuple[str, str], ...] = ()
    help: str = ""
    # Shown only when another field has one of these values: (controlling key, allowed values).
    visible_when: tuple[str, tuple[str, ...]] | None = None
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class TargetKind:
    id: str
    label: str
    model: GraphModel
    builtin: bool
    registrable: bool
    available: bool
    description: str
    unavailable_reason: str = ""
    fields: tuple[ConfigField, ...] = field(default_factory=tuple)
    family: Family = "sparql"
    protocol: str = ""
    deployment_supported: bool = False
    read_supported: bool = False
    live_tested: bool = False
    verification_note: str = ""


def _auth_fields(choices: tuple[str, ...], *, token_help: str = "") -> tuple[ConfigField, ...]:
    return (
        ConfigField(
            "auth_type", "Authentication", type="select", default="none",
            options=tuple((c, _AUTH_LABELS[c]) for c in choices),
        ),
        ConfigField(
            "username", "User name", required=True, visible_when=("auth_type", ("basic",)),
        ),
        ConfigField(
            "secret_env", "Credential (environment variable name)", required=True, secret=True, type="secret_ref",
            placeholder="OLS_GRAPH_PASSWORD", help=token_help or "Name of a server environment variable; the value is never stored.",
            visible_when=("auth_type", tuple(c for c in choices if c != "none")),
        ),
    )


KINDS: dict[str, TargetKind] = {
    k.id: k
    for k in (
        TargetKind(
            id="cosmos-gremlin",
            label="Azure Cosmos DB for Apache Gremlin",
            model="property-graph",
            builtin=False,
            registrable=True,
            available=True,
            family="gremlin",
            protocol="Gremlin over WebSocket (GraphSON 2)",
            description=(
                "Gremlin property graph (TinkerPop) with a required partition key. Each build is written under its "
                "own partition-key value."
            ),
            deployment_supported=True,
            read_supported=True,
            live_tested=False,
            verification_note=(
                "Implemented with the official gremlinpython client and unit-tested against a scripted Gremlin client. "
                "No Azure Cosmos DB account or emulator was available, so live deployment is unverified."
            ),
            fields=(
                ConfigField("endpoint", "Account / Gremlin endpoint", required=True, type="text",
                            placeholder="my-account.gremlin.cosmos.azure.com",
                            help="Account name, Gremlin host name or wss:// URL."),
                ConfigField("port", "Port", type="integer", default="443", minimum=1, maximum=65535),
                ConfigField("database", "Database name", required=True, placeholder="graphdb"),
                ConfigField("graph", "Graph / container name", required=True, placeholder="knowledge"),
                ConfigField("partition_key_path", "Graph partition-key path", required=True, default="/pk",
                            placeholder="/pk", help="Single-level path chosen when the graph was created."),
                ConfigField("secret_env", "Account key (environment variable name)", required=True, secret=True,
                            type="secret_ref", placeholder="COSMOS_GREMLIN_KEY",
                            help="Name of a server environment variable holding the primary or secondary key."),
                ConfigField("timeout_seconds", "Connection timeout (seconds)", type="number", default="30",
                            minimum=5, maximum=120),
            ),
        ),
        TargetKind(
            id="neo4j",
            label="Neo4j / Neo4j AuraDB",
            model="property-graph",
            builtin=False,
            registrable=True,
            available=True,
            family="neo4j",
            protocol="Bolt / Cypher (official neo4j driver)",
            description="Labelled property graph over Bolt: Neo4j AuraDB or a self-hosted Neo4j 5 server.",
            deployment_supported=True,
            read_supported=True,
            live_tested=True,
            verification_note=(
                "Deployment, read-back, explorer reads and scope cleanup were exercised against Neo4j AuraDB 5.27 "
                "(see docs/GRAPH_DATABASES.md)."
            ),
            fields=(
                ConfigField("uri", "Bolt URI", required=True, placeholder="neo4j+s://xxxxxxxx.databases.neo4j.io",
                            help="Schemes: " + ", ".join(f"{s}://" for s in BOLT_SCHEMES) + ". Public hosts require TLS."),
                ConfigField("database", "Database name", required=True, default="neo4j"),
                ConfigField("username", "User name", required=True, default="neo4j"),
                ConfigField("secret_env", "Password (environment variable name)", required=True, secret=True,
                            type="secret_ref", placeholder="NEO4J_PASSWORD",
                            help="Name of a server environment variable; the password is never stored."),
                ConfigField("timeout_seconds", "Connection timeout (seconds)", type="number", default="15",
                            minimum=5, maximum=120),
            ),
        ),
        TargetKind(
            id="graphdb",
            label="Ontotext GraphDB",
            model="rdf",
            builtin=False,
            registrable=True,
            available=True,
            family="sparql",
            protocol="SPARQL 1.1 Protocol",
            description=(
                "A GraphDB repository on any host, including Azure-hosted deployments (the same API). Endpoints are "
                "derived from the server URL and repository unless overridden."
            ),
            deployment_supported=True,
            read_supported=True,
            live_tested=False,
            verification_note=(
                "Uses the generic SPARQL 1.1 adapter, which is verified against a live Oxigraph SPARQL server. "
                "It has not been run against a live GraphDB instance."
            ),
            fields=(
                ConfigField("server_url", "Server URL", required=True, type="url", placeholder="http://localhost:7200"),
                ConfigField("repository_id", "Repository ID", required=True, placeholder="knowledge"),
                ConfigField("query_url", "Query endpoint override", type="url",
                            help="Default: {server}/repositories/{repository}"),
                ConfigField("update_url", "Update endpoint override", type="url",
                            help="Default: {server}/repositories/{repository}/statements"),
                ConfigField("access_mode", "Access", type="select", default="read-write",
                            options=(("read-write", "Read and write (can deploy)"), ("read-only", "Read only"))),
                *_auth_fields(("none", "basic", "bearer", "gdb-token")),
            ),
        ),
        TargetKind(
            id="fuseki",
            label="Apache Jena Fuseki",
            model="rdf",
            builtin=False,
            registrable=True,
            available=True,
            family="sparql",
            protocol="SPARQL 1.1 Protocol",
            description="A Fuseki dataset with SPARQL query and update endpoints. Omit the update endpoint for read-only use.",
            deployment_supported=True,
            read_supported=True,
            live_tested=False,
            verification_note=(
                "Uses the generic SPARQL 1.1 adapter, which is verified against a live Oxigraph SPARQL server. "
                "It has not been run against a live Fuseki server."
            ),
            fields=(
                ConfigField("query_url", "SPARQL query endpoint", required=True, type="url",
                            placeholder="http://localhost:3030/ds/query"),
                ConfigField("update_url", "SPARQL update endpoint (required to deploy)", type="url",
                            placeholder="http://localhost:3030/ds/update"),
                *_auth_fields(("none", "basic", "bearer")),
            ),
        ),
        TargetKind(
            id="sparql-http",
            label="Generic SPARQL 1.1 endpoint",
            model="rdf",
            builtin=False,
            registrable=True,
            available=True,
            family="sparql",
            protocol="SPARQL 1.1 Protocol",
            description=(
                "Any store implementing the SPARQL 1.1 Protocol (query and update): Jena Fuseki, GraphDB, Stardog, "
                "Oxigraph server, Virtuoso, Amazon Neptune. Omit the update endpoint for a read-only connection."
            ),
            deployment_supported=True,
            read_supported=True,
            live_tested=True,
            verification_note="Deployment and read-back are integration-tested against a live Oxigraph SPARQL server.",
            fields=(
                ConfigField("query_url", "Query endpoint URL", required=True, type="url",
                            placeholder="http://localhost:3030/ds/query"),
                ConfigField("update_url", "Update endpoint URL (required to deploy)", type="url",
                            placeholder="http://localhost:3030/ds/update"),
                *_auth_fields(("none", "basic", "bearer")),
            ),
        ),
        TargetKind(
            id="local-sql",
            label="Local SQL Graph Store",
            model="property-graph",
            builtin=False,
            registrable=True,
            available=True,
            family="local",
            protocol="Internal adapter (application database)",
            description=(
                "Vertices and edges in the application database (SqlGraphStore). Needs no credentials; intended for "
                "development and testing. The built-in 'Local SQL property graph' is always available."
            ),
            deployment_supported=True,
            read_supported=True,
            live_tested=True,
            verification_note="The application's canonical graph store; covered by the regular test suite.",
        ),
        TargetKind(
            id="oxigraph",
            label="Embedded Oxigraph (RDF quad store)",
            model="rdf",
            builtin=True,
            registrable=False,
            available=True,
            family="oxigraph",
            protocol="Embedded (pyoxigraph)",
            description="RDF quad store embedded in the backend (pyoxigraph, on disk). One named graph per build.",
            deployment_supported=True,
            read_supported=True,
            live_tested=True,
            verification_note="Covered by the regular test suite.",
        ),
    )
}

BUILTIN_TARGETS = {
    "local-sql": ("Local SQL property graph", "local-sql"),
    "oxigraph-embedded": ("Embedded Oxigraph", "oxigraph"),
}

REGISTRATION_ORDER = ("cosmos-gremlin", "neo4j", "graphdb", "fuseki", "sparql-http", "local-sql")

# ---------------------------------------------------------------------------------- validation

_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_COSMOS_HOST = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.gremlin\.cosmos(db)?\.azure\.(com|us|cn)$", re.IGNORECASE)
_COSMOS_ACCOUNT = re.compile(r"^[a-z0-9][a-z0-9-]{1,43}$", re.IGNORECASE)
_COSMOS_SUFFIX = ".gremlin.cosmos.azure.com"
_PARTITION_PATH = re.compile(r"^/[A-Za-z_][A-Za-z0-9_]{0,63}$")


def invalid(message: str) -> BusinessRuleError:
    return BusinessRuleError(message, code="GRAPH_CONFIG_INVALID")


def _visible(spec: ConfigField, values: dict[str, str]) -> bool:
    if spec.visible_when is None:
        return True
    key, allowed = spec.visible_when
    return values.get(key, "") in allowed


def _coerce(spec: ConfigField, raw: Any) -> str:
    text = "" if raw is None else ("true" if raw is True else "false" if raw is False else str(raw)).strip()
    if len(text) > 500:
        raise invalid(f"{spec.label}: too long.")
    if not text:
        return ""
    if spec.type in ("number", "integer"):
        try:
            number = float(text)
        except ValueError as error:
            raise invalid(f"{spec.label}: must be a number.") from error
        if spec.type == "integer" and number != int(number):
            raise invalid(f"{spec.label}: must be a whole number.")
        if spec.minimum is not None and number < spec.minimum or spec.maximum is not None and number > spec.maximum:
            raise invalid(f"{spec.label}: must be between {spec.minimum:g} and {spec.maximum:g}.")
        return str(int(number)) if number == int(number) else str(number)
    if spec.type == "select" and text not in {value for value, _ in spec.options}:
        raise invalid(f"{spec.label}: choose one of {', '.join(value for value, _ in spec.options)}.")
    return text


def _prepare(kind: TargetKind, config: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(config)
    if kind.family == "sparql" and not str(prepared.get("auth_type") or "").strip():
        # Registrations made before authentication types existed: a user name implied HTTP basic.
        prepared["auth_type"] = "basic" if str(prepared.get("username") or "").strip() else "none"
    return prepared


def normalize_config(
    kind_id: str, config: dict[str, Any], secret_env: str | None, *, allow_private: bool
) -> tuple[dict[str, str], str | None]:
    """Validate a registration for its provider; returns the cleaned config and credential reference."""
    kind = KINDS.get(kind_id)
    if kind is None:
        raise BusinessRuleError(f"Unknown graph database provider '{kind_id}'.", code="GRAPH_KIND_UNKNOWN")
    if not kind.registrable:
        reason = kind.unavailable_reason or "Built-in targets are always available and cannot be registered again."
        raise BusinessRuleError(f"{kind.label} cannot be registered: {reason}", code="GRAPH_KIND_NOT_AVAILABLE")
    data_fields = [f for f in kind.fields if not f.secret]
    unknown = sorted(set(config) - {f.key for f in data_fields})
    if unknown:
        raise invalid(f"Unknown configuration fields for {kind.label}: {', '.join(unknown)}.")
    source = _prepare(kind, config)
    values: dict[str, str] = {}
    missing: list[str] = []
    credential = secret_env
    for spec in kind.fields:
        if spec.secret:
            if not _visible(spec, values):
                credential = None
            elif spec.required and not secret_env:
                missing.append(spec.label)
            continue
        if not _visible(spec, values):
            continue
        value = _coerce(spec, source.get(spec.key)) or spec.default
        if value:
            values[spec.key] = value
        elif spec.required:
            missing.append(spec.label)
    if missing:
        raise invalid(f"Required: {', '.join(missing)}.")
    try:
        _validate_endpoints(kind, values, allow_private)
    except EndpointError as error:
        raise BusinessRuleError(str(error), code="GRAPH_ENDPOINT_UNSAFE") from error
    return values, credential


def _validate_endpoints(kind: TargetKind, values: dict[str, str], allow_private: bool) -> None:
    if kind.family == "sparql":
        for key in ("server_url", "query_url", "update_url"):
            if values.get(key):
                values[key] = check_http_url(values[key], field=_label(kind, key), allow_private=allow_private)
        if kind.id == "graphdb":
            if not _IDENT.match(values["repository_id"]):
                raise invalid("Repository ID: use letters, digits, '.', '_' or '-'.")
            values["server_url"] = values["server_url"].rstrip("/")
        return
    if kind.family == "neo4j":
        check_bolt_uri(values["uri"], field="Bolt URI", allow_private=allow_private)
        values["uri"] = values["uri"].rstrip("/")
        if not _IDENT.match(values["database"]):
            raise invalid("Database name: use letters, digits, '.', '_' or '-'.")
        return
    if kind.family == "gremlin":
        values["endpoint"] = normalize_cosmos_endpoint(values["endpoint"], allow_private=allow_private)
        for key, label in (("database", "Database name"), ("graph", "Graph / container name")):
            if not _IDENT.match(values[key]):
                raise invalid(f"{label}: use letters, digits, '.', '_' or '-'.")
        if not _PARTITION_PATH.match(values["partition_key_path"]):
            raise invalid("Graph partition-key path: use a single-level path such as /pk.")


def _label(kind: TargetKind, key: str) -> str:
    return next((f.label for f in kind.fields if f.key == key), key)


def normalize_cosmos_endpoint(endpoint: str, *, allow_private: bool) -> str:
    """Account name, host or ws(s):// URL -> ``host`` or ``ws://host`` (plain WebSocket only for local emulators)."""
    text = endpoint.strip()
    scheme = "wss"
    if "://" in text:
        scheme, _, text = text.partition("://")
        scheme = scheme.lower()
        if scheme not in ("ws", "wss"):
            raise invalid("Account / Gremlin endpoint: use a ws:// or wss:// URL, a host name or an account name.")
    host = text.split("/", 1)[0]
    if "@" in host:
        raise invalid("Account / Gremlin endpoint: credentials must not be embedded.")
    if ":" in host and not host.startswith("["):
        host, _, port_text = host.partition(":")
        if not port_text.isdigit():
            raise invalid("Account / Gremlin endpoint: invalid port.")
        check_port(int(port_text), field="Account / Gremlin endpoint")
    if "." not in host and classify_host(host) is None and _COSMOS_ACCOUNT.match(host):
        host = host.lower() + _COSMOS_SUFFIX
    host_class = check_host(host, field="Account / Gremlin endpoint", allow_private=allow_private)
    local = host_class in ("loopback", "private")
    if not local and not _COSMOS_HOST.match(host):
        raise invalid(
            "Account / Gremlin endpoint: expected <account>.gremlin.cosmos.azure.com "
            "(or a loopback/private address for the local emulator)."
        )
    if scheme == "ws" and not local:
        raise invalid("Account / Gremlin endpoint: plain ws:// is only allowed for the local emulator; use wss://.")
    return f"ws://{host}" if scheme == "ws" else host.lower() if not local else host


# ---------------------------------------------------------------------------------- derived settings


def effective_auth_type(config: dict[str, Any]) -> str:
    value = str(config.get("auth_type") or "").strip()
    if value in AUTH_TYPES:
        return value
    return "basic" if str(config.get("username") or "").strip() else "none"


def sparql_endpoints(kind_id: str, config: dict[str, Any]) -> tuple[str, str | None]:
    """(query endpoint, update endpoint or ``None`` when the connection is read-only)."""
    if kind_id == "graphdb":
        server = str(config.get("server_url") or "").rstrip("/")
        repository = str(config.get("repository_id") or "")
        query = str(config.get("query_url") or "") or f"{server}/repositories/{repository}"
        if config.get("access_mode") == "read-only":
            return query, None
        update = str(config.get("update_url") or "") or f"{server}/repositories/{repository}/statements"
        return query, update
    return str(config.get("query_url") or ""), (str(config.get("update_url") or "") or None)


def is_writable(kind_id: str, config: dict[str, Any]) -> bool:
    """Whether the registration can receive a deployment (the adapter exists *and* the config allows writes)."""
    kind = KINDS.get(kind_id)
    if kind is None or not kind.deployment_supported:
        return False
    if kind.family == "sparql":
        return sparql_endpoints(kind_id, config)[1] is not None
    return True


def display_config(kind_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """The stored config as shown to the UI; legacy SPARQL rows get their implied authentication type."""
    shown = dict(config)
    kind = KINDS.get(kind_id)
    if kind is not None and kind.family == "sparql":
        shown.setdefault("auth_type", effective_auth_type(config))
    return shown
