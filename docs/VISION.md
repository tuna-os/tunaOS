# Vision

## Erase the Mystique of the Linux Distribution

A Linux distribution shouldn't be a monolithic artifact hand-tuned by a single vendor. It should be a **composition of choices** — base OS, desktop environment, kernel, drivers — assembled by a build matrix and delivered as an immutable image.

TunaOS exists to demonstrate this: there is no "TunaOS distro." There is a **build factory** that takes:

```
base OS  ×  desktop  ×  kernel  ×  drivers  =  image
```

Every cell in that matrix is a valid, shippable, bootable system. Users traverse the matrix at runtime with `bootc switch`. The factory stamps them all out — same pipeline, same Containerfile, same tooling.

## Principles

1. **The image IS the distribution.** There is no installer that assembles packages at install time. The image is pre-composed, tested, and shipped whole. What you pull is what you run.

2. **Composition over customization.** Adding a new desktop, kernel, or driver variant should be a config change — not a fork, not a new repo, not new scripts. One matrix, many outputs.

3. **Bootc is the delivery mechanism.** Atomic updates, rollback, switching between images — these aren't features we build, they're features we inherit from the container-native Linux stack.

4. **Enterprise Linux on the desktop.** The base layer is RHEL-compatible (AlmaLinux, CentOS Stream). You get the stability and ecosystem of Enterprise Linux with the desktop experience of Fedora or Arch.

5. **Declarative over imperative.** The build system should read a manifest and produce an image. Not: "run these 15 shell scripts in this order and hope the COPR repos are up." The manifest is the single source of truth for what goes into each image.

## The Build Factory

```
┌─────────────────────────────────────────────────────────────┐
│                      build-config.yml                        │
│  variant: yellowfin (AlmaLinux Kitten 10)                   │
│  desktops: [gnome, kde, niri, cosmic, xfce]        │
│  kernels: [standard, hwe]                                   │
│  drivers: [none, nvidia]                                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Containerfile (parameterized)             │
│  FROM $base → base packages → DE stage → overlay            │
│  One file. Every combination. Same pipeline.                │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              ghcr.io/tuna-os/yellowfin:gnome-hwe            │
│              ghcr.io/tuna-os/yellowfin:kde-nvidia           │
│              ghcr.io/tuna-os/albacore:niri                  │
│              ghcr.io/tuna-os/bonito:cosmic                  │
│              ... (every cell in the matrix)                  │
└─────────────────────────────────────────────────────────────┘
```

## Where We're Going

The end state is a build system where:

- **Adding a new desktop** = one YAML entry (package list + display manager + a few config files)
- **Adding a new base OS** = one YAML entry (image ref + package manager + repo setup)
- **Adding a new kernel/driver layer** = one YAML entry (overlay script + akmods ref)
- **No per-variant shell scripts.** The factory reads the manifest and knows what to do.

The current build scripts (`gnome.sh`, `kde.sh`, `cosmic.sh`, etc.) are stepping stones. They encode the knowledge of "what packages make a GNOME desktop on EL10 vs Fedora vs Ubuntu." The goal is to extract that knowledge into declarative manifests and have a single generic installer that reads them.

## Non-Goals

- We are NOT building a package manager, repo, or installer from scratch.
- We are NOT forking the desktops or kernels — we consume upstream.
- We are NOT competing with Fedora/Ubuntu/Arch — we compose their work into a matrix they don't ship.

## Inspiration

- [Universal Blue](https://universal-blue.org/) — proved bootc-based desktop images work at scale
- [Project Bluefin](https://projectbluefin.io) — showed that "opinionated defaults + bootc" is a valid product
- [NixOS](https://nixos.org/) — declarative system configuration (we want the DX without the Nix complexity)
- [Talos Linux](https://www.talos.dev/) — a "Linux distribution" that's just a manifest + an image factory
