# Content claim checklist

Anyone writing a user-facing guide, campaign post, or adoption brief for TunaOS
works through this list before opening the PR. It exists because five guide PRs
in a row (#2142, #2143, #2146, #2150, #2152) were closed for the same two
defects: an image reference the project does not publish, and a toolchain the
images do not ship.

The rule underneath every item: **a plausible default is not evidence.** If the
repository does not show the behavior, the guide does not claim it.

## 1. Image references

The flavor is a **tag**, not part of the repository name:

```
ghcr.io/tuna-os/albacore:gnome        # correct
ghcr.io/tuna-os/albacore-gnome:latest # not a published ref
ghcr.io/tuna-os/tunaos-albacore:latest # not a published ref
```

Tags are `<desktop>[-hardware]` — see [IMAGE-TAGS.md](IMAGE-TAGS.md) for the
desktop and hardware suffixes, and the variant table in the
[README](../README.md) for the registry path of each variant. Both halves need
checking: a real tag on the wrong variant path is still a broken pull command.

## 2. Named packages and toolchains

Before writing that a tool is available, grep for it:

```
git grep -iE '\b(rustc|cargo|apptainer|<your-tool>)\b' -- manifests build_scripts system_files
```

If it is not there, the images do not preinstall it. The guide then either
drops the claim or tells the reader how to install it themselves — and says
which route that is. Package names inside a `dnf install` or `apt install`
line count as claims too: #2142 was closed partly for `dnf install
cuda-toolkit libcudnn8` against an image that does not provide those packages.

Absence from `manifests/` is proof the repository does not install a tool. It
is not proof the base image lacks it — if you believe a tool arrives from the
base, cite where, or leave it out.

## 3. Hardware support

Hardware statements cite [HARDWARE.md](HARDWARE.md) and preserve its hedging.
Apple Silicon is the usual trap: M1/M2 support is in progress via Asahi and the
`-asahi` flavors are experimental, M3 and newer are not supported. "Native
Apple Silicon support" overstates all of that.

## 4. Readiness and quality claims

"Works", "production ready", "stable" and "supported" are claims about a
specific (variant, flavor) cell, and they are answered by
[GREEN-CRITERIA.md](GREEN-CRITERIA.md) and [MATRIX-STATUS.md](MATRIX-STATUS.md),
not by the fact that an image built. Green means the criteria in
[`.github/green-criteria.yml`](../.github/green-criteria.yml) have current
affirmative results; never-tested is not green. Cite the state, and if a cell
you want to recommend has not been verified, say so or pick a different one.

## 5. Regulatory and compliance language

No content in this repository describes TunaOS as compliant with, certified
for, conformant to, or ready for any healthcare, payment, privacy, audit, or
government-security regime, by name or by paraphrase. Shipping a feature is not
evidence of an organization's compliance posture, and this repository does not
carry the audits that such a statement would imply. If a campaign seems to need
this language, it goes to a human owner instead of into the draft — including
the decision about whether to use it at all.

## 6. Forward-looking statements

Future versions, platforms, dates, and integrations appear in content only when
a human-authored issue, release plan, or announcement already commits to them.
Cite that source and keep its uncertainty intact.

## 7. Indexing

A new doc is added to the table in [README.md](README.md) in the same PR.
Guides that skipped this step (#2150, #2152, and earlier #1404 and #2119) left
files nothing linked to.
