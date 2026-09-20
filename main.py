"""GitHub (OpenConnector) plugin — wiring: intro, settings, actions, meta RPCs,
then start() and block.

This node holds NO GitHub token and makes NO GitHub API calls. A GitHub account
is connected once, centrally, in FloMorphic → Connect (via OpenConnector /
oomol); this plugin is a request builder that asks the FloMorphic backend to run
each action as the chosen connected account.

Because it reaches FloMorphic's central services on the `flomorphic.svc.oc.*`
subjects, it must run with an OPEN (multi) runtime credential — a strict,
plugin-scoped credential cannot publish there. See the README.

Run:
    cp .env.inflow.example .env.inflow    # fill in the values Infra minted (OPEN cred)
    pip install -r requirements.txt
    python main.py
"""
import asyncio
import os

from inflow_plugin_sdk import new_plugin, with_dot_env, with_timeout

from github_oc import __version__
from github_oc.registry import Registry

# NATS request/reply deadline for the backend proxy round-trip. Above the SDK's
# 5s default because each action is a NATS hop to the backend, which then calls
# the OpenConnector gateway (and, for the security actions, GitHub). Override per
# deployment with REQ_TIMEOUT (seconds) in .env.inflow.
SEND_TIMEOUT_SECONDS = 30

MANUAL = (
    "Act as a GitHub account you connected in **FloMorphic → Connect** — no token "
    "lives in this node. Open **settings**, press **Load accounts**, pick your "
    "account, **Test**, then **Save**; bind that profile on any GitHub node.\n\n"
    "Read actions cover repositories, contents, activity and search (curated "
    "OpenConnector actions) plus the security surface — Dependabot / secret-"
    "scanning / code-scanning alerts, branch protection, org members and repo "
    "settings — through oomol's signed GitHub proxy. `Raw GitHub request` is the "
    "escape hatch for any other REST endpoint.\n\n"
    "The security actions need the connected token to carry the right scopes "
    "(`security_events`, `read:org`, `repo`); the node checks and fails with a "
    "clear message when one is missing."
)


async def main() -> None:
    env_file = os.getenv("INFLOW_ENV_FILE") or ".env.inflow"
    p = await new_plugin(with_dot_env(env_file), with_timeout(SEND_TIMEOUT_SECONDS))

    p.intro_data.name = "GitHub (OpenConnector)"
    p.intro_data.author = "Mehdi Shokohifar"
    p.intro_data.version = __version__
    p.intro_data.manual = MANUAL

    # The registry sends its account/action/proxy requests over the plugin's NATS
    # connection (Plugin.send: request/reply with retry).
    registry = Registry(p.send)

    # One settings object serves both the set-up dialog (intro.settings) and the
    # bound-profile requirement (required_params); it carries the submit handler.
    settings = registry.settings()
    p.intro_data.settings = settings
    p.required_params(settings)

    actions = registry.all_actions()
    p.add_action(*actions)
    p.add_meta(*registry.metas())

    await p.start()

    methods = ", ".join(a.method for a in actions)
    print(f"github-oc {__version__} ready with {len(actions)} actions: {methods}")
    print("github-oc: this node acts as a GitHub account connected in FloMorphic → Connect")

    await asyncio.Event().wait()  # keep the process alive to serve requests


if __name__ == "__main__":
    asyncio.run(main())
