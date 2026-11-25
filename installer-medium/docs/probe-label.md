# Probe label: evidence from the image config

Status: step 1 is in the tree. Steps 2 to 4 are not done. Epic: tunaOS#4905.

## Problem

`scripts/lib/installer_medium.py` takes the bootloader, the backend, the
filesystem and the Secure Boot mode of each cell from
`installer-medium/evidence/images.json`. `installer-medium/evidence/scan-images.py`
writes that file. It streams each layer of each published image, because the
probe inputs are files in the image. The scan of 2026-11-25 read 128 images
and 214 GB of layers.

The inputs are small. The largest record in `images.json` is 458 characters
as a label value. The image build has the final root directory on disk. The
build can write the inputs into the image config, and a refresh then reads
one config per cell.

## Decision

1. One label, `org.tunaos.installer.probe`, on the image config of each
   platform image. Its value is one JSON object.
2. The label carries the probe inputs (the facts). It does not carry the
   probe answer. The refresh runs the probe on the facts.
3. `installer-medium/evidence/probe_facts.py` computes the facts from a root
   directory. The image build and the scan share that file.
4. The label is a hint. A label that is absent, of another schema, or not
   valid sends the cell to the layer scan.
5. `installer-medium/verify-cell-layout.sh` does not change. It runs the
   probe in the image that a medium build uses, before `bootc install`.

## Label

Name: `org.tunaos.installer.probe`. Schema number: `1`.

```json
{"schema":1,"facts":{"files":["usr/lib/bootupd/updates/EFI.json"],"kernels":["6.12.0-264.17.1.el10_3.x86_64"],"prepare_root_conf":"[composefs]\nenabled = no\n","os_release":"ID=\"almalinux\"\nID_LIKE=\"rhel centos fedora\"\nVERSION_ID=\"10.3\"\nVARIANT_ID=\"albacore\"\n"}}
```

The `facts` object is the `facts` object of an `images.json` record, with no
change. The table shows each field and its reader.

| Field | Content | Reader |
|---|---|---|
| `files` | Names of the bootupd payload (`EFI.json`, `grub*.efi`), of `grub*.efi` and `shim*.efi` below `usr/lib/efi`, and of `systemd-boot*.efi` and `systemd-boot*.efi.signed` | The probe: ostree or composefs backend. The resolver: the signed systemd-boot of tunaOS#4955 |
| `kernels` | Directory names below `usr/lib/modules` | The probe: btrfs or ext4 for a composefs image |
| `prepare_root_conf` | Text of `usr/lib/ostree/prepare-root.conf` | The probe: the composefs pin |
| `os_release` | The `ID`, `ID_LIKE`, `VERSION_ID` and `VARIANT_ID` lines | The probe: the OS family. The resolver: the EL check |

The bootc version is not in the label, because the probe and the resolver do
not read it. A new input needs a new schema number.

### Why one JSON label

- The record is a tree: two lists and two texts. Flat labels need an
  encoding for each list, and the reader then needs one parser for each
  label.
- `images.json` stores the same object. The reader copies it and does no
  conversion.
- One label has one schema number. With flat labels, an image can carry
  half of an old set and half of a new set.

### Why a config label and not an index annotation

- The file names are different for each architecture (`grubx64.efi`,
  `grubaa64.efi`). An index annotation holds one value for all platforms.
- `skopeo copy --all` writes the index again during promotion
  (`.github/workflows/reusable-build-image.yml`, the promote job). The image
  config does not change, because the image digest covers it.

### Why the label carries the inputs and not the answer

- A change to the probe rules applies on the next refresh. No image build is
  necessary.
- `tests/test_installer_medium_cells.py` runs the probe on the stored facts
  of each record. A label record passes the same test.
- A wrong answer in a label cannot reach the resolver. The worst label gives
  wrong inputs, and `verify-cell-layout.sh` finds those.

## Where the build computes it

`scripts/build-image-inner.sh` has three passes: the primary build, the
chunkah rechunk, and the `Containerfile.final` build. A `RUN` step cannot
write a label. A build step after `Containerfile.final` that only sets a
label adds an empty layer, and bootc cannot import an empty layer
(tunaOS#3378).

Thus the wrapper computes the label between pass 2 and pass 3:

1. Mount the rechunked image (`RECHUNKED_REF`) on the build host.
2. Run `installer-medium/evidence/probe_facts.py <mount path>`. The script
   prints `org.tunaos.installer.probe=<JSON>`.
3. Give that line to the `Containerfile.final` build as `--label`. The
   hardware overlay labels (`HARDWARE_PARENT_LABELS`) use the same method.

The script runs on the build host, because an image does not always contain
Python. `Containerfile.final` adds `/etc/sudoers.d/10-tunaos-wheel` and
`/usr/share/tunaos/build-info.json`. Neither path is a probe input, so the
facts of the rechunked image are the facts of the final image.

The script prints no label and exits 1 when the probe cannot classify the
image or when a fact breaks a limit. The wrapper then builds the image with
no label and prints a warning. The image build does not fail.

### A child image inherits the label

A label passes from a parent image to each image that builds `FROM` it.
Measured on 2026-11-25: an image built `FROM` a labelled image, with one
more kernel directory, showed the label of the parent.

Three rules keep an inherited label out of the evidence:

- The primary build passes `--label org.tunaos.installer.probe=` (an empty
  value). An empty value is "no label" for the reader. Thus an image from
  the `SKIP_RECHUNK=1` path and each pre-chunk image carry no label.
- Pass 3 sets the label on each published image, overlay images included.
- `installer-medium/build-live-image.sh` passes the same empty label,
  because a live image has a different kernel command line and more files.

The published images carry only the labels of `Containerfile.final`.
Measured on 2026-11-25 for `ghcr.io/tuna-os/albacore:gnome`: the config has
seven labels and none from the AlmaLinux base. The rechunk does not keep
the labels of the primary build.

## How the refresh reads it

`scan-images.py` does these steps for each cell:

1. Read the index and the platform manifest. This step gives `digest`,
   `manifest` and `platform`, the same as before.
2. Read the config blob that the manifest names. It is some tens of
   kilobytes.
3. Decode the label and check each fact against the limits.
4. Run the probe on the facts. Write the record with `facts_from: label`.
5. On a failure in step 2, 3 or 4, read the layers as before. The script
   prints the reason.

`--layer-scan` skips steps 2 to 4 for all cells.

The script reads the config blob through its own registry client and not
through `skopeo inspect`. The client already has the token and the two
manifests, and the record needs the index digest and the platform manifest
digest. A person can read the same label with this command:

```bash
skopeo inspect --no-tags --override-arch amd64 docker://ghcr.io/tuna-os/albacore:gnome |
  jq -r '.Labels["org.tunaos.installer.probe"]'
```

Use `--no-tags`. Without it, the command also lists all tags of the
repository. On 2026-11-25 the call for `albacore:gnome` took 3 seconds with
`--no-tags` and 196 seconds without it.

## Trust

A label is text that the builder of an image writes. The scan reads images
of forks and of sibling repositories too. The reader thus refuses a label
before a tree is built from it:

- The value is at most 16 KiB and has only the fields `schema` and `facts`.
- Each file path matches the tracked names, has no `..` part, and is not
  absolute.
- Each kernel name is one path part.
- Each `os_release` line is one of the four keys with a plain value. The
  probe sources that file in bash.
- The lists are sorted, unique and short.

The label does not show which image it describes. The rules in "A child
image inherits the label" are the control for that. The last control is
`verify-cell-layout.sh`: a medium build fails when the image and the row
differ.

## Fallback

| Image | Result |
|---|---|
| Label with schema 1 and valid facts | Record from the label |
| No label, or an empty label | Layer scan |
| Other schema number | Layer scan |
| Facts that break a limit | Layer scan |
| Facts that the probe cannot classify | Layer scan |
| Config blob not readable | Layer scan |

All published images are in the "no label" row until step 2 is in the tree.
The scan result is thus the same as before this change.

## Rollout

1. Done in this change. `probe_facts.py`, the label reader in
   `scan-images.py`, and the tests. No build calls the script.
2. Call the script from `scripts/build-image-inner.sh` as "Where the build
   computes it" says, with the empty label on the primary build and on the
   live image. Prove it with one `just build` and one
   `skopeo inspect --no-tags`. Run `scripts/check-bootc-installable-layers`
   on the result.
3. After one nightly build, run `scan-images.py` for all cells and
   `scan-images.py --layer-scan` for five cells. The two results must be
   equal. Record the two run times here.
4. Add the label to the BuildStream sibling images (tunaOS#4962) with the
   same script. Until then those images use the layer scan.

## Measured on 2026-11-25

| Check | Result |
|---|---|
| Label round trip of the 127 measured records | All equal; largest value 458 characters |
| Script on the mounted `albacore:gnome` image (`sha256:8b3ea260fdd2`), against its layer scan record | Facts equal; 3.2 seconds with the mount |
| Script on the mounted `ghcr.io/tuna-os/xfce-linux:latest` | 0.15 seconds; `systemd`, composefs, `ext4` |
| Label written with `podman build --label`, then read back | Facts and probe equal to the `bonito:gnome` record |
| Manifests and config of `albacore:gnome` (65 layers, 2.37 GB) | 4.4 seconds and 2.6 seconds; no label, so layer scan |
