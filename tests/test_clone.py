"""The clone action, against a real git repository served over file://.

The gateway is still faked — it answers `get_repository` with a record whose
clone_url points at a repository this test built — so the whole action runs for
real: the access gate, the path containment, and `git clone` itself. No network.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from github_oc import clone as git_clone
from github_oc.actions import Actions
from github_oc.oc import Client
from tests.conftest import FakeJob, catalog, gateway, one_github_account

_DEFS = catalog()
SETTINGS = {"alias": "work", "org": "acme"}

# git is a hard requirement of this action, and of these tests.
HAS_GIT = subprocess.run(["git", "--version"], capture_output=True).returncode == 0
pytestmark = pytest.mark.skipif(not HAS_GIT, reason="git is not installed")


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    return out.stdout.strip()


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A repository with one commit on `main` and a `v1` tag, to clone from."""
    source = tmp_path / "origin"
    source.mkdir()
    _git("init", cwd=source)
    (source / "README.md").write_text("hello\n")
    _git("add", "README.md", cwd=source)
    _git("commit", "-m", "first", cwd=source)
    _git("tag", "v1", cwd=source)
    return source


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    """The clone root this plugin is allowed to write under."""
    base = tmp_path / "root"
    monkeypatch.setenv("GITHUB_OC_CLONE_ROOT", str(base))
    return base


def make_actions(
    origin: Path,
    *,
    private: bool = False,
    permissions=None,
    proxy_permissions=None,
    endpoint_permission: str = "",
    privacy: bool = True,
    found: bool = True,
):
    """A gateway whose get_repository answers the way oomol's really does: the
    twelve fields its output schema declares, and NO `permissions` — the curated
    reply carries no permission at all. A test that needs one passes it explicitly:
    `permissions` forces it onto the curated record, `proxy_permissions` serves it
    from GitHub's own payload through the provider proxy, and `endpoint_permission`
    answers GitHub's permission endpoint."""
    record = {
        "id": 1,
        "name": "r",
        "full_name": "acme/r",
        "private": private,
        "html_url": "https://github.com/acme/r",
        "clone_url": origin.as_uri(),
        "ssh_url": f"ssh://invalid/{origin.name}",
        "default_branch": "main",
        "visibility": "private" if private else "public",
        "fork": False,
        "description": None,
        "owner": {"id": 1, "login": "acme"},
    }
    if permissions is not None:
        record["permissions"] = permissions
    if not privacy:  # a reply that says nothing about whether the repo is private
        record.pop("private", None)
        record.pop("visibility", None)

    def handler(req):
        path = req["path"]
        if path == "/v1/connections":
            return 200, {"success": True, "message": "OK", "data": [one_github_account()]}
        if path.startswith("/v1/actions/github.") and req["method"] == "GET":
            return 200, {"success": True, "message": "OK", "data": _DEFS[path.rsplit("github.", 1)[1]]}
        if path == "/v1/actions/github.get_repository":
            if not found:
                return 404, {"message": "Not Found"}
            return 200, {"success": True, "message": "OK", "data": record}
        if path == "/v1/actions/github.get_current_user":
            return 200, {"success": True, "message": "OK", "data": {"id": 1, "login": "octocat"}}
        if path == "/v1/actions/github.get_repository_permission_for_user":
            if not endpoint_permission:
                return 403, {"message": "Must have admin rights to Repository."}
            return 200, {"success": True, "message": "OK", "data": {"permission": endpoint_permission}}
        if path == "/v1/proxy/github":
            if proxy_permissions is None:
                return 404, {"message": "Not Found"}
            return 200, {
                "success": True,
                "message": "OK",
                "data": {**record, "permissions": proxy_permissions},
            }
        return 404, {"message": "Not Found"}

    send = gateway(handler)
    return Actions(Client(send)), send


async def run(origin: Path, body: dict, **kw) -> FakeJob:
    acts, _ = make_actions(origin, **kw)
    job = FakeJob(body={"repo": "r", "settings": SETTINGS, **body})
    await acts.handler_for("github.repo.clone")(job)
    return job


# ---------------------------------------------------------------- cloning --


async def test_clone_lands_in_the_root_and_reports_the_commit(origin, root):
    job = await run(origin, {})
    assert job.error is None
    out = job.done_data
    assert out["path"] == str(root / "r")
    assert (root / "r" / "README.md").read_text() == "hello\n"
    assert (root / "r" / ".git").exists()
    assert out["commit"] == _git("rev-parse", "HEAD", cwd=origin)
    assert out["branch"] == "main"
    assert out["permission"] == "pull"
    assert out["root"] == str(root)
    assert out["authenticated"] is False


async def test_a_nested_destination_is_created(origin, root):
    job = await run(origin, {"destination": "acme/api"})
    assert job.error is None
    assert (root / "acme" / "api" / "README.md").exists()


async def test_a_tag_is_checked_out_detached(origin, root):
    job = await run(origin, {"ref": "v1"})
    assert job.error is None
    assert job.done_data["branch"] is None  # detached HEAD on a tag
    assert job.done_data["commit"] == _git("rev-parse", "v1^{commit}", cwd=origin)


async def test_a_commit_sha_is_fetched_and_checked_out(origin, root):
    sha = _git("rev-parse", "HEAD", cwd=origin)
    job = await run(origin, {"ref": sha, "depth": 0})
    assert job.error is None
    assert job.done_data["commit"] == sha


async def test_full_history_when_depth_is_zero(origin, root):
    job = await run(origin, {"depth": 0})
    assert job.error is None
    assert job.done_data["depth"] is None


# ------------------------------------------------------------ the gate --


async def test_a_repository_the_account_cannot_see_is_refused(origin, root):
    job = await run(origin, {}, found=False)
    assert job.error and "cannot see acme/r" in job.error
    assert not root.exists() or not any(root.iterdir())


async def test_the_read_itself_proves_read_access(origin, root):
    """The case that matters in production: oomol sends no `permissions`, and a
    clone must still go ahead — GitHub 404s a repository the token cannot see, so
    the record coming back IS the pull grant."""
    job = await run(origin, {})
    assert job.error is None, job.error
    assert job.done_data["permission"] == "pull"
    assert job.done_data["permissionSource"] == "reading the repository as this account"


async def test_a_private_repo_read_also_proves_pull(origin, root):
    job = await run(origin, {"token": "ghp_x"}, private=True)
    assert job.error is None, job.error
    assert job.done_data["permission"] == "pull"


async def test_nothing_above_read_access_is_invented(origin, root):
    # push is required and no source can confirm it: refuse, and say why.
    job = await run(origin, {"minPermission": "push"})
    assert job.error and "requires push" in job.error
    assert "nothing above read access could be confirmed" in job.error
    assert not (root / "r").exists()


async def test_insufficient_permission_on_the_record_is_refused(origin, root):
    job = await run(origin, {"minPermission": "push"}, permissions={"pull": True})
    assert job.error and "requires push" in job.error
    assert "grant it in the organization" in job.error
    assert not (root / "r").exists()


async def test_push_permission_satisfies_push(origin, root):
    job = await run(origin, {"minPermission": "push"}, permissions={"pull": True, "push": True})
    assert job.error is None
    assert job.done_data["permission"] == "push"


async def test_push_is_confirmed_from_githubs_own_payload(origin, root):
    # oomol's reply has none, so the provider proxy is asked for GitHub's.
    job = await run(origin, {"minPermission": "push"}, proxy_permissions={"pull": True, "push": True})
    assert job.error is None, job.error
    assert job.done_data["permission"] == "push"
    assert job.done_data["permissionSource"] == "GitHub's repository permissions"


async def test_admin_is_confirmed_from_the_permission_endpoint(origin, root):
    # Neither the curated reply nor the proxy has it; the endpoint answers.
    job = await run(origin, {"minPermission": "admin"}, endpoint_permission="admin")
    assert job.error is None, job.error
    assert job.done_data["permission"] == "admin"
    assert job.done_data["permissionSource"] == "GitHub's permission endpoint"


async def test_pull_costs_no_extra_lookup(origin, root):
    """A clone needs read access, which the read already proved — so the common case
    must not spend calls hunting for a permission it does not need."""
    acts, send = make_actions(origin)
    job = FakeJob(body={"repo": "r", "settings": SETTINGS})
    await acts.handler_for("github.repo.clone")(job)
    assert job.error is None
    paths = [c["path"] for c in send.calls]
    assert "/v1/proxy/github" not in paths
    assert "/v1/actions/github.get_repository_permission_for_user" not in paths


async def test_a_private_repo_over_https_without_a_token_is_refused(origin, root):
    job = await run(origin, {}, private=True)
    assert job.error and "private" in job.error and "Token" in job.error
    assert not (root / "r").exists()


async def test_a_private_repo_with_a_token_proceeds(origin, root):
    # file:// ignores the HTTP header, but the action must accept the token and run.
    job = await run(origin, {"token": "ghp_secret"}, private=True)
    assert job.error is None
    assert job.done_data["authenticated"] is True


# ------------------------------------------------------- the destination --


async def test_an_absolute_destination_is_refused(origin, root, tmp_path):
    job = await run(origin, {"destination": str(tmp_path / "escape")})
    assert job.error and "absolute path" in job.error
    assert not (tmp_path / "escape").exists()


async def test_a_parent_traversal_is_refused(origin, root):
    job = await run(origin, {"destination": "../escape"})
    assert job.error and ".." in job.error
    assert not (root.parent / "escape").exists()


async def test_a_symlink_out_of_the_root_is_refused(origin, root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "link").symlink_to(outside, target_is_directory=True)
    job = await run(origin, {"destination": "link/escape"})
    assert job.error and "inside the clone root" in job.error
    assert not (outside / "escape").exists()


async def test_the_root_itself_is_not_a_destination(origin, root):
    job = await run(origin, {"destination": "."})
    assert job.error and "inside the clone root" in job.error


# -------------------------------------------------- an existing directory --


async def test_an_existing_clone_fails_by_default(origin, root):
    assert (await run(origin, {})).error is None
    job = await run(origin, {})
    assert job.error and "already holds this repository" in job.error


async def test_reuse_fetches_the_new_commit(origin, root):
    assert (await run(origin, {})).error is None
    (origin / "second.txt").write_text("more\n")
    _git("add", "second.txt", cwd=origin)
    _git("commit", "-m", "second", cwd=origin)

    job = await run(origin, {"onExisting": "reuse"})
    assert job.error is None, job.error
    assert job.done_data["reused"] is True
    assert job.done_data["branch"] == "main"  # a reuse keeps its branch, not a detached HEAD
    assert job.done_data["commit"] == _git("rev-parse", "HEAD", cwd=origin)
    assert (root / "r" / "second.txt").exists()


async def test_replace_clones_again(origin, root):
    assert (await run(origin, {})).error is None
    (root / "r" / "scratch.txt").write_text("local\n")
    job = await run(origin, {"onExisting": "replace"})
    assert job.error is None
    assert job.done_data["reused"] is False
    assert not (root / "r" / "scratch.txt").exists()


async def test_an_unrelated_directory_is_never_touched(origin, root):
    (root / "r").mkdir(parents=True)
    (root / "r" / "precious.txt").write_text("mine\n")
    for mode in ("fail", "reuse", "replace"):
        job = await run(origin, {"onExisting": mode})
        assert job.error and "not a git checkout" in job.error, mode
        assert (root / "r" / "precious.txt").read_text() == "mine\n"


async def test_a_checkout_of_another_repository_is_never_touched(origin, root, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    _git("init", cwd=other)
    (other / "x").write_text("x")
    _git("add", "x", cwd=other)
    _git("commit", "-m", "x", cwd=other)
    _git("clone", other.as_uri(), str(root / "r"), cwd=tmp_path)

    job = await run(origin, {"onExisting": "replace"})
    assert job.error and "is a checkout of" in job.error
    assert (root / "r" / "x").exists()


# ------------------------------------------------- the URL and the privacy --
#
# oomol's curated get_repository does not reliably carry clone_url / ssh_url or
# `private`, so neither may be depended on.


def test_the_clone_url_is_derived_when_the_reply_has_none():
    from github_oc.actions import _clone_url

    assert _clone_url({}, "Venapce", "venapce-api", False) == "https://github.com/Venapce/venapce-api.git"
    assert _clone_url({}, "Venapce", "venapce-api", True) == "git@github.com:Venapce/venapce-api.git"


def test_the_reply_url_wins_when_it_is_there():
    from github_oc.actions import _clone_url

    record = {"clone_url": "https://github.com/a/b.git", "ssh_url": "git@github.com:a/b.git"}
    assert _clone_url(record, "a", "b", False) == "https://github.com/a/b.git"
    assert _clone_url(record, "a", "b", True) == "git@github.com:a/b.git"


def test_an_enterprise_host_is_honoured():
    from github_oc.actions import _clone_url

    record = {"html_url": "https://git.acme.internal/acme/r"}
    assert _clone_url(record, "acme", "r", False) == "https://git.acme.internal/acme/r.git"
    assert _clone_url(record, "acme", "r", True) == "git@git.acme.internal:acme/r.git"


def test_privacy_is_unknown_rather_than_public_when_unsaid():
    from github_oc.actions import _is_private

    assert _is_private({"private": True}) is True
    assert _is_private({"private": False}) is False
    assert _is_private({"visibility": "internal"}) is True
    assert _is_private({"visibility": "public"}) is False
    assert _is_private({}) is None  # never assume public: git's error speaks instead


async def test_an_unknown_privacy_still_clones(origin, root):
    # A reply with neither `private` nor `visibility` must not be refused up front.
    job = await run(origin, {}, privacy=False)
    assert job.error is None, job.error
    assert job.done_data["private"] is None
    assert job.done_data["url"] == origin.as_uri()


def test_a_missing_credential_is_explained(monkeypatch):
    assert "switch Transport to HTTPS" in git_clone._hint("git@github.com: Permission denied (publickey).")
    assert "fill the Token input" in git_clone._hint("fatal: Authentication failed for 'https://…'")
    assert git_clone._hint("fatal: repository not found") == ""


# ----------------------------------------------------------- the host --


async def test_a_host_without_git_says_so(origin, root, monkeypatch):
    monkeypatch.setenv("GITHUB_OC_GIT", str(root / "no-such-git"))
    job = await run(origin, {})
    assert job.error and "not installed on the plugin host" in job.error


def test_the_root_defaults_beside_the_plugin(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_OC_CLONE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert git_clone.root() == (tmp_path / git_clone.DEFAULT_ROOT).resolve()


async def test_a_clone_url_that_is_not_a_git_transport_is_refused(origin, root, monkeypatch):
    # git's ext:: transport runs a shell command; the URL comes from the gateway's
    # JSON, so the scheme is checked rather than trusted.
    with pytest.raises(git_clone.CloneError, match="only https, ssh, git and file"):
        await git_clone.clone(url="ext::sh -c touch% /tmp/pwned", dest=root / "x")


def test_the_github_url_forms_are_accepted():
    for url in (
        "https://github.com/acme/r.git",
        "ssh://git@github.com/acme/r.git",
        "git@github.com:acme/r.git",
        "file:///srv/mirror/r.git",
    ):
        git_clone._check_url(url)


def test_a_token_is_never_reported_back():
    git = git_clone._Git(secret="ghp_secret")
    assert git.scrub("fatal: ghp_secret rejected") == "fatal: *** rejected"


def test_the_token_config_binds_the_header_to_the_remote_host(tmp_path):
    env, scratch = git_clone._token_config("https://github.com/acme/r.git", "ghp_secret")
    try:
        config = Path(env["GIT_CONFIG_GLOBAL"]).read_text()
        assert '[http "https://github.com/"]' in config
        assert "ghp_secret" not in config  # it is base64 of x-access-token:<token>
        assert "extraheader = Authorization: Basic " in config
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert oct(os.stat(env["GIT_CONFIG_GLOBAL"]).st_mode)[-3:] == "600"
    finally:
        if scratch:
            __import__("shutil").rmtree(scratch, ignore_errors=True)


def test_git_is_never_left_waiting_for_a_human(monkeypatch):
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    env = git_clone._child_env({"GIT_CONFIG_GLOBAL": "/tmp/x"})
    assert env["GIT_TERMINAL_PROMPT"] == "0"  # a missing credential errors, never hangs
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert env["GIT_CONFIG_GLOBAL"] == "/tmp/x"


def test_an_operators_own_ssh_command_is_kept(monkeypatch):
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i /keys/deploy")
    assert git_clone._child_env({})["GIT_SSH_COMMAND"] == "ssh -i /keys/deploy"


def test_no_token_config_for_an_ssh_remote():
    env, scratch = git_clone._token_config("git@github.com:acme/r.git", "ghp_secret")
    assert env == {} and scratch is None
