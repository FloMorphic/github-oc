# Wires the OpenConnector bridge onto the plugin's node actions, the settings
# meta RPCs, and the settings profile. One Client (over the plugin's NATS send)
# is shared by the action handlers and the meta handlers, so the account list,
# scope cache and proxy are consistent across both.
#
# A canvas action is named in exactly three places: here (its title, blurb and
# icon), in forms.py (its dialog) and in ops.py (the curated action each of its
# operations runs). The order of _CURATED, _PROXIED and _LOCAL is the order the
# canvas shows them in.
from __future__ import annotations

from inflow_plugin_sdk import Action, Icon, Meta as SdkMeta, Settings

from . import forms
from .actions import Actions
from .meta import Meta
from .oc import Client, Send

# The curated surfaces: method, title, blurb, icon. Each is served by the generic
# runner over its ops.py table (Actions.handler_for).
_CURATED: tuple[tuple[str, str, str, str], ...] = (
    # account & repositories
    ("github.user.get", "Get user", "The connected account's profile, or another user's.", "mdi-account"),
    ("github.repos.list", "List repositories", "Repositories of the organization, the account, or a user.", "mdi-source-repository-multiple"),
    ("github.repo.get", "Get repository", "One repository's full record.", "mdi-source-repository"),
    ("github.repo.create", "Create repository", "Create a repository for the connected account.", "mdi-source-repository-plus"),
    ("github.repo.update", "Update repository", "Rename, re-describe or re-configure a repository.", "mdi-cog-outline"),
    ("github.repo.delete", "Delete repository", "Delete a repository permanently.", "mdi-delete-forever"),
    ("github.repo.fork", "Fork repository", "Fork a repository to the account or an organization.", "mdi-source-fork"),
    ("github.repo.insights", "Repository insights", "Tags, languages, contributors, forks, stargazers, watchers.", "mdi-chart-box-outline"),
    ("github.repo.topics", "Repository topics", "Read the topics, or replace the whole set.", "mdi-tag-multiple"),
    ("github.repo.stars", "Stars", "Star or unstar a repository, or list the account's stars.", "mdi-star"),
    ("github.repo.collaborators", "List collaborators", "Who can push, and at what permission level.", "mdi-account-multiple"),
    ("github.repo.access", "Repository access", "Check, grant or revoke one user's access.", "mdi-account-key"),
    # contents
    ("github.repo.contents", "Get contents", "Read a file, a directory listing, or the README.", "mdi-file-document"),
    ("github.repo.file", "Write a file", "Commit a file, or commit its deletion.", "mdi-file-edit"),
    # branches, refs, commits
    ("github.branches", "Branches", "List a repository's branches, or get one.", "mdi-source-branch"),
    ("github.branch.update", "Update a branch", "Merge, rename, or sync a fork's branch.", "mdi-source-merge"),
    ("github.refs", "Git references", "Read, create, move or delete a ref behind a branch or tag.", "mdi-source-commit-start"),
    ("github.activity.list", "List activity", "Recent commits or workflow runs for a window.", "mdi-history"),
    ("github.commit.get", "Get / compare commits", "One commit, or a comparison between two refs.", "mdi-source-commit"),
    ("github.commit.comments", "Commit comments", "Read or write the comments on a commit.", "mdi-comment-text-outline"),
    ("github.commit.status", "Commit statuses", "Read the statuses on a ref, or post one.", "mdi-check-circle-outline"),
    ("github.checks", "Checks", "Check runs for a ref, and re-requesting them.", "mdi-checkbox-marked-circle-outline"),
    # workflows
    ("github.workflows", "Workflows", "List, get, dispatch, enable or disable a workflow.", "mdi-cogs"),
    ("github.workflow.runs", "Workflow runs", "Get, cancel or re-run one workflow run.", "mdi-play-circle-outline"),
    ("github.workflow.jobs", "Workflow jobs", "A run's jobs, and one job's logs.", "mdi-file-tree"),
    ("github.workflow.artifacts", "Workflow artifacts", "A run's artifacts, and downloading one.", "mdi-package-variant-closed"),
    # issues
    ("github.issues", "Issues", "The issue list, or one issue.", "mdi-alert-circle-outline"),
    ("github.issue.write", "Create / update an issue", "Open, edit, lock or unlock an issue.", "mdi-pencil-plus"),
    ("github.issue.labels", "Issue labels", "The labels on one issue.", "mdi-label-outline"),
    ("github.issue.assignees", "Issue assignees", "Who an issue is assigned to.", "mdi-account-arrow-right"),
    ("github.issue.comments", "Issue comments", "Comments on an issue or pull request.", "mdi-comment-multiple-outline"),
    ("github.issue.reactions", "Add a reaction", "React to an issue or to a comment.", "mdi-emoticon-outline"),
    ("github.issue.events", "Issue events", "What happened to an issue, or to all of them.", "mdi-timeline-text-outline"),
    ("github.labels", "Labels", "The repository's label definitions.", "mdi-label"),
    ("github.milestones", "Milestones", "The repository's milestones.", "mdi-flag-outline"),
    # pull requests
    ("github.pulls", "Pull requests", "The pull request list, one PR, or its merge state.", "mdi-source-pull"),
    ("github.pull.write", "Create / update a pull request", "Open, edit, update or merge a pull request.", "mdi-source-branch-plus"),
    ("github.pull.changes", "Pull request changes", "A pull request's files or commits.", "mdi-file-compare"),
    ("github.pull.reviewers", "Pull request reviewers", "Who is asked to review a pull request.", "mdi-account-eye"),
    ("github.pull.reviews", "Pull request reviews", "Create, submit, dismiss or read a review.", "mdi-clipboard-check-outline"),
    ("github.pull.review_comments", "Review comments", "The inline comments on a diff.", "mdi-comment-edit-outline"),
    # releases
    ("github.releases", "Releases", "The repository's releases and their notes.", "mdi-tag-check"),
    ("github.release.assets", "Release assets", "The files attached to a release.", "mdi-paperclip"),
    # search & activity feeds
    ("github.search", "Search GitHub", "Repositories, code, issues & PRs, users, commits or topics.", "mdi-magnify"),
    ("github.events", "List events", "The public and received event feeds GitHub exposes.", "mdi-rss"),
)

# The surfaces oomol does not curate: each has its own handler over the provider
# proxy. See the module comment in actions.py.
_PROXIED: tuple[tuple[str, str, str, str], ...] = (
    ("github.repo.protection", "Branch protection", "Branch protection and rulesets on a branch (via the GitHub proxy).", "mdi-shield-lock"),
    ("github.alerts.dependabot", "Dependabot alerts", "Vulnerable-dependency alerts, repo or org-wide (via the GitHub proxy).", "mdi-shield-bug"),
    ("github.alerts.secret_scanning", "Secret-scanning alerts", "Leaked-credential alerts, repo or org-wide (via the GitHub proxy).", "mdi-key-alert"),
    ("github.alerts.code_scanning", "Code-scanning alerts", "SAST alerts, repo or org-wide (via the GitHub proxy).", "mdi-shield-search"),
    ("github.org.members", "Org members", "Members (2FA filter), admins, or outside collaborators (via the GitHub proxy).", "mdi-account-group"),
    ("github.repo.settings", "Repo settings", "Deploy keys, webhooks, Actions permissions & secret names (via the GitHub proxy).", "mdi-cog"),
    ("github.request", "Raw GitHub request", "Signed passthrough to any GitHub REST endpoint (via the GitHub proxy).", "mdi-api"),
)


# The one action that runs on the plugin host instead of at the gateway: no
# gateway can hand over a working tree. Its permission still comes from
# OpenConnector — see actions.repo_clone and clone.py.
_LOCAL: tuple[tuple[str, str, str, str], ...] = (
    (
        "github.repo.clone",
        "Clone repository",
        "Clone a repository onto the plugin host with git, gated by the connected account's access.",
        "mdi-folder-download",
    ),
)


class Registry:
    def __init__(self, send: Send):
        self._oc = Client(send)
        self._actions = Actions(self._oc)
        self._meta = Meta(self._oc)

    # -------------------------------------------------------- actions --

    def all_actions(self) -> list[Action]:
        """Every action this plugin exposes, in the order the canvas shows them."""
        out = [
            Action(
                method=method,
                title=title,
                description=f"{description} (via OpenConnector).",
                icon=Icon(icon=icon),
                form=forms.ACTION_FORMS[method](),
                request_handler=self._actions.handler_for(method),
            )
            for method, title, description, icon in _CURATED
        ]
        out.extend(
            Action(
                method=method,
                title=title,
                description=description,
                icon=Icon(icon=icon),
                form=forms.ACTION_FORMS[method](),
                request_handler=self._actions.handler_for(method),
            )
            for method, title, description, icon in _PROXIED
        )
        out.extend(
            Action(
                method=method,
                title=title,
                description=description,
                icon=Icon(icon=icon),
                form=forms.ACTION_FORMS[method](),
                request_handler=self._actions.handler_for(method),
            )
            for method, title, description, icon in _LOCAL
        )
        return out

    # ---------------------------------------------------------- metas --

    def metas(self) -> list[SdkMeta]:
        """The settings/form meta RPCs: list & test accounts, check identity, and
        the org / repo pickers the action forms use."""
        m = self._meta
        return [
            SdkMeta(method="github.meta.account.list", request_handler=m.account_list),
            SdkMeta(method="github.meta.account.test", request_handler=m.account_test),
            SdkMeta(method="github.meta.user.info", request_handler=m.user_info),
            SdkMeta(method="github.meta.org.list", request_handler=m.org_list),
            SdkMeta(method="github.meta.repo.list", request_handler=m.repo_list),
        ]

    # ------------------------------------------------------- settings --

    def settings(self) -> Settings:
        """The settings profile: the form plus the submit handler that validates it."""
        return forms.settings_form().settings(self._meta.settings_submit)
