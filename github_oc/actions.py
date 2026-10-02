# Action handlers. Each casts the request envelope, binds the OpenConnector
# account the node points at, takes the organization / owner from that profile,
# resolves {{$...}} tokens, then either runs a CURATED OpenConnector action or a
# RAW GitHub REST call through oomol's provider proxy — and finishes the job with
# exactly one terminal call on every path.
#
# CURATED FIRST. oomol curates ~150 GitHub actions, which ops.py maps surface by
# surface; `node()` serves every one of them, so the only thing a curated surface
# needs here is its table. oomol declares every curated input with
# additionalProperties:false and camelCase names (perPage, issueNumber …), so the
# spelling lives in ops.py and tests/test_ops.py checks it against the catalog
# itself rather than against this file's memory of it.
#
# THE PROXY IS THE REMAINDER. Branch protection, Dependabot / secret-scanning /
# code-scanning alerts, org membership, deploy keys / webhooks / Actions secrets
# and the raw escape hatch are NOT curated by oomol, so they go through the
# provider proxy as exact GitHub REST paths, where GitHub's own snake_case
# parameter names apply. Those handlers are written out below.
#
# Scopes are not second-guessed: oomol checks its own requiredScopes for curated
# actions (this plugin refuses a visibly under-scoped account first, to save a
# round-trip), GitHub answers 403 for the rest, and both errors are rendered with
# their message.
#
# This plugin is a pure request builder: it holds no GitHub token and makes no
# GitHub calls. It builds and vets each request; FloMorphic proxies it.
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional

from inflow_plugin_sdk import Frame, Job, cast_request_to

from . import ops
from .oc import Client, GitHub, OcError
from .vars import resolve_input_vars


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _blank(v: Any) -> bool:
    """Whether a form field carries nothing: no value, an empty string, or an empty
    list / object. `false` and `0` are values, and are sent."""
    return v is None or v == "" or v == [] or v == {}


def _unset(v: Any) -> bool:
    """Whether a field was left unfilled. A number field the renderer hands back as
    0 counts as unfilled: every number oomol curates is an id, a 1-based position or
    a page, so 0 is the empty box rather than a value. A boolean false is a value."""
    if _blank(v):
        return True
    return isinstance(v, int) and not isinstance(v, bool) and v == 0


def _tri_bool(v: Any) -> Optional[bool]:
    """Read a three-state toggle: "true"/"false" become booleans, anything else
    (the untouched empty value) becomes None and is dropped. See forms.py."""
    if isinstance(v, bool):
        return v
    text = _text(v).lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _object(data: Any) -> dict[str, Any]:
    """Shape a gateway payload into the map the SDK commits onto the node's scope.
    An object is used as-is; a list is wrapped with a count so a downstream node
    can branch on "any results?"; anything else lands under "result"."""
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"items": data, "count": len(data)}
    if data is None:
        return {"ok": True}
    return {"result": data}


def _query(**pairs: Any) -> dict[str, str]:
    """Build a REST query string map, dropping empties and stringifying values
    (the FloMorphic proxy takes query as string→string)."""
    out: dict[str, str] = {}
    for key, value in pairs.items():
        if value in (None, "", False):
            continue
        out[key] = str(value)
    return out


def _inputs(body: dict[str, Any], op: ops.Op) -> dict[str, Any]:
    """Build one curated action's input from the form body: the fields the op
    declares, under oomol's names, with the unfilled ones left out so a blank field
    never overwrites anything. Raises ValueError on malformed JSON text."""
    out: dict[str, Any] = {}
    for spec in op.fields:
        form_name, _, curated = spec.partition(":")
        value = body.get(form_name)
        if form_name in op.json:
            value = _parse_json(value)
        elif form_name in op.bools:
            value = _tri_bool(value)
        if _unset(value):
            continue
        out[curated or form_name] = value
    return out


def _op_name(body: dict[str, Any], table: ops.Table) -> str:
    """Which operation the form picked. `op` is what every curated form sends;
    `kind` and `scope` are the names three of these forms used before the curated
    surface was widened, so a flow saved back then keeps its selection."""
    for key in ("op", "kind", "scope"):
        name = _text(body.get(key))
        if name:
            return name
    return table.default


_NO_OWNER = "no organization / owner set — open the node's account settings and fill Organization / owner"


class _Prep:
    """What every handler starts from: the bound account handle, the decoded
    action input (tokens resolved), and the organization / owner the profile
    carries."""

    __slots__ = ("gh", "body", "owner")

    def __init__(self, gh: GitHub, body: dict[str, Any], owner: str):
        self.gh, self.body, self.owner = gh, body, owner


class Actions:
    """The canvas action handlers, sharing the OpenConnector client."""

    def __init__(self, oc: Client):
        self._oc = oc

    # ------------------------------------------------------- pipeline --

    async def _prepare(self, job: Job, need_owner: bool = True) -> Optional[_Prep]:
        """Decode the envelope, bind the account, read the profile's owner, and
        resolve tokens. On any failure it finishes the job and returns None, so
        the caller returns."""
        try:
            rb = cast_request_to(job.req.data)
        except Exception as e:
            await job.done_with_error(f"invalid request body: {e}")
            return None
        body = dict(rb.body) if isinstance(rb.body, dict) else {}
        settings = body.pop("settings", None)  # the account travels separately
        settings = settings if isinstance(settings, dict) else {}
        owner = _text(settings.get("org"))
        if need_owner and not owner:
            await job.done_with_error(_NO_OWNER)
            return None
        try:
            gh = await self._oc.bind(_text(settings.get("alias")), _text(settings.get("connection")))
        except OcError as e:
            await job.done_with_error(str(e))
            return None
        await resolve_input_vars(job, body)
        return _Prep(gh, body, owner)

    async def _repo(self, job: Job, p: _Prep) -> Optional[str]:
        repo = _text(p.body.get("repo"))
        if not repo:
            await job.done_with_error("missing required input: repo")
        return repo or None

    async def _deny_curated(self, job: Job, gh: GitHub, action: str, verb: str) -> bool:
        """Refuse an under-scoped account before the call, using oomol's own
        requirement for the curated action. Returns True when it finished the job."""
        missing = await gh.missing_scopes(action)
        if missing:
            await job.done_with_error(
                f'the account "{gh.account.name()}" lacks the '
                f"{', '.join(repr(s) for s in missing)} scope needed to {verb} — "
                "reconnect it in FloMorphic → Connect with that scope"
            )
            return True
        return False

    async def _run(self, job: Job, title: str, content: str, call) -> None:
        """Report progress, await the gateway call, and finish the job."""
        await job.progress(20, Frame(title=title, content=content))
        try:
            data = await call
        except OcError as e:
            await job.done_with_error(str(e))
            return
        await job.progress(90, Frame(title=title, content="done"))
        await job.done(_object(data))

    # ----------------------------------------------- curated surfaces --

    def handler_for(self, method: str) -> Callable[[Job], Awaitable[None]]:
        """The handler one canvas action is wired to: the generic runner over the
        surface's ops table, or the handler written out below when the surface needs
        logic the table cannot express (search builds its own query) or is not
        curated by oomol at all (the proxy surfaces)."""
        own: dict[str, Callable[[Job], Awaitable[None]]] = {
            "github.search": self.search,
            "github.repo.protection": self.repo_protection,
            "github.alerts.dependabot": self.alerts_dependabot,
            "github.alerts.secret_scanning": self.alerts_secret_scanning,
            "github.alerts.code_scanning": self.alerts_code_scanning,
            "github.org.members": self.org_members,
            "github.repo.settings": self.repo_settings,
            "github.request": self.request,
        }
        return own.get(method) or self.node(method)

    def node(self, method: str) -> Callable[[Job], Awaitable[None]]:
        """The generic handler for a curated surface, bound to its ops table."""
        table = ops.TABLES[method]

        async def handler(job: Job) -> None:
            await self._curated(job, table)

        handler.__name__ = method.replace(".", "_")
        return handler

    async def _curated(self, job: Job, table: ops.Table) -> None:
        """Run the curated action the form's operation names: resolve the target
        (owner / repo from the profile), refuse an unfilled requirement or a
        visibly under-scoped account, then hand oomol the pruned input."""
        p = await self._prepare(job, need_owner=False)  # the op decides
        if p is None:
            return
        name = _op_name(p.body, table)
        op = table.ops.get(name)
        if op is None:
            await job.done_with_error(
                f"unknown operation {name!r} — expected one of {', '.join(table.names())}"
            )
            return
        if op.scope != "none" and not p.owner:
            await job.done_with_error(_NO_OWNER)
            return
        inputs: dict[str, Any] = {}
        where = f"as {p.gh.account.name()}"
        if op.scope == "repo":
            repo = await self._repo(job, p)
            if repo is None:
                return
            inputs, where = {"owner": p.owner, "repo": repo}, f"{p.owner}/{repo}"
        elif op.scope == "owner":
            inputs, where = {"owner": p.owner}, p.owner
        elif op.scope == "org":
            inputs, where = {"org": p.owner}, p.owner
        for field in op.needs:
            if _unset(p.body.get(field)):
                await job.done_with_error(f"missing required input: {field}")
                return
        try:
            inputs.update(_inputs(p.body, op))
        except ValueError as e:
            await job.done_with_error(str(e))
            return
        if await self._deny_curated(job, p.gh, op.action, op.verb()):
            return
        await self._run(job, op.title(), where, p.gh.action(op.action, inputs))

    async def search(self, job: Job) -> None:
        """`github.search` — the curated searches. The query is assembled here,
        because the "within the organization" prefix is this plugin's convenience
        rather than an oomol input; everything else comes from the table."""
        p = await self._prepare(job, need_owner=False)  # owner only when scoping to the org
        if p is None:
            return
        q = _text(p.body.get("q"))
        if not q:
            await job.done_with_error("missing required input: q")
            return
        if p.body.get("inOrg", True) is not False:
            if not p.owner:
                await job.done_with_error(_NO_OWNER)
                return
            if f"org:{p.owner}" not in q and f"user:{p.owner}" not in q:
                q = f"org:{p.owner} {q}"
        name = _op_name(p.body, ops.SEARCH)
        op = ops.SEARCH.ops.get(name)
        if op is None:
            await job.done_with_error(
                f"unknown operation {name!r} — expected one of {', '.join(ops.SEARCH.names())}"
            )
            return
        inputs: dict[str, Any] = {"query": q}
        inputs.update(_inputs(p.body, op))
        if await self._deny_curated(job, p.gh, op.action, op.verb()):
            return
        await self._run(job, f"Searching {name}", q, p.gh.action(op.action, inputs))

    # --------------------------------------- security surface (proxy) --

    async def repo_protection(self, job: Job) -> None:
        p = await self._prepare(job)
        if p is None:
            return
        repo = await self._repo(job, p)
        if repo is None:
            return
        branch = _text(p.body.get("branch"))
        await job.progress(20, Frame(title="Reading branch protection", content=f"{p.owner}/{repo}"))
        base = f"/repos/{p.owner}/{repo}"
        try:
            if not branch:
                repo_data = await p.gh.rest("GET", base)
                branch = repo_data.get("default_branch", "main") if isinstance(repo_data, dict) else "main"
            out: dict[str, Any] = {"owner": p.owner, "repo": repo, "branch": branch}
            try:
                out["protection"] = await p.gh.rest("GET", f"{base}/branches/{branch}/protection")
                out["protected"] = True
            except OcError as e:
                if "404" not in str(e):
                    raise
                out["protected"], out["protection"] = False, None
            if p.body.get("rulesets", True):
                try:
                    out["rulesets"] = await p.gh.rest("GET", f"{base}/rules/branches/{branch}")
                except OcError:
                    out["rulesets"] = None
        except OcError as e:
            await job.done_with_error(str(e))
            return
        await job.progress(90, Frame(title="Reading branch protection", content="done"))
        await job.done(out)

    async def _alerts(self, job: Job, kind: str, title: str) -> None:
        p = await self._prepare(job)
        if p is None:
            return
        query = _query(
            state=_text(p.body.get("state")),
            severity=_text(p.body.get("severity")),
            per_page=_int(p.body.get("perPage"), 30),
            page=_int(p.body.get("page"), 1),
        )
        if _text(p.body.get("target")) == "org":
            endpoint, where = f"/orgs/{p.owner}/{kind}/alerts", f"{p.owner} (org-wide)"
        else:
            repo = await self._repo(job, p)
            if repo is None:
                return
            endpoint, where = f"/repos/{p.owner}/{repo}/{kind}/alerts", f"{p.owner}/{repo}"
        await self._run(job, title, where, p.gh.rest("GET", endpoint, query=query))

    async def alerts_dependabot(self, job: Job) -> None:
        await self._alerts(job, "dependabot", "Listing Dependabot alerts")

    async def alerts_secret_scanning(self, job: Job) -> None:
        await self._alerts(job, "secret-scanning", "Listing secret-scanning alerts")

    async def alerts_code_scanning(self, job: Job) -> None:
        await self._alerts(job, "code-scanning", "Listing code-scanning alerts")

    async def org_members(self, job: Job) -> None:
        p = await self._prepare(job)
        if p is None:
            return
        per_page, page = _int(p.body.get("perPage"), 30), _int(p.body.get("page"), 1)
        kind = _text(p.body.get("kind")) or "members"
        if kind == "outside_collaborators":
            endpoint = f"/orgs/{p.owner}/outside_collaborators"
            query = _query(per_page=per_page, page=page)
        else:
            endpoint = f"/orgs/{p.owner}/members"
            filt, role = _text(p.body.get("filter")), _text(p.body.get("role"))
            query = _query(
                filter=filt if filt != "all" else "",
                role=role if role != "all" else "",
                per_page=per_page,
                page=page,
            )
        await self._run(job, "Listing org members", f"{p.owner} · {kind}", p.gh.rest("GET", endpoint, query=query))

    async def repo_settings(self, job: Job) -> None:
        p = await self._prepare(job)
        if p is None:
            return
        repo = await self._repo(job, p)
        if repo is None:
            return
        include = _text(p.body.get("include")) or "all"
        base = f"/repos/{p.owner}/{repo}"
        surfaces = {
            "keys": f"{base}/keys",
            "hooks": f"{base}/hooks",
            "actions_permissions": f"{base}/actions/permissions",
            "actions_secrets": f"{base}/actions/secrets",
        }
        wanted = list(surfaces) if include == "all" else [include]
        await job.progress(20, Frame(title="Reading repo settings", content=f"{p.owner}/{repo}"))
        out: dict[str, Any] = {"owner": p.owner, "repo": repo}
        for name in wanted:
            try:
                out[name] = await p.gh.rest("GET", surfaces[name])
            except OcError as e:
                out[name] = {"error": str(e)}
        await job.progress(90, Frame(title="Reading repo settings", content="done"))
        await job.done(out)

    async def request(self, job: Job) -> None:
        p = await self._prepare(job, need_owner=False)
        if p is None:
            return
        endpoint = _text(p.body.get("endpoint"))
        if not endpoint:
            await job.done_with_error("missing required input: endpoint")
            return
        if "{org}" in endpoint:
            if not p.owner:
                await job.done_with_error(_NO_OWNER)
                return
            endpoint = endpoint.replace("{org}", p.owner)
        method = _text(p.body.get("method")) or "GET"
        try:
            query = _parse_json_obj(p.body.get("query"))
            payload = _parse_json(p.body.get("body"))
        except ValueError as e:
            await job.done_with_error(str(e))
            return
        await self._run(
            job, "GitHub request", f"{method} {endpoint}",
            p.gh.rest(method, endpoint, query=query, body=payload),
        )


def _parse_json(value: Any) -> Any:
    """Parse an optional JSON text field. Empty → None; invalid → ValueError."""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception as e:
        raise ValueError(f"invalid JSON: {e}")


def _parse_json_obj(value: Any) -> Optional[dict[str, Any]]:
    parsed = _parse_json(value)
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise ValueError("query must be a JSON object")
    return parsed
