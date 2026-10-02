"""The forms build, carry no Owner / Organization input (that lives on the
settings profile), and wire the repo picker to their own action."""
from __future__ import annotations

import json

from github_oc import forms

# Every action form, from the map registry.py and meta.py build the canvas from.
ACTION_FORMS = forms.ACTION_FORMS


def _controls(fb):
    out = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "Control":
                out.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(json.loads(fb.jsonui))
    return out


def _find(fb, name):
    scope = f"#/properties/{name}"
    return next(c for c in _controls(fb) if c.get("scope") == scope)


def test_all_forms_build():
    for build in ACTION_FORMS.values():
        fb = build()
        assert fb.jsonschema and fb.jsonui


def test_no_action_form_has_owner_or_org_input():
    for method, build in ACTION_FORMS.items():
        props = json.loads(build().jsonschema)["properties"]
        assert "owner" not in props and "org" not in props, method
        # and no control anywhere asks the org picker
        for c in _controls(build()):
            fn = c.get("x-inflow-ui", {}).get("action", {}).get("fn")
            assert fn != "github.meta.org.list", (method, c["scope"])


def test_settings_form_owns_the_org_and_its_picker():
    s = forms.settings_form().build()
    assert s.submit_to == "github.meta.account.test"
    org = _find(s, "org")["x-inflow-ui"]["action"]
    assert org["fn"] == "github.meta.org.list"
    assert org["body"] == {"targetField": "org", "form": "github.settings"}
    alias = _find(s, "alias")["x-inflow-ui"]["action"]
    assert alias["fn"] == "github.meta.account.list"


def test_repo_pickers_rebuild_their_own_form():
    for method, build in ACTION_FORMS.items():
        fb = build()
        if "repo" not in json.loads(fb.jsonschema)["properties"]:
            continue
        body = _find(fb, "repo")["x-inflow-ui"]["action"]["body"]
        assert body == {"targetField": "repo", "form": method}, method


def test_alerts_form_scope_toggles_repo_field():
    fb = forms.alerts_dependabot_form()
    repo = _find(fb, "repo")
    assert repo["rule"]["effect"] == "SHOW"
    assert repo["rule"]["condition"]["schema"]["const"] == "repo"


def test_paging_fields_are_camel_case():
    props = json.loads(forms.repos_list_form().jsonschema)["properties"]
    assert "perPage" in props and "per_page" not in props
