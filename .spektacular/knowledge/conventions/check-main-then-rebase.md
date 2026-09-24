---
tags: [git, prs, branching]
---

# Check main and open PRs before fixing; rebase before opening

Before diagnosing, run `git log --oneline -20` on main and search open PRs: the bug may already be fixed or in flight. Rebase onto main before opening a PR and re-run the tests on the new base.

Source: `AGENTS.md` PR contract rules 4-5.
