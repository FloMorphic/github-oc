# The plugin's bridge to OpenConnector, over FloMorphic's central credential.
#
# The FloMorphic backend is a GENERIC proxy: it stores the OpenConnector
# connection (a GitHub OAuth token or PAT) and forwards a request verbatim over
# the single NATS subject `flomorphic.svc.oc.proxy`. It knows nothing about
# GitHub, accounts, actions or capabilities — ALL of that lives here, in the
# plugin. This plugin holds no GitHub credentials and makes no GitHub calls; it
# builds OpenConnector requests and lets the backend execute them.
#
# It reaches the gateway two ways, both through that one NATS proxy:
#   * CURATED actions  — POST /v1/actions/github.<action> {input}
#   * PROVIDER proxy   — POST /v1/proxy/github {endpoint, method, query, body}
#     (a signed passthrough to https://api.github.com for what oomol does not
#     curate: Dependabot / secret-scanning / code-scanning alerts, branch
#     protection, org members, deploy keys, webhooks, the audit log …)
#
# Reaching the proxy needs an OPEN (multi) runtime credential — a strict,
# plugin-scoped credential cannot publish on `flomorphic.>`. See the README.
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

# The OpenConnector service id this plugin targets — the `service` field
# GET /v1/connections reports for GitHub connections on the gateway.
APP = "github"

# The FloMorphic OpenConnector NATS proxy (see the backend's ocproxy.go). It
# sits OUTSIDE the inflow node protocol.
PROXY_SUBJECT = "flomorphic.svc.oc.proxy"

# Send is a NATS request/reply, satisfied by Plugin.send: it returns (msg, err)
# and never raises (a workflow the user has stopped leaves no responders).
Send = Callable[[str, bytes], Awaitable["tuple[Optional[Any], Optional[Exception]]"]]


class OcError(Exception):
    """A failure talking to OpenConnector, already phrased for the user."""


@dataclass
class Account:
    """One connected GitHub account, from OpenConnector's GET /v1/connections.
    `scopes` is what the plugin checks an action's requirement against."""

    id: str = ""
    service: str = ""
    status: str = ""
    account_label: str = ""
    alias: str = ""
    auth_type: str = ""
    is_default: bool = False
    scopes: list[str] = field(default_factory=list)

    def name(self) -> str:
        """The human label, falling back to the alias then the service."""
        return self.account_label or self.alias or self.service


def _to_account(c: dict[str, Any]) -> Account:
    raw = c.get("scopes")
    scopes = [str(s) for s in raw] if isinstance(raw, list) else []
    return Account(
        id=str(c.get("id") or ""),
        service=str(c.get("service") or ""),
        status=str(c.get("status") or ""),
        account_label=str(c.get("accountLabel") or ""),
        alias=str(c.get("alias") or ""),
        auth_type=str(c.get("authType") or ""),
        is_default=c.get("isDefault") is True,
        scopes=scopes,
    )


def _enc(v: Any) -> bytes:
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False).encode()


def _dec(data: Optional[bytes]) -> Any:
    if not data:
        return {}
    text = data.decode(errors="replace").strip()
    if text == "":
        return {}
    return json.loads(text)


# The keys oomol's reply envelope carries around the payload: {success, message,
# data} on the REST API, {data} alone on some paths, {status, headers, data} on
# the provider proxy. A body made of only these keys is an envelope to unwrap;
# anything else (a GitHub record that happens to have a `data` key, say) is not.
_ENVELOPE_KEYS = {"success", "message", "data", "status", "headers"}


def _unwrap(body: Any) -> Any:
    """Return the payload inside oomol's reply envelope, or the body as-is."""
    if isinstance(body, dict) and "data" in body and set(body.keys()) <= _ENVELOPE_KEYS:
        return body["data"]
    return body


def _gateway_error(body: Any, status: int) -> str:
    """Render a 4xx/5xx into the most specific message the gateway gave — GitHub's
    own "Not Found" / "Bad credentials" rather than a bare status code."""
    if isinstance(body, dict):
        for key in ("message", "error", "description"):
            msg = body.get(key)
            if isinstance(msg, str) and msg.strip():
                return f"{msg.strip()} (HTTP {status})"
        data = body.get("data")
        if isinstance(data, dict):
            for key in ("message", "description"):
                msg = data.get(key)
                if isinstance(msg, str) and msg.strip():
                    return f"{msg.strip()} (HTTP {status})"
    if isinstance(body, str) and body.strip() and len(body) <= 300:
        return f"HTTP {status}: {body.strip()}"
    return f"HTTP {status}"


class Client:
    """A generic OpenConnector client that runs every request through the
    FloMorphic NATS proxy. All GitHub knowledge is in the helpers below and in
    the actions, never in the backend."""

    def __init__(self, send: Send):
        self._send = send
        # A curated action's definition (requiredScopes, inputSchema) is stable
        # for a running plugin, so fetch each one from the catalog only once.
        self._def_cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------- transport --

    async def proxy(
        self,
        method: str,
        path: str,
        *,
        connection: str = "",
        query: Optional[dict[str, str]] = None,
        body: Any = None,
    ) -> Any:
        """Forward one gateway request and return its (unwrapped) response body."""
        req: dict[str, Any] = {"method": method, "path": path}
        if connection:
            req["connection"] = connection
        if query:
            req["query"] = query
        if body is not None:
            req["body"] = body

        msg, err = await self._send(PROXY_SUBJECT, _enc(req))
        if err is not None:
            raise OcError(f"OpenConnector round-trip failed: {err}")
        if msg is None:
            raise OcError(f"OpenConnector {path} timed out with no reply")

        try:
            reply = _dec(msg.data)
        except Exception as e:
            raise OcError(f"OpenConnector {path}: unreadable reply: {e}")

        if isinstance(reply, dict):
            if reply.get("error"):
                raise OcError(str(reply["error"]))
            status = reply.get("status")
            if isinstance(status, int) and status >= 400:
                raise OcError(f"{path}: {_gateway_error(reply.get('body'), status)}")
            return reply.get("body")
        return reply

    # ------------------------------------------------------------- accounts --

    async def accounts(self, connection: str = "") -> list[Account]:
        """The connected GitHub accounts (GET /v1/connections, filtered to this app)."""
        body = await self.proxy("GET", "/v1/connections", connection=connection)
        rows = body.get("data") if isinstance(body, dict) else None
        rows = rows if isinstance(rows, list) else []
        return [_to_account(c) for c in rows if isinstance(c, dict) and c.get("service") == APP]

    async def resolve(self, alias: str = "", connection: str = "") -> Optional[Account]:
        """Resolve one account by alias (or the default when alias is empty).
        None means "nothing connected / no such alias" — the caller phrases it."""
        rows = await self.accounts(connection)
        if not rows:
            return None
        wanted = (alias or "").strip()
        if wanted == "":
            for a in rows:
                if a.is_default:
                    return a
            return rows[0]
        for a in rows:
            if a.alias == wanted or a.account_label == wanted:
                return a
        return None

    # ---------------------------------------------------------- capabilities --

    async def definition(self, action: str, connection: str = "") -> dict[str, Any]:
        """A CURATED action's definition, read live from the gateway's own catalog
        (GET /v1/actions/github.<action>) and cached: `requiredScopes` drives the
        capability check and `inputSchema` (which oomol declares with
        additionalProperties:false) drives input pruning. {} when unreadable —
        callers then skip both and let oomol be the gate."""
        cached = self._def_cache.get(action)
        if cached is not None:
            return cached
        try:
            body = await self.proxy("GET", f"/v1/actions/{APP}.{action}", connection=connection)
            defn = _unwrap(body)
            defn = defn if isinstance(defn, dict) else {}
        except OcError:
            defn = {}
        self._def_cache[action] = defn
        return defn

    async def required_scopes(self, action: str, connection: str = "") -> list[str]:
        """The scopes oomol says a curated action needs (authoritative, not
        hardcoded); [] when unknown."""
        raw = (await self.definition(action, connection)).get("requiredScopes")
        return [str(s) for s in raw] if isinstance(raw, list) else []

    # -------------------------------------------------------------- binding --

    async def bind(self, alias: str = "", connection: str = "") -> "GitHub":
        """Resolve the account a node is bound to and return a GitHub handle
        scoped to it. The error is already phrased for the user."""
        acct = await self.resolve(alias, connection)
        if acct is None:
            if (alias or "").strip():
                raise OcError(
                    f'no connected GitHub account with alias "{alias}" — pick one in the node\'s settings'
                )
            raise OcError("no GitHub account connected in FloMorphic → Connect")
        return GitHub(self, acct, connection)


class GitHub:
    """An OpenConnector client bound to one resolved GitHub account. An action
    either runs a curated action (`action`) or a raw REST call (`rest`); the
    backend performs it as this account and returns the gateway's payload."""

    def __init__(self, client: Client, account: Account, connection: str = ""):
        self._client = client
        self.account = account
        self._connection = connection

    def _query(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        q: dict[str, str] = {}
        if self.account.alias:
            q["alias"] = self.account.alias
        if extra:
            q.update(extra)
        return q

    async def action(self, name: str, input: dict[str, Any]) -> Any:
        """Run one curated GitHub action — POST /v1/actions/github.<name> {input}.

        oomol declares every input schema with additionalProperties:false, so a
        key it does not know is a hard 400. The input is therefore pruned to the
        properties the LIVE definition declares (and empties are dropped), which
        keeps a gateway that curates a field differently from failing the whole
        call. When the definition is unreadable the input passes through as-is."""
        defn = await self._client.definition(name, self._connection)
        schema = defn.get("inputSchema") if isinstance(defn, dict) else None
        props = schema.get("properties") if isinstance(schema, dict) else None
        clean = {k: v for k, v in input.items() if v not in (None, "")}
        if isinstance(props, dict) and schema.get("additionalProperties") is False:
            clean = {k: v for k, v in clean.items() if k in props}
        body = await self._client.proxy(
            "POST",
            f"/v1/actions/{APP}.{name}",
            connection=self._connection,
            query=self._query(),
            body={"input": clean},
        )
        return _unwrap(body)

    async def rest(
        self,
        method: str,
        endpoint: str,
        *,
        query: Optional[dict[str, Any]] = None,
        body: Any = None,
    ) -> Any:
        """Run one raw GitHub REST call through oomol's provider proxy —
        POST /v1/proxy/github {endpoint, method, query, body}. Use it for the
        security surface oomol does not curate; oomol signs the path with this
        account's credential and sets the GitHub API headers."""
        payload: dict[str, Any] = {"endpoint": endpoint, "method": method.upper()}
        if query:
            # The FloMorphic proxy takes query as string→string; drop empties.
            payload["query"] = {k: str(v) for k, v in query.items() if v not in (None, "")}
        if body is not None:
            payload["body"] = body
        out = await self._client.proxy(
            "POST",
            f"/v1/proxy/{APP}",
            connection=self._connection,
            query=self._query(),
            body=payload,
        )
        return _unwrap(out)

    async def missing_scopes(self, action: str) -> list[str]:
        """The scopes this account lacks for a curated action, or [] when the two
        sides cannot be compared (leaving oomol as the authoritative gate): either
        is unknown, or they use different vocabularies — the catalog speaks
        oomol's `github.repo.read`, while a connection may report GitHub's own
        OAuth scopes (`repo`, `read:org`)."""
        required = await self._client.required_scopes(action, self._connection)
        have = self.account.scopes
        if not required or not have:
            return []
        if not any(s.startswith(f"{APP}.") for s in have):
            return []  # GitHub-OAuth-style scopes; not comparable to oomol's
        return [s for s in required if s not in have]
