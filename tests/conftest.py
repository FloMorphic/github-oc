"""Shared test doubles: a fake NATS sender that speaks the OpenConnector proxy
protocol, and a fake Job that captures a handler's terminal call. No NATS, no
network — the plugin's logic is exercised in-process."""
from __future__ import annotations

import functools
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class _Msg:
    def __init__(self, data: bytes):
        self.data = data


# oomol's own GitHub catalog (GET /v1/actions?service=github), saved at the repo
# root. The fake gateway answers definition reads from it, so an action's input is
# pruned against the REAL inputSchema rather than a hand-copied one, and
# tests/test_ops.py checks the plugin's mapping against it.
CATALOG_FILE = pathlib.Path(__file__).resolve().parents[1] / "openconnector-github-schema.json"


@functools.lru_cache(maxsize=1)
def _catalog() -> dict[str, dict[str, Any]]:
    """Every curated GitHub action oomol declares, by its name without the
    `github.` prefix."""
    if not CATALOG_FILE.exists():
        raise FileNotFoundError(
            f"{CATALOG_FILE.name} is missing. It is oomol's own GitHub catalog, which these "
            "tests check github_oc/ops.py against; refresh it with\n"
            f'  curl -s "$GATEWAY/v1/actions?service=github" > {CATALOG_FILE.name}'
        )
    raw = json.loads(CATALOG_FILE.read_text())
    rows = raw.get("data") if isinstance(raw, dict) else raw
    return {str(r["id"]).split(".", 1)[1]: r for r in rows}


def catalog() -> dict[str, dict[str, Any]]:
    """The catalog, read once per test session."""
    return _catalog()


def gateway(handler: Callable[[dict[str, Any]], "tuple[int, Any]"]):
    """Wrap a request→(status, body) function into a Plugin.send-shaped async
    sender. It records every decoded proxy request on `.calls`."""

    calls: list[dict[str, Any]] = []

    async def send(subject: str, data: bytes):
        req = json.loads(data.decode()) if data else {}
        calls.append(req)
        status, body = handler(req)
        reply = {"status": status}
        if body is not None:
            reply["body"] = body
        return _Msg(json.dumps(reply).encode()), None

    send.calls = calls  # type: ignore[attr-defined]
    return send


def every_scope() -> list[str]:
    """Every scope oomol asks for anywhere in its GitHub catalog — what a fully
    granted connection reports. A test that cares about an under-scoped account
    passes its own narrower list instead."""
    out: set[str] = set()
    for defn in catalog().values():
        out.update(str(s) for s in defn.get("requiredScopes") or [])
    return sorted(out)


def one_github_account(alias: str = "work", scopes: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "id": "acc_1",
        "service": "github",
        "status": "connected",
        "accountLabel": "octocat",
        "alias": alias,
        "authType": "oauth2",
        "isDefault": True,
        # oomol-style scopes, as the catalog's requiredScopes are phrased
        "scopes": scopes if scopes is not None else every_scope(),
    }


@dataclass
class FakeReq:
    data: bytes


@dataclass
class FakeJob:
    """Captures progress/terminal calls and answers scope reads from `scope`."""

    body: dict[str, Any]
    scope: dict[str, str] = field(default_factory=dict)
    progress_calls: list = field(default_factory=list)
    done_data: Any = None
    error: Optional[str] = None

    def __post_init__(self):
        self.req = FakeReq(data=json.dumps({"body": self.body}).encode())

    async def progress(self, pct: int, frame: Any) -> None:
        self.progress_calls.append((pct, frame))

    async def done(self, data: dict[str, Any], *key: str) -> None:
        self.done_data = data

    async def done_with_error(self, error: str) -> None:
        self.error = error

    async def cmd_get_scope(self, json_path: str):
        if json_path in self.scope:
            return json.dumps(self.scope[json_path]).encode()
        return b""
