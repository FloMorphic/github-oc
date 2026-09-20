# The settings meta RPCs the dialog calls while it is open, and the org / repo
# pickers the action forms use. A meta function is a synchronous request/reply
# (no job): it answers with a formkit patch (write a value + a message into the
# open form), a form envelope (rebuild a field as a drop-down), or the
# {data, error} Response the settings submit expects.
#
# These are the only places this plugin talks to the user's dialog. Everything
# GitHub-specific — which accounts exist, which orgs/repos to offer — is resolved
# here through the OpenConnector bridge, never in the backend.
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from inflow_plugin_sdk import Request, Response
from inflow_plugin_sdk import formkit
from inflow_plugin_sdk.formkit import Notification, Option

from . import forms
from .oc import Client, GitHub, OcError

# Keys the host and the lookup button add on top of the form's own fields — not
# form data, and never echoed back into a rebuilt form.
_HOST_KEYS = {"settings", "value", "targetField", "form"}


# ------------------------------------------------------------- decoding --


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def decode_meta(data: bytes) -> dict[str, Any]:
    """Read a meta RPC's arguments, tolerating the {_registry, body} envelope or a
    bare object, and treating anything unreadable as "no arguments"."""
    if not data:
        return {}
    text = data.decode(errors="replace").strip()
    if text == "":
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        body = parsed.get("body")
        if isinstance(body, dict):
            return body
        return parsed
    return {}


def conn_from(body: dict[str, Any]) -> dict[str, Any]:
    """Pull the profile values out of a meta/submit call. On an action's drawer the
    bound profile is under "settings"; the set-up dialog has no bound profile and
    sends the edited values at the top level, alongside host keys."""
    nested = body.get("settings")
    if isinstance(nested, dict) and nested:
        return nested
    return {k: v for k, v in body.items() if k not in _HOST_KEYS}


def _pick(body: dict[str, Any], key: str) -> Any:
    nested = body.get("settings")
    if isinstance(nested, dict) and key in nested:
        return nested[key]
    return body.get(key)


@dataclass
class MetaCall:
    """One press of a lookup button: the whole form as it stands, plus what the
    host adds (settings, value) and what the button declares (targetField, form)."""

    body: dict[str, Any]
    settings: dict[str, Any]
    value: str
    target: str
    form: str


def read_call(data: bytes, default_target: str) -> MetaCall:
    body = decode_meta(data)
    settings = body.get("settings")
    settings = settings if isinstance(settings, dict) else {}
    target = _text(body.get("targetField")) or default_target
    return MetaCall(
        body=body,
        settings=settings,
        value=_text(body.get("value")),
        target=target,
        form=_text(body.get("form")),
    )


# --------------------------------------------------------- patch helpers --


def _failed(fmt: str, *args: Any) -> dict[str, Any]:
    return formkit.failure(fmt, *args).patch(None)


def _missed(fmt: str, *args: Any) -> dict[str, Any]:
    return formkit.warning(fmt, *args).patch(None)


def _resolved(target: str, value: str, fmt: str, *args: Any) -> dict[str, Any]:
    return formkit.success(fmt, *args).patch({target: value})


def _resolve(options: list[Option], term: str) -> "tuple[Optional[Option], list[Option]]":
    """Turn what the user typed into the option they meant. An exact value hit
    wins; otherwise anything containing the term is a candidate. Empty term
    matches everything, so pressing the button on a blank field lists all."""
    term = term.strip().lower()
    candidates: list[Option] = []
    for opt in options:
        if term and opt.value.lower() == term:
            return opt, []
        if term == "" or term in opt.value.lower() or term in opt.label.lower():
            candidates.append(opt)
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates


class Meta:
    """The meta RPC handlers, sharing the OpenConnector client with the actions."""

    def __init__(self, oc: Client):
        self._oc = oc
        # method -> built form, so a picker rebuilds the dialog the button sits on.
        self._forms = {
            "github.repos.list": forms.repos_list_form,
            "github.repo.get": forms.repo_get_form,
            "github.repo.collaborators": forms.repo_collaborators_form,
            "github.repo.contents": forms.repo_contents_form,
            "github.activity.list": forms.activity_list_form,
            "github.repo.protection": forms.repo_protection_form,
            "github.alerts.dependabot": forms.alerts_dependabot_form,
            "github.alerts.secret_scanning": forms.alerts_secret_scanning_form,
            "github.alerts.code_scanning": forms.alerts_code_scanning_form,
            "github.org.members": forms.org_members_form,
            "github.repo.settings": forms.repo_settings_form,
            # The org picker on the settings dialog rebuilds the settings form.
            "github.settings": lambda: forms.settings_form().build(),
        }

    def _form_for(self, method: str):
        builder = self._forms.get(method)
        return builder() if builder else None

    async def _bind(self, settings: dict[str, Any]) -> "tuple[Optional[GitHub], Optional[dict[str, Any]]]":
        """Resolve a meta call's account into a bound handle. A missing profile is
        reported into the form (the host has no channel for a raised error)."""
        try:
            gh = await self._oc.bind(_text(settings.get("alias")), _text(settings.get("connection")))
            return gh, None
        except OcError as e:
            return None, _failed("%s", str(e))

    async def _bind_call(self, call: MetaCall) -> "tuple[Optional[GitHub], Optional[dict[str, Any]]]":
        """Bind the account a picker call points at. On an action drawer the profile
        is nested under "settings"; on the settings set-up dialog it is edited at
        the top level (no bound profile yet), so fall back to conn_from()."""
        creds = call.settings or conn_from(call.body)
        return await self._bind(creds)

    def _picker(self, call: MetaCall, options: list[Option], status: str) -> Any:
        form = self._form_for(call.form)
        if form is None:
            # No known form to rebuild — list the candidates as text on the field.
            body = formkit.lines(options)
            return Notification(
                severity="info", field=call.target, message=(status + "\n" + body).strip()
            ).patch(None)
        return formkit.choose(
            form, call.target, options, formkit.form_data(call.body), formkit.info("%s", status).about(call.target)
        )

    # ----------------------------------------------------- account RPCs --

    async def account_list(self, req: Request) -> Any:
        """Backs "Load accounts": rebuild the alias field into a drop-down of the
        GitHub accounts connected in FloMorphic → Connect."""
        body = decode_meta(req.data)
        connection = _text(_pick(body, "connection"))
        try:
            accounts = await self._oc.accounts(connection)
        except OcError as e:
            return formkit.failure("%s", str(e)).about("alias").patch(None)
        if not accounts:
            return (
                formkit.warning(
                    "No GitHub account connected. Connect one in FloMorphic → Connect, then retry."
                )
                .about("alias")
                .patch(None)
            )
        options = [
            Option(a.alias, f"{a.name()}{'  (default)' if a.is_default else ''}") for a in accounts
        ]
        return formkit.choose(
            forms.settings_form().build(),
            "alias",
            options,
            formkit.form_data(body),
            formkit.success("%d connected GitHub account(s) — pick one:", len(accounts)).about("alias"),
        )

    async def account_test(self, req: Request) -> Any:
        """Backs "Test account" and submit validation: the chosen account resolves."""
        conn = conn_from(decode_meta(req.data))
        alias = _text(conn.get("alias"))
        connection = _text(conn.get("connection"))
        try:
            acc = await self._oc.resolve(alias, connection)
        except OcError as e:
            return _failed("%s", str(e))
        if acc is None:
            if alias:
                return _failed('No connected GitHub account with alias "%s".', alias)
            return _failed("No GitHub account connected.")
        suffix = " — default" if acc.is_default else ""
        return formkit.success("Resolved %s (alias %s)%s.", acc.name(), acc.alias or "—", suffix).patch(None)

    async def user_info(self, req: Request) -> Any:
        """Backs "Check identity": show the connected login and granted scopes."""
        conn = conn_from(decode_meta(req.data))
        gh, bad = await self._bind(conn)
        if bad is not None:
            return {formkit.NotifKey: bad[formkit.NotifKey].about("identity")}
        scopes = ", ".join(gh.account.scopes) if gh.account.scopes else "none reported"
        try:
            data = await gh.rest("GET", "/user")
            login = data.get("login") if isinstance(data, dict) else None
        except OcError:
            login = None
        who = f"@{login}" if login else gh.account.name()
        return formkit.success("Connected as %s. Scopes: %s.", who, scopes).about("identity").patch(None)

    # ------------------------------------------------------ pickers --

    async def org_list(self, req: Request) -> Any:
        """Backs "Load orgs": offer the organizations the account belongs to."""
        call = read_call(req.data, default_target="owner")
        gh, bad = await self._bind_call(call)
        if bad is not None:
            return {formkit.NotifKey: bad[formkit.NotifKey].about(call.target)}
        try:
            data = await gh.rest("GET", "/user/orgs", query={"per_page": "100"})
        except OcError as e:
            return formkit.failure("could not list orgs: %s", str(e)).about(call.target).patch(None)
        logins = [o.get("login") for o in data] if isinstance(data, list) else []
        options = [Option(str(l), str(l)) for l in logins if l]
        if not options:
            return (
                formkit.warning(
                    "This token cannot list organizations (a connection granted to one specific org "
                    "can't enumerate them) — type the organization it was granted to."
                )
                .about(call.target)
                .patch(None)
            )
        match, candidates = _resolve(options, call.value)
        if match is not None:
            return _resolved(call.target, match.value, "Owner: %s", match.label)
        if not candidates:
            return _missed('No org matches "%s" — type the owner login directly.', call.value)
        return self._picker(call, candidates, f"{len(candidates)} organization(s) — pick one.")

    async def repo_list(self, req: Request) -> Any:
        """Backs "Load repos": offer the repositories for the owner in the form."""
        call = read_call(req.data, default_target="repo")
        # The owner is the organization on the bound profile — never an action field.
        owner = _text((call.settings or conn_from(call.body)).get("org"))
        if not owner:
            return (
                formkit.warning(
                    "No organization / owner on this account profile — set it in the node's account settings first."
                )
                .about(call.target)
                .patch(None)
            )
        gh, bad = await self._bind_call(call)
        if bad is not None:
            return {formkit.NotifKey: bad[formkit.NotifKey].about(call.target)}
        try:
            data = await self._repos_for(gh, owner)
        except OcError as e:
            return formkit.failure("could not list repos: %s", str(e)).about(call.target).patch(None)
        names = [r.get("name") for r in data] if isinstance(data, list) else []
        options = [Option(str(n), str(n)) for n in names if n]
        if not options:
            return (
                formkit.warning('No repositories found for "%s" — type the name directly.', owner)
                .about(call.target)
                .patch(None)
            )
        match, candidates = _resolve(options, call.value)
        if match is not None:
            return _resolved(call.target, match.value, "Repository: %s", match.label)
        if not candidates:
            return _missed('No repo matches "%s" — type the name directly.', call.value)
        return self._picker(call, candidates, f"{len(candidates)} repositor(y/ies) — pick one.")

    async def _repos_for(self, gh: GitHub, owner: str) -> Any:
        """Repos for an owner: try the org endpoint (private repos when scoped),
        fall back to the user endpoint (works for users and orgs)."""
        query = {"per_page": "100", "type": "all", "sort": "full_name"}
        try:
            return await gh.rest("GET", f"/orgs/{owner}/repos", query=query)
        except OcError:
            return await gh.rest("GET", f"/users/{owner}/repos", query={"per_page": "100"})

    # ------------------------------------------------------ submit --

    async def settings_submit(self, req: Request) -> Response:
        """Validate a profile on save: the chosen account must resolve."""
        conn = conn_from(decode_meta(req.data))
        alias = _text(conn.get("alias"))
        connection = _text(conn.get("connection"))
        try:
            acc = await self._oc.resolve(alias, connection)
        except OcError as e:
            return Response(error=str(e))
        if acc is None:
            if alias:
                return Response(error=f'No connected GitHub account with alias "{alias}". Press Load accounts.')
            return Response(error="No GitHub account connected in FloMorphic → Connect.")
        return Response(data={"ok": True, "account": acc.name(), "alias": acc.alias})
