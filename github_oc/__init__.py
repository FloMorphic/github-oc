"""GitHub (OpenConnector) plugin for Inflowenger.

A FloMorphic plugin node for GitHub that authenticates through FloMorphic's
central Connect feature (OpenConnector / oomol) instead of holding a GitHub
token of its own. It is a *request builder*: a GitHub account is connected once,
centrally, and every action asks the FloMorphic backend to run the matching
OpenConnector action — or a raw GitHub REST call — as the chosen account.

Curated OpenConnector actions cover everything oomol curates — repositories,
contents, branches, refs, commits, checks, workflows, issues, labels, milestones,
pull requests, reviews, releases, search and the event feeds — grouped surface by
surface in ops.py. The security surface oomol does not curate (Dependabot /
secret-scanning / code-scanning alerts, branch protection, org members, repo
settings) is reached through oomol's provider proxy over the same central
credential.

One action is local: `clone` runs git on the plugin host, because no gateway can
hand over a working tree. Its permission still comes from OpenConnector — the
repository is read as the connected account, and the clone is refused unless that
account's own access grants it. See clone.py.
"""

__version__ = "v0.2.0"
