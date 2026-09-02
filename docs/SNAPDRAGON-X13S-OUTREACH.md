# Snapdragon X Elite / X13s Community Outreach Draft

> Status: **draft** — for maintainer review and explicit approval before any
> external contact.
> Tracking issue: [#1374](https://github.com/tuna-os/tunaOS/issues/1374).
> Prepared: 2026-08-13.

## Story

**Working title: TunaOS on Snapdragon X Elite laptops — an honest Bonito and
Dakota X13s story**

Windows-on-ARM laptops are becoming interesting Linux hardware, but support
still depends on the exact model, firmware, kernel support, and desktop image.
The Lenovo ThinkPad X13s is a useful reference device because it is a known
ARM laptop target rather than an abstract architecture claim. TunaOS already
has device-specific documentation for [Bonito on the X13s](https://github.com/tuna-os/docs/tree/main/docs/bonito-x13s)
and [Dakota on the X13s](https://github.com/tuna-os/docs/tree/main/docs/dakota-x13s).

The outreach should present those pages as a starting point for real-hardware
testing, not as a promise that every Snapdragon X Elite laptop is supported.
Readers should be able to see the install path, what is known to work, what is
still experimental, and where to report a result.

## Suggested post

TunaOS has device-focused documentation for trying its Bonito and Dakota ARM
images on the ThinkPad X13s. This is aimed at Linux users who already own an
X13s or are evaluating Snapdragon laptops and want an immutable, bootable
container desktop rather than a conventional package-installed root.

The useful part is the test loop: follow the matching device guide, record the
image and kernel versions, check suspend, audio, display, networking, and
external-device behavior, then report both successes and failures. Results
from real hardware are more valuable than a generic “ARM supported” label, and
different Snapdragon models should not be treated as interchangeable.

Start with the [Bonito X13s guide](https://github.com/tuna-os/docs/tree/main/docs/bonito-x13s)
or the [Dakota X13s guide](https://github.com/tuna-os/docs/tree/main/docs/dakota-x13s),
then join the [TunaOS Matrix room](https://matrix.to/#/%23tunaos:reilly.asia)
for discussion. Please include the laptop model, firmware state, image tag,
and the exact behavior observed when asking for help.

## Distribution plan

1. Ask maintainers of the Qualcomm Linux community channels whether a short
   technical announcement is welcome and which format they prefer.
2. Prepare a concise, hardware-focused post for `r/linuxhardware` and review
   its current self-promotion rules immediately before posting.
3. Share the two device guides and solicit reports from X13s owners; do not
   imply support for Surface, Dell, Lenovo Yoga, or other Snapdragon models
   without model-specific evidence.
4. Feed reproducible reports back into the canonical device documentation.
5. Add an ecosystem or adopter entry only after a public relationship or
   independently verifiable use exists. This draft does not change
   `ADOPTERS.md`.

## Maintainer checklist

- [ ] Confirm the linked device guides and download instructions are current.
- [ ] Confirm the Bonito/Dakota status and known limitations on real X13s
      hardware.
- [ ] Approve the final wording and posting identity.
- [ ] Check community rules and obtain channel approval where required.
- [ ] Record incoming hardware reports and link any resulting documentation
      fixes to #1374.

## Guardrails

- No external contact or posting without maintainer approval.
- No cold claims that TunaOS is an adopter of Qualcomm or any laptop vendor.
- No broad “Snapdragon X Elite supported” claim based only on X13s results.
- Keep known limitations visible; this is a testing invitation, not a release
  announcement.
