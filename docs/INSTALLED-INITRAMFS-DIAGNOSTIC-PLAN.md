# Installed boot diagnostic candidate

Integrated base: `cf04a15e5e2bb59556f209e7bdca891a5878e9ae` (#3431).
Branch: `codex/installed-initramfs-diagnostic`.
This candidate has source tests only. No ISO, VM or disk inspection has run.
Publication and dispatch need parent review.

## Entry point

`scripts/diagnose-installed-luks.py` takes `--iso`, `--binding`, `--provenance`,
`--tool-lock` and `--output`. Output must be a new private directory.
The binding must come from the existing native artifact fetcher. The source
must be clean and match the collector commit in the input. Run identity
must match the current GitHub job. The only target is Skipjack/GNOME amd64/v2.

The old ISO artifact 12560149748 is absent. Run 40093907774 did not retain its
installed disk. The next run therefore needs one fresh producer and one fresh
installation. Inspect the installed disk, not the live media.

The existing workflow verifies the new ISO's embedded receipts. The report
records the identity of media inputs. It does not prove the identity of installed root.

## Process and disk boundaries

The supervisor owns each QEMU through a unique systemd invocation.
The proxy removes `-daemonize`. It preserves boot arguments.

The collector closes launch requests and checks same-user open descriptors.
The new private directory excludes other users; this trusts the CI host root.
It needs process exit. A pidfile does not prove ownership. Stop failures block inspection.
TERM/INT and timeouts stop owned processes before the result.

Read only the new qcow2 file. Refuse links, parent images, external data and unknown qcow features. Before/after hashes must agree.

 No host disk, host mount, root unlock or guest command is used.
Libguestfs opens the disk read-only with network disabled. It discovers GPT
ESP/XBOOTLDR, or a Linux partition labelled `boot`. Refuse root layouts.
Support only vfat/ext4. For ext4, disable journal replay.

Check paths in BLS entries, hashes of kernel/initrd files and boot metadata,
Plymouth components, DRM modules and known kernel-config symbols. Reads use
small chunks. Parse newc, gzip, XZ and ZSTD without extraction.
Never follow links or create devices. Refuse UKI, encrypted boot and unknown formats. Boot selection remains unresolved;
static file presence is never driver initialization or proof of a prompt.

Missing kernel config means unknown, not disabled or absent.

## Budgets and outputs

Each job in the diagnostic route has an explicit time limit.
The reusable caller has no runner of its own; its jobs appear below.

| Job | Minutes |
|---|---:|
| live-iso-bootc.yml/diagnostic-preflight | 3 |
| live-iso-bootc.yml/build | 120 |
| iso-e2e.yml/generate-matrix | 5 |
| iso-e2e.yml/e2e | 120 |

Total job budget: **248 minutes**. This excludes queue time.
This sum covers one Skipjack/GNOME cell and one run, with no retry.
It is a limit, not a measured duration.

Normal matrix generation keeps its prior 360-minute default as an explicit value.
The opt-in path runs one diagnosis. Normal readiness and strict routes do not change.

The supervisor allows 45 minutes for the strict run. Collection has 10 minutes. QEMU uses 4 CPUs/4096 MiB; the later appliance uses 2 CPUs/1024 MiB.
The disk is at most 64 GiB virtual/65 GiB actual. File reads have a 256 MiB
per-file and 512 MiB total cap; archive expansion has a 512 MiB cap. Accept at most 32 partitions, 16 entries per partition and 8 kernel candidates.

The inspector has a 2 GiB address-space limit and a process timeout.

Upload exactly `installed-boot-diagnostic/report.json` and `manifest.json`.
Report limit: 1 MiB. Proposed retention: 3 days. Never upload disks, binaries, raw logs, archive lists, passphrases, keys or private files.

Raw initramfs bytes may contain secrets; they remain in private process memory.
The report has fixed component keys, hashes and redacted boot arguments.
It cannot certify the absence of embedded secrets.

Diagnostic and strict results are separate. A failed boot keeps its exit code
even if collection passes. Missing evidence never produces qualification.
Preserve the default harness path and NativeISOQualification/v2.

## CI tools and remaining checks

The proposed setup for Ubuntu 24.04 uses signed packages from Ubuntu:
`python3-guestfs=1:1.52.0-5ubuntu3` and
`requirements-iso-diagnostic-apt.txt`. It pins QEMU x86, common, data and utils
to `1:8.2.2+ds-0ubuntu1.18` at both install steps. Do not substitute versions. See the official
[guestfs package](https://packages.ubuntu.com/noble/python3-guestfs) and
[QEMU package](https://packages.ubuntu.com/noble/qemu-system-x86).
Record the QEMU path/hash and guestfs version in the tool lock: `1.52.0`.

The normal ISO harness also needs its existing OVMF, swtpm, OCR and shell tools.
No local runtime tools were installed or probed by execution.

The fixture suite uses temporary ordinary files and mock process/guest APIs.
It rejects runtime launches.

Real CI must check tools, resources, boot layout and process cleanup.
No run has occurred. Review must precede publication and dispatch.

## Compression and layout review

At this base, `build_scripts/26-packages-post.sh:78` uses `dracut --zstd`.
Install `requirements-iso-diagnostic.txt` from PyPI. It pins `zstandard==0.25.0`.
The parser checks that version.

It caps the window at 64 MiB and reads at most
64 KiB per step. Each archive has a 30-second deadline, 64 compressed members,
100000 entries and a 512 MiB expansion cap. Each ZSTD frame has at most 100000
blocks.

It checks frame bounds before decode and rejects missing bytes or bad
checksums. It does not extract paths. Tests cover these limits and joined frames.

`live-iso/common/src/installer-recipe-backend.sh` selects GRUB or systemd from
image contents. The stock recipe is not proof of the installed layout.
BLS entries with separate kernel/initrd files are supported. The parser refuses UKI, encrypted
boot, XFS boot and unknown layouts. Actual boot selection is unknown.
No retained installed disk was available for this review.

## Missing evidence

If collection fails, retain the fixed reason and strict exit code. Do not treat
file presence as a loaded driver. Do not retry with root unlock or changed boot
arguments. Resolve the missing format or provenance before a new run.

## Registered dispatch path

Use the existing `live-iso-bootc.yml` workflow on
`codex/installed-initramfs-diagnostic` after publication approval:

```sh
gh workflow run live-iso-bootc.yml --repo tuna-os/tunaOS \
  --ref codex/installed-initramfs-diagnostic \
  -f variant=skipjack -f flavor=gnome -f build_runner=github \
  -f installed_boot_diagnostic=true
```

This is a proposed command, not an executed dispatch. No new workflow needs
registration on main. The existing reusable `iso-e2e.yml` consumes the exact
artifact from the current run and `run_attempt` after build success. Its existing media checks
run before diagnosis. The input defaults to false. No schedule enables it.

The owner merged main into the feature base at `cf04a15e` after `3e61b0e`.
The next diagnostic uses that new source, not byte-identical inputs from the old run.
TOML adapters, package policy and transport contracts changed in that merge.

The Brew and Utah OCI digests also changed. The tacklebox pin stayed at `d3070b5`.
Record the new producer commit, media receipts and installed file hashes.
This is a fresh diagnostic reproduction, not an inspection of the old disk.

QEMU, harness and inspector helpers run in separate system services at the
runner UID. These services do not delegate cgroup control.

They use
`KillMode=control-group`, a 3700-second cap and a 20-second stop limit.
The service retains its state after exit. The collector checks the actual
invocation, user, cgroup path and policy. Explicit stop must succeed. The unit
must then be inactive or failed, and its cgroup
must be absent or report `populated 0`. This includes helpers that change sessions.

Missing systemd, cgroup v2 or noninteractive sudo stops the diagnostic.
No local service ran. Tests use mocks for commands and cgroup files.

The collector reads installed BLS candidates after the failed cold boot and
confirmed process stop. It records a configured default only when an exact
saved-entry or loader default matches. It does not claim runtime selection.
If that mapping is absent or ambiguous, selection remains unresolved. This is
an explicit evidence limit, not a successful BLS-selected boot claim.

The diagnostic path skips the existing KVM udev and rootless security setup.
It needs existing KVM access, user mappings and user-namespace access. Missing
access stops the run; the workflow does not change those settings.

The diagnostic serial observer sends no input. A visible password prompt stops
observation before unlock; an emergency shell receives no commands. The default
strict path keeps its normal behavior. A prompt-only stop is diagnostic evidence,
not a successful cold boot. All failed starts remain in the service registry.
The collector blocks inspection until all services have proof of closure.

The preflight job checks existing KVM access before the costly producer. The
consumer repeats that check. The two jobs use separate Ubuntu 24.04 runners;
one successful preflight does not prove access on the next machine. A missing
capability fails without a permission change or fallback run.

Artifact transfer has a 20-minute cap in diagnostic mode. The media hash has a
5-minute cap. The 120-minute job limit includes setup, transfer and collection;
phase limits do not extend that shared limit. Slow setup can still prevent
collection. A timeout or absent artifact must remain a failed diagnostic.

### Workflow contract integration

Test run `40228536871` found four failures in the workflow contracts.
The timeout expression now uses nested branches with literal bounds.
The check of budgets treats each route on its own.
It checks both truthiness values and rejects unknown budgets.

The KVM preflight has an explicit guard for manual dispatch.
It cannot run on a PR. The diagnostic still needs KVM; it has no TCG fallback.
The runner check accepts only the three declared choices.

Rootless setup checks existing access before any build command.
In diagnostic mode it exits before any change to host security.
Absent mappings or a failed namespace probe still cause failure.
Strict mode retains its setup behavior.

Albacore run `40228536828` failed before boot.
Its published ISO lacked `etc/tunaos/live-source.json`.
No installed-disk diagnostic ran. Do not relax provenance to accept that media.
Use a fresh producer with the exact artifact identity.

### Setup failure evidence

Run 40244509229 failed before ISO fetch: `qemu-system-x86=.16` needed `qemu-system-common=.16`, but APT selected `.18`. The Noble index lists all four QEMU packages at `.18`. Both install steps now use the same lock file. APT
still checks signatures on repository metadata; missing pins fail the job. This is
a host tool change, not a product image change.

An always-run step uses only Python's standard library to write a failure
report if the collector wrote none. It records step outcomes and declared
input IDs as unverified, not boot or stop evidence. It copies no logs or
error text. The report limit is 4 KiB, with the same two-file upload and
three-day retention. Existing evidence is kept; incomplete evidence fails.

A job timeout or lost runner can still prevent upload. No report means no
evidence. The job and campaign time limits stay unchanged.

Inputs must name the same producer run, `run_attempt` and source.
A retry with this repair needs a fresh whole run. Reuse of an older ISO
needs a separate input contract for diagnostics; this change does not add one.
