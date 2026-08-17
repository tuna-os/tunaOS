# What "green" means

A **cell** is one (variant, flavor) pair — `yellowfin:gnome`, `marlin:kde`.

Until 2026-08-17, green meant *the image built and promoted*. That is the
weakest claim this pipeline can make. An image can build, push, promote and
ship no desktop at all: `marlin:kde` published with no
`/usr/share/wayland-sessions/` whatsoever, because one AUR-only package failed
the entire KDE set silently (tunaOS#858).

Green now means the image **works**: it boots, the desktop starts, the ISO
installs, the installed system updates and rolls back, and the package set is
what it claims to be.

The criteria live in [`.github/green-criteria.yml`](../.github/green-criteria.yml).
That file is the source of truth; this document explains the reasoning.
`tests/test_green_criteria.py` keeps the two from drifting.

---

## The composite rule

> A cell is green only if every **blocking** criterion has an affirmative,
> current result. Skipped, never-tested and stale all count as **not green**.

This rule matters more than the list. Every criterion below already existed in
some form before the bar was raised, and almost none of them blocked anything:
the boot Gate was skippable, the parity manifest was written into every image
and read by nothing, and Bootc Lifecycle had never run for a single cell.

Adding criteria to a system that does not enforce the ones it has just adds
more things that silently do not run. On 2026-08-17 the boot Gate broke across
the whole matrix — a moved file path — and marlin still looked fine, because
21 of its 25 jobs were green and the 4 that mattered were the ones that
vanished (#1811).

**"Never tested" must never render as green.** It is the difference between
"we checked and it works" and "nobody has ever looked".

---

## The criteria

| # | Criterion | Enforcement | State on 2026-08-17 |
|---|---|---|---|
| 1 | Image builds and promotes | **blocking** | 84 / 142 cells |
| 2 | Declared desktop is present and startable | advisory | 35 / 52 (5 never tested) |
| 3 | Boots to a graphical session | advisory | skippable; broke matrix-wide |
| 4 | ISO boots and offers an installer | unimplemented | 31/36 ever tested, **0 pass** |
| 5 | Installation completes and boots | advisory | 31 / 52 (5 never tested) |
| 6 | Update, rebase and rollback work | unimplemented | **0 / 52 — never run** |
| 7 | Package parity with upstream | unimplemented | not scheduled |
| 8 | The build tells the truth about what it shipped | unimplemented | written, never read |
| 9 | The image can still be built tomorrow | advisory | 13 / 13 base pins resolve |
| 10 | No cell declares an arch it cannot satisfy | unimplemented | hummingbird arm64 404s |

### Why some of these are separate that look similar

**2 vs 3 — present vs startable.** Desktop Contract Sweep inspects the
published image without booting it; the Gate boots a disk and waits for a real
session. An image can satisfy one and fail the other, and guppy:gnome
currently does exactly that (#1801).

**4 vs 5 — ISO vs install.** LUKS E2E drives the installer backend over SSH and
never looks at the screen. It proves a system installs and boots; it does not
prove a human could have started that install. `yellowfin:cosmic` was green on
LUKS while its installer GUI had never once been observed.

**7 vs 8 — parity vs honesty.** Parity asks whether the package set matches
upstream. Honesty asks whether the build *admitted* what it dropped.
`install_available` and `--skip-unavailable` mean missing packages never fail a
build — deliberately, so a partial repo cannot hard-fail everything — and the
consequence is an image that builds cleanly with a hole in it. The evidence is
already written to `/usr/share/tunaos/missing-on-*.txt` inside every image. It
just needs to be read.

### Why lifecycle ranks higher than it looks

Criterion 6 has never run for a single cell in 52. For a bootc OS the update
transaction *is* the product. An image that installs perfectly and cannot
`bootc upgrade`, or cannot roll back off a bad deployment, has failed at the
one thing immutability is sold on. Every user meets upgrade repeatedly and the
ISO exactly once.

### What is deliberately excluded

**Signature and attestation are not green-blocking.** Provenance is reported on
its own axis. Sigstore outages are frequent and unrelated to whether an image
works; coupling them cost the matrix a full day on 2026-08-15, when a Rekor 502
took 136 cells down after signing had already succeeded (#1560).

**Anything CI structurally cannot test.** Four of five desktops need a DRM
render node that hosted runners do not have, and NVIDIA needs real hardware.
Folding those into green manufactures permanent red that says nothing about the
product. They are tracked as *not yet covered*, not as failures.

---

## Getting there

The gap is not evenly distributed, and the cheapest wins are not the loudest
ones:

1. **Run Bootc Lifecycle once.** It is written and has never executed. Going
   from "0 tested" to any number at all is the single largest information gain
   available.
2. **Make the boot Gate non-skippable** for any cell claiming green on a
   desktop CI can actually test.
3. **Read the omissions manifest on a schedule.** The data already exists in
   every published image.
4. **Unblock the ISO axis** (#1772, #1556). Zero cells pass today, so
   "working ISOs" is unproven everywhere.
5. **Make an unsatisfiable architecture a config error**, so it stops
   producing nightly failures nobody can fix (#1755 §3).

Raising the bar will drop the reported number sharply — a cell counted for
building is not a cell that works. That drop is the point: the smaller number
is the true one.
