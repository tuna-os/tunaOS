# Installed boot diagnostic candidate

Integrated base: `40ae2f46cde617cd03b6c85fcf024949f1cb32e1` (#3965),
which retains `cf04a15e5e2bb59556f209e7bdca891a5878e9ae` (#3431).
Branch: `codex/installed-initramfs-diagnostic`.
Run 40265940225 built a fresh ISO and completed the installer path. The check
then refused `/proc` access (`open_descriptor_scan_denied`). It collected no
initramfs data and did not qualify the boot. PR #3956 remains open.

## Integration review status

Integration `04a81cd2` retains commits `2d075cb6`, `927f8e7f` and base `824fa08c`.
This follow-up binds the root fallback to held objects and the original deadline.
Tests use synthetic proc trees, temporary files and mock systemd calls only.
They do not authorize runtime use or prove host compatibility. Runtime permission
remains a separate parent decision.

## Build-only run after the fallback change

Run `40392612254` at `2d075cb6` built artifact `12685383470`.
The diagnostic preflight and build passed. The ordinary preflight skipped as
intended, but the consumer also skipped due to its implicit `success()` check.
Thus the diagnostic was **not-run**, not collected. The green workflow result
does not prove a diagnostic run. No consumer or root fallback ran.

The consumer now needs an uncancelled workflow, a successful build and the
correct preflight. It retains the predicate for dispatch routes and excludes PR
qualification. Graph tests account for skips in all ancestors. The change
does not authorize another dispatch or privileged execution.

## Entry point

`scripts/diagnose-installed-luks.py` takes `--iso`, `--binding`, `--provenance`,
`--tool-lock` and `--output`. Output must be a new private directory.
The binding must come from the existing native artifact fetcher. The source
must be clean and match the collector commit in the input. Run identity
must match the current GitHub job. The only target is Skipjack/GNOME linux/amd64 (configured x86-64-v3 baseline).

Changed input after the base merge: `linux/amd64` replaces the prior diagnostic
request for `linux/amd64/v2`. [Skipjack configuration](../tunaos.toml) omits `/v2`
at variant level, but its GNOME flavor adds it. The native planner rejects that
configured row: its CPU baseline conflicts with native producer support.
The [CPU policy](../scripts/contracts/iso_qualification.py) assigns `x86-64-v3`
to Skipjack `linux/amd64`, while an explicit `/v2` means `x86-64-v2`.
This changes both the requested build platform and declared CPU contract.

The integration does not change the base-image pin or compiler flags. No new
image has run, and the earlier `/v2` label does not prove its actual CPU baseline.
A future run uses changed inputs. It cannot establish equivalence to, or a fix
for, the earlier `/v2` failure. Keep that earlier failure separate from new results.

The producer and consumer both validate the explicit configured target.
The consumer rejects an embedded platform that differs from that target.
Source, overlay, media and run identity checks remain in force. Checks on
`producer_attempt` and `attempt` also remain in force.

Run 40265940225 installed a fresh system but collected no disk data. A repeat
needs a new image and install. Inspect the installed disk, not live media.

The existing workflow verifies the new ISO's embedded receipts. The report
records the identity of media inputs. It does not prove the identity of installed root.

## Process and disk boundaries

The supervisor owns each QEMU through a unique systemd invocation.
The proxy removes `-daemonize`. It preserves boot arguments.

The collector checks open FDs after all QEMU and harness units stop.
On `/proc` denial, it starts a systemd unit that runs as root.

- Limits: 256 MiB, 100000 processes and 100000 FDs, and the original deadline on
  the monotonic clock. Setup and startup consume that budget. A separate bounded
  stop grace grants no extra scan time.
- Access: `CAP_DAC_READ_SEARCH` and `CAP_SYS_PTRACE`; no network. This is an
  explicit privilege expansion: the fallback enumerates FDs across all users.
  It compares device/inode metadata, not descriptor contents. `CAP_SYS_PTRACE`
  is broader than this operation. It is not a read-only capability.
- Failure: the report can keep an exit status from 0 to 255. The helper stops before disk inspection if the status is not zero. The report has no command text, environment values or descriptor contents.
- Identity: the parent holds the original disk with `O_PATH`. Only that exact
  parent PID/FD pair is exempt; other FDs in the same process still block use.
  The root helper compares the supplied original device/inode, not a new disk
  path lookup. Held ancestor descriptors and directory change times detect
  replacement. Unrelated ancestor changes can also cause conservative refusal.
- Result: the helper validates the original token and its ancestor chain before
  a descriptor write. It never truncates a path. The parent reads the held token,
  proves service stop, then checks identities and time again before the hash.
  The 0602 token stays inside the private 0700 directory on success or failure.
  No automatic unlink can remove a replacement. The token is not an upload.
- Evidence: retain the bounded denial record and the fallback outcome.
  Outcomes include clear, open, timeout, limit, start failure and cleanup failure.
  Never export raw exceptions, command lines, environments or FD target paths.

The host and other processes with the runner UID remain trusted. These controls
do not prove that systemd containment works on a particular host. Refusal blocks hash and guestfs.

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

Ubuntu 24.04 pins `python3-guestfs=1:1.52.0-5ubuntu3`. QEMU installs unpinned
from signed Noble archives. The tool lock/report records QEMU version and
SHA-256 plus guestfs `1.52.0`. The consumer checks KVM and supermin kernel
readability. See the official [guestfs package](https://packages.ubuntu.com/noble/python3-guestfs)
and [QEMU package](https://packages.ubuntu.com/noble/qemu-system-x86).

The ISO harness needs OVMF, swtpm, OCR and shell tools. The GitHub-hosted run
installed and checked runtime dependencies; no local QEMU/guestfs runtime was
installed.

The fixture suite uses temporary files and mock process/guest APIs. It rejects
VM and disk-inspection launches. The bounded run stopped before disk
inspection. A repeat must test the root-only descriptor scan and collect
initramfs metadata.

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

| Control | Diagnostic policy |
| --- | --- |
| KVM | Existing `kvm` group; no device-mode or udev change. |
| Host inputs | Runner read ACLs only on exact supermin kernel/module paths. Save and restore exact ACLs; other effective rights stay unchanged. Missing access stops. Producer checks; consumer repeats. |
| Memory | Inspector cgroup limit: 4 GiB. QEMU: 1 GiB. Parser address-space cap: 2 GiB. OOM stops inspection. Service stops; cgroup is empty on every exit. |

The diagnostic serial observer sends no input. A visible password prompt stops
observation before unlock; an emergency shell receives no commands. The default
strict path keeps its normal boot behavior. A prompt-only stop is diagnostic
evidence, not a successful cold boot. All failed starts remain in the service
registry. The collector blocks inspection until all services have proof of closure.

Preflight checks KVM, cgroup v2, systemd, ACL tools and supermin paths. Missing
items stop the job without device-mode or udev changes.

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

The rootless check runs before any build; diagnostic mode keeps rootless
settings and refuses missing mappings or a failed namespace test.
Another step gives the runner read access to the exact kernel and module inputs
for supermin. It removes those ACLs after use. It does not change KVM mode or
udev rules. Strict mode keeps its setup.

Albacore run `40228536828` failed before boot.
Its published ISO lacked `etc/tunaos/live-source.json`.
No installed-disk diagnostic ran. Do not relax provenance to accept that media.
Use a fresh producer with the exact artifact identity.

### Setup failure evidence

Run 40244509229 failed before ISO fetch: Noble did not have the `.16` QEMU
version. Diagnostic installs use the reviewed `.18` four-package set.
Pre-install checks: signed apt metadata and full dependency simulation.
APT checks signatures as usual. Installs verify package versions. The collector
saves QEMU's version and hash.

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

## Root scan control probe

The `descriptor_scan_probe` input selects a separate five-minute job on
`ubuntu-24.04`. All build and guest jobs are off in this mode. It rejects
the full diagnostic and XFCE inputs. It has no schedule and needs no package
install, image pull, KVM, guest, installed disk, or credential read.

The owner approved one run with two empty files in private directories.
The closed-file control must return `clear`. The open-file control must
refuse with `disk_still_open`. Each control calls the real root fallback
once, with a 60-second scan limit. The command has a 180-second limit and
45 seconds to stop after a signal. There is no retry.

The root user, two capabilities, network isolation, memory limit, inode
guards, and owned-service stop checks stay the same. Root stdout and stderr
stay off. Fixed root refusals become exit statuses 80 to 98; unknown refusals
stay at 77. The report maps known statuses back to fixed reason labels.
It includes no command text, error text, environment values, target paths,
or FD contents.

The job uploads only `report.json` and keeps it for one day.
The tokens stay private. The job does not remove them by path.

Local CLI proof: a non-root helper returned 80 with empty stdout and stderr,
before file access or service start. Tests check refusals but emit no error
text. Neither result proves the hosted root
service works. A control pass is not installed-boot or unlock-prompt evidence.
Another privileged run needs a separate owner decision.
