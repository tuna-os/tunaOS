# GNOME 51 content and publication handoff

> Unpublished draft. The release-week window has passed; this is not an
> availability announcement. Tracking: [#3064](https://github.com/tuna-os/tunaos/issues/3064).
> The original tracker [#1334](https://github.com/tuna-os/tunaos/issues/1334)
> was closed by a maintainer on September 24 because release week had passed.

## Upstream timing and scope

GNOME 51 was released on **September 16, 2026**, rather than the September 12
estimate in the original campaign. Sources: the [GNOME release calendar](https://release.gnome.org/calendar/)
and [release announcement](https://discourse.gnome.org/t/gnome-51-released/38820).
Do not backdate a TunaOS post or describe a later publication as release-day
coordination. No GNOME communications agreement or embargo is recorded here.

The [upstream release notes](https://release.gnome.org/51/) describe improvements
to Settings, Files and Calendar. For desktop administrators, these are topics
for compatibility and user-workflow testing, not evidence that a particular
TunaOS image contains or supports every upstream feature.

## Blog outline for a later verified availability announcement

Proposed title: **GNOME 51 on TunaOS: evaluating a current desktop on an EL10 base**.

1. Credit GNOME and link its release notes. Explain which upstream changes
   matter to desktop administrators, using only features verified in the image.
2. Explain the TunaOS image-factory approach: an OS base and a desktop assembled
   into a bootable OCI image. Link the [pipeline](PIPELINE.md) and
   [package sourcing policy](../PACKAGE-SOURCING.md).
3. Name only the variants and architectures with published, inspected GNOME 51
   artifacts and passing boot/login evidence. Packaging source or a successful
   package build alone does not establish image availability.
4. Describe testing and deployment using the [installation guide](INSTALL.md), after
   checking its commands against the qualified artifact. An EL base lifecycle
   does not promise the same support period for the added desktop stack.
5. Invite feedback through [the issue tracker](https://github.com/tuna-os/tunaos/issues).
   Link the actual published article and verified download page; do not invent
   a future blog URL.

## Social and upstream-community copy

These upstream-focused drafts make no TunaOS availability claim. An authorized
maintainer chooses whether and where to publish them, checks community rules,
and confirms links immediately before posting.

**Short social post**

> Congratulations to GNOME on version 51! Explore the upstream release notes:
> https://release.gnome.org/51/ . Follow TunaOS's GNOME testing and rollout work:
> https://github.com/tuna-os/tunaos/issues/3064 .

**GNOME community note**

> Congratulations on GNOME 51, and thank you to its contributors. TunaOS is an
> image factory exploring current desktops on multiple OS bases. We welcome
> packaging and desktop-testing feedback through our public tracker:
> https://github.com/tuna-os/tunaos/issues/3064 . Upstream release details:
> https://release.gnome.org/51/ .

## Availability CTA: held until qualified

The intended CTA is “Try GNOME 51 on Albacore.” Before using it, verify the
published `ghcr.io/tuna-os/albacore:gnome` artifact actually contains GNOME 51
and passes the required gates. The mutable tag does not select a GNOME major.

Only after that verification, on an existing compatible bootc installation,
the deployment example is:

```bash
sudo bootc switch ghcr.io/tuna-os/albacore:gnome
```

Follow the [installation guide](INSTALL.md) for reboot and rollback procedures. Switching
changes the deployed OS; evaluate in a disposable bootable VM first. A normal
`podman run` does not boot or validate a GNOME desktop session. Do not advertise
an ISO, architecture, immediate upgrade, or production readiness without its
own evidence.

## Publication checklist

Work through the [content claim checklist](CONTENT-CLAIM-CHECKLIST.md).
Keep live qualification evidence in the publication review rather than copying
an image-status table into this draft.

- [ ] Select the actual announcement scope and publication date; release week
      is over. Obtain maintainer approval for public messaging and accounts.
- [ ] Resolve a published digest for each advertised variant and architecture
      (including Albacore, Yellowfin and Bonito if all three are advertised).
- [ ] Record image inspection proving the installed GNOME version and package
      closure, plus boot/login runs for those same digests and architectures.
- [ ] Apply [GREEN-CRITERIA.md](GREEN-CRITERIA.md) and consult generated
      [MATRIX-STATUS.md](MATRIX-STATUS.md); build success alone is insufficient.
- [ ] Replace the outline with evidence-backed copy and validate the CTA,
      download links, supported features and rollback instructions.
- [ ] If GNOME communications coordination is desired, have an authorized
      maintainer agree timing with that team; do not imply endorsement.
- [ ] Have the authorized publisher post the approved blog and social copy.
- [ ] Record public URLs, publication time, campaign referral parameters and
      the resulting monthly referral data in [ADOPTION-METRICS.md](../ADOPTION-METRICS.md).

Repository edits can prepare this handoff. Public posting, external coordination
and post-publication measurements remain with the authorized campaign owner.
