"""Action handlers end-to-end over the fake gateway: the owner always comes from
the profile, curated inputs match oomol's camelCase schema (pruned against the
REAL catalog), the surface oomol does not curate goes over exact REST paths,
{{$...}} resolution, and the raw request.

Every curated surface is served by Actions.handler_for(method), so these tests
drive the handlers the canvas gets, not private helpers."""
from __future__ import annotations

from github_oc.actions import Actions
from github_oc.oc import Client
from tests.conftest import FakeJob, catalog, gateway, one_github_account

_DEFS = catalog()


def make_actions(scopes=None):
    def handler(req):
        path = req["path"]
        if path == "/v1/connections":
            return 200, {"success": True, "message": "OK", "data": [one_github_account(scopes=scopes)]}
        if path.startswith("/v1/actions/github.") and req["method"] == "GET":
            name = path.rsplit("github.", 1)[1]
            if name not in _DEFS:  # the plugin asked for an action oomol does not have
                return 404, {"message": f"unknown action {name}"}
            return 200, {"success": True, "message": "OK", "data": _DEFS[name]}
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


def _input(send, action):
    return _posted(send, action)[0]["body"]["input"]


def _proxied(send):
    return [c["body"] for c in send.calls if c["path"] == "/v1/proxy/github"]


async def run(method, body, scopes=None):
    """Drive one canvas action the way the host does, and hand back the job."""
    acts, send = make_actions(scopes=scopes)
    job = FakeJob(body=body)
    await acts.handler_for(method)(job)
    return job, send


SETTINGS = {"alias": "work", "org": "acme"}


# ------------------------------------------------------------ the pipeline --


async def test_repo_get_uses_profile_owner_and_camel_case_input():
    job, send = await run("github.repo.get", {"repo": "r", "perPage": 5, "settings": SETTINGS})
    assert job.error is None
    assert job.done_data["full_name"] == "o/r"
    # pruned to the live inputSchema: no settings leak, and no stray perPage
    assert _input(send, "get_repository") == {"owner": "acme", "repo": "r"}


async def test_no_owner_on_profile_is_a_clear_error():
    job, send = await run("github.repo.get", {"repo": "r", "settings": {"alias": "work"}})
    assert job.error and "account settings" in job.error
    assert not _posted(send, "get_repository")


async def test_missing_repo_is_refused_before_the_gateway():
    job, send = await run("github.issues", {"op": "list", "settings": SETTINGS})
    assert job.error == "missing required input: repo"
    assert not _posted(send, "list_repository_issues")


async def test_per_operation_requirement_is_refused_before_the_gateway():
    job, send = await run("github.issues", {"op": "get", "repo": "r", "settings": SETTINGS})
    assert job.error == "missing required input: issueNumber"
    assert not _posted(send, "get_issue")


async def test_unknown_operation_names_the_known_ones():
    job, _ = await run("github.issues", {"op": "nope", "repo": "r", "settings": SETTINGS})
    assert job.error and "unknown operation 'nope'" in job.error and "list" in job.error


async def test_under_scoped_account_is_refused_with_oomols_own_requirement():
    job, send = await run(
        "github.issue.write",
        {"op": "create", "repo": "r", "title": "t", "settings": SETTINGS},
        scopes=["github.user.read"],
    )
    assert job.error and "github.issue.write" in job.error and "FloMorphic → Connect" in job.error
    assert not _posted(send, "create_issue")


async def test_vars_resolved_from_scope():
    acts, send = make_actions()
    job = FakeJob(body={"repo": "{{$.trigger.repo}}", "settings": SETTINGS}, scope={"$.trigger.repo": "svc"})
    await acts.handler_for("github.repo.get")(job)
    assert _input(send, "get_repository")["repo"] == "svc"


# ----------------------------------------------- the curated operations --


async def test_repos_list_mine_is_curated_with_camel_case():
    job, send = await run(
        "github.repos.list",
        {"op": "mine", "visibility": "private", "sort": "pushed", "perPage": 50, "page": 2, "settings": {"alias": "work"}},
    )
    assert job.error is None
    assert _input(send, "list_my_repositories") == {
        "visibility": "private",
        "sort": "pushed",
        "perPage": 50,
        "page": 2,
    }


async def test_repos_list_org_is_curated_under_oomols_org_key():
    # `scope` is the key this form used before the curated surface was widened.
    job, send = await run("github.repos.list", {"scope": "org", "orgType": "sources", "settings": SETTINGS})
    assert job.error is None
    assert _input(send, "list_organization_repositories") == {"org": "acme", "type": "sources"}


async def test_activity_workflow_runs_is_curated_from_the_legacy_kind_key():
    job, send = await run(
        "github.activity.list",
        {"kind": "workflow_runs", "repo": "r", "status": "failure", "branch": "main", "settings": SETTINGS},
    )
    assert job.error is None
    assert _input(send, "list_workflow_runs") == {
        "owner": "acme",
        "repo": "r",
        "branch": "main",
        "status": "failure",
    }


async def test_contents_file_is_curated_not_proxied():
    job, send = await run(
        "github.repo.contents", {"op": "file", "repo": "r", "path": "SECURITY.md", "settings": SETTINGS}
    )
    assert job.error is None
    assert _input(send, "get_file_contents") == {"owner": "acme", "repo": "r", "path": "SECURITY.md"}
    assert not _proxied(send)


async def test_issue_create_sends_lists_and_drops_empty_fields():
    job, send = await run(
        "github.issue.write",
        {
            "op": "create",
            "repo": "r",
            "title": "Broken",
            "body": "",
            "labels": ["bug", "p1"],
            "assignees": [],
            "settings": SETTINGS,
        },
    )
    assert job.error is None
    assert _input(send, "create_issue") == {
        "owner": "acme",
        "repo": "r",
        "title": "Broken",
        "labels": ["bug", "p1"],
    }


async def test_an_empty_number_box_is_not_sent_as_zero():
    job, send = await run(
        "github.issue.write",
        {"op": "create", "repo": "r", "title": "t", "milestone": 0, "settings": SETTINGS},
    )
    assert job.error is None
    assert "milestone" not in _input(send, "create_issue")


async def test_renamed_field_reaches_oomol_under_its_own_name():
    job, send = await run(
        "github.refs",
        {"op": "create", "repo": "r", "fullRef": "refs/heads/release", "sha": "abc123", "settings": SETTINGS},
    )
    assert job.error is None
    assert _input(send, "create_ref") == {
        "owner": "acme",
        "repo": "r",
        "ref": "refs/heads/release",
        "sha": "abc123",
    }


async def test_milestone_filter_is_sent_as_state():
    job, send = await run(
        "github.milestones", {"op": "list", "repo": "r", "stateFilter": "all", "settings": SETTINGS}
    )
    assert job.error is None
    assert _input(send, "list_milestones") == {"owner": "acme", "repo": "r", "state": "all"}


async def test_three_state_toggles_omit_the_untouched_ones():
    job, send = await run(
        "github.repo.update",
        {"repo": "r", "hasWiki": "false", "archived": "", "hasIssues": "true", "settings": SETTINGS},
    )
    assert job.error is None
    assert _input(send, "update_repository") == {
        "owner": "acme",
        "repo": "r",
        "hasIssues": True,
        "hasWiki": False,
    }


async def test_workflow_dispatch_parses_its_json_inputs():
    job, send = await run(
        "github.workflows",
        {
            "op": "dispatch",
            "repo": "r",
            "workflowId": "ci.yml",
            "ref": "main",
            "inputs": '{"environment": "staging"}',
            "settings": SETTINGS,
        },
    )
    assert job.error is None
    assert _input(send, "dispatch_workflow")["inputs"] == {"environment": "staging"}


async def test_workflow_dispatch_bad_json_errors():
    job, send = await run(
        "github.workflows",
        {"op": "dispatch", "repo": "r", "workflowId": "ci.yml", "ref": "main", "inputs": "{bad", "settings": SETTINGS},
    )
    assert job.error and "invalid JSON" in job.error
    assert not _posted(send, "dispatch_workflow")


async def test_account_wide_operation_needs_no_owner():
    job, send = await run("github.user.get", {"op": "me", "settings": {"alias": "work"}})
    assert job.error is None
    assert _input(send, "get_current_user") == {}


async def test_search_is_curated_and_scoped_to_the_org():
    job, send = await run(
        "github.search", {"kind": "code", "q": "filename:Dockerfile", "codeSort": "indexed", "settings": SETTINGS}
    )
    assert job.error is None
    assert _input(send, "search_code") == {"query": "org:acme filename:Dockerfile", "sort": "indexed"}
    assert not _proxied(send)


async def test_search_without_the_org_prefix():
    job, send = await run(
        "github.search", {"op": "users", "q": "location:berlin", "inOrg": False, "settings": SETTINGS}
    )
    assert job.error is None
    assert _input(send, "search_users") == {"query": "location:berlin"}


# ------------------------------------------ the surface oomol does not curate --


async def test_dependabot_repo_and_org_endpoints():
    job, send = await run(
        "github.alerts.dependabot", {"target": "repo", "repo": "r", "state": "open", "settings": SETTINGS}
    )
    assert job.error is None
    assert job.done_data == {"items": [{"number": 1}, {"number": 2}], "count": 2}
    assert _proxied(send)[0]["endpoint"] == "/repos/acme/r/dependabot/alerts"
    assert _proxied(send)[0]["query"]["state"] == "open"

    job, send = await run("github.alerts.dependabot", {"target": "org", "settings": SETTINGS})
    assert _proxied(send)[0]["endpoint"] == "/orgs/acme/dependabot/alerts"


async def test_oomol_scopes_do_not_block_security_actions():
    # The account reports oomol-style scopes, not GitHub OAuth ones; the security
    # proxy actions must not second-guess them (GitHub answers 403 if lacking).
    job, _ = await run("github.alerts.dependabot", {"target": "org", "settings": SETTINGS}, scopes=["github.repo.read"])
    assert job.error is None


async def test_protection_resolves_default_branch():
    job, _ = await run("github.repo.protection", {"repo": "r", "rulesets": False, "settings": SETTINGS})
    assert job.error is None
    assert job.done_data["branch"] == "main"
    assert job.done_data["protected"] is False  # 404 on the protection path is not a failure


async def test_org_members_uses_profile_org():
    job, send = await run(
        "github.org.members", {"kind": "members", "filter": "2fa_disabled", "settings": SETTINGS}
    )
    inner = _proxied(send)[0]
    assert inner["endpoint"] == "/orgs/acme/members"
    assert inner["query"]["filter"] == "2fa_disabled"


async def test_raw_request_expands_org_and_parses_json():
    job, send = await run(
        "github.request",
        {"method": "GET", "endpoint": "/repos/{org}/r/branches", "query": '{"per_page": 5}', "settings": SETTINGS},
    )
    assert job.error is None
    inner = _proxied(send)[0]
    assert inner["endpoint"] == "/repos/acme/r/branches"
    assert inner["query"] == {"per_page": "5"}


async def test_raw_request_bad_json_errors():
    job, _ = await run("github.request", {"endpoint": "/x", "query": "{bad", "settings": SETTINGS})
    assert job.error and "invalid JSON" in job.error
