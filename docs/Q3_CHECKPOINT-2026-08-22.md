# Q3 Checkpoint Decision Policy & Scoring Rule (2026-08-22)

**Status**: ACCEPTED — 2026-08-14  
**Owner**: tuna-os (hanthor) / strategist  
**Tracks**: #1683, #1299, #1657  

---

## Purpose

Define the decision framework, the rules for scores, and the rules for evidence audits for the **Q3 Strategic Checkpoint** of 2026-08-22.

During merge queue jams or workflow permission bottlenecks (such as #1657), pull requests that pass all required status checks (`mergeable_state: clean`) may remain unmerged on GitHub. This policy protects the integrity of strategic plans. It also prevents a wrong classification of verified, completed work as "not done". For these reasons, it defines the **Merge-Eligible Score Rule** and an **Issue-Based Evidence Trail**.

---

## The Merge-Eligible Scoring Rule

For the assessment of the Q3 Checkpoint on 2026-08-22:

```math
\text{Status} = \begin{cases} 
\mathbf{DONE} & \text{if PR merged } \lor (\text{PR open } \land \text{mergeable\_state: clean } \land \text{CI checks PASS}) \\ 
\mathbf{IN\_PROGRESS} & \text{if PR open } \land \text{CI checks FAIL / pending review} \\ 
\mathbf{BLOCKED} & \text{if open blocker issue with no mergeable PR}
\end{cases}
```

### Decision Criteria
1. **Merge-Eligible == Done**: A Pull Request stays open, passes all required status checks, and GitHub marks it mergeable. In its decisions, the checkpoint then scores that feature, bugfix, or policy documentation as **DONE / SATISFIED**.
2. **Commit / Evidence Preservation**: The evidence of completion cites the Pull Request number and its clean commit SHA.
3. **Plan Loop Continuity**: Strategic decisions (STAFF, DESCOPE, DROP, PROMOTE) proceed based on merge-eligible evidence. Therefore, repository merge bottlenecks do not freeze work on the Q4 roadmap.

---

## Issue-Based Evidence Trail

To be sure that the decision inputs can survive delays in upstream merges:

1. **Issue Thread Audit**: Post checkpoint recommendations and status updates directly to the primary issues that track them. These are #1299, #1341, #272, #1123, #1383, and #1657.
2. **Divergence Correction**: Public status tables (including `ROADMAP.md` and `ADOPTION-METRICS.md`) maintain an audit log of issue comments. The log matches the verified repository state, and includes non-queue merges such as `bootc-installer` and PRs from external human contributors.

### External-capacity correction (2026-08-14)

The prior statement of “no external capacity” is stale. Two docs PRs, both
verified and human-authored, merged on 2026-08-14
([docs#234](https://github.com/tuna-os/docs/pull/234)
and [docs#239](https://github.com/tuna-os/docs/pull/239)). These PRs show a
contribution path through the docs channel. For #272/#1123, preserve the
conclusion only with the narrower evidence statement
**“no core-code capacity”**; do not cite the phrase
“no external capacity”. Contribution activity is not adopter evidence and must
remain separate from the Q4 adoption metrics. See #1714.

---

## Escalation Path (#1657)

- **Primary Target**: Restore the automatic merge of pull requests on `tuna-os/tunaos` and `tuna-os/tunaos-packages`. To do this, configure a ruleset bypass actor, or execute `gh pr merge --queue` before the 2026-08-19 pre-checkpoint freeze.
- **Fallback**: Execute the 2026-08-22 checkpoint assessment against merge-eligible PR state per this document.
