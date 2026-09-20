"""The OpenConnector client: account resolution, curated actions, the provider
proxy, and gateway error rendering — all over the fake sender."""
from __future__ import annotations

import pytest

from github_oc.oc import Client, OcError
from tests.conftest import gateway, one_github_account


def _default_handler(req):
    path = req["path"]
    if path == "/v1/connections":
        return 200, {"data": [one_github_account(), {"service": "gmail", "alias": "x"}]}
    if path.startswith("/v1/actions/github.") and req["method"] == "GET":
        return 200, {
            "success": True,
            "message": "OK",
            "data": {
                "requiredScopes": ["github.repo.read"],
                "inputSchema": {"properties": {"owner": {}, "repo": {}}, "additionalProperties": False},
            },
        }
    if path.startswith("/v1/actions/github."):
        return 200, {"data": {"echoed": req.get("body")}}
    if path == "/v1/proxy/github":
        # oomol's REST envelope around the proxied GitHub payload
        return 200, {"success": True, "message": "OK", "data": [{"login": "acme"}]}
    return 404, {"message": "Not Found"}


async def test_accounts_filtered_to_github():
    send = gateway(_default_handler)
    accounts = await Client(send).accounts()
    assert [a.service for a in accounts] == ["github"]
    assert accounts[0].alias == "work"
    assert "github.repo.read" in accounts[0].scopes


async def test_resolve_default_and_by_alias():
    c = Client(gateway(_default_handler))
    assert (await c.resolve()).alias == "work"          # default
    assert (await c.resolve("work")).alias == "work"    # by alias
    assert await c.resolve("nope") is None              # unknown alias


async def test_bind_missing_account_raises():
    def empty(req):
        if req["path"] == "/v1/connections":
            return 200, {"data": []}
        return 200, {}

    with pytest.raises(OcError, match="no GitHub account connected"):
        await Client(gateway(empty)).bind()


async def test_curated_action_payload():
    send = gateway(_default_handler)
    gh = await Client(send).bind("work")
    out = await gh.action("get_repository", {"owner": "o", "repo": "r"})
    call = [c for c in send.calls if c["path"] == "/v1/actions/github.get_repository" and c["method"] == "POST"][0]
    assert call["query"] == {"alias": "work"}
    assert call["body"] == {"input": {"owner": "o", "repo": "r"}}
    assert out == {"echoed": {"input": {"owner": "o", "repo": "r"}}}


async def test_curated_input_pruned_to_live_schema():
    send = gateway(_default_handler)
    gh = await Client(send).bind("work")
    await gh.action("get_repository", {"owner": "o", "repo": "r", "per_page": 30, "ref": ""})
    call = [c for c in send.calls if c["path"] == "/v1/actions/github.get_repository" and c["method"] == "POST"][0]
    # additionalProperties:false → the undeclared key is dropped, empties too
    assert call["body"]["input"] == {"owner": "o", "repo": "r"}


async def test_rest_proxy_payload_and_envelope_unwrap():
    send = gateway(_default_handler)
    gh = await Client(send).bind("work")
    out = await gh.rest("GET", "/user/orgs", query={"per_page": 100, "skip": ""})
    call = [c for c in send.calls if c["path"] == "/v1/proxy/github"][0]
    inner = call["body"]
    assert inner["endpoint"] == "/user/orgs"
    assert inner["method"] == "GET"
    assert inner["query"] == {"per_page": "100"}  # empties dropped, values stringified
    assert out == [{"login": "acme"}]  # {success, message, data} envelope unwrapped


async def test_required_scopes_cached():
    send = gateway(_default_handler)
    c = Client(send)
    assert await c.required_scopes("get_repository") == ["github.repo.read"]
    await c.required_scopes("get_repository")
    defs = [c for c in send.calls if c["path"] == "/v1/actions/github.get_repository" and c["method"] == "GET"]
    assert len(defs) == 1  # fetched once, then cached


async def test_missing_scopes_compares_only_same_vocabulary():
    send = gateway(_default_handler)
    gh = await Client(send).bind("work")  # account has github.user.read, github.repo.read
    assert await gh.missing_scopes("get_repository") == []
    gh.account.scopes = ["github.user.read"]  # same vocabulary, lacks repo.read
    assert await gh.missing_scopes("get_repository") == ["github.repo.read"]
    gh.account.scopes = ["repo", "read:org"]  # GitHub OAuth vocabulary → not comparable, defer to oomol
    assert await gh.missing_scopes("get_repository") == []


async def test_gateway_error_uses_github_message():
    def handler(req):
        if req["path"] == "/v1/connections":
            return 200, {"data": [one_github_account()]}
        return 404, {"message": "Not Found"}

    gh = await Client(gateway(handler)).bind("work")
    with pytest.raises(OcError, match="Not Found .HTTP 404."):
        await gh.rest("GET", "/repos/o/r")
