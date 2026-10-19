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
