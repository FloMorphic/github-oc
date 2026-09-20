# GitHub (OpenConnector) — `github-oc`

A FloMorphic **plugin node** for GitHub that authenticates through FloMorphic's
central **Connect** feature (OpenConnector / oomol), built on
[`inflowenger-plugin-sdk`](https://pypi.org/project/inflowenger-plugin-sdk/) — the
first `-oc` plugin written in **Python**.

It appears on the workflow canvas as a **GitHub (OpenConnector)** node with
thirteen read actions. It holds **no GitHub credentials** and makes **no GitHub
API calls** — it is a *request builder*. A GitHub account is connected **once,
centrally**, in **FloMorphic → Connect**; this node just picks which connected
account to act as, and asks the FloMorphic backend to run each action for it.

> Why the name? This plugin depends on FloMorphic's central auth. A future
> `github` plugin could instead talk to GitHub directly with its own PAT/OAuth —
> the `-oc` suffix keeps that door open.

## How it works

The FloMorphic backend is a **generic proxy**: it stores the OpenConnector token
and forwards any request over one NATS subject, `flomorphic.svc.oc.proxy`,
injecting the auth header. It knows nothing about GitHub. **All** GitHub
knowledge — which accounts exist, what an action needs, which endpoint to call —
lives in this plugin.

```
 github-oc node                    FloMorphic backend            OpenConnector gateway
 (builds + vets the request)       (injects auth, forwards)      (oomol cloud / self-host)
   │  flomorphic.svc.oc.proxy                │                            │
   │  {method,path,body,connection?}         │  <method> <path>           │
   ├──────────── NATS req ──────────────────▶│  + Authorization header ──▶│  ──▶ api.github.com
   │◀──────────── {status,body} ─────────────┤◀───────────────────────────┤
```

The plugin reaches the gateway **two ways**, both through that one NATS proxy:

1. **Curated OpenConnector actions** — `POST /v1/actions/github.<action>` — for
   the surface oomol curates (repos, collaborators, activity, search).
2. **The provider proxy** — `POST /v1/proxy/github {endpoint, method, query, body}`
   — a signed passthrough to `api.github.com` for the **security surface oomol
   does not curate**: Dependabot / secret-scanning / code-scanning alerts, branch
   protection & rulesets, org members, deploy keys, webhooks, and any other REST
   path via the **Raw GitHub request** escape hatch.

It also uses the proxy to `GET /v1/connections` (the connected GitHub accounts,
filtered to `github`) and, for curated actions, `GET /v1/actions/github.<action>`
to read `requiredScopes` and check them against the chosen account.

- The plugin never sees a GitHub token. The backend holds the OpenConnector
  credential and performs the call.
- One connected account can be shared by many nodes; rotating it happens in the
  Connect page, no plugin redeploy.

## Requirements

- **An OPEN (multi) runtime credential.** This plugin publishes on
  `flomorphic.svc.oc.*`; a strict, plugin-scoped credential cannot. Mint one from
  **FloMorphic → Settings → MultiPlugin Credential** and put it in `.env.inflow`
  as `INFRA_CRED`.
- **A GitHub account connected in FloMorphic → Connect** — an OAuth app *or* a
  fine-grained PAT (a PAT is simplest for org security reads).
- **The right token scopes for the security actions** (checked live per action):
  `security_events` (alerts), `read:org` (org members / 2FA filter), `repo`
  (private repos, branch protection), `admin:repo_hook` (webhooks). Fine-grained
  PAT equivalents: *Dependabot / Secret-scanning / Code-scanning alerts: read*,
  *Administration: read*, *Members: read*.

## Set-up (pick from a list — nothing to type)

1. **Connect a GitHub account** once in FloMorphic → **Connect** (it shows as
   connected there, e.g. `octocat`).
2. On the node, open **settings**, press **Load accounts**, and **pick** your
   account from the drop-down. (Leave it on the default to use the default
   connection.) Set the **Organization / owner** this account works with — press
   **Load orgs** if your token can list them, or just type it (a connection scoped
   to one org in OpenConnector can't enumerate orgs, so you type the one it's
   scoped to). Press **Test account** and **Check identity** (shows the login and
   granted scopes), then **Save** — the platform stores this as a reusable
   **settings profile**.
3. On any GitHub node, bind that profile in the node drawer. Every action targets
   the organization set here — there is no Owner input on the actions. A token
   that spans several orgs gets one profile per org.

There is **no** token to paste, alias to copy, or OAuth consent to click through —
the account list is populated live from Connect. The optional **Gateway** field
pins to one Connect connection when several are configured (hosted oomol vs
self-hosted); leave it empty to span all.

## Actions

**No action form has an Owner / Organization input.** An OpenConnector GitHub
connection is granted to an account and, typically, to one organization — so the
organization belongs to the *connection*, not to any single action. It is set once
on the settings profile and every action reads it from there. A profile per org,
if a token spans several.

| Method | Title | Backed by | Notes |
|--------|-------|-----------|-------|
| `github.repos.list`             | List repositories        | curated (mine) · proxy (org) | the settings org's, or the account's own |
| `github.repo.get`               | Get repository           | curated | |
| `github.repo.collaborators`     | List collaborators       | proxy   | who can push, at what level |
| `github.repo.contents`          | Get contents             | proxy   | file or directory (CODEOWNERS, SECURITY.md, workflows) |
| `github.activity.list`          | List activity            | curated (commits) · proxy (workflow runs) | |
| `github.search`                 | Search GitHub            | proxy   | repos / code / issues & PRs, scoped to the org by default |
| `github.repo.protection`        | Branch protection        | proxy   | classic protection + rulesets; resolves the default branch |
| `github.alerts.dependabot`      | Dependabot alerts        | proxy   | repo or org-wide |
| `github.alerts.secret_scanning` | Secret-scanning alerts   | proxy   | repo or org-wide |
| `github.alerts.code_scanning`   | Code-scanning alerts     | proxy   | repo or org-wide |
| `github.org.members`            | Org members              | proxy   | members (2FA filter) / outside collaborators |
| `github.repo.settings`          | Repo settings            | proxy   | deploy keys, webhooks, Actions permissions & secret names |
| `github.request`                | Raw GitHub request       | proxy   | escape hatch — any REST endpoint; `{org}` expands to the settings org |

Every text input accepts `{{$.path}}` tokens resolved against the flow scope.
**Repository** fields carry a **↻ Load repos** button that lists the settings
organization's repositories.

**Curated vs proxy.** oomol declares every curated input with
`additionalProperties: false` and camelCase names (`perPage`, `issueNumber`), so a
guessed field is a hard 400. Only actions whose schema was confirmed against the
live catalog (`GET /v1/actions?service=github`) are called curated —
`list_my_repositories`, `get_repository`, `list_commits`, `get_current_user` —
and even those are **pruned at runtime to the properties the live `inputSchema`
declares**. Everything else uses an exact GitHub REST path through the proxy.

**Capability checks.** For curated actions the plugin reads `requiredScopes`
**live from oomol** (cached) and compares them with the account's `scopes` only
when both use oomol's vocabulary (`github.repo.read`); a connection reporting
GitHub OAuth scopes (`repo`, `read:org`) is not second-guessed. The security
proxy actions are not pre-checked at all — GitHub answers 403 with its own
message when a token lacks `security_events` / `read:org` / `repo`.

## Meta RPCs (used by the settings and action forms)

`github.meta.account.list` · `github.meta.account.test` · `github.meta.user.info`
· `github.meta.org.list` · `github.meta.repo.list`.

## Layout

```
main.py                     intro + settings + actions/metas wiring, then start()
github_oc/
  oc.py                     the OpenConnector bridge (accounts, curated actions, REST proxy, scope cache)
  forms.py                  settings + action forms (formkit)
  meta.py                   meta RPCs (account/org/repo pickers) + settings submit
  actions.py                the 13 action handlers (job pipeline)
  vars.py                   {{$...}} token resolution
  registry.py               wires actions + metas + settings
tests/                      unit tests over a fake OpenConnector gateway (no NATS)
```

## Run

```bash
cp .env.inflow.example .env.inflow    # fill in the values Infra minted (OPEN cred)
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python main.py
```

On startup the SDK logs every subject it subscribes to — that log is the
confirmation the plugin registered with Infra.

## Test

```bash
pip install -e ".[dev]"    # or: pip install pytest pytest-asyncio
pytest -q
```

The suite exercises the OpenConnector bridge, the forms, the pickers and every
action handler against an in-process fake gateway — no NATS, no network.

## Notes & caveats

- **Adding a curated action.** Check its `inputSchema` in
  `GET /v1/actions?service=github` first (names are camelCase, unknown keys are
  rejected), then call `gh.action(name, input)` — the runtime pruning covers
  optional drift, not a wrong required name.
- **Rate limits.** Org-wide alert listing over many repos burns the REST budget;
  the org-scoped `/orgs/{org}/…/alerts` endpoints are used where they exist (one
  call per org), and paging is exposed on every list action.
- **GitHub Enterprise Server.** oomol's proxy base URL is `api.github.com`; GHES
  needs a per-connection base URL configured on the OpenConnector side.
