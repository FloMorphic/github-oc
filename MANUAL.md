# GitHub (OpenConnector)

Read GitHub — repositories, activity, search — and its **security surface**
(Dependabot / secret-scanning / code-scanning alerts, branch protection, org
members, repo settings) from your workflow, acting as a GitHub account you
connect **once** in FloMorphic → **Connect**. This node holds **no GitHub
token**: it builds each request and asks the FloMorphic backend to run it as your
connected account.

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

For the security actions, the connected token needs the right scopes —
`security_events` (alerts), `read:org` (org members / 2FA filter), `repo`
(private repos, branch protection). A token lacking one gets GitHub's own
403 message on the node.

## Actions

| Action | What it does |
|--------|--------------|
| **List repositories**       | Your repos, an org's, or a user's. |
| **Get repository**          | One repository's full record. |
| **List collaborators**      | Who can push, and at what permission level. |
| **Get contents**            | A file or directory — CODEOWNERS, SECURITY.md, workflows. |
| **List activity**           | Recent commits or workflow runs. |
| **Search GitHub**           | Repositories, code, or issues & PRs. |
| **Branch protection**       | Classic protection + rulesets on a branch (default branch if blank). |
| **Dependabot alerts**       | Vulnerable-dependency alerts, per repo or org-wide. |
| **Secret-scanning alerts**  | Leaked-credential alerts, per repo or org-wide. |
| **Code-scanning alerts**    | SAST alerts, per repo or org-wide. |
| **Org members**             | Members (2FA filter), admins, or outside collaborators. |
| **Repo settings**           | Deploy keys, webhooks, Actions permissions & secret names. |
| **Raw GitHub request**      | Any other GitHub REST endpoint (escape hatch). |

Text inputs accept `{{$.path}}` tokens resolved against the flow scope, so a
`repo` or query can reference upstream data. **Repository** fields have a
**↻ Load repos** button that lists the settings organization's repositories.

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
so you can confirm the security actions will have what they need.

```inflow-meta
github.meta.user.info
Check identity
```

## Notes

- The security actions read the endpoints oomol does not curate through a
  **signed GitHub proxy** — no token ever leaves FloMorphic's backend.
- Org-wide alert scans use the one-call-per-org endpoints where they exist; still,
  large orgs return many rows — use the **State** / **Severity** filters and
  paging.
