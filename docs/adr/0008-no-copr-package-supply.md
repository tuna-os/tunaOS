# ADR 0008: Replace COPR with project-owned RPM repositories

## Status

Proposed

## Context

TunaOS currently uses COPR repositories for packages absent from Fedora or
EL10. This makes image builds depend on external chroots, repository
availability, and package lifecycles that the project cannot reproduce or
control. Fedora Hummingbird makes the limitation more visible: its minimal,
image-native base does not provide the normal DNF composition path.

## Decision

Use a project-owned RPM supply chain for every non-upstream RPM:

1. Keep sources, spec files, patches, and build manifests in a TunaOS-owned
   package repository.
2. Build signed RPMs in GitHub Actions for each supported Fedora and EL target
   and architecture.
3. Publish a signed `rpm-md` repository to `repo.tunaos.org` (or an equivalent
   object-store-backed HTTPS endpoint). Desktop manifests consume only this
   repository and upstream distribution repositories.
4. Publish the same signed repository snapshot as an OCI artifact with ORAS,
   including SBOM and provenance. ORAS is not DNF's primary endpoint: DNF
   consumes `rpm-md` over HTTPS.
5. Compose Hummingbird only after its required RPMs are present in that
   project-owned repository and tested against its base. Until then it is
   base-only.

## Consequences

* No new COPR dependency is permitted.
* Existing COPR-backed desktops must not be removed until replacement RPMs,
  metadata, signatures, and install tests exist; otherwise images regress.
* Migration begins with the project-controlled XFCE Wayland stack, then GNOME,
  COSMIC, Niri/DMS, and KDE integration packages.
