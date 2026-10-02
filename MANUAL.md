# GitHub (OpenConnector)

Work with GitHub from your workflow — repositories, files, branches, commits,
issues, pull requests, reviews, releases, Actions, search — plus the **security
surface** (Dependabot / secret-scanning / code-scanning alerts, branch protection,
org members, repo settings), acting as a GitHub account you connect **once** in
FloMorphic → **Connect**. This node holds **no GitHub token**: it builds each
request and asks the FloMorphic backend to run it as your connected account.

## Set up (nothing to type)

1. Connect a GitHub account once in **FloMorphic → Connect** (OAuth app or a
   fine-grained PAT).
2. On the node, open **settings** → **Load accounts**, pick your account, set the
   **Organization / owner** (press **Load orgs**, or just type it — a connection
   scoped to one org can't list them), **Test account**, **Check identity**, then
   **Save**. That becomes a reusable settings profile.
3. Bind the profile in any GitHub node's drawer. Every action targets the
   organization set here — no Owner input on the actions. A token that spans
   several orgs gets one profile per org.

Each action checks the scopes it needs before it calls: a write action on a
read-only connection fails with the scope it is missing, so reconnect it in
**Connect** with that scope. The security actions need the GitHub scopes
themselves — `security_events` (alerts), `read:org` (org members / 2FA filter),
`repo` (private repos, branch protection) — and a token lacking one gets GitHub's
own 403 message on the node.

## Actions

Every action opens with an **Operation** choice: one node covers a whole GitHub
surface, and the form shows only the inputs that operation uses.

| Action | What it does |
|--------|--------------|
| **Get user**                | The connected account's profile, or another user's. |
| **List repositories**       | The organization's, your own, or another user's. |
| **Get repository**          | One repository's full record. |
| **Create / Update / Delete / Fork repository** | Make a repository, re-configure it, remove it, fork it. |
| **Repository insights**     | Tags, languages, contributors, forks, stargazers, watchers. |
| **Repository topics**       | Read the topics, or replace the whole set. |
| **Stars**                   | Star or unstar a repository, check one, list your stars. |
| **List collaborators**      | Who can push, and at what permission level. |
| **Repository access**       | Check, grant or revoke one user's access. |
| **Get contents**            | A file, a directory listing, or the README. |
| **Write a file**            | Commit a file, or commit its deletion. |
| **Branches**                | List the branches, or get one. |
| **Update a branch**         | Merge, rename, or sync a fork's branch with upstream. |
| **Git references**          | Read, create, move or delete the ref behind a branch or tag. |
| **List activity**           | Recent commits or workflow runs. |
| **Get / compare commits**   | One commit, or a `base...head` comparison. |
| **Commit comments**         | Read or write the comments on a commit. |
| **Commit statuses**         | Read the statuses on a ref, or post one. |
| **Checks**                  | Check runs for a ref, and re-requesting a run or suite. |
| **Workflows**               | List, get, dispatch, enable or disable a workflow. |
| **Workflow runs**           | Get, cancel, re-run a run, or re-run just its failed jobs. |
| **Workflow jobs**           | A run's jobs, and one job's logs. |
| **Workflow artifacts**      | A run's artifacts, and downloading one. |
| **Issues**                  | The issue list, or one issue. |
| **Create / update an issue**| Open, edit, lock or unlock an issue. |
| **Issue labels / assignees / comments / reactions / events** | Everything attached to one issue. |
| **Labels**                  | The repository's label definitions, and label search. |
| **Milestones**              | List, get, create, update or delete a milestone. |
| **Pull requests**           | The list, one PR, the PRs for a commit, or whether one is merged. |
| **Create / update a pull request** | Open, edit, update its branch, or merge it. |
| **Pull request changes**    | Its changed files or its commits. |
| **Pull request reviewers**  | Who is asked to review it. |
| **Pull request reviews**    | Create, submit, dismiss or read a review. |
| **Review comments**         | The inline comments on a diff. |
| **Releases**                | List, get (by ID or tag), create, update, delete, generate notes. |
| **Release assets**          | The files attached to a release. |
| **Search GitHub**           | Repositories, code, issues & PRs, users, commits or topics. |
| **List events**             | The public and received event feeds. |
| **Branch protection**       | Classic protection + rulesets on a branch (default branch if blank). |
| **Dependabot alerts**       | Vulnerable-dependency alerts, per repo or org-wide. |
| **Secret-scanning alerts**  | Leaked-credential alerts, per repo or org-wide. |
| **Code-scanning alerts**    | SAST alerts, per repo or org-wide. |
| **Org members**             | Members (2FA filter), admins, or outside collaborators. |
| **Repo settings**           | Deploy keys, webhooks, Actions permissions & secret names. |
| **Raw GitHub request**      | Any other GitHub REST endpoint (escape hatch). |
| **Clone repository**        | Clone it onto the machine the plugin runs on (see below). |

Text inputs accept `{{$.path}}` tokens resolved against the flow scope, so a
`repo`, an issue body or a query can reference upstream data. **Repository**
fields have a **↻ Load repos** button that lists the settings organization's
repositories.

**Nothing you leave empty is sent.** On the forms that change a GitHub setting,
toggles are *empty / true / false* rather than checkboxes — an untouched one keeps
the current value instead of switching it off.

## Clone repository

The only action that touches a filesystem. It runs `git` on the **plugin host** —
not on your machine — and the files land under the plugin's clone root
(`GITHUB_OC_CLONE_ROOT`, or `./workspace` beside the plugin). **Destination** is a
path relative to that root; absolute paths and `..` are refused.

**It is allowed by your org access.** The repository is read as the connected
account first, and one that account cannot see is refused — GitHub hides a private
repository from a token without access, so a successful read is itself proof of the
read access a clone needs.

**Require permission** is *pull* by default, which is exactly that, and costs no
extra call. Set it to *push* or *admin* when the flow goes on to commit: the node
then asks GitHub for the account's real permission and refuses if it cannot be
confirmed — saying so plainly, since OpenConnector's own reply does not report
permissions.

**Credentials.** OpenConnector keeps the GitHub token inside the gateway and never
hands it out, so git needs its own:

- **Public repository** — nothing to do. It clones anonymously.
- **Private over HTTPS** — put a GitHub token in **Token**. Best filled from an
  upstream node with a `{{$.path}}` token, so the value is not written into the
  flow. It is used for that one clone: never stored in `.git/config`, never in the
  remote URL, never printed back.
- **Private over SSH** — set **Transport: SSH** and the host's own key answers for
  it.

**An existing directory is safe.** *Fail* refuses it; *Fetch into it* and *Clone it
again* only ever act on a checkout of this same repository — anything else is left
untouched.

The host needs **git installed** and nothing else; if it is missing the node says
so instead of failing obscurely.

## Try it — live checks

Press **Run** on any block below to call that helper live; the raw JSON reply
appears beneath the button.

> The buttons pass no input, so they act on your **default** connected account.
> Nothing connected yet? Each returns a friendly notice, not an error — connect a
> GitHub account in **FloMorphic → Connect** first.

**List connected accounts** — the GitHub accounts connected in Connect (what the
settings dialog's *Load accounts* button calls).

```inflow-meta
github.meta.account.list
List connected accounts
```

**Test the default account** — resolves your default account, so a
misconfiguration shows up here rather than at run time.

```inflow-meta
github.meta.account.test
Test default account
```

**Check identity** — shows the connected login and the token's granted scopes,
so you can confirm the actions you need will have what they require.

```inflow-meta
github.meta.user.info
Check identity
```

## Notes

- Almost everything runs as a **curated OpenConnector action**. The security
  actions read the endpoints oomol does not curate through a **signed GitHub
  proxy** — no token ever leaves FloMorphic's backend.
- **Issue paging**: the issue list filters pull requests out, so a page can come
  back short. Keep paging while `pageInfo.fetched` equals **Per page**.
- Org-wide alert scans use the one-call-per-org endpoints where they exist; still,
  large orgs return many rows — use the **State** / **Severity** filters and
  paging.
- Not curated by oomol, so reach them with **Raw GitHub request**: uploading a
  release asset, and creating a repository *inside an organization*.
