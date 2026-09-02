# CFP demo video — recording script

The one recordable artifact both Q1 2027 CFPs depend on (#1135 action 2).
[FOSDEM](./CFP-FOSDEM-2027.md) attaches it; the SCaLE 21x draft explicitly
reuses the same recording rather than shooting a second one.

## Why this file exists

The CFP drafts carry a four-bullet demo outline. That is enough to describe a
demo in an abstract and not enough to record one: it names no commands, no
running order, no timings, and — the part that actually decides whether the
video helps — no statement of what each shot has to *prove* to a reviewer.

A 3–5 minute video improvised from four bullets gets reshot. This is the shot
list, with the commands taken from this repo rather than invented.

> **Not executed.** Every command below was read out of `Justfile`,
> `scripts/run-vm.sh` and `scripts/corral-build.sh` in this repo, and the image
> refs were confirmed to resolve in GHCR (2026-08-14). Nothing here has been
> run end-to-end by the person who wrote it — no Apple-silicon-free VM host in
> that session. **Do the dry run in "Before you record" first.** If a command
> has drifted, fix it here in the same sitting, so the next recorder inherits a
> corrected script rather than the same surprise.

## The through-line

Everything in the talk reduces to one claim, so the video should too:

> A desktop is an OCI image. You upgrade it like one, you roll it back like
> one, and you can schedule one like any other workload.

Three shots, one per verb: **upgrade**, **roll back**, **schedule**. Anything
that does not serve one of those verbs is cut — a CFP reviewer is deciding
whether the talk has a real system behind it, not evaluating the desktop.

## Before you record

Run these first, on the machine you will record on. They are also the honest
answer to "needs a spare laptop/VM" in the FOSDEM checklist — this is what
"spare" has to mean.

| Check | Command | Wanted |
|---|---|---|
| KVM present | `test -e /dev/kvm && echo ok` | `ok` — `run-vm.sh` passes `--device=/dev/kvm` |
| Image resolves | `skopeo inspect docker://ghcr.io/tuna-os/yellowfin:gnome \| head -5` | a manifest, not a 404 |
| Disk image builds | `just qcow2 yellowfin gnome` | `yellowfin-gnome.qcow2` in the repo root |
| VM boots | `scripts/run-vm.sh demo yellowfin gnome` | prints `Connect via Web: http://127.0.0.1:<port>`, GNOME reaches a session |

**Pre-pull the upgrade target before recording.** `bootc upgrade` on a cold
cache spends minutes fetching layers, which does not fit in a 3–5 minute video
and is not what the shot is about. Inside the guest, ahead of the take:

```sh
sudo podman pull ghcr.io/tuna-os/yellowfin:gnome
```

Then the recorded `bootc upgrade` shows the staging and the atomic swap, which
is the interesting part, rather than a progress bar.

## Shot list (target 3:30, hard ceiling 5:00)

### Shot 1 — "it is just an image" (0:00–0:30)

**Proves:** the desktop is an ordinary OCI artifact, not a bespoke installer.

```sh
skopeo inspect docker://ghcr.io/tuna-os/yellowfin:gnome | jq '{Architecture, Digest, Layers: (.Layers | length)}'
```

On screen: an arch, a digest, a layer count. Say the digest out loud or caption
it — it is the thing shot 3 rolls back to.

### Shot 2 — upgrade (0:30–1:45)

**Proves:** updates are atomic and staged, not in-place mutation.

```sh
bootc status                 # before: booted image + digest
sudo bootc upgrade           # stages the new deployment
bootc status                 # after: staged deployment alongside the booted one
sudo systemctl reboot
```

The frame that matters is the second `bootc status`: **two** deployments, the
booted one untouched and the new one staged. That side-by-side is the whole
argument for atomicity and it is invisible if you cut straight to the reboot.

### Shot 3 — roll back (1:45–2:45)

**Proves:** the previous state is still there, and reverting is one command —
not a restore from backup.

```sh
bootc status                 # now booted into the new digest
sudo bootc rollback
sudo systemctl reboot
bootc status                 # back to the shot-1 digest
```

Show the digest matching shot 1. A reviewer who has been burned by "atomic"
claims is checking exactly this.

### Shot 4 — schedule it (2:45–3:30)

**Proves:** the same artifact is a Kubernetes-native workload — the Corral
angle, and the reason this is a platform-engineering talk and not a desktop
one.

```sh
just corral-build yellowfin gnome
kubectl get vmi -w
```

On screen: the VM object being created and scheduled. If the cluster is not
available on the recording machine, **cut this shot rather than fake it** — a
three-shot video that is entirely real beats a four-shot video with one
reenactment, and reviewers do notice. Say in the abstract that Corral is shown
live in the talk instead.

## Cutting rules

- **No terminal that a viewer cannot read.** Large font, no tiling, one pane.
- **Keep the mistakes out, keep the waits in** — a two-second cut over a
  reboot is fine; speeding up `bootc upgrade` to make it look instant is the
  kind of thing that gets asked about in Q&A and cannot be answered well.
- **No audio required.** Both CFPs attach this as evidence, not as the talk.
  Captions beat narration for a reviewer skimming at 2×.
- **Nothing on screen that is not meant to be public**: `GH_TOKEN` in a shell,
  a registry login, a real hostname, the contents of `~/.ssh`. Record in a
  throwaway VM user, and watch the playback once before uploading.

## After recording

- Attach to the FOSDEM submission (see the checklist in
  [CFP-FOSDEM-2027.md](./CFP-FOSDEM-2027.md)).
- Reuse the same file for SCaLE 21x — its draft is written to match this
  running order, so no reshoot is needed unless the talk changes.
- If a command here drifted during the dry run, fix it in this file in the same
  sitting.
