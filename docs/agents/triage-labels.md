# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Applying either `ready-for-agent` or `ready-for-human` to an unassigned issue
automatically adds `help wanted`. The readiness label is the maintainer's
judgement; `.github/workflows/add-help-wanted.yml` only publishes it to
contributors and does not make triage decisions of its own. Assigned issues
and issues already carrying `help wanted` or `good first issue` are unchanged.

Edit the right-hand column to match whatever vocabulary you actually use.

For queue-level policy (SLA tiers, when to close a bot-filed finding, milestone-vs-backlog signal) see [TRIAGE-POLICY.md](../../TRIAGE-POLICY.md) — this file only maps individual-issue labels.
