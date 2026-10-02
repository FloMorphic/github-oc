"""The canvas the registry builds: every action has a form and a handler, the
method names are unique, and the curated ones are exactly the ops tables."""
from __future__ import annotations

from github_oc import forms, ops
from github_oc.registry import _CURATED, _LOCAL, _PROXIED, Registry


async def _send(subject: str, data: bytes):
    raise AssertionError("the registry must not talk to NATS while building the canvas")


def registry() -> Registry:
    return Registry(_send)


def test_every_action_builds_with_a_form_and_a_handler():
    actions = registry().all_actions()
    assert len(actions) == len(_CURATED) + len(_PROXIED) + len(_LOCAL)
    for a in actions:
        assert a.title and a.description and a.icon
        assert a.form.jsonschema and a.form.jsonui
        assert callable(a.request_handler)


def test_method_names_are_unique():
    methods = [a.method for a in registry().all_actions()]
    assert len(set(methods)) == len(methods)


def test_the_curated_actions_are_exactly_the_ops_tables():
    assert {m for m, *_ in _CURATED} == set(ops.TABLES)


def test_every_action_is_declared_in_all_three_places():
    """A canvas action needs its row here, its form in forms.py, and — unless it is
    a proxy surface or the local clone — its table in ops.py."""
    declared = {m for m, *_ in _CURATED} | {m for m, *_ in _PROXIED} | {m for m, *_ in _LOCAL}
    assert declared == set(forms.ACTION_FORMS)


def test_the_metas_and_settings_profile_are_served():
    r = registry()
    assert {m.method for m in r.metas()} == {
        "github.meta.account.list",
        "github.meta.account.test",
        "github.meta.user.info",
        "github.meta.org.list",
        "github.meta.repo.list",
    }
    assert r.settings().submit_to == "github.meta.account.test"
