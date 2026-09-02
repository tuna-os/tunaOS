# PR review rubric

What a reviewer (human or agent) checks before approving a PR here, beyond
"CI is green":

1. **Checks actually ran, and ran on the real change.** `just fix && just
   check` and `just test` are mandatory per `CONTRIBUTING.md` — verify the
   PR's CI ran them on the current head, not a stale commit.
2. **Green-criteria impact.** If the change touches build, desktop, or boot
   behavior, check whether it moves any cell's status in
   `.github/green-criteria.yml` — a PR that silently regresses a
   `blocking` criterion (see `docs/quality.md`) needs that called out
   explicitly, not discovered later in a nightly sweep.
3. **Scope matches the issue.** The smallest change that satisfies the
   linked issue's acceptance criteria, per `CONTRIBUTING.md`'s fork→PR loop
   — flag unrelated changes bundled into the same PR.
4. **Known landmines.** Check the PR against `AGENTS.md`'s documented
   gotchas (e.g. "know your base before reasoning about its packages") —
   a fix that looks right in isolation can still repeat a mistake that's
   already been made and recorded once.
5. **CI failures are diagnosed, not silenced.** A failing check should come
   with either a fix or a clear explanation of why it's unrelated
   (pre-existing, infra) — never a skip, disable, or retry-until-green with
   no root cause.
