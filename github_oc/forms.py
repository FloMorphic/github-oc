# Every form this plugin serves, declared once with the SDK's formkit builder,
# which generates the JSON Schema and the JSON Forms UI schema from one statement
# per field. A malformed form raises at start-up (build() calls validate()),
# where it is a programming error rather than a dialog that won't open.
#
# WHERE THE OWNER LIVES. An OpenConnector GitHub connection is granted to an
# account and, typically, to one organization — so the organization is part of
# the *connection*, not of any single action. It is set ONCE on the settings form
# (with a picker for tokens that can list their orgs; typed for tokens scoped to
# a single org, which cannot) and every action reads it from the bound profile.
# No action form carries an Owner / Organization input.
from __future__ import annotations

from inflow_plugin_sdk import formkit
from inflow_plugin_sdk.formkit import Option


# ------------------------------------------------------------ shared fields --


def _repo(method: str) -> formkit.Field:
    """The repository name, with a picker that lists the settings organization's
    repos. `.picks(method)` names the ACTION whose form the picker rebuilds —
    otherwise an ambiguous match would replace the open dialog with a different
    form. See meta.form_for."""
    return (
        formkit.text("repo", "Repository")
        .required()
        .describe("Repository name (without the owner). Press ↻ to list the repositories of the organization set in the account settings.")
        .lookup("github.meta.repo.list", "Load repos")
        .picks(method)
    )


def _per_page() -> formkit.Field:
    return (
        formkit.integer("perPage", "Per page")
        .default(30)
        .between(1, 100)
        .describe("Results per page (1–100).")
    )


def _page() -> formkit.Field:
    return formkit.integer("page", "Page").default(1).min(1).describe("Page number to fetch.")


# ---------------------------------------------------------------- settings --


def settings_form() -> formkit.Form:
    """The connection form: which connected GitHub account this node acts as, and
    the organization / owner it works with. It carries no credentials — the
    account is connected centrally in FloMorphic → Connect."""
    return (
        formkit.form("GitHub account (OpenConnector)")
        .describe(
            "This node acts as a GitHub account you connected in FloMorphic → Connect, "
            "within one organization (or owner). Press Load accounts and pick one — "
            "no GitHub token lives here."
        )
        .submit_to("github.meta.account.test")
        .add(
            formkit.text("alias", "GitHub account")
            .describe(
                "Press ↻ to load the GitHub accounts connected in FloMorphic → Connect, "
                "then pick one. Empty uses the default connection."
            )
            .lookup("github.meta.account.list", "Load accounts")
            .picks("github.meta.account.list"),
            formkit.text("org", "Organization / owner")
            .describe(
                "The organization (or owner login) every action of this profile targets. "
                "Press ↻ to load the orgs your token can list. If the connection was "
                "granted to one specific organization in OpenConnector, that list is "
                "empty — type the org it was granted to."
            )
            .lookup("github.meta.org.list", "Load orgs")
            .picks("github.settings"),
            formkit.text("connection", "Gateway (optional)").describe(
                "Advanced: pin to one Connect connection id when several gateways are "
                "configured (hosted oomol vs self-hosted). Empty spans all."
            ),
            formkit.text("test", "Test account")
            .describe("Press ↻ to confirm the selected account resolves before saving.")
            .lookup("github.meta.account.test", "Test account"),
            formkit.text("identity", "GitHub identity")
            .describe("Press ↻ to show the connected login and the token's granted scopes.")
            .lookup("github.meta.user.info", "Check identity"),
        )
    )


# ------------------------------------------------------------------ actions --


def repos_list_form() -> formkit.FormBuilder:
    """`github.repos.list` — the settings organization's repositories, or the
    account's own."""
    return (
        formkit.form("List repositories")
        .add(
            formkit.choice(
                "scope",
                "List",
                Option("org", "The organization's (from settings)"),
                Option("mine", "My repositories"),
            ).default("org"),
            formkit.enum_("visibility", "Visibility", "all", "public", "private")
            .default("all")
            .describe("Filter by repository visibility."),
            formkit.enum_("sort", "Sort by", "full_name", "created", "updated", "pushed")
            .default("full_name"),
            _per_page(),
            _page(),
        )
        .build()
    )


def repo_get_form() -> formkit.FormBuilder:
    """`github.repo.get` — one repository's full record."""
    return formkit.form("Get repository").add(_repo("github.repo.get")).build()


def repo_collaborators_form() -> formkit.FormBuilder:
    """`github.repo.collaborators` — who can push, and at what permission level."""
    return (
        formkit.form("List collaborators")
        .add(
            _repo("github.repo.collaborators"),
            formkit.enum_("affiliation", "Affiliation", "all", "direct", "outside")
            .default("all")
            .describe("all = direct + inherited; outside = non-members with access."),
            formkit.enum_("permission", "Minimum permission", "", "pull", "triage", "push", "maintain", "admin")
            .default("")
            .describe("Return only collaborators with at least this permission. Empty = any."),
            _per_page(),
            _page(),
        )
        .build()
    )


def repo_contents_form() -> formkit.FormBuilder:
    """`github.repo.contents` — a file or directory (CODEOWNERS, SECURITY.md, …)."""
    return (
        formkit.form("Get file / directory contents")
        .add(
            _repo("github.repo.contents"),
            formkit.text("path", "Path").describe(
                "File or directory path in the repo, e.g. .github/CODEOWNERS or SECURITY.md. "
                "Empty returns the repository root."
            ),
            formkit.text("ref", "Ref").describe(
                "Branch, tag or commit SHA to read from. Empty uses the default branch."
            ),
        )
        .build()
    )


def activity_list_form() -> formkit.FormBuilder:
    """`github.activity.list` — recent commits or workflow runs for a window."""
    return (
        formkit.form("List activity")
        .add(
            formkit.choice(
                "kind",
                "Activity",
                Option("commits", "Commits"),
                Option("workflow_runs", "Workflow runs"),
            ).default("commits"),
            _repo("github.activity.list"),
            formkit.text("sha", "Branch / SHA")
            .describe("Branch name or commit SHA to start from. Empty uses the default branch.")
            .show_when("kind", "commits"),
            formkit.date_time("since", "Since")
            .describe("Only commits after this instant (RFC 3339).")
            .show_when("kind", "commits"),
            formkit.enum_("status", "Run status", "", "queued", "in_progress", "completed", "success", "failure")
            .default("")
            .describe("Filter workflow runs by status/conclusion. Empty = all.")
            .show_when("kind", "workflow_runs"),
            _per_page(),
            _page(),
        )
        .build()
    )


def search_form() -> formkit.FormBuilder:
    """`github.search` — code / issues / repos with GitHub search syntax."""
    return (
        formkit.form("Search GitHub")
        .add(
            formkit.choice(
                "kind",
                "Search",
                Option("repositories", "Repositories"),
                Option("code", "Code"),
                Option("issues", "Issues & PRs"),
            ).default("repositories"),
            formkit.text("q", "Query")
            .required()
            .describe(
                "GitHub search query, e.g. language:go archived:false, or "
                "filename:Dockerfile. Tick the box below to limit it to the settings "
                "organization. Accepts {{$.path}} tokens."
            ),
            formkit.boolean("inOrg", "Within the organization")
            .default(True)
            .describe("Prefix the query with org:<settings organization>."),
            _per_page(),
            _page(),
        )
        .build()
    )


# ---------------------------------------------- provider-proxy (security) --


def repo_protection_form() -> formkit.FormBuilder:
    """`github.repo.protection` — branch protection and rulesets on a branch."""
    return (
        formkit.form("Get branch protection & rulesets")
        .add(
            _repo("github.repo.protection"),
            formkit.text("branch", "Branch").describe(
                "Branch to inspect. Empty resolves the repository's default branch."
            ),
            formkit.boolean("rulesets", "Include rulesets")
            .default(True)
            .describe("Also fetch the newer branch rulesets alongside classic protection."),
        )
        .build()
    )


def _alert_target_fields(method: str) -> list[formkit.Field]:
    return [
        formkit.choice(
            "target",
            "Scope",
            Option("repo", "One repository"),
            Option("org", "The whole organization (from settings)"),
        ).default("repo"),
        formkit.text("repo", "Repository")
        .describe("Repository name. Press ↻ to list the settings organization's repositories.")
        .lookup("github.meta.repo.list", "Load repos")
        .picks(method)
        .show_when("target", "repo"),
    ]


def alerts_dependabot_form() -> formkit.FormBuilder:
    """`github.alerts.dependabot` — vulnerable-dependency alerts."""
    return (
        formkit.form("List Dependabot alerts")
        .add(
            *_alert_target_fields("github.alerts.dependabot"),
            formkit.enum_("state", "State", "", "open", "dismissed", "fixed", "auto_dismissed")
            .default("open"),
            formkit.enum_("severity", "Severity", "", "low", "medium", "high", "critical").default(""),
            _per_page(),
            _page(),
        )
        .build()
    )


def alerts_secret_scanning_form() -> formkit.FormBuilder:
    """`github.alerts.secret_scanning` — leaked-credential alerts."""
    return (
        formkit.form("List secret-scanning alerts")
        .add(
            *_alert_target_fields("github.alerts.secret_scanning"),
            formkit.enum_("state", "State", "", "open", "resolved").default("open"),
            _per_page(),
            _page(),
        )
        .build()
    )


def alerts_code_scanning_form() -> formkit.FormBuilder:
    """`github.alerts.code_scanning` — SAST alerts."""
    return (
        formkit.form("List code-scanning alerts")
        .add(
            *_alert_target_fields("github.alerts.code_scanning"),
            formkit.enum_("state", "State", "", "open", "dismissed", "fixed").default("open"),
            formkit.enum_("severity", "Severity", "", "note", "warning", "error", "critical").default(""),
            _per_page(),
            _page(),
        )
        .build()
    )


def org_members_form() -> formkit.FormBuilder:
    """`github.org.members` — members (2FA filter), admins, outside collaborators
    of the settings organization."""
    return (
        formkit.form("List organization members")
        .describe("Lists the organization set in the account settings.")
        .add(
            formkit.choice(
                "kind",
                "Listing",
                Option("members", "Members"),
                Option("outside_collaborators", "Outside collaborators"),
            ).default("members"),
            formkit.enum_("filter", "2FA filter", "all", "2fa_disabled")
            .default("all")
            .describe("2fa_disabled surfaces members without two-factor auth.")
            .show_when("kind", "members"),
            formkit.enum_("role", "Role", "", "all", "admin", "member")
            .default("")
            .describe("Filter members by their org role. Empty = all.")
            .show_when("kind", "members"),
            _per_page(),
            _page(),
        )
        .build()
    )


def repo_settings_form() -> formkit.FormBuilder:
    """`github.repo.settings` — deploy keys, webhooks, Actions permissions & secret names."""
    return (
        formkit.form("Get repository settings")
        .add(
            _repo("github.repo.settings"),
            formkit.choice(
                "include",
                "Fetch",
                Option("all", "Everything below"),
                Option("keys", "Deploy keys"),
                Option("hooks", "Webhooks"),
                Option("actions_permissions", "Actions permissions"),
                Option("actions_secrets", "Actions secret names"),
            )
            .default("all")
            .describe("Which settings surface to fetch."),
        )
        .build()
    )


def request_form() -> formkit.FormBuilder:
    """`github.request` — raw GitHub REST request, the escape hatch."""
    return (
        formkit.form("Raw GitHub request")
        .describe(
            "Signed passthrough to the GitHub REST API through OpenConnector. "
            "The account's credential and API headers are added by oomol. "
            "`{org}` in the endpoint expands to the settings organization."
        )
        .add(
            formkit.enum_("method", "Method", "GET", "POST", "PATCH", "PUT", "DELETE").default("GET"),
            formkit.text("endpoint", "Endpoint")
            .required()
            .describe("A GitHub REST path, e.g. /repos/{org}/my-repo/branches. Accepts {{$.path}} tokens."),
            formkit.text_area("query", "Query (JSON)").describe(
                'Optional query parameters as a JSON object, e.g. {"per_page": 100, "state": "open"}.'
            ),
            formkit.text_area("body", "Body (JSON)").describe(
                "Optional request body as JSON, for POST/PATCH/PUT calls."
            ),
        )
        .build()
    )
