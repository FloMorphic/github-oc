# The one thing this plugin does LOCALLY: run `git clone` on the host the plugin
# is installed on.
#
# WHY IT IS NOT AN OPENCONNECTOR ACTION. oomol curates no clone, and it could not:
# cloning is a git transport to the host's filesystem, not a REST call. Nor can the
# gateway be made to carry one — FloMorphic's NATS proxy injects the OOMOL token
# (not GitHub's), its reply is `{status, body, error}` with no headers, and a body
# that is not JSON comes back as a JSON *string*, so neither a credential nor a
# binary tarball can be obtained through it. Clone therefore runs `git` here.
#
# WHERE THE CREDENTIAL COMES FROM. This module never stores one. It accepts a
# token per call — the clone form takes it as an input, so a flow supplies it with
# a {{$...}} token from an upstream node — and when none is given it simply runs
# git, which means an anonymous clone for a public repository and the host's own
# ssh key or credential helper for a private one. A supplied token is written to a
# private temporary git config as an `http.extraheader`, the way GitHub's own
# checkout action does it, so it is:
#   * never a command-line argument (argv is world-readable through ps),
#   * never written into the clone's .git/config or its remote URL,
#   * scrubbed out of anything this module reports back.
#
# WHERE THE FILES GO. Inside one root — GITHUB_OC_CLONE_ROOT, or ./workspace next
# to the running plugin. A destination is a path RELATIVE to that root and must
# resolve inside it, symlinks included, so a workflow input cannot write anywhere
# else on the host. The paths are on the PLUGIN HOST, not on the user's machine.
from __future__ import annotations

import asyncio
import base64
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional
from urllib.parse import urlsplit

# Where clones land when GITHUB_OC_CLONE_ROOT is unset, relative to the plugin's
# working directory.
DEFAULT_ROOT = "workspace"

# How long one git command may run, overridable with GITHUB_OC_CLONE_TIMEOUT.
DEFAULT_TIMEOUT_SECONDS = 600

# What `git` is invoked as, overridable with GITHUB_OC_GIT (an absolute path for a
# host where git is installed somewhere unusual).
GIT = "git"


class CloneError(Exception):
    """A clone that cannot be done, already phrased for the user."""


# ------------------------------------------------------------------- paths --


def root() -> Path:
    """The one directory clones may be written under, created if missing."""
    configured = (os.getenv("GITHUB_OC_CLONE_ROOT") or "").strip()
    base = Path(configured) if configured else Path.cwd() / DEFAULT_ROOT
    try:
        base = base.expanduser()
        base.mkdir(parents=True, exist_ok=True)
        return base.resolve()
    except OSError as e:
        raise CloneError(
            f"the clone root {base} cannot be created on the plugin host ({e}) — "
            "set GITHUB_OC_CLONE_ROOT to a writable directory"
        )


def _is_absolute(path: str) -> bool:
    """Absolute on either platform's rules — a plugin host may be Windows."""
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def resolve_dest(base: Path, destination: str) -> Path:
    """Turn a destination from the form into an absolute path inside the root.

    Refuses an absolute path, a `..` segment, and a path that only lands outside
    through an existing symlink — the containment is checked on the deepest part
    that already exists, because the clone's own directory does not yet."""
    raw = (destination or "").strip()
    wanted = raw.replace("\\", "/").strip("/")
    if wanted == "":
        raise CloneError("missing required input: destination")
    if _is_absolute(raw):
        raise CloneError(
            f"destination must be relative to the clone root ({base}) — "
            f"{raw!r} is an absolute path"
        )
    if ".." in PurePosixPath(wanted).parts:
        raise CloneError("destination must not contain '..'")

    target = base / wanted
    existing = target
    while not existing.exists():
        parent = existing.parent
        if parent == existing:  # reached the filesystem root
            break
        existing = parent
    settled = existing.resolve()
    if settled != target:
        settled = settled / target.relative_to(existing)
    if settled == base or not settled.is_relative_to(base):
        raise CloneError(f"destination must resolve inside the clone root ({base})")
    return settled


def _empty(path: Path) -> bool:
    return not any(path.iterdir())


# --------------------------------------------------------------------- git --


def _git_binary() -> str:
    return (os.getenv("GITHUB_OC_GIT") or "").strip() or GIT


def _timeout() -> int:
    raw = (os.getenv("GITHUB_OC_CLONE_TIMEOUT") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def _child_env(extra: dict[str, str]) -> dict[str, str]:
    """The environment a git child runs with: the host's, plus the switches that
    stop git from waiting for a human it will never hear from.

    GIT_TERMINAL_PROMPT=0 turns a missing credential into an error instead of a
    hang on a username prompt, and ssh's BatchMode does the same for a key
    passphrase or an unknown host key — unless the operator set their own
    GIT_SSH_COMMAND, which is then left alone."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    env.update(extra)
    return env


@dataclass
class _Git:
    """One git invocation context: the environment the commands run with, and the
    secret to keep out of everything they print."""

    env: dict[str, str] = field(default_factory=dict)
    secret: str = ""

    def scrub(self, text: str) -> str:
        """Never report a token back, whatever git decided to echo."""
        return text.replace(self.secret, "***") if self.secret else text

    async def run(self, *args: str, cwd: Optional[Path] = None) -> str:
        """Run one git command, returning its combined output. Raises CloneError on
        a non-zero exit or a timeout, with git's own message."""
        binary = _git_binary()
        env = _child_env(self.env)
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                *args,
                cwd=str(cwd) if cwd else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        except FileNotFoundError:
            raise CloneError(
                f"{binary!r} is not installed on the plugin host — install git "
                "(apt install git / dnf install git / brew install git) or set "
                "GITHUB_OC_GIT to its full path. Cloning needs it; no other action does."
            )
        except OSError as e:
            raise CloneError(f"cannot run {binary!r} on the plugin host: {e}")

        seconds = _timeout()
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise CloneError(
                f"git {args[0]} took longer than {seconds}s and was stopped — "
                "shallow-clone a smaller depth, or raise GITHUB_OC_CLONE_TIMEOUT"
            )
        text = self.scrub(out.decode(errors="replace").strip())
        if proc.returncode != 0:
            raise CloneError(
                f"git {args[0]} failed: {text or f'exit {proc.returncode}'}{_hint(text)}"
            )
        return text


def _hint(output: str) -> str:
    """Turn git's own refusal into the next thing to do. Both forms mean the same
    thing — the host has no credential for this remote — and neither says so in
    terms of this node's inputs."""
    text = output.lower()
    if "permission denied (publickey)" in text or "host key verification failed" in text:
        return (
            ". The plugin host has no usable SSH key for this remote (its known_hosts may "
            "also be empty) — add one for the account, or switch Transport to HTTPS and, for "
            "a private repository, fill the Token input"
        )
    if "authentication failed" in text or "could not read username" in text or "403" in text:
        return (
            ". git was not authenticated for this remote — fill the Token input (a "
            "{{$.path}} token from an upstream node), or switch Transport to SSH"
        )
    return ""


def _token_config(url: str, token: str) -> "tuple[dict[str, str], Optional[str]]":
    """The environment that authenticates one clone with a caller-supplied token,
    and the temporary directory to delete afterwards.

    The token goes into a private git config as an Authorization header bound to
    the remote's own origin, so it never reaches argv, the clone's config, or any
    other host a submodule might point at."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        # ssh and file remotes carry no HTTP header; the token cannot help them.
        return {}, None
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    directory = tempfile.mkdtemp(prefix="github-oc-clone-")
    config = Path(directory) / "config"
    config.write_text(
        f'[http "{parts.scheme}://{parts.netloc}/"]\n'
        f"\textraheader = Authorization: Basic {basic}\n",
        encoding="utf-8",
    )
    config.chmod(0o600)
    return (
        {
            "GIT_CONFIG_GLOBAL": str(config),
            "GIT_CONFIG_NOSYSTEM": "1",  # a host helper must not override it
        },
        directory,
    )


# The git transports a clone URL may use. The URL is not typed by the user — it is
# `clone_url` / `ssh_url` out of the gateway's JSON — but git's `ext::` transport
# runs a shell command as part of connecting, so the scheme is checked rather than
# trusted. (`--` already separates the URL from git's options.)
_TRANSPORTS = ("https://", "http://", "ssh://", "git://", "file://")


def _check_url(url: str) -> None:
    """Refuse a clone URL that is not a plain git transport."""
    text = url.strip()
    if text.startswith(_TRANSPORTS):
        return
    # scp-like: git@github.com:owner/repo.git — a host, a colon, then a path.
    head, _, path = text.partition(":")
    if path and "/" not in head and "@" in head and not head.startswith("-"):
        return
    raise CloneError(
        f"refusing to clone from {text!r}: only https, ssh, git and file URLs are "
        "cloned, and GitHub returned something else"
    )


def _looks_like_sha(ref: str) -> bool:
    return 7 <= len(ref) <= 40 and all(c in "0123456789abcdefABCDEF" for c in ref)


async def _origin_of(git: _Git, path: Path) -> Optional[str]:
    """The `origin` URL of an existing checkout, or None when it is not a repo."""
    if not (path / ".git").exists():
        return None
    try:
        return await git.run("remote", "get-url", "origin", cwd=path)
    except CloneError:
        return None


def _same_remote(a: str, b: str) -> bool:
    """Whether two remote URLs name the same repository, ignoring the forms GitHub
    accepts interchangeably (scheme, a trailing .git, a credential in the URL)."""

    def key(url: str) -> str:
        text = url.strip().rstrip("/")
        if text.endswith(".git"):
            text = text[: -len(".git")]
        if "://" in text:
            parts = urlsplit(text)
            host = parts.netloc.rsplit("@", 1)[-1]
            return f"{host}{parts.path}".lower()
        if text.startswith("git@"):  # git@github.com:owner/repo
            return text[len("git@") :].replace(":", "/", 1).lower()
        return text.lower()

    return key(a) == key(b)


# ------------------------------------------------------------------- clone --


async def clone(
    *,
    url: str,
    dest: Path,
    ref: str = "",
    depth: int = 1,
    single_branch: bool = True,
    submodules: bool = False,
    token: str = "",
    on_existing: str = "fail",
) -> dict[str, object]:
    """Clone `url` into `dest` and report what landed there.

    `on_existing` decides what a destination that is already there means:
    "fail" refuses it, "reuse" fetches into a checkout of the SAME repository, and
    "replace" re-clones one. Neither reuse nor replace will touch a directory that
    is not a checkout of this repository, so nothing unrelated is ever removed."""
    _check_url(url)
    env, scratch = ({}, None)
    if token:
        env, scratch = _token_config(url, token)
    git = _Git(env=env, secret=token)
    try:
        # Fail on a host without git before anything touches the disk.
        version = (await git.run("--version")).replace("git version ", "")

        reused = False
        if dest.exists() and not dest.is_dir():
            raise CloneError(f"{dest} exists on the plugin host and is not a directory")
        if dest.exists() and not _empty(dest):
            origin = await _origin_of(git, dest)
            if origin is None:
                raise CloneError(
                    f"{dest} already exists on the plugin host and is not a git checkout — "
                    "choose another destination"
                )
            if not _same_remote(origin, url):
                raise CloneError(
                    f"{dest} already exists on the plugin host and is a checkout of "
                    f"{origin} — choose another destination"
                )
            if on_existing == "fail":
                raise CloneError(
                    f"{dest} already holds this repository — set 'If it already exists' to "
                    "Reuse (fetch into it) or Replace (clone it again)"
                )
            if on_existing == "reuse":
                await _fetch_into(git, dest, ref, depth)
                reused = True
            else:
                shutil.rmtree(dest)
        if not reused:
            await _fresh_clone(git, url, dest, ref, depth, single_branch, submodules)

        commit = await git.run("rev-parse", "HEAD", cwd=dest)
        branch = await git.run("rev-parse", "--abbrev-ref", "HEAD", cwd=dest)
        return {
            "path": str(dest),
            "commit": commit,
            "branch": None if branch == "HEAD" else branch,  # detached on a tag or SHA
            "ref": ref or branch,
            "reused": reused,
            "depth": depth or None,
            "git": version,
        }
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)


async def _fresh_clone(
    git: _Git, url: str, dest: Path, ref: str, depth: int, single_branch: bool, submodules: bool
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["-c", "advice.detachedHead=false", "clone"]
    if depth > 0:
        args += [f"--depth={depth}"]
        if single_branch:
            args.append("--single-branch")
    if submodules:
        args.append("--recurse-submodules")
    # --branch takes a branch or a tag; a raw commit SHA has to be fetched after.
    wants_sha = bool(ref) and _looks_like_sha(ref)
    if ref and not wants_sha:
        args += ["--branch", ref]
    args += ["--", url, str(dest)]
    try:
        await git.run(*args)
    except CloneError:
        if dest.exists() and _empty(dest):
            dest.rmdir()  # leave no empty shell behind after a failure
        raise
    if wants_sha:
        await _checkout_sha(git, dest, ref, depth)


async def _has_ref(git: _Git, dest: Path, name: str) -> bool:
    try:
        await git.run("rev-parse", "--verify", "--quiet", name, cwd=dest)
        return True
    except CloneError:
        return False


async def _fetch_into(git: _Git, dest: Path, ref: str, depth: int) -> None:
    """Bring an existing checkout of the same repository up to date.

    With no ref it refreshes whatever the checkout is already on, so a reuse keeps
    its branch instead of silently detaching HEAD."""
    args = ["fetch", "--tags"]
    if depth > 0:
        args.append(f"--depth={depth}")
    await git.run(*args, "origin", cwd=dest)
    if ref and _looks_like_sha(ref):
        await _checkout_sha(git, dest, ref, depth)
        return
    if not ref:
        current = await git.run("rev-parse", "--abbrev-ref", "HEAD", cwd=dest)
        if current == "HEAD":  # already detached: take the fetched head
            await git.run("-c", "advice.detachedHead=false", "checkout", "--force", "FETCH_HEAD", cwd=dest)
            return
        ref = current
    await git.run("-c", "advice.detachedHead=false", "checkout", "--force", ref, cwd=dest)
    # A branch is moved onto its remote; a tag has no origin/<name> to move to.
    if await _has_ref(git, dest, f"refs/remotes/origin/{ref}"):
        await git.run("reset", "--hard", f"origin/{ref}", cwd=dest)


async def _checkout_sha(git: _Git, dest: Path, sha: str, depth: int) -> None:
    args = ["fetch"]
    if depth > 0:
        args.append(f"--depth={depth}")
    await git.run(*args, "origin", sha, cwd=dest)
    await git.run("-c", "advice.detachedHead=false", "checkout", "--detach", sha, cwd=dest)
