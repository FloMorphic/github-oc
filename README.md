# GitHub (OpenConnector) — `github-oc`

A FloMorphic **plugin node** for GitHub that authenticates through FloMorphic's
central **Connect** feature (OpenConnector / oomol), built on
[`inflowenger-plugin-sdk`](https://pypi.org/project/inflowenger-plugin-sdk/) — the
first `-oc` plugin written in **Python**.

It appears on the workflow canvas as a **GitHub (OpenConnector)** node with **52
actions** that together reach **every one of the ~150 GitHub actions oomol
curates**, plus the security surface oomol does not. It holds **no GitHub
credentials** and makes **no GitHub API calls** — it is a *request builder*. A
GitHub account is connected **once, centrally**, in **FloMorphic → Connect**; this
node just picks which connected account to act as, and asks the FloMorphic backend
to run each action for it.

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

1. **Curated OpenConnector actions** — `POST /v1/actions/github.<action>` — the
   default and by far the larger part: repositories, contents, branches, refs,
   commits, checks, workflows, issues, labels, milestones, pull requests,
   reviews, releases, search and the event feeds.
2. **The provider proxy** — `POST /v1/proxy/github {endpoint, method, query, body}`
   — a signed passthrough to `api.github.com` for what oomol **does not** curate:
   Dependabot / secret-scanning / code-scanning alerts, branch protection &
   rulesets, org members, deploy keys, webhooks, Actions secrets, and any other
   REST path via the **Raw GitHub request** escape hatch.

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
- **The scopes the actions you use need.** Curated actions are gated by oomol's
  own `requiredScopes` (`github.repo.read`, `github.issue.write`,
  `github.pull_request.write`, `github.review.write`, `github.contents.write`,
  `github.workflow.write`, `github.status.write`, `github.repository.delete`, …)
  and the plugin refuses a visibly under-scoped account before the call. The
  security proxy actions need the GitHub scopes themselves: `security_events`
  (alerts), `read:org` (org members / 2FA filter), `repo` (private repos, branch
  protection), `admin:repo_hook` (webhooks). Fine-grained PAT equivalents:
  *Dependabot / Secret-scanning / Code-scanning alerts: read*,
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

**One action is a surface, not a single API call.** oomol curates ~150 GitHub
actions; packing 150 nodes onto the canvas would be unusable, so a node covers a
*surface* and its form opens with an **Operation** choice that picks the curated
action, hiding the inputs the other operations use. The mapping lives in one
place, [`github_oc/ops.py`](github_oc/ops.py), and `tests/test_ops.py` checks it
against oomol's own catalog.

### Curated surfaces

| Method | Title | Operations |
|--------|-------|------------|
| `github.user.get`         | Get user               | `me` · `user` |
| `github.repos.list`       | List repositories      | `org` · `mine` · `user` |
| `github.repo.get`         | Get repository         | — |
| `github.repo.create`      | Create repository      | — |
| `github.repo.update`      | Update repository      | — |
| `github.repo.delete`      | Delete repository      | — |
| `github.repo.fork`        | Fork repository        | — |
| `github.repo.insights`    | Repository insights    | `tags` · `languages` · `contributors` · `forks` · `stargazers` · `watchers` |
| `github.repo.topics`      | Repository topics      | `list` · `replace` |
| `github.repo.stars`       | Stars                  | `check` · `star` · `unstar` · `mine` |
| `github.repo.collaborators` | List collaborators   | — |
| `github.repo.access`      | Repository access      | `permission` · `add` · `remove` |
| `github.repo.contents`    | Get contents           | `file` · `dir` · `readme` |
| `github.repo.file`        | Write a file           | `save` · `delete` |
| `github.branches`         | Branches               | `list` · `get` |
| `github.branch.update`    | Update a branch        | `merge` · `rename` · `sync` |
| `github.refs`             | Git references         | `get` · `matching` · `create` · `update` · `delete` |
| `github.activity.list`    | List activity          | `commits` · `workflow_runs` |
| `github.commit.get`       | Get / compare commits  | `get` · `compare` |
| `github.commit.comments`  | Commit comments        | `list` · `create` |
| `github.commit.status`    | Commit statuses        | `list` · `create` |
| `github.checks`           | Checks                 | `runs` · `rerequest_run` · `rerequest_suite` |
| `github.workflows`        | Workflows              | `list` · `get` · `dispatch` · `enable` · `disable` |
| `github.workflow.runs`    | Workflow runs          | `get` · `cancel` · `rerun` · `rerun_failed` |
| `github.workflow.jobs`    | Workflow jobs          | `list` · `logs` |
| `github.workflow.artifacts` | Workflow artifacts   | `list` · `download` |
| `github.issues`           | Issues                 | `list` · `get` |
| `github.issue.write`      | Create / update an issue | `create` · `update` · `lock` · `unlock` |
| `github.issue.labels`     | Issue labels           | `list` · `add` · `set` · `remove` · `clear` |
| `github.issue.assignees`  | Issue assignees        | `available` · `add` · `remove` |
| `github.issue.comments`   | Issue comments         | `list` · `create` · `get` · `update` · `delete` |
| `github.issue.reactions`  | Add a reaction         | `issue` · `comment` |
| `github.issue.events`     | Issue events           | `timeline` · `issue` · `repository` |
| `github.labels`           | Labels                 | `list` · `get` · `create` · `update` · `delete` · `search` |
| `github.milestones`       | Milestones             | `list` · `get` · `create` · `update` · `delete` |
| `github.pulls`            | Pull requests          | `list` · `get` · `for_commit` · `merged` |
| `github.pull.write`       | Create / update a pull request | `create` · `update` · `update_branch` · `merge` |
| `github.pull.changes`     | Pull request changes   | `files` · `commits` |
| `github.pull.reviewers`   | Pull request reviewers | `list` · `request` · `remove` |
| `github.pull.reviews`     | Pull request reviews   | `list` · `get` · `create` · `submit` · `dismiss` · `delete_pending` |
| `github.pull.review_comments` | Review comments    | `list` · `create` · `reply` · `update` · `delete` |
| `github.releases`         | Releases               | `list` · `latest` · `get` · `by_tag` · `create` · `update` · `delete` · `notes` |
| `github.release.assets`   | Release assets         | `list` · `get` · `delete` |
| `github.search`           | Search GitHub          | `repositories` · `code` · `issues` · `users` · `commits` · `topics` |
| `github.events`           | List events            | `repository` · `public` · `user_public` · `user_received_public` · `user_all` · `user_received` |

### The surface oomol does not curate (provider proxy)

| Method | Title | Notes |
|--------|-------|-------|
| `github.repo.protection`        | Branch protection      | classic protection + rulesets; resolves the default branch |
| `github.alerts.dependabot`      | Dependabot alerts      | repo or org-wide |
| `github.alerts.secret_scanning` | Secret-scanning alerts | repo or org-wide |
| `github.alerts.code_scanning`   | Code-scanning alerts   | repo or org-wide |
| `github.org.members`            | Org members            | members (2FA filter) / outside collaborators |
| `github.repo.settings`          | Repo settings          | deploy keys, webhooks, Actions permissions & secret names |
| `github.request`                | Raw GitHub request     | escape hatch — any REST endpoint; `{org}` expands to the settings org |

Every text input accepts `{{$.path}}` tokens resolved against the flow scope.
**Repository** fields carry a **↻ Load repos** button that lists the settings
organization's repositories.

**Curated inputs.** oomol declares every curated input with
`additionalProperties: false` and camelCase names (`perPage`, `issueNumber`,
`pullNumber`), so a guessed field is a hard 400. The forms therefore use oomol's
own spelling, `ops.py` records the handful of places where a form must differ (a
`state` *filter* of open/closed/all versus a `state` to *set* of open/closed;
`refs/heads/x` for `create_ref` versus `heads/x` for `get_ref`), and every input
is additionally **pruned at run time to the properties the live `inputSchema`
declares**, so a gateway that curates a field differently cannot fail the call.

**Nothing is sent that you did not fill.** An empty field is dropped, and a form
that *updates* a GitHub setting (repository features, draft / prerelease,
maintainers-can-modify) uses a three-state ""/true/false choice instead of a
checkbox, so an untouched toggle cannot switch a setting off.

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
  ops.py                    every curated action, by surface and operation (the source of truth)
  forms.py                  settings + action forms (formkit)
  meta.py                   meta RPCs (account/org/repo pickers) + settings submit
  actions.py                the job pipeline: one generic curated runner + the proxy handlers
  vars.py                   {{$...}} token resolution
  registry.py               wires actions + metas + settings
openconnector-github-schema.json   oomol's GitHub catalog, as the gateway returns it
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

The suite exercises the OpenConnector bridge, the forms, the pickers, the canvas
wiring and every action handler against an in-process fake gateway — no NATS, no
network. The fake gateway serves action definitions from
`openconnector-github-schema.json`, so inputs are pruned against oomol's **real**
schemas, and `tests/test_ops.py` asserts that the plugin's mapping matches that
catalog: every action exists, every key it would send is declared, nothing
required is missing, and the whole catalog is reachable from the canvas.

## Notes & caveats

- **Adding or changing a curated action.** Refresh the catalog, then edit
  `ops.py` — the tests tell you immediately if a name or a required input is
  wrong:
  ```bash
  curl -s "$GATEWAY/v1/actions?service=github" > openconnector-github-schema.json
  pytest -q tests/test_ops.py
  ```
  A new operation needs three edits: its `Op` in `ops.py`, its fields in
  `forms.py`, and — only for a brand-new surface — a row in `registry.py`.
- **Not curated, so not exposed as its own action.** Uploading a release asset
  (it goes to a separate GitHub upload host) and creating a repository *inside an
  organization* have no curated action; use **Raw GitHub request**.
- **Rate limits.** Org-wide alert listing over many repos burns the REST budget;
  the org-scoped `/orgs/{org}/…/alerts` endpoints are used where they exist (one
  call per org), and paging is exposed on every list action.
- **`github.issues` paging.** oomol filters pull requests out of the issue list
  and reports the raw page length as `pageInfo.fetched`, so a paginating flow must
  continue while that equals **Per page**, even when `issues` comes back short or
  empty.
- **GitHub Enterprise Server.** oomol's proxy base URL is `api.github.com`; GHES
  needs a per-connection base URL configured on the OpenConnector side.
