# Q3 Checkpoint Decision Policy & Scoring Rule (2026-08-22)

**Status**: ACCEPTED — 2026-08-14
**Owner**: tuna-os (hanthor) / strategist
**Tracks**: #1683 (Q3 checkpoint decision integrity & merge jam), #1299 (Q3 milestone review), #1657 (Merge queue unblock escalation)

---

## Purpose

Define the decision framework, scoring rules, and evidence audit rules for the **2026-08-22 Q3 Strategic Checkpoint**.

During merge queue jams or workflow permission bottlenecks (such as #1657), pull requests that pass all required status checks (`mergeable_state: clean`) may remain unmerged on GitHub. To protect strategic planning integrity and prevent misclassifying verified, completed work as "not done", this policy defines the **Merge-Eligible Scoring Rule** and an **Issue-Based Evidence Trail**.

---

## The Merge-Eligible Scoring Rule

For the 2026-08-22 Q3 Checkpoint assessment:

$$\text{Status} = \begin{cases} 
\mathbf{DONE} & \text{if PR merged } \lor (\text{PR open } \land \text{mergeable\_state: clean } \land \text{CI checks PASS}) \\ 
\mathbf{IN\_PROGRESS} & \text{if PR open } \land \text{CI checks FAIL / pending review} \\ 
\mathbf{BLOCKED} & \text{if open blocker issue with no mergeable PR}
\end{cases}$$

### Decision Criteria
1. **Merge-Eligible == Done**: Any feature, bugfix, or policy documentation whose implementing Pull Request is open, passes all required status checks, and is marked mergeable by GitHub is scored as **DONE / SATISFIED** for checkpoint decision-making.
2. **Commit / Evidence Preservation**: The evidence of completion is recorded by referencing the Pull Request number and its clean commit SHA.
3. **Planning Loop Continuity**: Strategic decisions (STAFF, DESCOPE, DROP, PROMOTE) proceed based on merge-eligible evidence, ensuring Q4 roadmap planning is not frozen by repository merge bottlenecks.

---

## Issue-Based Evidence Trail

To ensure decision inputs survive upstream merge delays:

1. **Issue Thread Auditing**: Checkpoint recommendations and status updates must be posted directly to their primary tracking issues (#1299, #1341, #272, #1123, #1383, #1657).
2. **Divergence Correction**: Public status tables (including `ROADMAP.md` and `ADOPTION-METRICS.md`) maintain an issue comment audit log matching verified repository state (e.g. tracking non-queue merges such as `bootc-installer` and external human contributor PRs).

### External-capacity correction (2026-08-14)

The prior “no external capacity” framing is stale. Two verified human-authored
docs PRs merged on 2026-08-14 ([docs#234](https://github.com/tuna-os/docs/pull/234)
and [docs#239](https://github.com/tuna-os/docs/pull/239)), demonstrating a
docs-channel contribution path. For #272/#1123, preserve the conclusion only
with the narrower evidence statement **“no core-code capacity”**; do not cite
“no external capacity.” Contribution activity is not adopter evidence and must
remain separate from the Q4 adoption metrics. See #1714.

---

## Escalation Path (#1657)

- **Primary Target**: Restore automated pull request merging on `tuna-os/tunaos` and `tuna-os/tunaos-packages` by configuring a ruleset bypass actor or executing `gh pr merge --queue` prior to the 2026-08-19 pre-checkpoint freeze.
- **Fallback**: Execute the 2026-08-22 checkpoint scoring against merge-eligible PR state per this document.
