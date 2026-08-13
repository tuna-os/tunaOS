# Q3 community recap — draft for 2026-08-22

> **Editorial status:** draft for maintainer and strategist review. Publish on
> tunaos.org only after the 2026-08-22 checkpoint decisions are recorded.
>
> Tracking: [tunaos#1345](https://github.com/tuna-os/tunaos/issues/1345)

## Suggested title

**TunaOS Q3 checkpoint: expanding the project with users and contributors**

## Draft post

Q3 has been about expanding TunaOS beyond a working build pipeline: making
more variants discoverable, making releases easier to trust, and making room
for more people to contribute. As we reach the 2026-08-22 checkpoint, here is
what changed and where we are going next.

### A healthier path from image to download

The download path is working again: tunaos.org serves the current ISO set,
and the project has verified a catalog of 179 downloadable images. GitHub
Release publishing also resumed with release assets and SBOM material. A new
browser-catalog parity gate now fails when an on-demand flavor has no
published catalog facts, so a missing entry is caught during CI instead of by
someone finding a broken download link later.

The work is not finished. Release cadence is still uneven across desktop
flavors, and desktop completeness on several non-RPM bases needs more
verification. These are visible follow-up items, not claims that every
variant has reached the same support tier.

### More ways to build a TunaOS desktop

Hummingbird and Gurnard/Pantheon are now represented in the build catalog and
are building as experimental variants. They are being brought through the
same admission and acceptance process as the rest of the portfolio; the
checkpoint will decide whether their next work stays in Q3 or moves to Q4
with an owner.

The maintainer team also adopted a flavor-equality direction: GNOME is no
longer the product definition for the project. KDE, COSMIC, Niri, XFCE, and
other supported flavors need the same catalog, release, and verification
standards. This is a change in operating discipline, not just a change to a
table in the README.

### A first external contributor is now part of the story

In August, shimonenator became TunaOS's first recurring external human
contributor, with work spanning EL10/OBS design, the image-factory completion
gate, flavor-equality documentation, and related repository fixes. Thank you
for turning an initial contribution into an ongoing collaboration.

The next step is to make that path easier for the next person. We are
curating good-first issues, improving the contributor documentation, and
tracking whether new contributors can find a useful second task. If you want
to help, start with an issue labeled `good first issue` or `help wanted`, or
join the [TunaOS Matrix room](https://matrix.to/#/%23tunaos:reilly.asia) and
tell us which variant, desktop, or documentation area you use.

### What the checkpoint decides

The checkpoint is an explicit decision point for Q3 carryover. For each open
goal, maintainers will either staff it with an owner and a concrete first PR,
descope it to Q4 with a named owner, or drop it. The community-facing result
will be recorded here before publication:

| Area | Decision after 08-22 | Next step / owner |
|---|---|---|
| Bonito Fedora GA | **[STAFF / DESCOPE / DROP]** | **[fill after checkpoint]** |
| Redfin RHEL 10 alpha | **[STAFF / DESCOPE / DROP]** | **[fill after checkpoint]** |
| RFC governance | **[STAFF / DESCOPE / DROP]** | **[fill after checkpoint]** |
| ADR coverage | **[STAFF / DESCOPE / DROP]** | **[fill after checkpoint]** |
| Flavor release parity | **[STAFF / DESCOPE / DROP]** | **[fill after checkpoint]** |
| Package sourcing policy | **[STAFF / DESCOPE / DROP]** | **[fill after checkpoint]** |

This makes the roadmap legible: a goal that moves to Q4 is not silently
forgotten, and a goal that stays in Q3 has a person and a next action behind
it.

### Join the next phase

You do not need to know the whole build system to participate. Try an image,
report an install or desktop issue, improve a guide, or take a small labeled
issue. The project is especially interested in testing the non-GNOME flavors,
checking downloads on real hardware, and helping turn the new variant catalog
into reliable releases.

Thanks to everyone testing images, reviewing changes, filing issues, and
contributing code and documentation. Q3 is not a claim that every goal is
complete; it is the point where we make the next set of commitments visible.

## Publication checklist

- [ ] Fill the decision table from `Q3_CHECKPOINT-2026-08-22.md` after the
      checkpoint; do not publish placeholders.
- [ ] Confirm the contributor acknowledgment and retention status with the
      contributor before naming them publicly.
- [ ] Refresh the download count, release-asset status, and variant wording
      against the current README and build catalog.
- [ ] Replace the `good first issue` sentence with the current curated issue
      list once #1362 has landed.
- [ ] Publish on tunaos.org/blog and cross-post the link to Matrix #tunaos.
- [ ] Link the final post from issue #1345 and record the publication date.
