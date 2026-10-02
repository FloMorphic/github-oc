# What each node action runs on OpenConnector, declared once.
#
# oomol curates ~150 GitHub actions (GET /v1/actions?service=github). Every one
# of them is reached from this table: a canvas action is a SURFACE (issues,
# releases, refs …) whose form carries an `op` choice, and each op names the
# curated action it runs plus the form fields that become its input.
#
# WHY A TABLE. oomol declares every curated input with additionalProperties:false
# and camelCase names (perPage, issueNumber, pullNumber …), so a guessed field is
# a hard 400 and a hand-written handler per action would be ~150 near-identical
# functions. Declaring the mapping instead keeps the action names, the required
# inputs and the camelCase spelling in one readable place that a test can check
# against the catalog itself (tests/test_ops.py).
#
# A field entry is "formField" when the form already uses oomol's own name, or
# "formField:curatedName" when the form must name it differently — because two
# ops of the same surface take the same curated key with different meanings (a
# `state` FILTER of open/closed/all versus a `state` to SET of open/closed), or a
# different vocabulary (`refs/heads/x` for create_ref, `heads/x` for get_ref).
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# Where an op's owner / repo come from. The organization is a property of the
# connection (see forms.py), so no form asks for it:
#   "repo"  — {owner, repo}: the profile's org plus the form's repository
#   "owner" — {owner}: the profile's org alone
#   "org"   — {org}: the profile's org, under oomol's `org` key
#   "none"  — neither; the action is account-wide or takes its own target
SCOPES = ("repo", "owner", "org", "none")


@dataclass(frozen=True)
class Op:
    """One curated OpenConnector action, as one choice on a node's form."""

    action: str
    scope: str = "repo"
    # Form fields this op sends, as "name" or "formName:curatedName".
    fields: tuple[str, ...] = ()
    # Form fields that must be filled, refused before the gateway is called.
    needs: tuple[str, ...] = ()
    # Form fields whose text is parsed as JSON before it is sent.
    json: tuple[str, ...] = ()
    # Form fields that are three-state strings ("", "true", "false"), so an
    # untouched toggle is omitted rather than sent as false and flipping a
    # setting off. Everything oomol declares as a boolean and this does not name
    # is a real checkbox whose false is harmless (a filter, not a setting).
    bools: tuple[str, ...] = ()

    def verb(self) -> str:
        """The action phrased for the under-scoped-account error ("create issue")."""
        return self.action.replace("_", " ")

    def title(self) -> str:
        """The action phrased for the progress frame ("Create issue")."""
        verb = self.verb()
        return verb[:1].upper() + verb[1:]


@dataclass(frozen=True)
class Table:
    """The ops one canvas action offers, and the one its form defaults to."""

    default: str
    ops: Mapping[str, Op] = field(default_factory=dict)

    def names(self) -> tuple[str, ...]:
        return tuple(self.ops)


# Field groups repeated across surfaces.
_PAGING = ("perPage", "page")


# ------------------------------------------------------------------ account --

USER = Table(
    "me",
    {
        "me": Op("get_current_user", scope="none"),
        "user": Op("get_user", scope="none", fields=("username",), needs=("username",)),
    },
)

EVENTS = Table(
    "repository",
    {
        "repository": Op("list_repository_events", fields=_PAGING),
        "public": Op("list_public_events", scope="none", fields=_PAGING),
        "user_public": Op(
            "list_user_public_events", scope="none", fields=("username",) + _PAGING, needs=("username",)
        ),
        "user_received_public": Op(
            "list_user_received_public_events",
            scope="none",
            fields=("username",) + _PAGING,
            needs=("username",),
        ),
        "user_all": Op(
            "list_authenticated_user_events",
            scope="none",
            fields=("username",) + _PAGING,
            needs=("username",),
        ),
        "user_received": Op(
            "list_authenticated_user_received_events",
            scope="none",
            fields=("username",) + _PAGING,
            needs=("username",),
        ),
    },
)


# ----------------------------------------------------------- repositories --

REPOS_LIST = Table(
    "org",
    {
        # The organization's. oomol takes the org under `org`, not `owner`.
        "org": Op(
            "list_organization_repositories",
            scope="org",
            fields=("orgType:type", "sort", "direction") + _PAGING,
        ),
        "mine": Op(
            "list_my_repositories",
            scope="none",
            fields=("visibility", "sort", "direction") + _PAGING,
        ),
        "user": Op(
            "list_user_repositories",
            scope="none",
            fields=("username", "userType:type", "sort", "direction") + _PAGING,
            needs=("username",),
        ),
    },
)

REPO_GET = Table("get", {"get": Op("get_repository")})

REPO_CREATE = Table(
    "create",
    {
        "create": Op(
            "create_repository",
            scope="none",
            fields=(
                "name",
                "description",
                "homepage",
                "private",
                "autoInit",
                "hasIssues",
                "hasProjects",
                "hasWiki",
                "hasDiscussions",
                "gitignoreTemplate",
                "licenseTemplate",
            ),
            needs=("name",),
            bools=("hasIssues", "hasProjects", "hasWiki", "hasDiscussions"),
        )
    },
)

REPO_UPDATE = Table(
    "update",
    {
        "update": Op(
            "update_repository",
            fields=(
                "name",
                "description",
                "homepage",
                "visibility",
                "defaultBranch",
                "private",
                "hasIssues",
                "hasProjects",
                "hasWiki",
                "hasDiscussions",
                "allowSquashMerge",
                "allowMergeCommit",
                "allowRebaseMerge",
                "allowAutoMerge",
                "deleteBranchOnMerge",
                "archived",
            ),
            # Every toggle is three-state: an untouched one must not turn a
            # repository setting off.
            bools=(
                "private",
                "hasIssues",
                "hasProjects",
                "hasWiki",
                "hasDiscussions",
                "allowSquashMerge",
                "allowMergeCommit",
                "allowRebaseMerge",
                "allowAutoMerge",
                "deleteBranchOnMerge",
                "archived",
            ),
        )
    },
)

REPO_DELETE = Table("delete", {"delete": Op("delete_repository")})

REPO_FORK = Table(
    "fork",
    {"fork": Op("fork_repository", fields=("organization", "name", "defaultBranchOnly"))},
)

REPO_INSIGHTS = Table(
    "tags",
    {
        "tags": Op("list_repository_tags", fields=_PAGING),
        "languages": Op("list_repository_languages"),
        "contributors": Op("list_repository_contributors", fields=("anon",) + _PAGING),
        "forks": Op("list_repository_forks", fields=("sort",) + _PAGING),
        "stargazers": Op("list_repository_stargazers", fields=_PAGING),
        "watchers": Op("list_repository_watchers", fields=_PAGING),
    },
)

REPO_TOPICS = Table(
    "list",
    {
        "list": Op("list_repository_topics", fields=_PAGING),
        "replace": Op("replace_repository_topics", fields=("names",), needs=("names",)),
    },
)

REPO_STARS = Table(
    "check",
    {
        "check": Op("check_repository_starred"),
        "star": Op("star_repository"),
        "unstar": Op("unstar_repository"),
        "mine": Op(
            "list_my_starred_repositories", scope="none", fields=("sort", "direction") + _PAGING
        ),
    },
)

REPO_COLLABORATORS = Table(
    "list",
    {
        "list": Op(
            "list_repository_collaborators", fields=("affiliation", "permission") + _PAGING
        )
    },
)

REPO_ACCESS = Table(
    "permission",
    {
        "permission": Op(
            "get_repository_permission_for_user", fields=("username",), needs=("username",)
        ),
        "add": Op(
            "add_repository_collaborator",
            fields=("username", "permission"),
            needs=("username",),
        ),
        "remove": Op(
            "remove_repository_collaborator", fields=("username",), needs=("username",)
        ),
    },
)


# --------------------------------------------------------------- contents --

REPO_CONTENTS = Table(
    "file",
    {
        "file": Op("get_file_contents", fields=("path", "ref"), needs=("path",)),
        "dir": Op("list_directory_contents", fields=("path", "ref")),
        "readme": Op("get_repository_readme", fields=("ref",)),
    },
)

REPO_FILE = Table(
    "save",
    {
        "save": Op(
            "create_or_update_file",
            fields=("path", "message", "content", "contentBase64", "sha", "branch"),
            needs=("path", "message"),
        ),
        "delete": Op(
            "delete_file",
            fields=("path", "message", "sha", "branch"),
            needs=("path", "message", "sha"),
        ),
    },
)


# --------------------------------------------------------- branches & refs --

BRANCHES = Table(
    "list",
    {
        "list": Op("list_branches", fields=("protectedOnly",) + _PAGING),
        "get": Op("get_branch", fields=("branch",), needs=("branch",)),
    },
)

BRANCH_UPDATE = Table(
    "merge",
    {
        "merge": Op(
            "merge_branch", fields=("base", "head", "commitMessage"), needs=("base", "head")
        ),
        "rename": Op("rename_branch", fields=("branch", "newName"), needs=("branch", "newName")),
        "sync": Op("sync_fork_branch_with_upstream", fields=("branch",), needs=("branch",)),
    },
)

REFS = Table(
    "get",
    {
        # get / update / delete speak `heads/main`; create_ref speaks the fully
        # qualified `refs/heads/main`, so the form keeps the two apart.
        "get": Op("get_ref", fields=("ref",), needs=("ref",)),
        "matching": Op("list_matching_refs", fields=("ref",), needs=("ref",)),
        "create": Op("create_ref", fields=("fullRef:ref", "sha"), needs=("fullRef", "sha")),
        "update": Op("update_ref", fields=("ref", "sha", "force"), needs=("ref", "sha")),
        "delete": Op("delete_ref", fields=("ref",), needs=("ref",)),
    },
)


# ---------------------------------------------------------------- commits --

ACTIVITY_LIST = Table(
    "commits",
    {
        "commits": Op(
            "list_commits",
            fields=("sha", "path", "author", "committer", "since", "until") + _PAGING,
        ),
        "workflow_runs": Op(
            "list_workflow_runs",
            fields=("branch", "actor", "event", "status", "headSha", "created", "excludePullRequests")
            + _PAGING,
        ),
    },
)

COMMIT_GET = Table(
    "get",
    {
        "get": Op("get_commit", fields=("ref",), needs=("ref",)),
        "compare": Op("compare_commits", fields=("basehead",) + _PAGING, needs=("basehead",)),
    },
)

COMMIT_COMMENTS = Table(
    "list",
    {
        "list": Op("list_commit_comments", fields=("commitSha",) + _PAGING, needs=("commitSha",)),
        "create": Op(
            "create_commit_comment",
            fields=("commitSha", "body", "path", "position"),
            needs=("commitSha", "body"),
        ),
    },
)

COMMIT_STATUS = Table(
    "list",
    {
        "list": Op("get_commit_statuses", fields=("ref",) + _PAGING, needs=("ref",)),
        "create": Op(
            "create_commit_status",
            fields=("sha", "state", "context", "targetUrl", "description"),
            needs=("sha", "state"),
        ),
    },
)

CHECKS = Table(
    "runs",
    {
        "runs": Op(
            "list_check_runs_for_ref",
            fields=("ref", "checkName", "appId", "filter", "status") + _PAGING,
            needs=("ref",),
        ),
        "rerequest_run": Op("rerequest_check_run", fields=("checkRunId",), needs=("checkRunId",)),
        "rerequest_suite": Op(
            "rerequest_check_suite", fields=("checkSuiteId",), needs=("checkSuiteId",)
        ),
    },
)


# --------------------------------------------------------------- workflows --

WORKFLOWS = Table(
    "list",
    {
        "list": Op("list_repository_workflows", fields=_PAGING),
        "get": Op("get_workflow", fields=("workflowId",), needs=("workflowId",)),
        "dispatch": Op(
            "dispatch_workflow",
            fields=("workflowId", "ref", "inputs"),
            needs=("workflowId", "ref"),
            json=("inputs",),
        ),
        "enable": Op("enable_workflow", fields=("workflowId",), needs=("workflowId",)),
        "disable": Op("disable_workflow", fields=("workflowId",), needs=("workflowId",)),
    },
)

WORKFLOW_RUNS = Table(
    "get",
    {
        "get": Op("get_workflow_run", fields=("runId",), needs=("runId",)),
        "cancel": Op("cancel_workflow_run", fields=("runId",), needs=("runId",)),
        "rerun": Op("rerun_workflow", fields=("runId", "enableDebugLogging"), needs=("runId",)),
        "rerun_failed": Op(
            "rerun_failed_jobs", fields=("runId", "enableDebugLogging"), needs=("runId",)
        ),
    },
)

WORKFLOW_JOBS = Table(
    "list",
    {
        "list": Op("list_workflow_run_jobs", fields=("runId", "filter") + _PAGING, needs=("runId",)),
        "logs": Op("get_workflow_job_logs", fields=("jobId",), needs=("jobId",)),
    },
)

WORKFLOW_ARTIFACTS = Table(
    "list",
    {
        "list": Op(
            "list_workflow_run_artifacts", fields=("runId", "name") + _PAGING, needs=("runId",)
        ),
        "download": Op(
            "download_workflow_artifact",
            fields=("artifactId", "fileName"),
            needs=("artifactId",),
        ),
    },
)


# ------------------------------------------------------------------ issues --

ISSUES = Table(
    "list",
    {
        "list": Op(
            "list_repository_issues",
            fields=("state", "labels", "sort", "direction", "since") + _PAGING,
        ),
        "get": Op("get_issue", fields=("issueNumber",), needs=("issueNumber",)),
    },
)

ISSUE_WRITE = Table(
    "create",
    {
        "create": Op(
            "create_issue",
            fields=("title", "body", "assignees", "labels", "milestone"),
            needs=("title",),
        ),
        "update": Op(
            "update_issue",
            fields=("issueNumber", "title", "body", "state", "assignees", "labels", "milestone"),
            needs=("issueNumber",),
        ),
        "lock": Op("lock_issue", fields=("issueNumber", "lockReason"), needs=("issueNumber",)),
        "unlock": Op("unlock_issue", fields=("issueNumber",), needs=("issueNumber",)),
    },
)

ISSUE_LABELS = Table(
    "list",
    {
        "list": Op("list_issue_labels", fields=("issueNumber",) + _PAGING, needs=("issueNumber",)),
        "add": Op(
            "add_issue_labels", fields=("issueNumber", "labels"), needs=("issueNumber", "labels")
        ),
        "set": Op(
            "set_issue_labels", fields=("issueNumber", "labels"), needs=("issueNumber", "labels")
        ),
        "remove": Op(
            "remove_issue_label", fields=("issueNumber", "label"), needs=("issueNumber", "label")
        ),
        "clear": Op("clear_issue_labels", fields=("issueNumber",), needs=("issueNumber",)),
    },
)

ISSUE_ASSIGNEES = Table(
    "available",
    {
        "available": Op("list_assignees", fields=_PAGING),
        "add": Op(
            "add_issue_assignees",
            fields=("issueNumber", "assignees"),
            needs=("issueNumber", "assignees"),
        ),
        "remove": Op(
            "remove_issue_assignees",
            fields=("issueNumber", "assignees"),
            needs=("issueNumber", "assignees"),
        ),
    },
)

ISSUE_COMMENTS = Table(
    "list",
    {
        "list": Op(
            "list_issue_comments", fields=("issueNumber",) + _PAGING, needs=("issueNumber",)
        ),
        "get": Op("get_issue_comment", fields=("commentId",), needs=("commentId",)),
        "create": Op(
            "create_issue_comment", fields=("issueNumber", "body"), needs=("issueNumber", "body")
        ),
        "update": Op(
            "update_issue_comment", fields=("commentId", "body"), needs=("commentId", "body")
        ),
        "delete": Op("delete_issue_comment", fields=("commentId",), needs=("commentId",)),
    },
)

ISSUE_REACTIONS = Table(
    "issue",
    {
        "issue": Op(
            "create_issue_reaction",
            fields=("issueNumber", "content"),
            needs=("issueNumber", "content"),
        ),
        "comment": Op(
            "create_issue_comment_reaction",
            fields=("commentId", "content"),
            needs=("commentId", "content"),
        ),
    },
)

ISSUE_EVENTS = Table(
    "timeline",
    {
        "timeline": Op(
            "list_issue_timeline_events", fields=("issueNumber",) + _PAGING, needs=("issueNumber",)
        ),
        "issue": Op(
            "list_issue_events", fields=("issueNumber",) + _PAGING, needs=("issueNumber",)
        ),
        "repository": Op("list_repository_issue_events", fields=_PAGING),
    },
)

LABELS = Table(
    "list",
    {
        "list": Op("list_repository_labels", fields=_PAGING),
        "get": Op("get_label", fields=("name",), needs=("name",)),
        "create": Op(
            "create_label", fields=("name", "color", "description"), needs=("name", "color")
        ),
        "update": Op(
            "update_label", fields=("name", "newName", "color", "description"), needs=("name",)
        ),
        "delete": Op("delete_label", fields=("name",), needs=("name",)),
        # oomol's label search takes a repository ID, not owner/repo.
        "search": Op(
            "search_labels",
            scope="none",
            fields=("repositoryId", "query", "sort", "order") + _PAGING,
            needs=("repositoryId", "query"),
        ),
    },
)

MILESTONES = Table(
    "list",
    {
        "list": Op(
            "list_milestones", fields=("stateFilter:state", "sort", "direction") + _PAGING
        ),
        "get": Op("get_milestone", fields=("milestoneNumber",), needs=("milestoneNumber",)),
        "create": Op(
            "create_milestone", fields=("title", "description", "dueOn", "state"), needs=("title",)
        ),
        "update": Op(
            "update_milestone",
            fields=("milestoneNumber", "title", "description", "dueOn", "state"),
            needs=("milestoneNumber",),
        ),
        "delete": Op(
            "delete_milestone", fields=("milestoneNumber",), needs=("milestoneNumber",)
        ),
    },
)


# ----------------------------------------------------------- pull requests --

PULLS = Table(
    "list",
    {
        "list": Op(
            "list_pull_requests", fields=("state", "head", "base", "sort", "direction") + _PAGING
        ),
        "get": Op("get_pull_request", fields=("pullNumber",), needs=("pullNumber",)),
        "for_commit": Op(
            "list_pull_requests_associated_with_commit",
            fields=("commitSha",) + _PAGING,
            needs=("commitSha",),
        ),
        "merged": Op("check_pull_request_merged", fields=("pullNumber",), needs=("pullNumber",)),
    },
)

PULL_WRITE = Table(
    "create",
    {
        "create": Op(
            "create_pull_request",
            fields=("title", "head", "base", "body", "draft", "maintainerCanModify"),
            needs=("title", "head", "base"),
            bools=("draft", "maintainerCanModify"),
        ),
        "update": Op(
            "update_pull_request",
            fields=("pullNumber", "title", "body", "state", "base", "maintainerCanModify"),
            needs=("pullNumber",),
            bools=("maintainerCanModify",),
        ),
        "update_branch": Op(
            "update_pull_request_branch",
            fields=("pullNumber", "expectedHeadSha"),
            needs=("pullNumber",),
        ),
        "merge": Op(
            "merge_pull_request",
            fields=("pullNumber", "commitTitle", "commitMessage", "sha", "mergeMethod"),
            needs=("pullNumber",),
        ),
    },
)

PULL_CHANGES = Table(
    "files",
    {
        "files": Op(
            "list_pull_request_files", fields=("pullNumber",) + _PAGING, needs=("pullNumber",)
        ),
        "commits": Op(
            "list_pull_request_commits", fields=("pullNumber",) + _PAGING, needs=("pullNumber",)
        ),
    },
)

PULL_REVIEWERS = Table(
    "list",
    {
        "list": Op(
            "list_pull_request_requested_reviewers",
            fields=("pullNumber",),
            needs=("pullNumber",),
        ),
        "request": Op(
            "request_pull_request_reviewers",
            fields=("pullNumber", "reviewers", "teamReviewers"),
            needs=("pullNumber",),
        ),
        "remove": Op(
            "remove_pull_request_reviewers",
            fields=("pullNumber", "reviewers", "teamReviewers"),
            needs=("pullNumber",),
        ),
    },
)

PULL_REVIEWS = Table(
    "list",
    {
        "list": Op(
            "list_pull_request_reviews", fields=("pullNumber",) + _PAGING, needs=("pullNumber",)
        ),
        "get": Op(
            "get_pull_request_review",
            fields=("pullNumber", "reviewId"),
            needs=("pullNumber", "reviewId"),
        ),
        "create": Op(
            "create_pull_request_review",
            fields=("pullNumber", "body", "event", "commitId", "comments"),
            needs=("pullNumber",),
            json=("comments",),
        ),
        "submit": Op(
            "submit_pull_request_review",
            fields=("pullNumber", "reviewId", "event", "body"),
            needs=("pullNumber", "reviewId", "event"),
        ),
        "dismiss": Op(
            "dismiss_pull_request_review",
            fields=("pullNumber", "reviewId", "message"),
            needs=("pullNumber", "reviewId", "message"),
        ),
        "delete_pending": Op(
            "delete_pending_pull_request_review",
            fields=("pullNumber", "reviewId"),
            needs=("pullNumber", "reviewId"),
        ),
    },
)

PULL_REVIEW_COMMENTS = Table(
    "list",
    {
        "list": Op(
            "list_pull_request_review_comments",
            fields=("pullNumber", "sort", "direction", "since") + _PAGING,
            needs=("pullNumber",),
        ),
        "create": Op(
            "create_pull_request_review_comment",
            fields=("pullNumber", "body", "commitId", "path", "line", "side", "startLine", "startSide"),
            needs=("pullNumber", "body", "commitId", "path"),
        ),
        "reply": Op(
            "reply_pull_request_review_comment",
            fields=("pullNumber", "commentId", "body"),
            needs=("pullNumber", "commentId", "body"),
        ),
        "update": Op(
            "update_pull_request_review_comment",
            fields=("commentId", "body"),
            needs=("commentId", "body"),
        ),
        "delete": Op(
            "delete_pull_request_review_comment", fields=("commentId",), needs=("commentId",)
        ),
    },
)


# ---------------------------------------------------------------- releases --

RELEASES = Table(
    "list",
    {
        "list": Op("list_releases", fields=_PAGING),
        "latest": Op("get_latest_release"),
        "get": Op("get_release", fields=("releaseId",), needs=("releaseId",)),
        "by_tag": Op("get_release_by_tag", fields=("tag",), needs=("tag",)),
        "create": Op(
            "create_release",
            fields=(
                "tagName",
                "targetCommitish",
                "name",
                "body",
                "draft",
                "prerelease",
                "generateReleaseNotes",
                "makeLatest",
            ),
            needs=("tagName",),
            bools=("draft", "prerelease"),
        ),
        "update": Op(
            "update_release",
            fields=(
                "releaseId",
                "tagName",
                "targetCommitish",
                "name",
                "body",
                "draft",
                "prerelease",
                "makeLatest",
            ),
            needs=("releaseId",),
            bools=("draft", "prerelease"),
        ),
        "delete": Op("delete_release", fields=("releaseId",), needs=("releaseId",)),
        "notes": Op(
            "generate_release_notes",
            fields=("tagName", "targetCommitish", "previousTagName", "configurationFilePath"),
            needs=("tagName",),
        ),
    },
)

RELEASE_ASSETS = Table(
    "list",
    {
        "list": Op("list_release_assets", fields=("releaseId",) + _PAGING, needs=("releaseId",)),
        "get": Op("get_release_asset", fields=("assetId",), needs=("assetId",)),
        "delete": Op("delete_release_asset", fields=("assetId",), needs=("assetId",)),
    },
)


# ------------------------------------------------------------------ search --

# The query itself is built by the handler (it prefixes org: when asked), so no
# op lists it. Each kind sorts by its own vocabulary, hence a sort field per kind.
SEARCH = Table(
    "repositories",
    {
        "repositories": Op(
            "search_repositories", scope="none", fields=("repoSort:sort", "order") + _PAGING
        ),
        "code": Op("search_code", scope="none", fields=("codeSort:sort", "order") + _PAGING),
        "issues": Op(
            "search_issues_and_pull_requests",
            scope="none",
            fields=("issueSort:sort", "order", "type", "state", "label", "author", "assignee", "mentions", "language", "isMerged")
            + _PAGING,
        ),
        "users": Op("search_users", scope="none", fields=("userSort:sort", "order") + _PAGING),
        "commits": Op(
            "search_commits", scope="none", fields=("commitSort:sort", "order") + _PAGING
        ),
        "topics": Op("search_topics", scope="none", fields=_PAGING),
    },
)


# Every table, by the canvas action it backs — the map registry.py and the
# catalog-coverage test walk.
TABLES: dict[str, Table] = {
    "github.user.get": USER,
    "github.events": EVENTS,
    "github.repos.list": REPOS_LIST,
    "github.repo.get": REPO_GET,
    "github.repo.create": REPO_CREATE,
    "github.repo.update": REPO_UPDATE,
    "github.repo.delete": REPO_DELETE,
    "github.repo.fork": REPO_FORK,
    "github.repo.insights": REPO_INSIGHTS,
    "github.repo.topics": REPO_TOPICS,
    "github.repo.stars": REPO_STARS,
    "github.repo.collaborators": REPO_COLLABORATORS,
    "github.repo.access": REPO_ACCESS,
    "github.repo.contents": REPO_CONTENTS,
    "github.repo.file": REPO_FILE,
    "github.branches": BRANCHES,
    "github.branch.update": BRANCH_UPDATE,
    "github.refs": REFS,
    "github.activity.list": ACTIVITY_LIST,
    "github.commit.get": COMMIT_GET,
    "github.commit.comments": COMMIT_COMMENTS,
    "github.commit.status": COMMIT_STATUS,
    "github.checks": CHECKS,
    "github.workflows": WORKFLOWS,
    "github.workflow.runs": WORKFLOW_RUNS,
    "github.workflow.jobs": WORKFLOW_JOBS,
    "github.workflow.artifacts": WORKFLOW_ARTIFACTS,
    "github.issues": ISSUES,
    "github.issue.write": ISSUE_WRITE,
    "github.issue.labels": ISSUE_LABELS,
    "github.issue.assignees": ISSUE_ASSIGNEES,
    "github.issue.comments": ISSUE_COMMENTS,
    "github.issue.reactions": ISSUE_REACTIONS,
    "github.issue.events": ISSUE_EVENTS,
    "github.labels": LABELS,
    "github.milestones": MILESTONES,
    "github.pulls": PULLS,
    "github.pull.write": PULL_WRITE,
    "github.pull.changes": PULL_CHANGES,
    "github.pull.reviewers": PULL_REVIEWERS,
    "github.pull.reviews": PULL_REVIEWS,
    "github.pull.review_comments": PULL_REVIEW_COMMENTS,
    "github.releases": RELEASES,
    "github.release.assets": RELEASE_ASSETS,
    "github.search": SEARCH,
}


def actions() -> set[str]:
    """Every curated OpenConnector action this plugin can run."""
    return {op.action for table in TABLES.values() for op in table.ops.values()}
