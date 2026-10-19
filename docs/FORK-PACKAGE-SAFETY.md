# Fork package removal qualification

Normal fork preparation still rejects every removal. The standalone
`build_scripts/lib/fork-removals.sh` candidate is for disposable qualification
roots only. It needs `TUNAOS_FORK_REMOVAL_QUALIFICATION=1`; normal builds do not source it. This switch is not a declaration of production support.

Use exact names for packages. The adapter rejects missing targets.
A fixed policy protects boot, network, security and system packages.

It uses native dependency checks and never requests recursive cleanup or forces
broken dependencies. RPM families use `rpm -e --test` then `rpm -e`; Debian uses
`dpkg --dry-run --remove` then `dpkg --remove`; Arch uses `pacman -R`.
This is removal, not purge. Package configuration files may remain. The native tool checks the complete set together when its interface supports it.

A native error
stops the operation and propagates to the caller.
Package scripts can fail after
partial changes; discard a failed qualification root and do not retry it as a successful image. Do not run package transactions concurrently.

The adapter rejects Portage. `emerge --deselect` does not uninstall, while unmerge alone
does not establish the reverse-dependency protection required here. Existing
legacy removal wrappers remain unchanged and are never used by this candidate.

## Evidence and promotion requirements

`tests/test_fork_removals.py` executes exact dispatch with stub binaries. These
are failure-propagation tests, not solver evidence.
`tests/test_fork_removals_native.py` builds empty packages for Debian in a
private dpkg database. It checks native refusal to remove a depended-on package,
unchanged installed inventory after refusal, exact unrelated-package removal,
missing-target failure and dependency-ordered removal. The test does not change packages or repositories on the host. Its wrapper redirects the database/root
and lets the test use an unprivileged fixture; dependency checks are not disabled.

This fixture does not qualify RPM, Arch, Portage, maintainer scripts, real desktop
packages, image boot, or install behavior. Each family needs native fixtures and
full image qualification before the host compiler or image consumer may accept
removal intent. The name policy is intentionally conservative and adds to the native checks for dependencies. It does not prove that all leaf packages are safe to remove. A later production adapter must also protect the resolved
base/desktop requirements and check the exact changes to installed packages and image
contracts. Keep source receipts tied to the exact tested implementation.

## Protected baseline qualification

The separate `build_scripts/lib/fork-removal-inventory.py` wrapper protects the
inventory of all packages from both base and desktop stages. It is
qualification-only; it does not change the production removal rejection.
Run it only in a disposable root with no concurrent package operations.

Capture each stage before adding the optional packages under test:

```sh
python3 build_scripts/lib/fork-removal-inventory.py capture \
  --manager apt --stage base --source-sha256 "$SOURCE_SHA256" \
  --image-digest "$IMAGE_DIGEST" --output base.json
# Finish the desktop stage, then capture its complete inventory.
python3 build_scripts/lib/fork-removal-inventory.py capture \
  --manager apt --stage desktop --source-sha256 "$SOURCE_SHA256" \
  --image-digest "$IMAGE_DIGEST" --output desktop.json
# Add the qualification fixture package, then request its exact removal.
TUNAOS_FORK_REMOVAL_QUALIFICATION=1 \
  python3 build_scripts/lib/fork-removal-inventory.py qualify \
  --manager apt --source-sha256 "$SOURCE_SHA256" --image-digest "$IMAGE_DIGEST" \
  --base base.json --desktop desktop.json --remove fixture-spare \
  --receipt removal.json
```

Supported inventory backends are apt, dnf, zypper and pacman. RPM queries retain
all installed versions and architectures; dpkg needs each package to be fully installed.
Pacman records architecture as null because its inventory query does not report
it. Portage has no supported inventory/removal adapter here.

Version 1 of the baseline JSON schema has exactly `schema_version`, `stage`,
`package_manager`, `source_sha256`, `image_digest` and `packages`. Each package
record has exactly `name`, `version` and `architecture`. Stage is `base` or
`desktop`; identities need a SHA-256 digest of the source, in lowercase, and
`sha256:<64 lowercase hex digits>` image digest. The tool rejects inventories that are empty, duplicate records/JSON keys, invalid records,
mismatched identities, symlink paths and pre-existing output files.

The tool protects all names from either capture, including baseline user-facing
applications and leaf packages. If desktop setup upgraded a base package, its
desktop version set becomes the expected protected version set. A base name
omitted from the desktop capture remains protected. Missing or changed protected
records stop qualification before mutation. The caller cannot add exceptions.
The static policy for package protection in the native helper also still applies.

After native removal, the complete inventory must equal the prior inventory
minus only the named targets, with no other removals, additions or version
changes. A successful receipt records both inventories, requested names, baseline
file hashes and provenance with status `qualified-fixture-only`. Failure produces
no success receipt. Checks after removal cannot undo changes from package scripts; discard
the root after any failure, including a receipt-write failure.

The caller supplies source/image identities; this standalone tool does not verify their origin.
It cannot prove that the root came from that image or that baseline files are authentic.
Production integration must capture inventories in trusted build stages, verify
provenance and prevent changes to those files. These fixtures do not qualify
arbitrary scripts, active services or security policy. Inventory protection and
native dependency evidence are necessary but do not replace image qualification.

`tests/test_fork_removal_inventory.py` tests schema, provenance, baseline drift,
protected names, failure propagation and exact deltas. Its native dpkg test uses
an isolated package database to capture both stages, reject protected removal,
and remove an additional fixture with a verified receipt.
