"""Every operation of every curated surface, driven end to end.

test_ops.py checks the mapping statically; this fills each operation's form the
way a user would, runs the handler through the fake gateway, and asserts the call
actually went out with everything oomol's schema requires. It is the test that
catches a form field that exists but is never read, a `needs` that refuses a
filled form, or a renamed field that never arrives.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from github_oc import forms, ops
from tests.conftest import catalog
from tests.test_actions import SETTINGS, make_actions
from tests.conftest import FakeJob

CATALOG = catalog()

CASES = [(method, name) for method, table in ops.TABLES.items() for name in table.ops]


def _value(name: str, schema: dict[str, Any], op: ops.Op) -> Any:
    """A plausible entry for one form field, honouring its type and its choices."""
    if name in op.json:
        return '[{"path": "main.go", "body": "nit"}]' if name == "comments" else '{"k": "v"}'
    if name in op.bools:
        return "true"
    choices = [c for c in schema.get("enum", []) if c != ""]
    choices += [o["const"] for o in schema.get("oneOf", []) if o.get("const") not in (None, "")]
    if choices:
        return choices[0]
    kind = schema.get("type")
    if kind == "integer":
        return 7
    if kind == "boolean":
        return True
    if kind == "array":
        return ["x"]
    return "x"


def _body(method: str, op_name: str) -> dict[str, Any]:
    op = ops.TABLES[method].ops[op_name]
    props = json.loads(forms.ACTION_FORMS[method]().jsonschema)["properties"]
    body: dict[str, Any] = {"op": op_name, "settings": SETTINGS}
    if op.scope == "repo":
        body["repo"] = "r"
    for spec in op.fields:
        name = spec.partition(":")[0]
        body[name] = _value(name, props[name], op)
    if method == "github.search":
        body["q"] = "needle"
    return body


@pytest.mark.parametrize(("method", "op_name"), CASES, ids=[f"{m}/{o}" for m, o in CASES])
async def test_a_filled_form_reaches_oomol_with_what_it_requires(method, op_name):
    op = ops.TABLES[method].ops[op_name]
    acts, send = make_actions()
    job = FakeJob(body=_body(method, op_name))
    await acts.handler_for(method)(job)
    assert job.error is None, f"{method}/{op_name}: {job.error}"

    posted = [c for c in send.calls if c["path"] == f"/v1/actions/github.{op.action}" and c["method"] == "POST"]
    assert len(posted) == 1, f"{method}/{op_name} did not call github.{op.action}"
    sent = posted[0]["body"]["input"]
    required = set(CATALOG[op.action]["inputSchema"].get("required", []))
    assert required <= set(sent), f"{method}/{op_name}: missing {sorted(required - set(sent))}"
