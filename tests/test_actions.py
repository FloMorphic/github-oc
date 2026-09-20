"""Action handlers end-to-end over the fake gateway: the owner always comes from
the profile, curated inputs match oomol's camelCase schema, the rest goes over
exact REST paths, {{$...}} resolution, and the raw request."""
from __future__ import annotations

from github_oc.actions import Actions
from github_oc.oc import Client
from tests.conftest import FakeJob, gateway, one_github_account

# oomol's live definition shape (from GET /v1/actions?service=github), trimmed.
_DEFS = {
    "get_repository": {
        "requiredScopes": ["github.repo.read"],
        "inputSchema": {"type": "object", "properties": {"owner": {}, "repo": {}}, "additionalProperties": False},
    },
    "list_my_repositories": {
        "requiredScopes": ["github.repo.read"],
        "inputSchema": {
            "type": "object",
            "properties": {"visibility": {}, "sort": {}, "direction": {}, "perPage": {}, "page": {}},
            "additionalProperties": False,
        },
    },
    "list_commits": {
        "requiredScopes": ["github.repo.read"],
        "inputSchema": {
            "type": "object",
            "properties": {"owner": {}, "repo": {}, "sha": {}, "since": {}, "perPage": {}, "page": {}},
            "additionalProperties": False,
        },
    },
}


def make_actions(scopes=None):
    def handler(req):
        path = req["path"]
        if path == "/v1/connections":
            return 200, {"success": True, "message": "OK", "data": [one_github_account(scopes=scopes)]}
        if path.startswith("/v1/actions/github.") and req["method"] == "GET":
            return 200, {"success": True, "message": "OK", "data": _DEFS[path.rsplit(".", 1)[1]]}
        if path.startswith("/v1/actions/github."):
            return 200, {"success": True, "message": "OK", "data": {"full_name": "o/r", "input": req["body"]["input"]}}
        if path == "/v1/proxy/github":
            inner = req["body"]
            endpoint = inner["endpoint"]
            if endpoint.endswith("/dependabot/alerts"):
                return 200, {"success": True, "message": "OK", "data": [{"number": 1}, {"number": 2}]}
            if endpoint == "/repos/acme/r":
                return 200, {"success": True, "message": "OK", "data": {"default_branch": "main"}}
            if endpoint.endswith("/protection"):
                return 404, {"message": "Branch not protected"}
            return 200, {"success": True, "message": "OK", "data": {"endpoint": endpoint, "query": inner.get("query")}}
        return 404, {"message": "Not Found"}

    send = gateway(handler)
    return Actions(Client(send)), send


def _posted(send, action):
    return [c for c in send.calls if c["path"] == f"/v1/actions/github.{action}" and c["method"] == "POST"]


def _proxied(send):
    return [c["body"] for c in send.calls if c["path"] == "/v1/proxy/github"]


SETTINGS = {"alias": "work", "org": "acme"}


async def test_repo_get_uses_profile_owner_and_camel_case_input():
    acts, send = make_actions()
    job = FakeJob(body={"repo": "r", "perPage": 5, "settings": SETTINGS})
    await acts.repo_get(job)
    assert job.error is None
    assert job.done_data["full_name"] == "o/r"
    inp = _posted(send, "get_repository")[0]["body"]["input"]
    assert inp == {"owner": "acme", "repo": "r"}  # pruned to the live inputSchema; no settings leak


async def test_no_owner_on_profile_is_a_clear_error():
    acts, send = make_actions()
    job = FakeJob(body={"repo": "r", "settings": {"alias": "work"}})
    await acts.repo_get(job)
    assert job.error and "account settings" in job.error
    assert not _posted(send, "get_repository")


async def test_repos_list_mine_is_curated_with_camel_case():
    acts, send = make_actions()
    job = FakeJob(body={"scope": "mine", "perPage": 50, "page": 2, "settings": {"alias": "work"}})
    await acts.repos_list(job)
    assert job.error is None
    inp = _posted(send, "list_my_repositories")[0]["body"]["input"]
    assert inp == {"visibility": "all", "sort": "full_name", "perPage": 50, "page": 2}


async def test_repos_list_org_is_rest_on_profile_org():
    acts, send = make_actions()
    job = FakeJob(body={"scope": "org", "perPage": 50, "settings": SETTINGS})
    await acts.repos_list(job)
    assert job.error is None
    inner = _proxied(send)[0]
    assert inner["endpoint"] == "/orgs/acme/repos"
    assert inner["query"] == {"type": "all", "sort": "full_name", "per_page": "50", "page": "1"}


async def test_dependabot_repo_and_org_endpoints():
    acts, send = make_actions()
    job = FakeJob(body={"target": "repo", "repo": "r", "state": "open", "settings": SETTINGS})
    await acts.alerts_dependabot(job)
    assert job.error is None
    assert job.done_data == {"items": [{"number": 1}, {"number": 2}], "count": 2}
    assert _proxied(send)[0]["endpoint"] == "/repos/acme/r/dependabot/alerts"
    assert _proxied(send)[0]["query"]["state"] == "open"

    acts, send = make_actions()
    job = FakeJob(body={"target": "org", "settings": SETTINGS})
    await acts.alerts_dependabot(job)
    assert _proxied(send)[0]["endpoint"] == "/orgs/acme/dependabot/alerts"


async def test_oomol_scopes_do_not_block_security_actions():
    # The account reports oomol-style scopes, not GitHub OAuth ones; the security
    # proxy actions must not second-guess them (GitHub answers 403 if lacking).
    acts, send = make_actions(scopes=["github.repo.read"])
    job = FakeJob(body={"target": "org", "settings": SETTINGS})
    await acts.alerts_dependabot(job)
    assert job.error is None


async def test_protection_resolves_default_branch():
    acts, send = make_actions()
    job = FakeJob(body={"repo": "r", "rulesets": False, "settings": SETTINGS})
    await acts.repo_protection(job)
    assert job.error is None
    assert job.done_data["branch"] == "main"
    assert job.done_data["protected"] is False  # 404 on the protection path is not a failure


async def test_org_members_uses_profile_org():
    acts, send = make_actions()
    job = FakeJob(body={"kind": "members", "filter": "2fa_disabled", "settings": SETTINGS})
    await acts.org_members(job)
    inner = _proxied(send)[0]
    assert inner["endpoint"] == "/orgs/acme/members"
    assert inner["query"]["filter"] == "2fa_disabled"


async def test_search_scopes_to_org():
    acts, send = make_actions()
    job = FakeJob(body={"kind": "code", "q": "filename:Dockerfile", "settings": SETTINGS})
    await acts.search(job)
    inner = _proxied(send)[0]
    assert inner["endpoint"] == "/search/code"
    assert inner["query"]["q"] == "org:acme filename:Dockerfile"


async def test_vars_resolved_from_scope():
    acts, send = make_actions()
    job = FakeJob(body={"repo": "{{$.trigger.repo}}", "settings": SETTINGS}, scope={"$.trigger.repo": "svc"})
    await acts.repo_get(job)
    assert _posted(send, "get_repository")[0]["body"]["input"]["repo"] == "svc"


async def test_raw_request_expands_org_and_parses_json():
    acts, send = make_actions()
    job = FakeJob(body={"method": "GET", "endpoint": "/repos/{org}/r/branches", "query": '{"per_page": 5}', "settings": SETTINGS})
    await acts.request(job)
    assert job.error is None
    inner = _proxied(send)[0]
    assert inner["endpoint"] == "/repos/acme/r/branches"
    assert inner["query"] == {"per_page": "5"}


async def test_raw_request_bad_json_errors():
    acts, send = make_actions()
    job = FakeJob(body={"endpoint": "/x", "query": "{bad", "settings": SETTINGS})
    await acts.request(job)
    assert job.error and "invalid JSON" in job.error
