# PR review rubric

What a reviewer (human or agent) checks before they approve a PR here, beyond
a green CI result:

1. **Checks ran, and ran on the real change.** `just fix && just
   check` and `just test` are mandatory per `CONTRIBUTING.md`. Verify that the
   PR's CI ran them on the current head, not a stale commit.
2. **Green-criteria impact.** If the change touches build, desktop, or boot
   behavior, check whether it moves any cell's status in
   `.github/green-criteria.yml`. A PR that silently regresses a
   `blocking` criterion (see `docs/quality.md`) must state that
   explicitly. Do not let a nightly sweep discover it later.
3. **Scope matches the issue.** The PR must be the smallest change that
   satisfies the acceptance criteria of the linked issue. The fork→PR loop in
   `CONTRIBUTING.md` sets this rule. Flag unrelated changes bundled into the same PR.
4. **Known landmines.** Check the PR against documented gotchas in
   `AGENTS.md`, e.g. the section
   [Know your base](../AGENTS.md#know-your-base-before-reasoning-about-its-packages).
   A fix that looks right in isolation can still repeat a mistake that
   someone already made and recorded once.
5. **Diagnose CI failures; do not silence them.** A failed check needs a fix.
   If the failure has no relation to the PR (pre-existing, infra), give a clear explanation
   of why. Never accept a skip, disable, or retry-until-green with
   no root cause.
