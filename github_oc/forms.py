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
#
# ONE SURFACE, SEVERAL OPERATIONS. A curated action is not a node: oomol curates
# ~150 GitHub actions, so a node is a SURFACE (issues, releases, refs …) whose
# `op` choice picks the curated action, and `show_when` hides the inputs the other
# operations use. ops.py maps each op to its action and its required inputs.
#
# WHAT `.required()` MEANS HERE. Only a field every operation of the form needs is
# required in the schema — marking one that a single op needs would block the
# dialog for all the others. Per-operation requirements are refused at run time
# from ops.Op.needs, with the same "missing required input: x" message.
#
# THREE-STATE TOGGLES. A checkbox cannot say "leave this as it is", so a form that
# UPDATES a GitHub setting (repository features, draft / prerelease, …) offers
# ""/true/false instead; ops.Op.bools converts those back to booleans and drops
# the empty one. Checkboxes are kept for filters, where false means nothing.
from __future__ import annotations

from inflow_plugin_sdk import FormBuilder, formkit
from inflow_plugin_sdk.formkit import Option


# ------------------------------------------------------------ shared fields --


def _repo(method: str, required: bool = True) -> formkit.Field:
    """The repository name, with a picker that lists the settings organization's
    repos. `.picks(method)` names the ACTION whose form the picker rebuilds —
    otherwise an ambiguous match would replace the open dialog with a different
    form. See meta.form_for.

    `required=False` is for a surface where some operations are not about a
    repository at all (label search, my starred repositories): a hidden field the
    schema still demands would block the dialog. Those operations are checked at
    run time instead, from ops.Op.scope."""
    field = formkit.text("repo", "Repository")
    if required:
        field = field.required()
    return (
        field
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


def _op(*options: Option) -> formkit.Field:
    """The operation selector every curated surface opens with. Its values are the
    keys of the surface's table in ops.py."""
    return (
        formkit.choice("op", "Operation", *options)
        .default(options[0].value)
        .describe("Which GitHub operation this node performs.")
    )


def _only(field: formkit.Field, *ops: str) -> formkit.Field:
    """Show a field only while the operation is one of these. formkit's show_when
    compares against a single value, so several are expressed as the JSON Forms
    `enum` condition directly."""
    if len(ops) == 1:
        return field.show_when("op", ops[0])
    field.rule = {
        "effect": "SHOW",
        "condition": {"scope": formkit.scope_of("op"), "schema": {"enum": list(ops)}},
    }
    return field


def _tri(name: str, title: str, what: str) -> formkit.Field:
    """A leave-it-alone toggle: empty sends nothing, so an untouched switch cannot
    turn a GitHub setting off. ops.Op.bools converts the two filled values."""
    return (
        formkit.enum_(name, title, "", "true", "false")
        .default("")
        .describe(f"{what} Leave empty to keep the current value.")
    )


def _number(name: str, title: str, what: str) -> formkit.Field:
    return formkit.integer(name, title).min(1).describe(what)


def _direction() -> formkit.Field:
    return formkit.enum_("direction", "Direction", "", "asc", "desc").default("").describe("Sort direction.")


def _order() -> formkit.Field:
    return formkit.enum_("order", "Order", "", "asc", "desc").default("").describe("Sort order.")


def _issue_number() -> formkit.Field:
    return _number("issueNumber", "Issue number", "The issue (or pull request) number.")


def _pull_number() -> formkit.Field:
    return _number("pullNumber", "Pull request number", "The pull request number.")


def _comment_id() -> formkit.Field:
    return _number("commentId", "Comment ID", "The comment ID, as GitHub reports it.")


def _run_id() -> formkit.Field:
    return _number("runId", "Run ID", "The workflow run ID.")


def _release_id() -> formkit.Field:
    return _number("releaseId", "Release ID", "The release ID, as GitHub reports it.")


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


# ------------------------------------------------------------------ account --


def user_get_form() -> FormBuilder:
    """`github.user.get` — the connected account's own profile, or another user's."""
    return (
        formkit.form("Get user")
        .add(
            _op(
                Option("me", "The connected account"),
                Option("user", "Another user by login"),
            ),
            _only(formkit.text("username", "Username").describe("The GitHub login to look up."), "user"),
        )
        .build()
    )


def events_form() -> FormBuilder:
    """`github.events` — the public/received event feeds GitHub exposes."""
    return (
        formkit.form("List events")
        .add(
            _op(
                Option("repository", "A repository's events"),
                Option("public", "The public timeline"),
                Option("user_public", "A user's public events"),
                Option("user_received_public", "Public events a user received"),
                Option("user_all", "A user's events (needs their token)"),
                Option("user_received", "Events a user received (needs their token)"),
            ),
            _only(_repo("github.events", required=False), "repository"),
            _only(
                formkit.text("username", "Username").describe(
                    "The GitHub login whose feed to read. The two 'needs their token' feeds "
                    "only return data for the connected account itself."
                ),
                "user_public",
                "user_received_public",
                "user_all",
                "user_received",
            ),
            _per_page(),
            _page(),
        )
        .build()
    )


# ------------------------------------------------------------- repositories --


def repos_list_form() -> FormBuilder:
    """`github.repos.list` — the settings organization's repositories, the
    account's own, or another user's."""
    return (
        formkit.form("List repositories")
        .add(
            _op(
                Option("org", "The organization's (from settings)"),
                Option("mine", "My repositories"),
                Option("user", "Another user's"),
            ),
            _only(formkit.text("username", "Username").describe("The GitHub login whose repositories to list."), "user"),
            _only(
                formkit.enum_("visibility", "Visibility", "all", "public", "private")
                .default("all")
                .describe("Filter by repository visibility."),
                "mine",
            ),
            _only(
                formkit.enum_("orgType", "Type", "all", "public", "private", "forks", "sources", "member")
                .default("all")
                .describe("Which of the organization's repositories to include."),
                "org",
            ),
            _only(
                formkit.enum_("userType", "Type", "all", "owner", "member")
                .default("all")
                .describe("Which of the user's repositories to include."),
                "user",
            ),
            formkit.enum_("sort", "Sort by", "full_name", "created", "updated", "pushed")
            .default("full_name"),
            _direction(),
            _per_page(),
            _page(),
        )
        .build()
    )


def repo_get_form() -> FormBuilder:
    """`github.repo.get` — one repository's full record."""
    return formkit.form("Get repository").add(_repo("github.repo.get")).build()


def repo_create_form() -> FormBuilder:
    """`github.repo.create` — a new repository for the connected account."""
    return (
        formkit.form("Create repository")
        .describe(
            "Creates the repository under the CONNECTED ACCOUNT. To create one inside an "
            "organization, use the Raw GitHub request action against POST /orgs/{org}/repos "
            "— oomol does not curate that endpoint."
        )
        .add(
            formkit.text("name", "Name").required().describe("The repository name."),
            formkit.text_area("description", "Description"),
            formkit.text("homepage", "Homepage").describe("A URL shown on the repository page."),
            formkit.boolean("private", "Private").default(False),
            formkit.boolean("autoInit", "Create an initial commit")
            .default(False)
            .describe("Let GitHub create a first commit with a README."),
            _tri("hasIssues", "Issues", "Whether issues are enabled."),
            _tri("hasProjects", "Projects", "Whether projects are enabled."),
            _tri("hasWiki", "Wiki", "Whether the wiki is enabled."),
            _tri("hasDiscussions", "Discussions", "Whether discussions are enabled."),
            formkit.text("gitignoreTemplate", ".gitignore template").describe(
                "A GitHub .gitignore template name, e.g. Python or Go."
            ),
            formkit.text("licenseTemplate", "License template").describe(
                "An SPDX-ish license keyword, e.g. mit or apache-2.0."
            ),
        )
        .build()
    )


def repo_update_form() -> FormBuilder:
    """`github.repo.update` — rename, re-describe or re-configure a repository."""
    return (
        formkit.form("Update repository")
        .describe("Only the fields you fill are sent. Toggles left empty keep their current value.")
        .add(
            _repo("github.repo.update"),
            formkit.text("name", "New name").describe("Renames the repository. Empty keeps the name."),
            formkit.text_area("description", "Description"),
            formkit.text("homepage", "Homepage"),
            formkit.enum_("visibility", "Visibility", "", "public", "private")
            .default("")
            .describe("Change who can see the repository."),
            formkit.text("defaultBranch", "Default branch").describe(
                "The branch GitHub opens by default. It must already exist."
            ),
            _tri("private", "Private", "Whether the repository is private."),
            _tri("hasIssues", "Issues", "Whether issues are enabled."),
            _tri("hasProjects", "Projects", "Whether projects are enabled."),
            _tri("hasWiki", "Wiki", "Whether the wiki is enabled."),
            _tri("hasDiscussions", "Discussions", "Whether discussions are enabled."),
            _tri("allowSquashMerge", "Allow squash merge", "Whether squash merging is allowed."),
            _tri("allowMergeCommit", "Allow merge commit", "Whether merge commits are allowed."),
            _tri("allowRebaseMerge", "Allow rebase merge", "Whether rebase merging is allowed."),
            _tri("allowAutoMerge", "Allow auto-merge", "Whether auto-merge is allowed."),
            _tri("deleteBranchOnMerge", "Delete branch on merge", "Whether head branches are deleted after a merge."),
            _tri("archived", "Archived", "Archiving makes the repository read-only."),
        )
        .build()
    )


def repo_delete_form() -> FormBuilder:
    """`github.repo.delete` — delete a repository. Irreversible."""
    return (
        formkit.form("Delete repository")
        .describe(
            "Deletes the repository permanently. The connection needs the "
            "github.repository.delete scope, which OpenConnector grants separately."
        )
        .add(_repo("github.repo.delete"))
        .build()
    )


def repo_fork_form() -> FormBuilder:
    """`github.repo.fork` — fork a repository to the account or an org."""
    return (
        formkit.form("Fork repository")
        .add(
            _repo("github.repo.fork"),
            formkit.text("organization", "Fork into organization").describe(
                "Where the fork is created. Empty forks to the connected account."
            ),
            formkit.text("name", "Fork name").describe("A name for the fork. Empty keeps the source name."),
            formkit.boolean("defaultBranchOnly", "Default branch only").default(False),
        )
        .build()
    )


def repo_insights_form() -> FormBuilder:
    """`github.repo.insights` — the read-only facts around a repository."""
    return (
        formkit.form("Repository insights")
        .add(
            _op(
                Option("tags", "Tags"),
                Option("languages", "Languages"),
                Option("contributors", "Contributors"),
                Option("forks", "Forks"),
                Option("stargazers", "Stargazers"),
                Option("watchers", "Watchers"),
            ),
            _repo("github.repo.insights"),
            _only(
                formkit.boolean("anon", "Include anonymous contributors").default(False),
                "contributors",
            ),
            _only(
                formkit.enum_("sort", "Sort forks by", "", "newest", "oldest", "stargazers", "watchers").default(""),
                "forks",
            ),
            _per_page(),
            _page(),
        )
        .build()
    )


def repo_topics_form() -> FormBuilder:
    """`github.repo.topics` — read the topics, or replace the whole set."""
    return (
        formkit.form("Repository topics")
        .add(
            _op(Option("list", "List topics"), Option("replace", "Replace all topics")),
            _repo("github.repo.topics"),
            _only(
                formkit.list_("names", "Topics").describe(
                    "The FULL set of lowercase topics to set — anything not listed is removed."
                ),
                "replace",
            ),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def repo_stars_form() -> FormBuilder:
    """`github.repo.stars` — star, unstar, check, or list the account's stars."""
    return (
        formkit.form("Stars")
        .add(
            _op(
                Option("check", "Is it starred?"),
                Option("star", "Star it"),
                Option("unstar", "Unstar it"),
                Option("mine", "List my starred repositories"),
            ),
            _only(_repo("github.repo.stars", required=False), "check", "star", "unstar"),
            _only(
                formkit.enum_("sort", "Sort by", "", "created", "updated").default(""),
                "mine",
            ),
            _only(_direction(), "mine"),
            _only(_per_page(), "mine"),
            _only(_page(), "mine"),
        )
        .build()
    )


def repo_collaborators_form() -> FormBuilder:
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


def repo_access_form() -> FormBuilder:
    """`github.repo.access` — one user's access to a repository."""
    return (
        formkit.form("Repository access")
        .add(
            _op(
                Option("permission", "Check a user's permission"),
                Option("add", "Add / invite a collaborator"),
                Option("remove", "Remove a collaborator"),
            ),
            _repo("github.repo.access"),
            formkit.text("username", "Username").describe("The GitHub login to act on."),
            _only(
                formkit.text("permission", "Permission").describe(
                    "pull, triage, push, maintain, admin, or a custom repository role name. "
                    "Empty lets GitHub apply its default (pull)."
                ),
                "add",
            ),
        )
        .build()
    )


# ---------------------------------------------------------------- contents --


def repo_contents_form() -> FormBuilder:
    """`github.repo.contents` — a file, a directory listing, or the README."""
    return (
        formkit.form("Get file / directory contents")
        .add(
            _op(
                Option("file", "One file"),
                Option("dir", "A directory listing"),
                Option("readme", "The README"),
            ),
            _repo("github.repo.contents"),
            _only(
                formkit.text("path", "Path").describe(
                    "File or directory path in the repo, e.g. .github/CODEOWNERS or SECURITY.md. "
                    "For a directory listing, empty reads the repository root."
                ),
                "file",
                "dir",
            ),
            formkit.text("ref", "Ref").describe(
                "Branch, tag or commit SHA to read from. Empty uses the default branch."
            ),
        )
        .build()
    )


def repo_file_form() -> FormBuilder:
    """`github.repo.file` — commit a file, or commit its deletion."""
    return (
        formkit.form("Write a file")
        .describe("Commits straight to a branch through the GitHub contents API.")
        .add(
            _op(Option("save", "Create or update a file"), Option("delete", "Delete a file")),
            _repo("github.repo.file"),
            formkit.text("path", "Path").describe("The file path in the repository."),
            formkit.text("message", "Commit message"),
            formkit.text("branch", "Branch").describe(
                "The branch to commit to. Empty uses the default branch."
            ),
            _only(
                formkit.text_area("content", "Content").describe(
                    "The new file content as plain text. Accepts {{$.path}} tokens."
                ),
                "save",
            ),
            _only(
                formkit.text_area("contentBase64", "Content (base64)").describe(
                    "Base64 content, for binary files. Use this instead of Content, not both."
                ),
                "save",
            ),
            formkit.text("sha", "Blob SHA").describe(
                "The SHA of the file being replaced or deleted — required to delete, and to "
                "update an existing file. Read it from Get contents first."
            ),
        )
        .build()
    )


# --------------------------------------------------------- branches & refs --


def branches_form() -> FormBuilder:
    """`github.branches` — list a repository's branches, or get one."""
    return (
        formkit.form("Branches")
        .add(
            _op(Option("list", "List branches"), Option("get", "Get one branch")),
            _repo("github.branches"),
            _only(formkit.text("branch", "Branch").describe("The branch name."), "get"),
            _only(
                formkit.boolean("protectedOnly", "Protected only")
                .default(False)
                .describe("List only branches that carry a protection rule."),
                "list",
            ),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def branch_update_form() -> FormBuilder:
    """`github.branch.update` — merge, rename, or sync a branch."""
    return (
        formkit.form("Update a branch")
        .add(
            _op(
                Option("merge", "Merge one branch into another"),
                Option("rename", "Rename a branch"),
                Option("sync", "Sync a fork's branch with upstream"),
            ),
            _repo("github.branch.update"),
            _only(formkit.text("base", "Into (base)").describe("The branch that receives the merge."), "merge"),
            _only(formkit.text("head", "From (head)").describe("The branch, tag or SHA to merge from."), "merge"),
            _only(formkit.text("commitMessage", "Merge commit message"), "merge"),
            _only(
                formkit.text("branch", "Branch").describe("The branch to rename, or the fork branch to sync."),
                "rename",
                "sync",
            ),
            _only(formkit.text("newName", "New name").describe("The branch's new name."), "rename"),
        )
        .build()
    )


def refs_form() -> FormBuilder:
    """`github.refs` — the Git references behind branches and tags."""
    return (
        formkit.form("Git references")
        .describe(
            "GitHub spells a ref two ways: `heads/main` when reading or changing one, "
            "`refs/heads/main` when creating one. Both fields are below."
        )
        .add(
            _op(
                Option("get", "Get a ref"),
                Option("matching", "List refs matching a prefix"),
                Option("create", "Create a ref"),
                Option("update", "Move a ref"),
                Option("delete", "Delete a ref"),
            ),
            _repo("github.refs"),
            _only(
                formkit.text("ref", "Ref").describe(
                    "The ref without the refs/ prefix, e.g. heads/main or tags/v1.0.0. "
                    "For a prefix match, heads/feature matches every branch under it."
                ),
                "get",
                "matching",
                "update",
                "delete",
            ),
            _only(
                formkit.text("fullRef", "New ref").describe(
                    "The fully qualified ref to create, e.g. refs/heads/release-1.2."
                ),
                "create",
            ),
            _only(
                formkit.text("sha", "Target SHA").describe("The commit SHA the ref points at."),
                "create",
                "update",
            ),
            _only(
                formkit.boolean("force", "Force")
                .default(False)
                .describe("Allow a move that is not a fast-forward."),
                "update",
            ),
        )
        .build()
    )


# ----------------------------------------------------------------- commits --


def activity_list_form() -> FormBuilder:
    """`github.activity.list` — recent commits or workflow runs for a window."""
    return (
        formkit.form("List activity")
        .add(
            _op(Option("commits", "Commits"), Option("workflow_runs", "Workflow runs")),
            _repo("github.activity.list"),
            _only(
                formkit.text("sha", "Branch / SHA").describe(
                    "Branch name or commit SHA to start from. Empty uses the default branch."
                ),
                "commits",
            ),
            _only(formkit.text("path", "Path").describe("Only commits that touched this path."), "commits"),
            _only(formkit.text("author", "Author").describe("Login or email of the author."), "commits"),
            _only(formkit.text("committer", "Committer").describe("Login or email of the committer."), "commits"),
            _only(
                formkit.date_time("since", "Since").describe("Only commits after this instant (RFC 3339)."),
                "commits",
            ),
            _only(
                formkit.date_time("until", "Until").describe("Only commits before this instant (RFC 3339)."),
                "commits",
            ),
            _only(formkit.text("branch", "Branch").describe("Only runs on this branch."), "workflow_runs"),
            _only(formkit.text("actor", "Actor").describe("Only runs triggered by this login."), "workflow_runs"),
            _only(
                formkit.text("event", "Event").describe("Only runs from this event, e.g. push or pull_request."),
                "workflow_runs",
            ),
            _only(formkit.text("headSha", "Head SHA").describe("Only runs for this commit."), "workflow_runs"),
            _only(
                formkit.text("created", "Created").describe(
                    "GitHub date filter for the run's creation, e.g. >=2024-01-01."
                ),
                "workflow_runs",
            ),
            _only(
                formkit.enum_(
                    "status",
                    "Run status",
                    "",
                    "queued",
                    "in_progress",
                    "completed",
                    "requested",
                    "waiting",
                    "pending",
                    "success",
                    "failure",
                    "cancelled",
                    "skipped",
                    "timed_out",
                    "action_required",
                    "neutral",
                    "stale",
                )
                .default("")
                .describe("Filter runs by status or conclusion. Empty = all."),
                "workflow_runs",
            ),
            _only(
                formkit.boolean("excludePullRequests", "Exclude pull-request runs").default(False),
                "workflow_runs",
            ),
            _per_page(),
            _page(),
        )
        .build()
    )


def commit_get_form() -> FormBuilder:
    """`github.commit.get` — one commit, or a comparison between two."""
    return (
        formkit.form("Get / compare commits")
        .add(
            _op(Option("get", "One commit"), Option("compare", "Compare two refs")),
            _repo("github.commit.get"),
            _only(
                formkit.text("ref", "Ref").describe("The commit SHA, branch or tag to read."),
                "get",
            ),
            _only(
                formkit.text("basehead", "Base...head").describe(
                    "The comparison, e.g. main...feature-x or two SHAs joined by three dots."
                ),
                "compare",
            ),
            _only(_per_page(), "compare"),
            _only(_page(), "compare"),
        )
        .build()
    )


def commit_comments_form() -> FormBuilder:
    """`github.commit.comments` — comments attached to a commit."""
    return (
        formkit.form("Commit comments")
        .add(
            _op(Option("list", "List comments"), Option("create", "Comment on a commit")),
            _repo("github.commit.comments"),
            formkit.text("commitSha", "Commit SHA"),
            _only(formkit.text_area("body", "Comment"), "create"),
            _only(
                formkit.text("path", "Path").describe("Attach the comment to a file in the commit."),
                "create",
            ),
            _only(
                _number("position", "Diff position", "The line index inside the commit's diff."),
                "create",
            ),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def commit_status_form() -> FormBuilder:
    """`github.commit.status` — the commit statuses CI writes."""
    return (
        formkit.form("Commit statuses")
        .add(
            _op(Option("list", "List statuses for a ref"), Option("create", "Post a status")),
            _repo("github.commit.status"),
            _only(formkit.text("ref", "Ref").describe("The commit SHA, branch or tag to read."), "list"),
            _only(formkit.text("sha", "Commit SHA").describe("The commit the status is about."), "create"),
            _only(
                formkit.enum_("state", "State", "", "pending", "success", "failure", "error")
                .default("")
                .describe("The state to post."),
                "create",
            ),
            _only(
                formkit.text("context", "Context").describe(
                    "The check's name, e.g. ci/lint. GitHub keys statuses by it."
                ),
                "create",
            ),
            _only(formkit.text("targetUrl", "Target URL").describe("Where the status links to."), "create"),
            _only(formkit.text("description", "Description"), "create"),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def checks_form() -> FormBuilder:
    """`github.checks` — check runs for a ref, and re-running them."""
    return (
        formkit.form("Checks")
        .add(
            _op(
                Option("runs", "List check runs for a ref"),
                Option("rerequest_run", "Re-request a check run"),
                Option("rerequest_suite", "Re-request a check suite"),
            ),
            _repo("github.checks"),
            _only(formkit.text("ref", "Ref").describe("The commit SHA, branch or tag."), "runs"),
            _only(formkit.text("checkName", "Check name").describe("Only runs with this name."), "runs"),
            _only(_number("appId", "App ID", "Only runs from this GitHub App."), "runs"),
            _only(
                formkit.enum_("filter", "Filter", "", "latest", "all")
                .default("")
                .describe("latest keeps only the most recent run per name."),
                "runs",
            ),
            _only(
                formkit.text("status", "Status").describe("queued, in_progress or completed."),
                "runs",
            ),
            _only(_number("checkRunId", "Check run ID", "The check run to re-request."), "rerequest_run"),
            _only(
                _number("checkSuiteId", "Check suite ID", "The check suite to re-request."),
                "rerequest_suite",
            ),
            _only(_per_page(), "runs"),
            _only(_page(), "runs"),
        )
        .build()
    )


# --------------------------------------------------------------- workflows --


def workflows_form() -> FormBuilder:
    """`github.workflows` — the workflow definitions, and dispatching one."""
    return (
        formkit.form("Workflows")
        .add(
            _op(
                Option("list", "List workflows"),
                Option("get", "Get one workflow"),
                Option("dispatch", "Dispatch a workflow"),
                Option("enable", "Enable a workflow"),
                Option("disable", "Disable a workflow"),
            ),
            _repo("github.workflows"),
            _only(
                formkit.text("workflowId", "Workflow").describe(
                    "The workflow file name (ci.yml) or its numeric ID."
                ),
                "get",
                "dispatch",
                "enable",
                "disable",
            ),
            _only(
                formkit.text("ref", "Ref").describe("The branch or tag to run the workflow on."),
                "dispatch",
            ),
            _only(
                formkit.text_area("inputs", "Inputs (JSON)").describe(
                    'The workflow_dispatch inputs as a JSON object, e.g. {"environment": "staging"}. '
                    "GitHub requires every value to be a string."
                ),
                "dispatch",
            ),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def workflow_runs_form() -> FormBuilder:
    """`github.workflow.runs` — one run, and cancelling or re-running it.
    Listing runs lives on List activity."""
    return (
        formkit.form("Workflow runs")
        .describe("To LIST runs, use the List activity action with Workflow runs.")
        .add(
            _op(
                Option("get", "Get a run"),
                Option("cancel", "Cancel a run"),
                Option("rerun", "Re-run everything"),
                Option("rerun_failed", "Re-run failed jobs"),
            ),
            _repo("github.workflow.runs"),
            _run_id(),
            _only(
                formkit.boolean("enableDebugLogging", "Enable debug logging").default(False),
                "rerun",
                "rerun_failed",
            ),
        )
        .build()
    )


def workflow_jobs_form() -> FormBuilder:
    """`github.workflow.jobs` — a run's jobs, and one job's logs."""
    return (
        formkit.form("Workflow jobs")
        .add(
            _op(Option("list", "List a run's jobs"), Option("logs", "Get a job's logs")),
            _repo("github.workflow.jobs"),
            _only(_run_id(), "list"),
            _only(
                formkit.enum_("filter", "Filter", "", "latest", "all")
                .default("")
                .describe("latest keeps only the last attempt of each job."),
                "list",
            ),
            _only(_number("jobId", "Job ID", "The workflow job whose logs to fetch."), "logs"),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def workflow_artifacts_form() -> FormBuilder:
    """`github.workflow.artifacts` — a run's artifacts, and downloading one."""
    return (
        formkit.form("Workflow artifacts")
        .add(
            _op(Option("list", "List a run's artifacts"), Option("download", "Download an artifact")),
            _repo("github.workflow.artifacts"),
            _only(_run_id(), "list"),
            _only(formkit.text("name", "Name").describe("Only artifacts with this exact name."), "list"),
            _only(_number("artifactId", "Artifact ID", "The artifact to download."), "download"),
            _only(
                formkit.text("fileName", "File name").describe(
                    "The name to give the downloaded ZIP in transit."
                ),
                "download",
            ),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


# ------------------------------------------------------------------ issues --


def issues_form() -> FormBuilder:
    """`github.issues` — the issue list, or one issue."""
    return (
        formkit.form("Issues")
        .describe(
            "The list filters pull requests out. Its pageInfo.fetched reports the raw page "
            "length, so a paginating flow keeps going while that equals Per page."
        )
        .add(
            _op(Option("list", "List issues"), Option("get", "Get one issue")),
            _repo("github.issues"),
            _only(_issue_number(), "get"),
            _only(
                formkit.enum_("state", "State", "open", "closed", "all").default("open"),
                "list",
            ),
            _only(formkit.list_("labels", "Labels").describe("Only issues carrying all of these labels."), "list"),
            _only(
                formkit.enum_("sort", "Sort by", "", "created", "updated", "comments").default(""),
                "list",
            ),
            _only(_direction(), "list"),
            _only(
                formkit.date_time("since", "Updated since").describe(
                    "Only issues updated after this instant (RFC 3339)."
                ),
                "list",
            ),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def issue_write_form() -> FormBuilder:
    """`github.issue.write` — open, edit, lock or unlock an issue."""
    return (
        formkit.form("Create / update an issue")
        .add(
            _op(
                Option("create", "Create an issue"),
                Option("update", "Update an issue"),
                Option("lock", "Lock the conversation"),
                Option("unlock", "Unlock the conversation"),
            ),
            _repo("github.issue.write"),
            _only(_issue_number(), "update", "lock", "unlock"),
            _only(formkit.text("title", "Title"), "create", "update"),
            _only(formkit.text_area("body", "Body").describe("Markdown. Accepts {{$.path}} tokens."), "create", "update"),
            _only(
                formkit.enum_("state", "State", "", "open", "closed")
                .default("")
                .describe("Close or reopen the issue. Empty leaves it as it is."),
                "update",
            ),
            _only(formkit.list_("assignees", "Assignees").describe("GitHub logins."), "create", "update"),
            _only(formkit.list_("labels", "Labels"), "create", "update"),
            _only(_number("milestone", "Milestone number", "The milestone to attach."), "create", "update"),
            _only(
                formkit.enum_("lockReason", "Lock reason", "", "off-topic", "too heated", "resolved", "spam").default(""),
                "lock",
            ),
        )
        .build()
    )


def issue_labels_form() -> FormBuilder:
    """`github.issue.labels` — the labels on one issue."""
    return (
        formkit.form("Issue labels")
        .add(
            _op(
                Option("list", "List an issue's labels"),
                Option("add", "Add labels"),
                Option("set", "Replace all labels"),
                Option("remove", "Remove one label"),
                Option("clear", "Remove all labels"),
            ),
            _repo("github.issue.labels"),
            _issue_number(),
            _only(
                formkit.list_("labels", "Labels").describe(
                    "Replace sends the FULL set — anything not listed is removed."
                ),
                "add",
                "set",
            ),
            _only(formkit.text("label", "Label").describe("The single label to remove."), "remove"),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def issue_assignees_form() -> FormBuilder:
    """`github.issue.assignees` — who an issue is assigned to."""
    return (
        formkit.form("Issue assignees")
        .add(
            _op(
                Option("available", "List assignable users"),
                Option("add", "Assign users"),
                Option("remove", "Unassign users"),
            ),
            _repo("github.issue.assignees"),
            _only(_issue_number(), "add", "remove"),
            _only(formkit.list_("assignees", "Assignees").describe("GitHub logins."), "add", "remove"),
            _only(_per_page(), "available"),
            _only(_page(), "available"),
        )
        .build()
    )


def issue_comments_form() -> FormBuilder:
    """`github.issue.comments` — comments on an issue or pull request."""
    return (
        formkit.form("Issue comments")
        .describe("Pull requests are issues to GitHub, so a PR number works here too.")
        .add(
            _op(
                Option("list", "List an issue's comments"),
                Option("create", "Add a comment"),
                Option("get", "Get one comment"),
                Option("update", "Edit a comment"),
                Option("delete", "Delete a comment"),
            ),
            _repo("github.issue.comments"),
            _only(_issue_number(), "list", "create"),
            _only(_comment_id(), "get", "update", "delete"),
            _only(
                formkit.text_area("body", "Comment").describe("Markdown. Accepts {{$.path}} tokens."),
                "create",
                "update",
            ),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def issue_reactions_form() -> FormBuilder:
    """`github.issue.reactions` — react to an issue or to a comment."""
    return (
        formkit.form("Add a reaction")
        .add(
            _op(Option("issue", "React to an issue"), Option("comment", "React to a comment")),
            _repo("github.issue.reactions"),
            _only(_issue_number(), "issue"),
            _only(_comment_id(), "comment"),
            formkit.enum_(
                "content", "Reaction", "", "+1", "-1", "laugh", "confused", "heart", "hooray", "rocket", "eyes"
            ).default(""),
        )
        .build()
    )


def issue_events_form() -> FormBuilder:
    """`github.issue.events` — what happened to an issue, or to all of them."""
    return (
        formkit.form("Issue events")
        .add(
            _op(
                Option("timeline", "One issue's timeline"),
                Option("issue", "One issue's events"),
                Option("repository", "The repository's issue events"),
            ),
            _repo("github.issue.events"),
            _only(_issue_number(), "timeline", "issue"),
            _per_page(),
            _page(),
        )
        .build()
    )


def labels_form() -> FormBuilder:
    """`github.labels` — the repository's label definitions."""
    return (
        formkit.form("Labels")
        .add(
            _op(
                Option("list", "List the repository's labels"),
                Option("get", "Get one label"),
                Option("create", "Create a label"),
                Option("update", "Update a label"),
                Option("delete", "Delete a label"),
                Option("search", "Search labels by repository ID"),
            ),
            _only(_repo("github.labels", required=False), "list", "get", "create", "update", "delete"),
            _only(
                formkit.text("name", "Label name").describe("The label to read, create or change."),
                "get",
                "create",
                "update",
                "delete",
            ),
            _only(formkit.text("newName", "New name").describe("Renames the label."), "update"),
            _only(
                formkit.text("color", "Color").describe("Six hex digits without the #, e.g. d73a4a."),
                "create",
                "update",
            ),
            _only(formkit.text("description", "Description"), "create", "update"),
            _only(
                _number("repositoryId", "Repository ID", "GitHub's numeric repository ID — label search takes no owner/repo."),
                "search",
            ),
            _only(formkit.text("query", "Query").describe("The label search terms."), "search"),
            _only(
                formkit.enum_("sort", "Sort by", "", "created", "updated").default(""),
                "search",
            ),
            _only(_order(), "search"),
            _only(_per_page(), "list", "search"),
            _only(_page(), "list", "search"),
        )
        .build()
    )


def milestones_form() -> FormBuilder:
    """`github.milestones` — the repository's milestones."""
    return (
        formkit.form("Milestones")
        .add(
            _op(
                Option("list", "List milestones"),
                Option("get", "Get one milestone"),
                Option("create", "Create a milestone"),
                Option("update", "Update a milestone"),
                Option("delete", "Delete a milestone"),
            ),
            _repo("github.milestones"),
            _only(
                _number("milestoneNumber", "Milestone number", "The milestone number, as shown in GitHub."),
                "get",
                "update",
                "delete",
            ),
            _only(formkit.text("title", "Title"), "create", "update"),
            _only(formkit.text_area("description", "Description"), "create", "update"),
            _only(
                formkit.date_time("dueOn", "Due on").describe("The due date (RFC 3339)."),
                "create",
                "update",
            ),
            _only(
                formkit.enum_("state", "State", "", "open", "closed")
                .default("")
                .describe("Open or close the milestone."),
                "create",
                "update",
            ),
            _only(
                formkit.enum_("stateFilter", "State", "open", "closed", "all").default("open"),
                "list",
            ),
            _only(
                formkit.enum_("sort", "Sort by", "", "due_on", "completeness").default(""),
                "list",
            ),
            _only(_direction(), "list"),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


# ----------------------------------------------------------- pull requests --


def pulls_form() -> FormBuilder:
    """`github.pulls` — the pull request list, one PR, or its merge state."""
    return (
        formkit.form("Pull requests")
        .add(
            _op(
                Option("list", "List pull requests"),
                Option("get", "Get one pull request"),
                Option("for_commit", "Pull requests for a commit"),
                Option("merged", "Is it merged?"),
            ),
            _repo("github.pulls"),
            _only(_pull_number(), "get", "merged"),
            _only(formkit.text("commitSha", "Commit SHA"), "for_commit"),
            _only(formkit.enum_("state", "State", "open", "closed", "all").default("open"), "list"),
            _only(
                formkit.text("head", "Head").describe("Filter by head branch, as user:branch."),
                "list",
            ),
            _only(formkit.text("base", "Base").describe("Filter by base branch name."), "list"),
            _only(
                formkit.enum_("sort", "Sort by", "", "created", "updated", "popularity", "long-running").default(""),
                "list",
            ),
            _only(_direction(), "list"),
            _only(_per_page(), "list", "for_commit"),
            _only(_page(), "list", "for_commit"),
        )
        .build()
    )


def pull_write_form() -> FormBuilder:
    """`github.pull.write` — open, edit, update or merge a pull request."""
    return (
        formkit.form("Create / update a pull request")
        .add(
            _op(
                Option("create", "Create a pull request"),
                Option("update", "Update a pull request"),
                Option("update_branch", "Update its branch from base"),
                Option("merge", "Merge it"),
            ),
            _repo("github.pull.write"),
            _only(_pull_number(), "update", "update_branch", "merge"),
            _only(formkit.text("title", "Title"), "create", "update"),
            _only(formkit.text_area("body", "Body").describe("Markdown. Accepts {{$.path}} tokens."), "create", "update"),
            _only(formkit.text("head", "Head branch").describe("The branch with the changes."), "create"),
            _only(
                formkit.text("base", "Base branch").describe(
                    "The branch to merge into — and, when updating, the new base."
                ),
                "create",
                "update",
            ),
            _only(_tri("draft", "Draft", "Whether the pull request is a draft."), "create"),
            _only(
                _tri("maintainerCanModify", "Maintainers can modify", "Whether maintainers may push to the head branch."),
                "create",
                "update",
            ),
            _only(
                formkit.enum_("state", "State", "", "open", "closed")
                .default("")
                .describe("Close or reopen the pull request."),
                "update",
            ),
            _only(
                formkit.text("expectedHeadSha", "Expected head SHA").describe(
                    "Refuse the branch update unless the head still matches this SHA."
                ),
                "update_branch",
            ),
            _only(formkit.text("commitTitle", "Merge commit title"), "merge"),
            _only(formkit.text_area("commitMessage", "Merge commit message"), "merge"),
            _only(
                formkit.text("sha", "Expected head SHA").describe(
                    "Refuse the merge unless the head still matches this SHA."
                ),
                "merge",
            ),
            _only(
                formkit.enum_("mergeMethod", "Merge method", "", "merge", "squash", "rebase").default(""),
                "merge",
            ),
        )
        .build()
    )


def pull_changes_form() -> FormBuilder:
    """`github.pull.changes` — a pull request's files or commits."""
    return (
        formkit.form("Pull request changes")
        .add(
            _op(Option("files", "Changed files"), Option("commits", "Commits")),
            _repo("github.pull.changes"),
            _pull_number(),
            _per_page(),
            _page(),
        )
        .build()
    )


def pull_reviewers_form() -> FormBuilder:
    """`github.pull.reviewers` — who is asked to review a pull request."""
    return (
        formkit.form("Pull request reviewers")
        .add(
            _op(
                Option("list", "List requested reviewers"),
                Option("request", "Request reviewers"),
                Option("remove", "Remove requested reviewers"),
            ),
            _repo("github.pull.reviewers"),
            _pull_number(),
            _only(formkit.list_("reviewers", "Reviewers").describe("GitHub logins."), "request", "remove"),
            _only(
                formkit.list_("teamReviewers", "Team reviewers").describe("Team slugs within the organization."),
                "request",
                "remove",
            ),
        )
        .build()
    )


def pull_reviews_form() -> FormBuilder:
    """`github.pull.reviews` — the reviews on a pull request."""
    return (
        formkit.form("Pull request reviews")
        .add(
            _op(
                Option("list", "List reviews"),
                Option("get", "Get one review"),
                Option("create", "Create a review"),
                Option("submit", "Submit a pending review"),
                Option("dismiss", "Dismiss a review"),
                Option("delete_pending", "Delete a pending review"),
            ),
            _repo("github.pull.reviews"),
            _pull_number(),
            _only(
                _number("reviewId", "Review ID", "The review, as GitHub reports it."),
                "get",
                "submit",
                "dismiss",
                "delete_pending",
            ),
            _only(formkit.text_area("body", "Body").describe("The review's summary comment."), "create", "submit"),
            _only(
                formkit.enum_("event", "Event", "", "APPROVE", "REQUEST_CHANGES", "COMMENT")
                .default("")
                .describe("Empty on create leaves the review PENDING, to submit later."),
                "create",
                "submit",
            ),
            _only(
                formkit.text("commitId", "Commit SHA").describe("The commit the review applies to."),
                "create",
            ),
            _only(
                formkit.text_area("comments", "Inline comments (JSON)").describe(
                    'A JSON array of inline comments, e.g. [{"path": "main.go", "body": "…", "line": 12}].'
                ),
                "create",
            ),
            _only(formkit.text("message", "Dismissal message").describe("Why the review is dismissed."), "dismiss"),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def pull_review_comments_form() -> FormBuilder:
    """`github.pull.review_comments` — the inline comments on a diff."""
    return (
        formkit.form("Review comments")
        .add(
            _op(
                Option("list", "List review comments"),
                Option("create", "Comment on a line"),
                Option("reply", "Reply to a comment"),
                Option("update", "Edit a comment"),
                Option("delete", "Delete a comment"),
            ),
            _repo("github.pull.review_comments"),
            _only(_pull_number(), "list", "create", "reply"),
            _only(_comment_id(), "reply", "update", "delete"),
            _only(formkit.text_area("body", "Comment"), "create", "reply", "update"),
            _only(formkit.text("commitId", "Commit SHA").describe("The commit whose diff is commented on."), "create"),
            _only(formkit.text("path", "Path").describe("The file to comment on."), "create"),
            _only(_number("line", "Line", "The line in the file's diff."), "create"),
            _only(
                formkit.enum_("side", "Side", "", "LEFT", "RIGHT")
                .default("")
                .describe("RIGHT is the new version, LEFT the old one."),
                "create",
            ),
            _only(_number("startLine", "Start line", "For a multi-line comment, where it starts."), "create"),
            _only(formkit.enum_("startSide", "Start side", "", "LEFT", "RIGHT").default(""), "create"),
            _only(formkit.enum_("sort", "Sort by", "", "created", "updated").default(""), "list"),
            _only(_direction(), "list"),
            _only(
                formkit.date_time("since", "Since").describe("Only comments after this instant (RFC 3339)."),
                "list",
            ),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


# ---------------------------------------------------------------- releases --


def releases_form() -> FormBuilder:
    """`github.releases` — the repository's releases and their notes."""
    return (
        formkit.form("Releases")
        .add(
            _op(
                Option("list", "List releases"),
                Option("latest", "The latest release"),
                Option("get", "Get one release by ID"),
                Option("by_tag", "Get one release by tag"),
                Option("create", "Create a release"),
                Option("update", "Update a release"),
                Option("delete", "Delete a release"),
                Option("notes", "Generate release notes"),
            ),
            _repo("github.releases"),
            _only(_release_id(), "get", "update", "delete"),
            _only(formkit.text("tag", "Tag").describe("The tag name to look up."), "by_tag"),
            _only(
                formkit.text("tagName", "Tag name").describe("The tag the release points at."),
                "create",
                "update",
                "notes",
            ),
            _only(
                formkit.text("targetCommitish", "Target").describe(
                    "The branch or commit the tag is created from. Empty uses the default branch."
                ),
                "create",
                "update",
                "notes",
            ),
            _only(formkit.text("name", "Title"), "create", "update"),
            _only(formkit.text_area("body", "Notes").describe("Markdown. Accepts {{$.path}} tokens."), "create", "update"),
            _only(_tri("draft", "Draft", "Whether the release is a draft."), "create", "update"),
            _only(_tri("prerelease", "Pre-release", "Whether the release is a pre-release."), "create", "update"),
            _only(
                formkit.boolean("generateReleaseNotes", "Generate notes")
                .default(False)
                .describe("Let GitHub write the notes from merged pull requests."),
                "create",
            ),
            _only(
                formkit.enum_("makeLatest", "Mark latest", "", "true", "false", "legacy").default(""),
                "create",
                "update",
            ),
            _only(
                formkit.text("previousTagName", "Previous tag").describe(
                    "Where the generated notes start. Empty lets GitHub choose."
                ),
                "notes",
            ),
            _only(
                formkit.text("configurationFilePath", "Config path").describe(
                    "A release-notes configuration file in the repository."
                ),
                "notes",
            ),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


def release_assets_form() -> FormBuilder:
    """`github.release.assets` — the files attached to a release."""
    return (
        formkit.form("Release assets")
        .describe(
            "Uploading an asset goes to a separate GitHub upload host, which oomol does not "
            "curate — use the Raw GitHub request action for that."
        )
        .add(
            _op(
                Option("list", "List a release's assets"),
                Option("get", "Get one asset"),
                Option("delete", "Delete an asset"),
            ),
            _repo("github.release.assets"),
            _only(_release_id(), "list"),
            _only(_number("assetId", "Asset ID", "The release asset, as GitHub reports it."), "get", "delete"),
            _only(_per_page(), "list"),
            _only(_page(), "list"),
        )
        .build()
    )


# ------------------------------------------------------------------ search --


def search_form() -> FormBuilder:
    """`github.search` — every curated GitHub search, each with its own sort."""
    return (
        formkit.form("Search GitHub")
        .add(
            _op(
                Option("repositories", "Repositories"),
                Option("code", "Code"),
                Option("issues", "Issues & PRs"),
                Option("users", "Users"),
                Option("commits", "Commits"),
                Option("topics", "Topics"),
            ),
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
            _only(
                formkit.enum_("repoSort", "Sort by", "", "stars", "forks", "help-wanted-issues", "updated").default(""),
                "repositories",
            ),
            _only(formkit.enum_("codeSort", "Sort by", "", "indexed", "updated").default(""), "code"),
            _only(
                formkit.enum_(
                    "issueSort", "Sort by", "", "comments", "reactions", "interactions", "created", "updated"
                ).default(""),
                "issues",
            ),
            _only(
                formkit.enum_("userSort", "Sort by", "", "followers", "repositories", "joined").default(""),
                "users",
            ),
            _only(
                formkit.enum_("commitSort", "Sort by", "", "author-date", "committer-date").default(""),
                "commits",
            ),
            _only(formkit.enum_("type", "Type", "", "issue", "pr").default(""), "issues"),
            _only(formkit.enum_("state", "State", "", "open", "closed", "all").default(""), "issues"),
            _only(formkit.text("label", "Label"), "issues"),
            _only(formkit.text("author", "Author"), "issues"),
            _only(formkit.text("assignee", "Assignee"), "issues"),
            _only(formkit.text("mentions", "Mentions"), "issues"),
            _only(formkit.text("language", "Language"), "issues"),
            _only(formkit.boolean("isMerged", "Merged only").default(False), "issues"),
            _only(_order(), "repositories", "code", "issues", "users", "commits"),
            _per_page(),
            _page(),
        )
        .build()
    )


# ---------------------------------------------- provider-proxy (security) --
#
# What follows is NOT curated by oomol: these go through the provider proxy as
# exact GitHub REST paths. See actions.py.


def repo_protection_form() -> FormBuilder:
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


def alerts_dependabot_form() -> FormBuilder:
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


def alerts_secret_scanning_form() -> FormBuilder:
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


def alerts_code_scanning_form() -> FormBuilder:
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


def org_members_form() -> FormBuilder:
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


def repo_settings_form() -> FormBuilder:
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


def request_form() -> FormBuilder:
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


# Every action's form, by the canvas action it belongs to. registry.py builds the
# canvas from it, meta.py rebuilds a dialog from it when a picker fires, and the
# form tests walk it.
ACTION_FORMS = {
    "github.user.get": user_get_form,
    "github.events": events_form,
    "github.repos.list": repos_list_form,
    "github.repo.get": repo_get_form,
    "github.repo.create": repo_create_form,
    "github.repo.update": repo_update_form,
    "github.repo.delete": repo_delete_form,
    "github.repo.fork": repo_fork_form,
    "github.repo.insights": repo_insights_form,
    "github.repo.topics": repo_topics_form,
    "github.repo.stars": repo_stars_form,
    "github.repo.collaborators": repo_collaborators_form,
    "github.repo.access": repo_access_form,
    "github.repo.contents": repo_contents_form,
    "github.repo.file": repo_file_form,
    "github.branches": branches_form,
    "github.branch.update": branch_update_form,
    "github.refs": refs_form,
    "github.activity.list": activity_list_form,
    "github.commit.get": commit_get_form,
    "github.commit.comments": commit_comments_form,
    "github.commit.status": commit_status_form,
    "github.checks": checks_form,
    "github.workflows": workflows_form,
    "github.workflow.runs": workflow_runs_form,
    "github.workflow.jobs": workflow_jobs_form,
    "github.workflow.artifacts": workflow_artifacts_form,
    "github.issues": issues_form,
    "github.issue.write": issue_write_form,
    "github.issue.labels": issue_labels_form,
    "github.issue.assignees": issue_assignees_form,
    "github.issue.comments": issue_comments_form,
    "github.issue.reactions": issue_reactions_form,
    "github.issue.events": issue_events_form,
    "github.labels": labels_form,
    "github.milestones": milestones_form,
    "github.pulls": pulls_form,
    "github.pull.write": pull_write_form,
    "github.pull.changes": pull_changes_form,
    "github.pull.reviewers": pull_reviewers_form,
    "github.pull.reviews": pull_reviews_form,
    "github.pull.review_comments": pull_review_comments_form,
    "github.releases": releases_form,
    "github.release.assets": release_assets_form,
    "github.search": search_form,
    "github.repo.protection": repo_protection_form,
    "github.alerts.dependabot": alerts_dependabot_form,
    "github.alerts.secret_scanning": alerts_secret_scanning_form,
    "github.alerts.code_scanning": alerts_code_scanning_form,
    "github.org.members": org_members_form,
    "github.repo.settings": repo_settings_form,
    "github.request": request_form,
}
