# Asahi hardware CI tiers (tunaOS#780)

`verify-asahi.yml` (see [MATRIX-STATUS.md §4](MATRIX-STATUS.md)) proves an
image *contains* what Apple Silicon boot needs — the kernel, DTBs, m1n1/U-Boot
payloads, modules. It never boots the image. GitHub-hosted arm64 runners have
no `/dev/kvm`, and nothing anywhere emulates the Apple SoC. So CI stops at
"looks right" and cannot answer "boots on a Mac". That gap let six of eight
promoted `:gnome-asahi` tags ship unbootable (tunaOS#776).

Two hardware tiers close that gap. No sandboxed contributor can set up or
enroll either one. Tier 2 needs a funded Scaleway account, which bills in
real EUR per hour. Tier 3 needs physical hands on a specific person's laptop.

This document and the script beside it (`scripts/asahi-remote-switch.sh`)
give two things to whoever *does* have that access. The first is
safety-checked automation to run against either host once it exists. The
second is CI wiring that activates the moment someone configures its target
host. No code change is necessary at that point.

## The one rule that matters more than either tier

**Never let anything write `<ESP>/m1n1/boot.bin` on a hardware-tier host
outside of a deliberate, watched, one-off action.**

This is not a generic caution — it is a landmine already present in this
repo. `build_scripts/asahi/install-bootbin-sync.sh` ships
`asahi-bootbin-sync.service`. This oneshot runs on **every boot** and
regenerates `boot.bin` whenever its content stamp is stale. It does so
*because* `bootc` deploys never run package scriptlets. Without it,
`update-m1n1` would never re-run after `bootc switch`/`bootc upgrade`.

That is the correct behaviour on a machine with a keyboard next to it. The
keyboard lets a person hold the recovery key combo if a bad payload leaves
the machine unbootable.

Neither hardware tier has that. A Scaleway rental has no console access
beyond SSH, and the issue that created this tier also states a "brick risk,
no physical access" clause. James's M1 Air only has whoever is at James's
desk.

On both hosts, a switch to a **deliberately experimental or known-broken
test image** can trigger an automatic `boot.bin` rewrite. Iteration on such
test images is the entire point of this tier. That rewrite turns a bad OS
image into a bricked machine, with no path back.

So: on both tiers, someone must mask `asahi-bootbin-sync.service` before any
iteration begins, and it stays masked. `scripts/asahi-remote-switch.sh` does
this itself on every run (idempotent, safe to repeat), instead of a one-time
setup step that nobody re-checks. The script also hard-refuses to run any
command that matches `update-m1n1`, `asahi-fwupdate`, `m1n1-installer`, or a
raw write to `/boot/efi` — see `DANGEROUS_PATTERNS` in the script. So a
copy-paste mistake in a future caller can never reach the firmware path, even
if something bypassed the mask above. Defense in depth on a mistake with no
undo.

## Tier 2 — Scaleway Mac mini M2 Pro rental

Scaleway offers bare metal rentals of the Mac mini M2 Pro with Asahi Linux
preinstalled (`~EUR 0.21/h`, 24h minimum unit of charge, provisionable via
their API). Ephemeral by design: rent it, run the nightly/release smoke pass,
tear it down. This is the tier that can exercise real m1n1 boot and the
`deqp-asahi-agx2` GPU acceptance suites from mesa (in-tree in mesa's
`src/asahi/ci/`). Neither is reachable any other way.

**What is out of scope for a code contribution:** the actual account, the
authority over the bills, and the API token. This repo does not — and should
not — carry a Scaleway credential. Nobody registers the rental as a
self-hosted runner for GitHub Actions at all, and that is deliberate.
`asahi-remote-switch.sh` (see its header for why) always drives its target
over SSH from somewhere else. So the rental only ever needs an SSH server. It
never gets a permanent credential of its own to keep secure, and no workflow
can compromise such a credential.

`.github/workflows/asahi-hw-nightly.yml` (added alongside this doc) runs on
an ordinary GitHub-hosted `ubuntu-latest` runner. It skips its one real step
when the `ASAHI_HW_TIER2_HOST` repository variable/secret isn't set. That is
its default state until someone with Scaleway access sets the value. So a
merge of the workflow now is safe, and it does nothing until then.

**Sequence once a rental exists:**

1. Rent the instance. Use the Scaleway console or API — see their docs for
   bare-metal Apple silicon; out of scope here. Then note its address. Use
   Tailscale if you join the instance to the same tailnet that the CI runner
   can reach. If not, use its public IP, with SSH locked down to GitHub's
   runner IP ranges.
2. SSH in once by hand and confirm it boots to the preinstalled Asahi Linux.
   Then set `ASAHI_HW_TIER2_HOST` (and `ASAHI_HW_TIER2_USER` if not `root`)
   as repository secrets/variables.
3. `asahi-hw-nightly.yml` picks it up on the next scheduled run, or on
   `workflow_dispatch`. The scheduled run is nightly at 05:40 UTC. That is
   the same slot as the sweep of `verify-asahi.yml`. So a fresh promoted tag
   and a fresh hardware pass both land close together.
4. The workflow runs `scripts/asahi-remote-switch.sh` against that host. The
   script switches the host to the promoted image under test. It then
   confirms that the switch survived a reboot, and that bootc did not fall
   back to the previous deployment. The workflow then runs whatever
   live-hardware checks the repo has wired in (today: a `bootc status`
   confirmation over the same SSH connection). Two more checks are follow-up
   work. The first is the mesa `deqp-asahi-agx2` suite. The second is a
   live-system rerun of the checks in `verify-asahi-image.sh`, against the
   *live* filesystem instead of a container mount. The version that inspects
   the image already exists. The version for boot hardware does not yet
   exist.
5. Tear the instance down. Do this by hand, or with a script. Someone with a
   live account must write and test such a script; this repo does not include
   one — see below. Scaleway bills in 24h increments, whatever time the job
   took. So, once this is real, put several flavors into one rental window.
   That is better than one rental per flavor per night.

## Tier 3 — James's M1 Air (`jamess-macbook-air` on tailnet)

A permanent, non-ephemeral personal machine, reachable over Tailscale.
One-time physical setup, then indefinite remote iteration:

**One-time, physical, by James:**

1. Install [Fedora Asahi Remix](https://asahilinux.org/fedora/) with the
   official `asahi-installer` from macOS Recovery. Use the "Minimal" spin —
   the host itself needs no desktop, because TunaOS images bring their own.
2. Boot it, `dnf install tailscale openssh-server`, `systemctl enable --now
   tailscaled sshd`, `tailscale up`, note the tailnet hostname
   (`jamess-macbook-air`, per the issue).
3. Confirm SSH from a machine already on the tailnet:
   `ssh james@jamess-macbook-air.<tailnet>.ts.net true`.
4. Run `systemctl mask asahi-bootbin-sync.service` if you ever switch this
   host to a TunaOS bootc image (see the rule above). A stock install of
   Fedora Asahi Remix has no such unit. The first `bootc switch` to a TunaOS
   image installs it. So this step means "remember to do it as part of every
   first switch". The remote-switch script instead does it unconditionally on
   every run, and does not trust a human to remember once.

Nobody can do any of the above from this sandbox — it needs a keyboard in
front of James's laptop. What follows can run from anywhere with tailnet
reach, and nobody needs to repeat it for each machine.

**Ongoing, remote, by anyone (agent or human) on the tailnet:**

```sh
ASAHI_HW_HOST=jamess-macbook-air.<tailnet>.ts.net \
ASAHI_HW_USER=james \
  scripts/asahi-remote-switch.sh ghcr.io/tuna-os/bonito:gnome-asahi
```

masks `asahi-bootbin-sync.service`, records which deployment the host booted,
runs `bootc switch` to the given image, reboots, and waits for the host to
come back. It then reports one of three outcomes.

The first outcome is a clean switch to the new image. The second is a
rollback by the host itself. In that case, bootc's own boot counter selected
the previous deployment, because the new one never confirmed.

That rollback is the "greenboot" the issue refers to. TunaOS does not ship
literal `greenboot`. The actual mechanism is `bootc`'s built-in rollback,
which stages the deployment and counts boots. This script only *observes* it,
and contains none of the recovery logic itself.

The third outcome is that the host never came back within the timeout. This
is the one outcome that needs a human at the keyboard. bootc's rollback
covers "new deployment doesn't confirm," not "new deployment hangs the whole
boot before bootc's own health check can run".

## Community testing (informal, not a CI tier)

Maintainers control tiers 2 and 3 above. One is infrastructure that someone
pays for, and the other is a specific person's laptop. No community member
can volunteer either one.

If you own Apple Silicon hardware and want to try
[bootc-installer-asahi](https://github.com/tuna-os/bootc-installer-asahi)
independently of either tier, that's welcome. It is not part of the CI gate.
But real-hardware reports are exactly the signal that motivated M1/M2
support in the first place (tunaOS#911, the `gnome-asahi` unbootable-image
incident). Report results as an issue in
[bootc-installer-asahi](https://github.com/tuna-os/bootc-installer-asahi/issues),
tagged `hardware-report`, with the Mac model and which image/flavor you
tried.

## What is deliberately not in this PR

- A script to rent and tear down a Scaleway instance. Such a script would go
  against an API this repo has never called. Nobody can test it without real
  money. That is exactly the kind of "confident but unverified" contribution
  that is worse than no contribution at all. Compare the precedent of
  `iso-e2e-gpu.sh`. It ships the host-side script and documents the host
  requirements. It leaves the acquisition of the host itself to whoever
  controls it.
- Live-hardware GPU/`deqp-asahi-agx2` harness integration. `mesa`'s in-tree
  suite is a real, separate piece of tooling. It has its own invocation and
  result format. To wire it in blind, with no hardware to run it against, has
  the same problem as the point above.
- To rent any actual instance, to set any actual repository secret, or to
  touch James's actual laptop. All three need access this environment does
  not have.
