# Local fork-config consumer preview

This is an opt-in, experimental continuation of [RFC 013](rfc/rfc013-single-fork-config.md).
Normal builds still use the existing catalog, manifests and brand defaults.
Nothing here publishes images, changes admission, or qualifies a desktop for release.

## Start a new fork config

Use Python 3.10+, PyYAML and the existing build tools (`yq`, `jq`, Git, Bash).
Run `just setup-config` in an active virtual environment before these commands.
Install Pillow on the preparation host only if the config supplies a wallpaper.

```sh
# Create a NEW config; copy referenced assets beside that file.
mkdir -p /tmp/harbor
cp -a examples/fork/assets /tmp/harbor/
python3 scripts/resolve-fork-config.py \
  --init-template examples/fork/harbor.template.yaml > /tmp/harbor/harbor.yaml
python3 scripts/resolve-fork-config.py /tmp/harbor/harbor.yaml > /tmp/harbor-plan.json
python3 scripts/prepare-fork-config.py /tmp/harbor/harbor.yaml --output /tmp/harbor-preview
```

The sample adds `htop` to Yellowfin and Ubuntu GNOME.
It also tries to add `fastfetch` to Yellowfin as an optional package.
It changes the homepage/docs/support URLs and supplies a JPEG with a blue gradient.
It uses a namespace for local images.

These two example cells do not define a second matrix.
The compiler resolves **all selected enabled cells** from the current catalog.
Each cell must fit the supported subset below before the compiler writes any context.
Cells on hold stay in the review plan; the compiler never executes them.
Production workflows, their GNOME-only PR selection, and release gates stay unchanged.

The output directory must be new and outside the checkout.
It contains the full source receipt, unchanged review plan, `builds.json` and an isolated source context for each cell.
Each context contains a generated `manifests/fork-config.json` and optional content-addressed assets.
The compiler copies only Git-tracked inputs; stage new source files before you initialize the pin.
It does not rewrite the source checkout.
A change to source bytes during the copy fails the receipt comparison.

To also run each prepared cell through the existing local build engine:

```sh
python3 scripts/prepare-fork-config.py /tmp/harbor/harbor.yaml \
  --output /tmp/harbor-build --build
```

This needs the normal container-build tools and permissions.
It builds sequentially and stops on the first failure.
Images use local preview tags with platform suffixes; the builder does not rechunk them.
It never pushes, creates media, promotes, or changes production tags.

Fork image names use canonical variant IDs.
Thus, `bonito-rawhide` and `flounder-sid` do not collapse into upstream publication aliases.
Inspect `builds.json` for the exact environment, resolved base and local tag.
Use a new output directory for each try.
The builder keeps output from failed builds for diagnosis.

## Supported operations

- Desktop routes with direct manifest support through the six existing Containerfiles:
  RPM, Ubuntu, Debian, Arch, openSUSE and Gentoo.
  Existing flavor/base resolvers supply the route and exact upstream base for each platform.
  The compiler refuses base and overlay flavors until contracts define their package phases and parent closure.
  For upstream bases with deliberately mutable tags, the compiler keeps those tags.
  It emits an explicit warning and sets `base_digest_pinned: false` in `builds.json`.
  Source pins do not pin remote bytes; existing digest-pinned bases stay unchanged.
- Existing precedence: global → variant → desktop → exact cell.
  The phase-1 rules still govern stable deduplication of packages and conflicts.
- Required and optional additions of native packages on dnf, apt, pacman, zypper and Portage.
  Use plain package names, or `category/name` on Portage.
  The compiler refuses options, groups, file/URL installs, archives, globs and version expressions.
- Additional repositories only on dnf/zypper: literal HTTPS repository/key URLs
  and filename-safe IDs.
  The adapter uses `fork-<id>` as the namespace and needs both metadata and package signatures.
  The fork author explicitly chooses the key URL; there is no unsigned-repository fallback.
  Native trust/repository canary builds are still needed.
  Apt suites/components, pacman trust, and Portage overlay identities need an expanded family-specific schema.
- Homepage, documentation and support URLs, plus a JPEG wallpaper that you generate before the build.
  The JPEG must contain one frame, with 1..8192 pixels per axis and a maximum size of 16 MiB.
  The host decodes the JPEG and records its SHA-256; runtime helpers verify those exact bytes.
  Supply `branding.wallpaper` as a config-relative path.
  Overrides of wallpaper for Tuna Desktop fail until tests verify its upstream consumer for that setting.

The host prepares assets **before** the build; the image never generates them silently.
Referenced assets need not be Git tracked.
The compiler records their materialized hashes separately.

The adapter runs after the stock desktop packages/hooks and before experience checks.
It sets up repositories first, then adds required packages, then tries each optional package.
Required failures fail the build.

Fork apt installs use `--no-remove`, including retries.
Other managers keep their existing solver flags.
Tests of command calls do not prove replacement or dependency behavior in native transactions.
The adapter records failures of optional packages in a per-cell receipt under `/usr/share/tunaos/fork-config/packages`.

On a second call from a desktop script, it skips only an exact completed manifest.
A mismatched receipt fails.
The receipt contains the command outcomes; it does not independently solve dependencies or audit installed packages.

All removals fail explicitly.
For pacman, the existing wrapper does not report errors from removals.
Portage only deselects atoms.
A denylist cannot stop a solver from a transitive removal of boot/session dependencies.
Safe removals need their own transaction and protection design.

The helpers reapply URLs and wallpaper after stock writers on both desktop paths.
Verification uses the installed manifest/assets and the receipt in image-info.
Stock checks remain in place; the adapter changes only validated expectations for fork URLs and vendors.
Generated manifest and asset hashes also enter the build cache key.
For different forks, identical shell scripts do not let the builder reuse a stock layer.

## Source pins and templates

A real fork config always needs an exact `catalog.sha256`.
The review tool still rejects stale pins; this preview does not refresh them automatically.
`--init-template` accepts only a template **without** a catalog field.
It produces a new config pinned to the current bytes of tracked sources.
It refuses an existing config, even if its pin is stale.
This initialization explicitly selects current sources; it does not establish image acceptance.

Committed stock/fork examples are templates.
Updates to routine dependencies need no false approval of an example's frozen digest and do not break unrelated PRs from Renovate.
Tests initialize a fresh stock config and assert exact parity with the stock catalog.
Separate tests prove that a source mutation invalidates the old pin in a real config.
Review the source receipt before you manually update a real fork's pin.

## Next slices and acceptance

The compiler refuses name and logo overrides.
A complete rebrand must update fish names, CPE and console/fastfetch labels.
It must also update GNOME/KDE/COSMIC, greeter/Plymouth, and embedded GResource assets for the installer.
The next brand adapter must prepare those assets before build and record input/output hashes.
It must adapt verification for each consumer and prove visible behavior in the installer, boot and desktop.
URL changes alone do not constitute that full rebrand.

Rollout still needs safe removal plans, non-RPM repository schemas, base/overlay parent closure, and integration with the production matrix.
It also needs stock and fork canaries per family/desktop, with evidence from boot, login, install and screenshots.
Tests with temporary roots and stubbed package/builder commands prove only the connections between consumers and their failure behavior.
`uname` validates architecture, not amd64/v2 instruction support.
A green result from source-level tests cannot replace those gates.

Fork preview builds use `--no-cache`. Stock builds retain their cache behavior.
Some legacy stages declare the cache argument after their base hooks. Gentoo
has a separate branch for desktop builds. Tests must prove each stage before
fork builds can reuse layers.
