"""The op tables against oomol's own catalog.

ops.py is this plugin's copy of what oomol curates, and a wrong field name there
is a hard 400 at run time rather than a failure here — so every mapping is
checked against openconnector-github-schema.json (the saved
GET /v1/actions?service=github response): the action exists, every key the plugin
would send is declared, nothing oomol requires is left out, and the whole catalog
is reachable from the canvas.

Refresh the file from the gateway when oomol curates more:
    curl -s "$GATEWAY/v1/actions?service=github" > openconnector-github-schema.json
"""
from __future__ import annotations

import json

from github_oc import forms, ops
from tests.conftest import catalog

CATALOG = catalog()

# What the handler supplies rather than the form: the search surface builds its
# own query string (the "within the organization" prefix is a plugin convenience).
INJECTED = {"github.search": {"query"}}

_SCOPE_KEYS = {"repo": {"owner", "repo"}, "owner": {"owner"}, "org": {"org"}, "none": set()}


def _sent(method: str, op: ops.Op) -> set[str]:
    """Every key this op would put in the curated input."""
    keys = set(_SCOPE_KEYS[op.scope]) | INJECTED.get(method, set())
    for spec in op.fields:
        form_name, _, curated = spec.partition(":")
        keys.add(curated or form_name)
    return keys


def test_every_curated_action_is_reachable_from_the_canvas():
    assert ops.actions() == set(CATALOG), sorted(set(CATALOG) ^ ops.actions())


def test_every_op_names_an_action_oomol_curates():
    for method, table in ops.TABLES.items():
        for name, op in table.ops.items():
            assert op.action in CATALOG, f"{method}/{name}"
            assert op.scope in ops.SCOPES, f"{method}/{name}"


def test_no_op_sends_a_field_oomol_does_not_declare():
    for method, table in ops.TABLES.items():
        for name, op in table.ops.items():
            declared = set(CATALOG[op.action]["inputSchema"].get("properties", {}))
            stray = _sent(method, op) - declared
            assert not stray, f"{method}/{name} → {op.action}: {sorted(stray)}"


def test_every_op_can_supply_what_oomol_requires():
    for method, table in ops.TABLES.items():
        for name, op in table.ops.items():
            required = set(CATALOG[op.action]["inputSchema"].get("required", []))
            missing = required - _sent(method, op)
            assert not missing, f"{method}/{name} → {op.action}: {sorted(missing)}"


def test_needs_json_and_bools_name_fields_of_their_own_op():
    for method, table in ops.TABLES.items():
        for name, op in table.ops.items():
            fields = {spec.partition(":")[0] for spec in op.fields}
            for label, names in (("needs", op.needs), ("json", op.json), ("bools", op.bools)):
                stray = set(names) - fields
                assert not stray, f"{method}/{name}: {label} names {sorted(stray)}, which it never sends"


def test_each_table_defaults_to_one_of_its_own_ops():
    for method, table in ops.TABLES.items():
        assert table.default in table.ops, method


def test_every_table_has_a_form_whose_fields_it_uses():
    """A field an op sends must exist on the form, and a form must not carry a
    field no op ever sends — the two drift apart silently otherwise."""
    for method, table in ops.TABLES.items():
        props = set(json.loads(forms.ACTION_FORMS[method]().jsonschema)["properties"])
        used = {"op"} | ({"q", "inOrg"} if method == "github.search" else set())
        for name, op in table.ops.items():
            if op.scope == "repo":
                used.add("repo")
            for spec in op.fields:
                form_name = spec.partition(":")[0]
                used.add(form_name)
                assert form_name in props, f"{method}/{name}: {form_name!r} is not on the form"
        # `op` itself is absent from a single-operation form, hence the one-way check.
        extra = props - used
        assert not extra, f"{method}: form carries {sorted(extra)} that no operation sends"


def test_a_three_state_toggle_is_declared_boolean_by_oomol():
    for method, table in ops.TABLES.items():
        for name, op in table.ops.items():
            props = CATALOG[op.action]["inputSchema"].get("properties", {})
            for form_name in op.bools:
                curated = dict(spec.partition(":")[::2] for spec in op.fields).get(form_name) or form_name
                assert props[curated].get("type") == "boolean", f"{method}/{name}: {curated}"
