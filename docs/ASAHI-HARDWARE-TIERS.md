# Asahi hardware CI tiers (tunaOS#780)

`verify-asahi.yml` (see [MATRIX-STATUS.md §4](MATRIX-STATUS.md)) proves an
image *contains* what Apple Silicon boot needs — the kernel, DTBs, m1n1/U-Boot
payloads, modules. It never boots the image. GitHub-hosted arm64 runners have
no `/dev/kvm` and there is no Apple SoC emulation anywhere, so CI caps out at
"looks right" and cannot answer "boots on a Mac" — which is exactly the gap
that let six of eight promoted `:gnome-asahi` tags ship unbootable
(tunaOS#776).

Two hardware tiers close that gap. Neither can be provisioned or enrolled by
a sandboxed contributor: Tier 2 needs a funded Scaleway account (real EUR/hour
billing), and Tier 3 needs physical hands on a specific person's laptop. What
this document and the accompanying script (`scripts/asahi-remote-switch.sh`)
give whoever *does* have that access is the safety-checked automation to run
against either host once it exists, and CI wiring that activates the moment
its target host is configured — no code change required at that point.

## The one rule that matters more than either tier

**Never let anything write `<ESP>/m1n1/boot.bin` on a hardware-tier host
outside of a deliberate, watched, one-off action.**

This is not a generic caution — it is a landmine already sitting in this
repo. `build_scripts/asahi/install-bootbin-sync.sh` ships
`asahi-bootbin-sync.service`, a oneshot that runs on **every boot** and
regenerates `boot.bin` whenever its content stamp is stale, specifically
*because* `bootc` deploys never run package scriptlets, so `update-m1n1`
would otherwise never re-run after `bootc switch`/`bootc upgrade`. That is
the correct behaviour on a machine with a keyboard next to it and a person
who can hold the recovery key combo if a bad payload leaves it unbootable.

Neither hardware tier has that. A Scaleway rental has no console access
beyond SSH and a "brick risk, no physical access" clause in the issue that
created this tier; James's M1 Air only has whoever is at James's desk. On
both, an automatic `boot.bin` rewrite triggered by switching to a
**deliberately experimental or known-broken test image** — which is the
entire point of iterating against this tier — turns a bad OS image into a
bricked machine, with no path back.

So: `asahi-bootbin-sync.service` gets masked on both tiers before any
iteration begins, and stays masked. `scripts/asahi-remote-switch.sh` does
this itself on every run (idempotent, safe to repeat) rather than relying on
a one-time setup step nobody re-checks. It also hard-refuses to run any
command matching `update-m1n1`, `asahi-fwupdate`, `m1n1-installer`, or a raw
write to `/boot/efi` — see `DANGEROUS_PATTERNS` in the script — so a copy-paste
mistake in a future caller cannot reach the firmware path even if the mask
above were somehow bypassed. Defense in depth on a mistake with no undo.

## Tier 2 — Scaleway Mac mini M2 Pro rental

Scaleway rents Mac mini M2 Pro bare metal with Asahi Linux preinstalled
(`~EUR 0.21/h`, 24h minimum billing increment, provisionable via their API).
Ephemeral by design: rent it, run the nightly/release smoke pass, tear it
down. This is the tier that can exercise real m1n1 boot and the mesa
`deqp-asahi-agx2` GPU acceptance suites (in-tree in mesa's `src/asahi/ci/`) —
neither is reachable any other way.

**What is out of scope for a code contribution:** the actual account,
billing authority, and API token. This repo does not — and should not —
carry a Scaleway credential, and the rental is deliberately never registered
as a GitHub Actions self-hosted runner at all: `asahi-remote-switch.sh` (see
its header for why) always drives its target over SSH from somewhere else,
so the rental only ever needs an SSH server and never gets a standing
credential of its own to keep secure or to worry about a workflow
compromising. `.github/workflows/asahi-hw-nightly.yml` (added alongside this
doc) runs on an ordinary GitHub-hosted `ubuntu-latest` runner and simply
skips its one real step whenever the `ASAHI_HW_TIER2_HOST` repository
variable/secret isn't set — which is its default state until someone with
Scaleway access starts filling it in, so merging the workflow now is safe
and does nothing until then.

**Sequence once a rental exists:**

1. Rent the instance (Scaleway console or API — see their Apple silicon
   bare-metal docs; out of scope here) and note its address (Tailscale, if
   joined to the same tailnet as the CI runner can reach; otherwise its
   public IP with SSH locked down to GitHub's runner IP ranges).
2. SSH in once by hand, confirm it boots to the preinstalled Asahi Linux,
   and set `ASAHI_HW_TIER2_HOST` (and `ASAHI_HW_TIER2_USER` if not `root`)
   as repository secrets/variables.
3. `asahi-hw-nightly.yml` picks it up on the next scheduled run (nightly,
   05:40 UTC — same slot as `verify-asahi.yml`'s sweep, so a fresh promoted
   tag and a fresh hardware pass land close together) or `workflow_dispatch`.
4. The workflow runs `scripts/asahi-remote-switch.sh` against that host to
   switch it to the promoted image under test, confirm the switch survived a
   reboot without bootc falling back to the previous deployment, then runs
   whatever live-hardware checks are wired in (today: a `bootc status`
   confirmation over the same SSH connection; mesa `deqp-asahi-agx2` and a
   live-system rerun of `verify-asahi-image.sh`'s checks against the
   *running* filesystem rather than a container mount are follow-up work —
   the image-inspection version already exists, the boot-hardware version
   does not yet).
5. Tear the instance down (manual, or a provisioning script someone with a
   live account writes and tests — not included here, see below). Scaleway
   bills in 24h increments regardless of how long the job actually took, so
   batching multiple flavors into one rental window is worth doing once this
   is real rather than renting per flavor per night.

## Tier 3 — M1 MacBook Air (`macbook-air` on tailnet)

A standing, non-ephemeral personal machine reachable over Tailscale. One-time
physical setup, then indefinite remote iteration:

**One-time, physical, by the machine's owner:**

1. Install [Fedora Asahi Remix](https://asahilinux.org/fedora/) (the
   "Minimal" spin — no desktop needed on the host itself, TunaOS images
   bring their own) using the official `asahi-installer` from macOS Recovery.
2. Boot it, `dnf install tailscale openssh-server`, `systemctl enable --now
   tailscaled sshd`, `tailscale up`, note the tailnet hostname
   (`macbook-air`, per the issue).
3. Confirm SSH from a machine already on the tailnet:
   `ssh <user>@macbook-air.<tailnet>.ts.net true`.
4. `systemctl mask asahi-bootbin-sync.service` if a TunaOS bootc image is
   ever switched to on this host (see the rule above) — the stock Fedora
   Asahi Remix install won't have this unit at all until the first `bootc
   switch` to a TunaOS image installs it, so this step is really "remember
   to do it as part of every first switch," which is why the remote-switch
   script does it unconditionally on every run instead of trusting a human
   to remember once.

None of the above can be done from this sandbox — it requires a keyboard in
front of the machine. What follows can run from anywhere with tailnet
reach and does not need repeating per-machine.

**Ongoing, remote, by anyone (agent or human) on the tailnet:**

```sh
ASAHI_HW_HOST=macbook-air.<tailnet>.ts.net \
ASAHI_HW_USER=<user> \
  scripts/asahi-remote-switch.sh ghcr.io/tuna-os/bonito:gnome-asahi
```

masks `asahi-bootbin-sync.service`, records the currently-booted deployment,
runs `bootc switch` to the given image, reboots, waits for the host to come
back, and reports one of three outcomes: switched cleanly to the new image,
rolled back on its own (bootc's own boot-counting mechanism selected the
previous deployment because the new one never confirmed — the "greenboot"
the issue refers to; TunaOS does not ship literal `greenboot`, `bootc`'s
built-in staged-deployment/boot-counting rollback is the actual mechanism and
this script only *observes* it, it implements none of the recovery logic
itself), or never came back within the timeout (the one outcome that needs a
human at the keyboard — bootc's rollback covers "new deployment doesn't
confirm," not "new deployment hangs the whole boot before bootc's own health
check can run").

## Community testing (informal, not a CI tier)

Tiers 2 and 3 above are maintainer-controlled: one is funded infrastructure,
the other is a specific person's laptop. Neither can be volunteered into by
a community member. If you own Apple Silicon hardware and want to try
[bootc-installer-asahi](https://github.com/tuna-os/bootc-installer-asahi)
independently of either tier, that's welcome — it's not part of the CI gate,
but real-hardware reports are exactly the signal that motivated M1/M2
support in the first place (tunaOS#911, the `gnome-asahi` unbootable-image
incident). Report results as an issue in
[bootc-installer-asahi](https://github.com/tuna-os/bootc-installer-asahi/issues),
tagged `hardware-report`, with the Mac model and which image/flavor you
tried.

## What is deliberately not in this PR

- A Scaleway provisioning/teardown script. Writing one against an API this
  repo has never called, that cannot be tested without spending real money,
  is exactly the kind of "confident but unverified" contribution that is
  worse than not shipping it — see `iso-e2e-gpu.sh`'s precedent of shipping
  the host-side script and documenting the host requirements, and leaving
  actual host acquisition to whoever controls it.
- Live-hardware GPU/`deqp-asahi-agx2` harness integration. `mesa`'s in-tree
  suite is a real, separate piece of tooling with its own invocation and
  result format; wiring it in blind, with no hardware to run it against, has
  the same problem as the point above.
- Renting any actual instance, setting any actual repository secret, or
  touching James's actual laptop. All three require access this environment
  does not have.
