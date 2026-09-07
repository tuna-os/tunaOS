# GNOME 51 beta testing call: EL10 backport tier

**Status**: draft — publish after the image preflight below passes  
**Tracks**: [#1717](https://github.com/tuna-os/tunaOS/issues/1717) (testing call), [tunaos-packages#320](https://github.com/tuna-os/tunaos-packages/pull/320) (GNOME 51 EL10 packaging), [#1334](https://github.com/tuna-os/tunaOS/issues/1334) (release-week post)  
**Audience**: TunaOS users, Enterprise Linux desktop testers, and GNOME beta testers  
**Prepared**: 2026-08-15

## Why this call is running now

GNOME's official release calendar lists the GNOME 51 beta tarball date as
**2026-08-01**, the release candidate as **2026-08-29**, and GNOME 51.0 as
**2026-09-12**. The beta is already in its testing window; do not describe it
as an upcoming beta when publishing this call.

TunaOS's [GNOME 51 packaging tier](https://github.com/tuna-os/tunaos-packages/pull/320)
provides the EL10 backport path: 17 ordered build tiers, a CentOS Stream 10
mock configuration, and a published-repository gate. This call asks testers to
exercise the resulting image and report regressions while there is still time
to fix packaging before 2026-09-12.

Schedule source: [GNOME Release Calendar](https://release.gnome.org/calendar/).

## Maintainer launch gate

Publish this call only after all of these checks are true:

- [ ] `https://repo.tunaos.org/gnome51/10-stream-x86_64/repodata/repomd.xml`
      returns HTTP 200.
- [ ] A public TunaOS image tag is explicitly identified as carrying the
      `gnome51` tier. Record the exact tag, digest, base, and build date; do not
      ask testers to guess a tag.
- [ ] The image passes the normal boot gate and has a working GNOME login.
- [ ] The download or image link is public and the rollback path is documented.
- [ ] A maintainer has confirmed the report destination in the
      [tunaos-packages issue tracker](https://github.com/tuna-os/tunaos-packages/issues),
      or has opened a dedicated issue for the testing wave.

If the package repository or image is not ready, publish a waitlist/update
instead of directing users to an untestable image.

## Test targets

Start with the EL10 image that the launch gate names. The expected candidates
are:

| Target | Base | Suggested use |
|---|---|---|
| `yellowfin:gnome` | AlmaLinux Kitten 10 | EL10 validation after the tier is included |
| `albacore:gnome` | AlmaLinux 10 / RHEL 10 family | EL10 validation after the tier is included |
| `skipjack:gnome` | CentOS Stream 10 | Priority target for the `10-stream-x86_64` repository |

Only test a row once its exact published image digest is announced. This table
describes candidate targets, not a claim that every row is already GNOME 51
enabled. ISOs are currently amd64-only; use an amd64 VM or machine unless the
announcement says otherwise.

## Safe testing workflow

Prefer a disposable VM or spare machine. Do not test on a machine whose only
working deployment or irreplaceable data is at risk.

### 1. Capture the starting state

```bash
cat /etc/os-release
sudo bootc status
rpm -q gnome-shell mutter gtk4 libadwaita 2>&1 | tee gnome51-before.txt
```

Record the exact image reference and digest from the announcement. Keep the
previous deployment available so `bootc rollback` has a known-good target.

### 2. Install or switch to the announced image

For an existing bootc system, replace the placeholder with the exact published
reference from the announcement:

```bash
IMAGE='ghcr.io/tuna-os/<announced-variant>:gnome'
sudo bootc switch "$IMAGE"
sudo systemctl reboot
```

For a fresh trial, use the linked amd64 ISO or a disposable VM supplied by the
announcement. Do not infer that an existing `:gnome` tag contains GNOME 51
unless the launch gate identifies its digest.

### 3. Exercise the desktop

- [ ] GDM reaches a GNOME session and the session reports the expected GNOME 51 version.
- [ ] Mutter/Wayland works at the tested display resolution and scaling.
- [ ] Settings, Files, Terminal, Software, and a Flatpak launch normally.
- [ ] Audio, networking, suspend/resume, clipboard, screenshots, and portals work.
- [ ] A second monitor, fractional scaling, or touchpad gestures work when available.
- [ ] `sudo bootc upgrade` stages successfully and the next boot is healthy.
- [ ] `sudo bootc rollback` returns to the prior deployment and the next boot is usable.

Capture the final state:

```bash
gnome-shell --version
rpm -q gnome-shell mutter gtk4 libadwaita 2>&1 | tee gnome51-after.txt
sudo bootc status
```

## How to report results

Report one result per issue or regression in the
[tunaos-packages issue tracker](https://github.com/tuna-os/tunaos-packages/issues/new/choose)
unless the announcement names a dedicated testing issue. Link back to
[tunaos-packages#320](https://github.com/tuna-os/tunaos-packages/pull/320) when
the result concerns the packaging tier itself. Include:

```text
Image and digest:
Base / hardware or VM:
Test date (UTC):
GNOME version:
bootc status / deployment:
What worked:
What failed:
Reproduction steps:
Logs or screenshots:
Rollback result:
```

Remove usernames, hostnames, serial numbers, tokens, and other private data
before posting logs. Mark a report **release-blocking** when it prevents boot,
login, networking, or rollback. Mark packaging-only conflicts with the affected
RPM names and image digest.

Please report release-blocking issues by **2026-09-05** where possible so the
maintainers can triage them before the 2026-09-12 release-week post. Testing
can continue through release week; close the call with tested images, unique
testers, regressions fixed, and unresolved risks.

## Copy-ready announcement

> **Help test GNOME 51 on TunaOS's EL10 backport tier.** GNOME 51 is in its
> upstream beta window, with the release candidate scheduled for August 29 and
> GNOME 51.0 for September 12. We have an announced TunaOS image carrying the
> GNOME 51 packages for Enterprise Linux 10.
>
> Use the exact image/digest below in a disposable VM or spare machine. Check
> login, Wayland, Settings, Files, Flatpak, audio, networking, suspend/resume,
> `bootc upgrade`, and `bootc rollback`. Report the image digest, hardware or VM
> details, GNOME version, logs, and rollback result in the linked tracker.
>
> Image: `<maintainer fills exact image and digest>`  
> Test guide: `<link to this guide>`  
> Report issues: `https://github.com/tuna-os/tunaos-packages/issues/new/choose`
>
> This is beta software. Keep a known-good deployment, and do not test it on
> your only production machine.

## Close-out for #1334

Within one week of GNOME 51.0, summarize the testing wave for the release-week
post: images and bases tested, number of distinct testers, successful upgrade
and rollback results, fixed regressions, and unresolved limitations. Testing
participation demonstrates community testing, not production use.
