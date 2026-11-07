# ADR 0017: Protected native-package removal

- Status: accepted (design); implementation not started
- Date: 2026-10-31
- Approval: the maintainer approved all eight decisions of RFC 017 on 2026-10-31. The orchestrator that the maintainer delegated to recorded this on [#3803](https://github.com/tuna-os/tunaOS/issues/3803).
- RFC: [RFC 017](../rfc/rfc017-protected-package-removal.md)
- Specification: [F4b specification](../../.spektacular/specs/20261024100000-protected-native-package-removal.md)
- Issue: [#3803](https://github.com/tuna-os/tunaOS/issues/3803)

## Context

`tunaos.toml` takes package additions for the whole image (F4, #3739). It
rejects removals. A removal can take out a package that boot, init, the package
manager, the session, the network or the update path needs. The image can still
build.

## Decision

- The protected set comes from the base and runtime contracts and from native
  Essential and Protected metadata. The simulated plan must match the request
  exactly. No file holds a list of package names.
- The base contract gets new checks. They cover the kernel, the initramfs, the
  boot-loader tool, the package manager, the network unit and the image-store
  tools.
- A removal goes only under `variants.<v>.packages.remove`. A removal in
  `[defaults.packages]` stays rejected. One name is not one package in every
  family.
- The removal is the last transaction of each stage. It runs after the
  additions. Each derived stage repeats it.
- A removal that pulls out any extra package fails the build.
- Each cell has evidence levels E1 to E6. dnf and apt come first. Portage stays
  unsupported.
- The success receipt goes in the image under `/usr/share/tunaos/`. CI also
  uploads it as an artifact.
- Removals in `build_scripts/` stay outside this validator.

## Consequences

- The primary validator keeps the rejection of every `remove` list. The rejection
  is in `scripts/lib/tunaos_config.py`. `tests/test_image_packages.py` pins it.
  It stays until the implementation merges.
- The maintainer approved the design. The code, the native fixtures and the
  per-cell evidence do not exist yet.
- A cell enables removal only when that cell has its evidence.
