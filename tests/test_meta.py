"""Meta helpers and the account / org pickers."""
from __future__ import annotations

import json

from github_oc.meta import Meta, conn_from, decode_meta, read_call, _resolve
from github_oc.oc import Client
from inflow_plugin_sdk.formkit import NotifKey, Option
from tests.conftest import FakeReq, gateway, one_github_account


def test_decode_meta_envelope_and_bare():
    assert decode_meta(json.dumps({"body": {"a": 1}}).encode()) == {"a": 1}
    assert decode_meta(json.dumps({"a": 1}).encode()) == {"a": 1}
    assert decode_meta(b"") == {}
    assert decode_meta(b"not json") == {}


def test_conn_from_prefers_nested_settings():
    assert conn_from({"settings": {"alias": "w"}, "value": "x"}) == {"alias": "w"}
    # no bound profile: top-level values minus host keys
    assert conn_from({"alias": "w", "targetField": "alias", "form": "f"}) == {"alias": "w"}


def test_read_call_defaults_target():
    call = read_call(json.dumps({"body": {"value": "ac", "settings": {"alias": "w"}}}).encode(), "repo")
    assert call.target == "repo" and call.value == "ac" and call.settings == {"alias": "w"}


def test_resolve_exact_substring_and_ambiguous():
    opts = [Option("acme-api", "acme-api"), Option("acme-web", "acme-web"), Option("other", "other")]
    match, cands = _resolve(opts, "acme-api")
    assert match.value == "acme-api"
    match, cands = _resolve(opts, "acme")
    assert match is None and {c.value for c in cands} == {"acme-api", "acme-web"}
    match, cands = _resolve(opts, "")  # blank lists all
    assert match is None and len(cands) == 3


def _handler(req):
    path = req["path"]
    if path == "/v1/connections":
        return 200, {"data": [one_github_account()]}
    if path == "/v1/proxy/github":
        endpoint = req["body"]["endpoint"]
        if endpoint == "/user/orgs":
            return 200, {"data": [{"login": "acme"}, {"login": "globex"}]}
        if endpoint == "/user":
            return 200, {"data": {"login": "octocat"}}
    return 404, {"message": "Not Found"}


async def test_account_list_rebuilds_alias_dropdown():
    m = Meta(Client(gateway(_handler)))
    res = await m.account_list(FakeReq(data=json.dumps({"body": {}}).encode()))
    schema = res["schema"]
    one_of = schema["properties"]["alias"]["oneOf"]
    assert {o["const"] for o in one_of} == {"work"}
    assert NotifKey in res


async def test_org_list_picker_when_ambiguous():
    m = Meta(Client(gateway(_handler)))
    body = {"body": {"settings": {"alias": "work"}, "value": "", "targetField": "org", "form": "github.settings"}}
    res = await m.org_list(FakeReq(data=json.dumps(body).encode()))
    schema = res["schema"]
    assert {o["const"] for o in schema["properties"]["org"]["oneOf"]} == {"acme", "globex"}


async def test_org_list_resolves_exact():
    m = Meta(Client(gateway(_handler)))
    body = {"body": {"settings": {"alias": "work"}, "value": "acme", "targetField": "org", "form": "github.settings"}}
    res = await m.org_list(FakeReq(data=json.dumps(body).encode()))
    assert res["org"] == "acme"  # patched straight into the field


async def test_settings_submit_ok_and_missing():
    m = Meta(Client(gateway(_handler)))
    ok = await m.settings_submit(FakeReq(data=json.dumps({"body": {"settings": {"alias": "work"}}}).encode()))
    assert ok.data["ok"] is True and ok.data["alias"] == "work"
    bad = await m.settings_submit(FakeReq(data=json.dumps({"body": {"alias": "ghost"}}).encode()))
    assert bad.error and "ghost" in bad.error
