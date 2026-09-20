# Wires the OpenConnector bridge onto the plugin's node actions, the settings
# meta RPCs, and the settings profile. One Client (over the plugin's NATS send)
# is shared by the action handlers and the meta handlers, so the account list,
# scope cache and proxy are consistent across both.
from __future__ import annotations

from inflow_plugin_sdk import Action, Icon, Meta as SdkMeta, Settings

from . import forms
from .actions import Actions
from .meta import Meta
from .oc import Client, Send


class Registry:
    def __init__(self, send: Send):
        self._oc = Client(send)
        self._actions = Actions(self._oc)
        self._meta = Meta(self._oc)

    # -------------------------------------------------------- actions --

    def all_actions(self) -> list[Action]:
        """Every action this plugin exposes, in the order the canvas shows them."""
        a = self._actions
        return [
            Action(
                method="github.repos.list",
                title="List repositories",
                description="List repositories for the account, an org, or a user (via OpenConnector).",
                icon=Icon(icon="mdi-source-repository-multiple"),
                form=forms.repos_list_form(),
                request_handler=a.repos_list,
            ),
            Action(
                method="github.repo.get",
                title="Get repository",
                description="Fetch one repository's full record (via OpenConnector).",
                icon=Icon(icon="mdi-source-repository"),
                form=forms.repo_get_form(),
                request_handler=a.repo_get,
            ),
            Action(
                method="github.repo.collaborators",
                title="List collaborators",
                description="Who can push, and at what permission level (via OpenConnector).",
                icon=Icon(icon="mdi-account-multiple"),
                form=forms.repo_collaborators_form(),
                request_handler=a.repo_collaborators,
            ),
            Action(
                method="github.repo.contents",
                title="Get contents",
                description="Read a file or directory — CODEOWNERS, SECURITY.md, workflows (via the GitHub proxy).",
                icon=Icon(icon="mdi-file-document"),
                form=forms.repo_contents_form(),
                request_handler=a.repo_contents,
            ),
            Action(
                method="github.activity.list",
                title="List activity",
                description="Recent commits or workflow runs for a window (via OpenConnector).",
                icon=Icon(icon="mdi-history"),
                form=forms.activity_list_form(),
                request_handler=a.activity_list,
            ),
            Action(
                method="github.search",
                title="Search GitHub",
                description="Search repositories, code, or issues & PRs (via OpenConnector).",
                icon=Icon(icon="mdi-magnify"),
                form=forms.search_form(),
                request_handler=a.search,
            ),
            Action(
                method="github.repo.protection",
                title="Branch protection",
                description="Branch protection and rulesets on a branch (via the GitHub proxy).",
                icon=Icon(icon="mdi-shield-lock"),
                form=forms.repo_protection_form(),
                request_handler=a.repo_protection,
            ),
            Action(
                method="github.alerts.dependabot",
                title="Dependabot alerts",
                description="Vulnerable-dependency alerts, repo or org-wide (via the GitHub proxy).",
                icon=Icon(icon="mdi-shield-bug"),
                form=forms.alerts_dependabot_form(),
                request_handler=a.alerts_dependabot,
            ),
            Action(
                method="github.alerts.secret_scanning",
                title="Secret-scanning alerts",
                description="Leaked-credential alerts, repo or org-wide (via the GitHub proxy).",
                icon=Icon(icon="mdi-key-alert"),
                form=forms.alerts_secret_scanning_form(),
                request_handler=a.alerts_secret_scanning,
            ),
            Action(
                method="github.alerts.code_scanning",
                title="Code-scanning alerts",
                description="SAST alerts, repo or org-wide (via the GitHub proxy).",
                icon=Icon(icon="mdi-shield-search"),
                form=forms.alerts_code_scanning_form(),
                request_handler=a.alerts_code_scanning,
            ),
            Action(
                method="github.org.members",
                title="Org members",
                description="Members (2FA filter), admins, or outside collaborators (via the GitHub proxy).",
                icon=Icon(icon="mdi-account-group"),
                form=forms.org_members_form(),
                request_handler=a.org_members,
            ),
            Action(
                method="github.repo.settings",
                title="Repo settings",
                description="Deploy keys, webhooks, Actions permissions & secret names (via the GitHub proxy).",
                icon=Icon(icon="mdi-cog"),
                form=forms.repo_settings_form(),
                request_handler=a.repo_settings,
            ),
            Action(
                method="github.request",
                title="Raw GitHub request",
                description="Signed passthrough to any GitHub REST endpoint (via the GitHub proxy).",
                icon=Icon(icon="mdi-api"),
                form=forms.request_form(),
                request_handler=a.request,
            ),
        ]

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
