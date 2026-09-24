# PR review rubric

What a reviewer (human or agent) checks before approval of a PR here, beyond green CI status:

1. **Checks ran on the real change.** The `just fix && just check` and `just test` recipes are mandatory. Verify that CI ran them on the current head, not a stale commit.
2. **Green-criteria impact.** Check if the change moves any cell status in `.github/green-criteria.yml`. A PR must state any regression to a `blocking` criterion explicitly.
3. **Scope matches the issue.** Make the smallest change that satisfies the issue criteria. Flag unrelated changes in the PR.
4. **Known landmines.** Check the PR against documented gotchas in `AGENTS.md`. Do not repeat recorded mistakes.
5. **Diagnose CI failures.** A broken check must include a fix or a clear reason. Never disable checks or retry without a root cause.
