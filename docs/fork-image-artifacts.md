# Reuse an exact original fork canary image

The opt-in `Fork Image Qualification` workflow can retain the original
Yellowfin and Grouper GNOME images for `linux/amd64` in public Actions artifacts.
Signed-in readers of the repository can download them.
They expire after **three days** and use artifact storage in Actions.
They are not registry publications, releases, production images or proof of an installation.

## Producer limits

Both originals must pass the existing build, identity, boot, BASE and image checks.
The source export must preserve each digest.
Only then does `scripts/fork-image-artifact.py package` stage the OCI files.
It includes each blob that the original manifest refers to.
Each artifact has a **5 GiB raw** limit; the pair has a **10 GiB** limit.
These limits include space for metadata.

Uploads precede the disposable login and installation tests.
A later failure does not remove the original inputs.
The helper copies only these files:

- The exact OCI files that the original manifest refers to
- The unchanged receipt and manifest from the source export
- The original source receipt from the compiler
- The original fork manifest and wallpaper
- A bundle record with file hashes, observer hashes and run/head/build IDs

It never copies a whole evidence directory, derived image, guest disk, SSH key or password.
A consumer does not upload the originals again or renew their retention.

The normal evidence includes `fork-image-pins.json`.
It contains exact artifact IDs, archive hashes, OCI digests and the source run/head.
The bundle also records the actual checkout SHA.
For a pull request, the tested merge SHA can differ from the source head.

## Select a consumer run

By default `.github/fork-image-reuse.json` contains `null`, which builds both originals.
To reuse them, copy the complete `fork-image-pins.json` from the chosen producer into that file.
An update to the existing qualification PR then starts the consumer.
A manual dispatch on `feat/fork-image-qualification` can also use the same JSON in `reuse_sources`.

The exact schema is:

```json
{
  "run_id": 123,
  "head_sha": "<40 lowercase hexadecimal characters>",
  "images": {
    "yellowfin": {
      "artifact_id": 456,
      "archive_sha256": "sha256:<64 lowercase hexadecimal characters>",
      "manifest_digest": "sha256:<64 lowercase hexadecimal characters>",
      "config_digest": "sha256:<64 lowercase hexadecimal characters>"
    },
    "grouper": {
      "artifact_id": 457,
      "archive_sha256": "sha256:<64 lowercase hexadecimal characters>",
      "manifest_digest": "sha256:<64 lowercase hexadecimal characters>",
      "config_digest": "sha256:<64 lowercase hexadecimal characters>"
    }
  }
}
```

This example is not a usable pin. Use the values from the producer.
Never use `latest`, an unverified artifact, or another repository.
The producer must have completed with success or failure.
The helper rejects a cancelled or active run, an expired artifact, and any mismatch.
It never selects another artifact or starts a build as a fallback.

Set the pin file to `null` to request a new build.

## Source and harness records

The consumer checks the GitHub run/head/artifact data and archive hash.
It also checks each OCI blob, payload checksum and original source receipt.
It verifies both variants before it imports either.

ZIP metadata has a size limit before extraction or a full parse.
Only stored or deflated regular files are valid.
Downloads and import commands have deadlines.
The helper stops a command's process group if it times out.
It also removes only its own verification containers and checks their absence.

Import uses `skopeo --preserve-digests`.
The helper checks the local config ID, manifest digest and embedded source files again.
Then the new login and installation tests can start.

The old compiler hashes never change to describe a new checkout.
Original receipts and the fork manifest retain their exact bytes.
The current source receipt only serves as a comparison; a separate record identifies the new harness.
Only edits to the explicit list of host/derived-guest harness scripts can pass this comparison.

Changes to build scripts, Containerfiles, manifests, the image builder, exporter,
compiler or embedded observer need a new build.
So do file additions, deletions, mode changes and symlink substitutions.
The installation helper also checks the embedded observer against the current source.

Each consumer has an `image-reuse.json` file.
It records the original build/source IDs, new harness SHA/hash, changed files, pins and producer result.
Its login and installation fields start as `not-run`.
Only the new proof reports can establish those results.
The bundle attributes the original build/boot results to the producer.

## Local checks

Use a disk-backed `TMPDIR`.
Run the format and check commands before source-receipt tests; do not run them at the same time.

```sh
just fix && just check
pytest -q tests/test_fork_image_artifact.py tests/test_fork_source_export.py \
  tests/test_fork_qualification.py tests/test_fork_installer_source.py
```

Tests with fixtures cover corruption, bounds, unsafe paths, exact pins and separate stage results.
They also check that receipts retain their bytes.
They do not prove a native upload, download, import or guest installation.
A producer run and an explicit consumer run must supply that evidence.
