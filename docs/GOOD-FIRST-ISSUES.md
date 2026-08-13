# Good-first-issue starter brief

This page is a fallback when the [organization-wide good-first-issue
queue](https://github.com/issues?q=is%3Aissue+is%3Aopen+org%3Atuna-os+label%3A%22good+first+issue%22)
has no usable tasks. It is intentionally documentation-only: no image build,
registry login, or privileged access is needed.

## Starter task: documentation and download parity

Audit the published editions listed in the [tunaOS download
catalog](https://tunaos.org/download), using the 37-edition scope from
[tunaos-packages#133](https://github.com/tuna-os/tunaos-packages/issues/133).
For each edition, verify both:

1. The edition has a discoverable variant page or catalog entry.
2. Its download link resolves successfully and points to the intended artifact.

Do not infer a missing desktop from image size alone. The earlier audit found
that size is only a triage signal; a package/session check or a catalog fact is
needed before calling an edition broken.

| Variant family | Historical editions to check | Result | Evidence |
|---|---|---|---|
| yellowfin | base, gnome, kde, cosmic, niri, xfce | ⬜ | |
| bonito | base, gnome, kde, cosmic, niri, xfce | ⬜ | |
| sailfin | gnome, kde, niri, xfce | ⬜ | |
| flounder | base, gnome, kde, cosmic, niri, xfce | ⬜ | |
| grouper | gnome, kde, niri, xfce | ⬜ | |
| marlin | base, gnome, kde, cosmic, niri, xfce | ⬜ | |
| skipjack | base, gnome, kde, cosmic, niri, xfce | ⬜ | |
| albacore | base, gnome, kde, cosmic, niri, xfce | ⬜ | |
| guppy | gnome, kde | ⬜ | |

The table is the historical family checklist used to reproduce the #133
audit; the catalog is authoritative if the current published set differs from
it. Note any additions or removals in the result rather than silently changing
the checklist. The reported 37-edition scope is therefore a baseline to
reconcile, not a claim that every row above is still published today.

## Acceptance criteria

- Record the date checked, edition, catalog or variant-page URL, download URL,
  and HTTP/result status.
- Report missing pages and broken links in a follow-up issue or comment on
  [#1308](https://github.com/tuna-os/tunaOS/issues/1308), linking the evidence.
- If all links work, say so explicitly and include the checked-edition count.
- Keep the change documentation-only; do not “fix” a broken artifact by
  changing build configuration as part of this starter task.

## Other safe starter areas

Maintainers can turn the following into similarly scoped issues:

- Add a focused shell-test case for an existing script edge case.
- Improve one troubleshooting page with a reproduced command and output.
- Add a missing acceptance check to an existing documentation or lifecycle
  checklist.

When claiming a starter issue, comment on it first and keep the pull request
focused on its acceptance criteria.
