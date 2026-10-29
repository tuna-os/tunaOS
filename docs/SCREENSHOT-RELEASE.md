# Screenshot release URLs

Four workflows upload each `-latest` PNG twice. One copy goes to R2. The other
goes to the GitHub Release with the tag `screenshots`, which needs no R2
account (epic #3470). The R2 upload stays as it was, so the
`download.tunaos.org` URLs stay valid while the docs site moves over.

| Workflow | Kind | R2 key |
|---|---|---|
| `weekly-desktop-screenshots.yml` | `desktop` | `screenshots/<variant>-<flavor>-latest.png` |
| `weekly-qcow2-screenshots.yml` | `boot` | `screenshots/boot/<variant>-<flavor>-latest.png` |
| `installer-screenshots.yml` | `installer` | `screenshots/installer/<name>-latest.png` |
| `installer-smoke.yml` | `installer` | `screenshots/installer/smoke-<flavor>_<NN>-latest.png` |

## The release

- Tag: `screenshots`. It is a pre-release and never the "latest" release.
- Asset name: the R2 key without the leading `screenshots/`, with each `/`
  written as `__`.
- URL: `https://github.com/<owner>/<repo>/releases/download/screenshots/<asset>`.
- `scripts/screenshot-release.py` makes the release when it is missing and
  replaces the assets with `gh release upload --clobber`.
- The workflows upload only the `-latest` files. The dated R2 copies stay on R2.
- A name with `__` in it, or a character that GitHub would rename, fails the step.

## Key to URL

<!-- screenshot-url-table:start -->
| R2 key under `download.tunaos.org` | Release asset URL |
|---|---|
| `screenshots/yellowfin-gnome-latest.png` | `https://github.com/tuna-os/tunaos/releases/download/screenshots/yellowfin-gnome-latest.png` |
| `screenshots/installer/cosmic_01_welcome-latest.png` | `https://github.com/tuna-os/tunaos/releases/download/screenshots/installer__cosmic_01_welcome-latest.png` |
| `screenshots/installer/smoke-kde_03-latest.png` | `https://github.com/tuna-os/tunaos/releases/download/screenshots/installer__smoke-kde_03-latest.png` |
| `screenshots/boot/yellowfin-gnome-latest.png` | `https://github.com/tuna-os/tunaos/releases/download/screenshots/boot__yellowfin-gnome-latest.png` |
<!-- screenshot-url-table:end -->

Do not edit the table by hand. Run `python3 scripts/screenshot-release.py table`
and paste the output. `tests/test_screenshot_release_dual_publish.py` fails when
the table and the script disagree. A fork replaces `tuna-os/tunaos` with its own
`<owner>/<repo>`.

## When a workflow publishes to the release

A job publishes only when all of these are true:

- The event is `push`, `schedule` or `workflow_dispatch`. A `pull_request` run
  never publishes.
- The ref is the default branch of the repository.
- The job has `contents: write`. The other jobs keep the read-only workflow
  token. The only credential is `GITHUB_TOKEN`, and no R2 secret is read.

The R2 steps stay as they were. A fork with no R2 secrets still skips them, and
still publishes to its own release.

## Change for the docs site

This repository does not edit `tuna-os/docs`. When the release has the
assets, the docs site changes three files:

- `src/components/DesktopScreenshots/index.tsx` and
  `src/components/DesktopScreenshotCarousel/index.tsx`: set `SHOT_BASE` to
  `https://github.com/tuna-os/tunaos/releases/download/screenshots`. The path
  `${SHOT_BASE}/${variant}-${tag}-latest.png` stays the same.
- `src/components/InstallerWalkthrough/index.tsx`: set `SHOT_BASE` to the same
  value. Change `shotUrl` to return
  `${SHOT_BASE}/installer__${prefix}${file}-latest.png`.

The docs site does not need an index file. The components build each URL from a
variant, a flavor or a step name, and hide an image that returns 404.

## Adoption counts

Each page view of a screenshot is a download of a release asset.
`scripts/adoption-snapshot.py` leaves the `screenshots` release out of its
release and download counts, so page views do not count as adoption.
