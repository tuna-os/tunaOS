# Community Governance Model

**Status**: Active | **Tracks**: #1168 (Q4 goal — Community governance model)

## Roles and Authority

1. **Contributor**: Submits PRs, opens issues.
2. **Reviewer/Triage**: Can review PRs, label issues, and run initial triage.
3. **Maintainer**: Has review and merge authority, sets project direction.
4. **Project Lead**: Final escalation point for lazy-consensus disputes.

## Decision Process

We use a **lazy-consensus** model. When a PR or RFC is proposed, if no objections are raised within 72 hours, it is considered approved (assuming CI passes and it meets our guidelines). If objections arise, they must be resolved through discussion. If consensus cannot be reached, the Project Lead resolves the dispute.

## RFC Lifecycle Integration

Major architectural changes must go through an RFC process.
- Draft an RFC document.
- Open a PR for the RFC.
- Lazy-consensus applies for adoption.

## Per-Repo CODEOWNERS Policy

Each repository must have a `CODEOWNERS` file defining who has review and merge authority over specific paths. Code changes cannot be merged without approval from a designated code owner.
