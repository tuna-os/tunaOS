# Native removal checks

The standalone entrypoint in `build_scripts/lib/fork-removals.sh` needs
`TUNAOS_FORK_REMOVAL_QUALIFICATION=1`. It shares a private native primitive with
the [reviewed optional adapter](FORK-OPTIONAL-REMOVALS.md). That adapter accepts
only fastfetch for GNOME on Grouper and Yellowfin, with stricter checks.
A test pass does not authorize arbitrary removals or prove a desktop image works.

## Small container lane

`.github/workflows/fork-removal-native.yml` runs on changes to the candidate,
tests or runner. It can also run by workflow dispatch. It uses official images from Docker, separate from desktop builds:

- `docker.io/library/almalinux:10`: RPM through both the `dnf` and `zypper`
  candidate branches. This tests the shared RPM backend on AlmaLinux. It does
  not test a native openSUSE or Fedora image.
- `docker.io/library/archlinux:base`: pacman on Arch Linux.

The runner records the pulled image ID and repository digests, then starts that
image by that ID. It records the source commit, helper/test hashes, distro
release, installed package versions and repository settings. Tags and upstream
package repositories can change. These records identify the tested environment;
they do not claim that later runs resolve identical packages.

Run from a checkout with Docker and Python 3. Choose a new output directory for each run:

```sh
scripts/test-native-fork-removals.sh rpm /tmp/removal-evidence-rpm
scripts/test-native-fork-removals.sh pacman /tmp/removal-evidence-pacman
```

Each job has a 15-minute limit. Pulls, package setup, test processes and native
commands have shorter limits. The source mount is read-only. Containers use temporary roots for packages. Tests never install into or remove
from the runner's package database.

A missing native tool or root permission fails the
required family. The evidence check fails if cases skip or do not run.

## What the fixtures check

Three locally built packages have one text file each and no package scripts.
The app depends on the library. The spare has no dependencies. Each backend must:

1. Refuse an invocation without the qualification gate.
2. Refuse the library removal while the app remains, including a batch with the
   spare first. Installed versions and all fixture payload hashes must stay equal.
3. Reject unknown targets, including a batch with the spare first, with no
   change to that package or payload state.
4. Remove only the spare and its file, then reject its repeated removal.
5. Reject RPM version/architecture selectors that resolve to a different name.
6. Remove the app and library in dependency order, ending with an empty inventory.

Other tests call `fork-removal-inventory.py` through its CLI. They
capture the library as a base, add the app and capture the desktop, then add the
spare. The wrapper must protect both baseline names without state changes. It
must remove only the spare and save an exact delta receipt. Source hashes identify the code. The records also name the image by its actual ID.

Each test saves its exact before/after inventory, payload hashes, exit status
and command output. Successful jobs upload these JSON records and JUnit results.
A workflow run or a local skip is not native proof; inspect the result artifact.

The wrappers redirect paths only. They do not force dependencies, disable
signatures or replace errors with success. RPM uses its existing local-file
policy. Pacman reads the image's unchanged `/etc/pacman.conf`, including its local
package policy. If an image needs signatures for local fixtures, setup fails.
The test must not work around that policy.

Sources: [RPM root, database and erase options](https://rpm.org/docs/4.20.x/man/rpm.8.html),
[pacman root and database options](https://man.archlinux.org/man/pacman.8.en),
[Arch signature defaults](https://wiki.archlinux.org/title/Pacman/Package_signing),
[official AlmaLinux image](https://hub.docker.com/_/almalinux), and
[Arch Linux image](https://hub.docker.com/_/archlinux).

## Limits and diagnosis

These tests check dependencies with native tools and remove exact fixtures.
They do not cover failures in package scripts, every distro version, full
base/desktop package sets, solver replacements, desktop behavior, boot or install.
A package script failure can change a real root before it fails; discard the root if a test fails. Portage remains unsupported.

| Symptom | Cause to check | Next step |
| --- | --- | --- |
| Local suite reports six native skips | RPM/pacman tools or container root are absent | Run the small native lane. Do not count local skips as native passes. |
| CI fails with `needs tools` or `needs container root` | The required family cannot run its native backend | Fix container setup. Keep the test failure. |
| Local package signature check rejects a fixture | The image's local-file policy requires a signature | Review the image policy and fixture signing. Do not disable verification. |
| Test exits zero but evidence validation fails | Cases skipped, records are missing or the case count changed | Inspect JUnit and JSON records before changing the expected count. |
