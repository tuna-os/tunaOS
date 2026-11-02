# bootc native backend prerequisite candidate

This local prerequisite is opt-in and **unqualified**. It does not switch an
image, install a system, migrate OSTree, or change a production pin. The candidate
is bootc v1.17.1, commit `d01e723ae9480fa53aa9db09a7eff0439548e9f6`.
The production source-toolchain ceiling remains v1.16.10 until build and runtime
qualification allows a separate pin/consumer update.

## Source bootstrap

`scripts/bootc-candidate.py bootstrap` accepts a clean checkout of that exact
commit, an empty output directory, and an explicit family. It invokes upstream
`make bin install-all` with explicit features, so manpage and
completion rebuilds use the same features. It refuses paths with unsafe characters and
removes ambient Make feature overrides. It does not fetch source. It does not publish its output. Install build dependencies in a disposable build environment first.

```sh
python3 scripts/bootc-candidate.py bootstrap \
  --source /workspace/bootc-v1.17.1 --destination /workspace/bootc-stage \
  --family arch
```

Arch uses `--no-default-features` with `install-to-disk pre-6.15`. All other
profiles preserve defaults and explicitly include SELinux; EL10 also includes
`rhsm`. This is a build recipe, not measured binary-version evidence. The
[upstream Makefile](https://github.com/bootc-dev/bootc/blob/v1.17.1/Makefile)
and [optional SELinux change](https://github.com/bootc-dev/bootc/pull/2494)
provide the feature contract. Do not use the Arch output for an SELinux family.

The source routes need different follow-up work:

- `Containerfile.arch` compiles the `BOOTC_VERSION` build argument sourced from
  `image-versions.yaml`. The opt-in argument below selects the candidate helper.
- `toolchain/Containerfile.debian` builds the pinned source. Debian and Ubuntu
  consumers pull its prebuilt OCI trees. A new version string does not
  publish those trees or prove their ABI compatibility. Qualify trixie and sid,
  plus each Ubuntu consumer, before a new artifact pin.
- `Containerfile.gentoo` uses its own `BOOTC_COMMIT`, now
  `3e76c16556c55e6d15d31bd47602b231e2131cb2`; it does not follow the YAML pin.
- `Containerfile.el10` inherits bootc from its base images: yellowfin, albacore,
  skipjack, bonito, bonito-rawhide, wahoo, hummingbird, and local-only redfin.
  Each exact image digest needs its own executable/version/features evidence.
- `Containerfile.opensuse` installs bootc from OBS. It is a package consumer,
  not a source-pin consumer; inspect the installed package and binary.
- Overlay images inherit their parent route. A source pin alone changes none
  of these inherited or separately packaged binaries.

## Existing build path

The `bootc-builder` stage in `Containerfile.arch` now accepts
`TUNAOS_BOOTC_CANDIDATE=1`. It fetches v1.17.1, verifies the exact commit through
the helper, and builds into `/output`. The existing stage still installs bootupd.
The default value is `0`; that branch uses the production `BOOTC_VERSION`.
Other values fail. Production workflows do not set this argument.

For a later authorized toolchain-only build, use `Containerfile.arch` with
`--target bootc-builder --build-arg TUNAOS_BOOTC_CANDIDATE=1` and the existing
`BOOTUPD_VERSION` argument. No image or container build ran in this task.
Do not use this argument for a production image until the gates below pass.

The Debian toolchain also accepts the same argument. It adds the SELinux,
systemd and clang development packages, then calls the helper with the Debian
profile. It stages bootc separately before a copy into `/output`, which already
holds the optional libostree tree. Default builds retain their existing route.
Gentoo still needs its own explicit override of `BOOTC_COMMIT`.

## Bounded CI compile job

The existing `Test` workflow now has a `bootc-candidate-compile` job. Its exact
scope is a PR with head branch `candidate/composefs-bootstrap`, or a manual run
whose ref is `refs/heads/candidate/composefs-bootstrap`. Other branches and push
events skip this job. It has no dispatch inputs. The fixed matrix is:

| Family | Existing target | Candidate inputs |
| --- | --- | --- |
| Arch | `Containerfile.arch`, `bootc-builder` | `TUNAOS_BOOTC_CANDIDATE=1`; bootupd pin from YAML |
| Debian | `toolchain/Containerfile.debian`, `builder` | Same opt-in; `BUILD_OSTREE=1`; bootupd, OSTree and composefs pins from YAML |

Both bases use their existing digest pins. The helper verifies the candidate
commit. Debian keeps SELinux; Arch uses the documented reduced feature set.
The job holds only `contents: read`, and checkout does not persist credentials.
It does not log in, push images, upload artifacts or mount host paths.

Images stay under `localhost/bootc-candidate` on the runner. Each job has a
60-minute limit and a 3000-second build timeout. The matrix runs one job at a
time; the workflow cancels older runs on the same ref.

This uses the existing PR/manual workflow filename to avoid registration of a
new workflow on the default branch. A later authorized run still needs the
candidate commit on the remote branch and a hosted runner with Docker.
A new manual workflow file would need default-branch registration first.

No PR, dispatch or container build ran in this task. These jobs define commands. They do not prove a successful compile. Native libraries remain absent in
the local environment. Both actual CI builds must pass before the compile gap
can close; a compile pass alone does not qualify boot or storage behavior.

## Read-only backend contract

```sh
python3 scripts/bootc-candidate.py inspect \
  --root /workspace/extracted-candidate --family arch \
  --architecture amd64 --firmware uefi --filesystem ext4
```

This reads an extracted tree without mounts. It emits JSON and exits **1** even
when the markers match. It denies every runtime capability.

An empty
`usr/lib/composefs/setup-root-conf.toml` is a native signal. Either
`usr/lib/ostree/prepare-root.conf` or `etc/ostree/prepare-root.conf` prevents
native default selection. The inspector reports a conflict when both kinds exist.
Bootupd and systemd-boot presence do not override these markers. This contract does not detect UKIs or certify config contents.

The existing production probes, layout and dracut writers are still unchanged.
Update them together with the installer recipe in a later reviewed
candidate. A marker alone is unsafe. Preserve ext4 and mandatory
fs-verity. Reuse the Marlin defaults from #2996, Corral harness from #3249,
offline GUI qualification from #3399, and capability boundaries from #3503.
PR #3445 remains a draft for fork-image qualification; do not replace it with
a second harness.

## Capability gates before rollout

1. Build the exact candidate for each source family; execute the staged binary
   and record version, libraries, features and source digest. For inherited and
   OBS routes, record actual image/package evidence without inference.
2. Reconcile layout, dracut, probes and installer configuration as one change.
   Inspect the installed initramfs and verify target-only boot. Separate BIOS,
   UEFI, ARM64 and Asahi evidence is required. No BIOS/Asahi support follows
   from the amd64 UEFI baseline.
3. Qualify plain and LUKS offline GUI installs independently, including unlock,
   updates, rollback and recovery. Migration from OSTree to native is unavailable at this pin.
   Do not assume recovery from a boot counter.
4. Unified storage remains experimental. Its install switches are
   `--composefs-backend --experimental-unified-storage`; `bootc image set-unified`
   is for existing native deployments, not OSTree migration. Prove shared storage for images and containers.
   Test updates, rollback, garbage collection and failure recovery. Do not
   add an unmerged `[install.storage]` schema or make overlay `use_composefs` mandatory.
5. Partial pulls need OCI `zstd:chunked` metadata and measured client/registry
   transfers, including repeat pulls and old-client negatives. A successful full
   download is not partial success. Keep plain zstd for production
   for the GHCR multi-range 501 workaround. `enable_partial_images` is a string
   under `[storage.options.pull_options]`; never enable
   `insecure_allow_unpredictable_image_contents`.

Hummingbird admission is separate. The checkout still excludes `hummingbird:tuna`
and admits base/GNOME/COSMIC on amd64. Package #832 has recorded completion and
served-index evidence; that is not a fresh RPM-byte/signature or image test.
Admission successor #3885 supersedes #3338 and retains its manual-merge fence.
Keep that lane and its package closure/image proof requirement. This candidate
authorizes no change to Himachal or any installed system.

## Local evidence and limits

Run `python3 -m unittest discover -s tests -p test_bootc_candidate.py -v` for the
inert tests. They cover marker combinations, capability-specific refusals,
inherited/package routes, feature propagation, output paths, and CLI failure.
Upstream `make -n bin install-all` was also checked for all eight family profiles:
both manpage generation and binary builds preserve their selected features.

No container, mount, boot, disk or runtime test was run.
The 14 inert tests pass. The tools use repository pins and official releases.
Their checksums pass verification. The files live under `/workspace/bootc-devtools`.

Upstream declares Rust 1.85.0 as a minimum and has no toolchain file.
The local compiler is Rust 1.99.1 from the official stable manifest.

Both bounded `cargo check --locked --bins` commands stopped at the absent
`glib-2.0 >= 2.56` development files. One used the Arch feature set; the other
kept SELinux. The pkg-config probes also found no GIO/GObject, OSTree, systemd
or SELinux development metadata. Both commands kept the selected features. This patch preserves the production pins, security policy, signatures, SELinux policy and storage defaults.
