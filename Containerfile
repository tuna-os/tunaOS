ARG BASE_IMAGE
# NOTE: ENABLE_HWE and ENABLE_NVIDIA are passed by the Justfile _build helper
# to every Containerfile for interface uniformity. The main Containerfile never
# gates on them — HWE/NVIDIA behavior is controlled by Containerfile selection
# (main vs Containerfile.hwe vs Containerfile.nvidia) and AKMODS_VERSION dispatch.
ARG ENABLE_HWE="${ENABLE_HWE:-0}"
ARG ENABLE_NVIDIA="${ENABLE_NVIDIA:-0}"
ARG ENABLE_SSHD="${ENABLE_SSHD:-0}"
ARG DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
ARG IMAGE_NAME_VARIANT
# SECURITY: Defaults use placeholder tags that MUST be overridden at build time.
# The Justfile and scripts/build-image.sh always pin these to specific SHA256
# digests (e.g., ghcr.io/projectbluefin/common@sha256:...). Direct podman build
# without --build-arg overrides will fail with a clear error.
ARG COMMON_IMAGE_REF="ghcr.io/projectbluefin/common:unpinned-must-override"
ARG BREW_IMAGE_REF="ghcr.io/ublue-os/brew:unpinned-must-override"
ARG ZIRCONIUM_IMAGE_REF="ghcr.io/zirconium-dev/zirconium:latest"

FROM ${COMMON_IMAGE_REF} AS common
FROM ${BREW_IMAGE_REF} AS brew
FROM ${ZIRCONIUM_IMAGE_REF} AS zirconium

# Context layer combines build-time dependencies and configuration files.
# NOTE: no zirconium content here — the context stage feeds EVERY desktop
# stage, and Zirconium (DMS/Niri) files belong only on niri images, the same
# way Aurora files inform kde and Bluefin files inform gnome. The zirconium
# COPYs live in the niri stage below.
FROM scratch as context
COPY system_files /files
COPY --from=brew /system_files /files
COPY --from=common /system_files/shared /files
COPY --from=common /system_files/bluefin /files
COPY system_files_overrides /overrides
COPY build_scripts /build_scripts
COPY manifests /manifests
COPY image-versions.yaml /image-versions.yaml

# ==============================================================================
# Base stage (no DE) - Shared layer for all variants
# ==============================================================================
FROM ${BASE_IMAGE} AS base-no-de

ARG BASE_IMAGE
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
ARG ENABLE_SSHD
ARG DESKTOP_FLAVOR
ARG IMAGE_NAME
ARG IMAGE_VENDOR
ARG IMAGE_NAME_VARIANT
ARG IMAGE_REGISTRY="ghcr.io"

# RHSM credentials are NOT declared as ARG here — they're passed via
# `--secret id=rhsm` from the Justfile and consumed in the
# install_base_packages_no_de RUN below. Keeping them out of ARG/ENV
# ensures they never appear in `podman history --no-trunc` or in the
# final image config (`podman inspect`).

ENV BASE_IMAGE=${BASE_IMAGE}
ENV IMAGE_NAME=${IMAGE_NAME}
ENV IMAGE_VENDOR=${IMAGE_VENDOR}
ENV IMAGE_NAME_VARIANT=${IMAGE_NAME_VARIANT}
ENV IMAGE_REGISTRY=${IMAGE_REGISTRY}
ENV ENABLE_HWE=${ENABLE_HWE}
ENV ENABLE_NVIDIA=${ENABLE_NVIDIA}
ENV ENABLE_SSHD=${ENABLE_SSHD}

# Preserve desktop flavor so base-stage scripts don't fall back to GNOME defaults
ENV DESKTOP_FLAVOR=${DESKTOP_FLAVOR}

# Every build_scripts/*.sh RUN below uses
# `--mount=type=bind,from=context,source=/,target=/run/context` to invoke
# scripts without a COPY layer — but that bind mount's content is NOT part
# of buildah's cache-key hashing, so editing a script alone never
# invalidates the cached layer that ran it (confirmed: a runner reused a
# pre-fix cached layer for install_base_packages_no_de verbatim after the
# script changed, silently shipping the old package list). An ENV set here
# changes the cache key for every RUN after it, so hashing build_scripts/
# content into it forces correct invalidation — independent of
# SHA_HEAD_SHORT (declared much later, deliberately, so cache still hits
# across commits that don't touch these scripts at all).
ARG BUILD_SCRIPTS_HASH
ENV BUILD_SCRIPTS_HASH=${BUILD_SCRIPTS_HASH}
# Force layer cache invalidation when build scripts change
RUN echo "${BUILD_SCRIPTS_HASH}" > /dev/null

# Ensure /opt is a real directory so tmpfs mounts work in all subsequent stages
RUN rm -rf /opt && mkdir /opt

# Copy system files and apply TunaOS customizations
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/copy-files.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/00-workarounds.sh

# Install base packages WITHOUT DE.
# The optional RHSM secret is mounted at /run/secrets/rhsm only inside this
# RUN. It contains `export RHSM_USER=…` etc.; install_base_packages_no_de
# sources it if present. The mount is also gated by `required=false` so
# non-RHEL builds (which never pass --secret) succeed unchanged.
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  --mount=type=secret,id=rhsm,target=/run/secrets/rhsm,required=false \
  /run/context/build_scripts/10-base-packages.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/20-packages.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/26-packages-post.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/40-services.sh

# SHA_HEAD_SHORT changes on every commit. Declared HERE (not at the top of
# the stage) so only the layers from this point down rebuild per commit —
# with it in the early ENV block, the layer cache could never hit across
# commits and the expensive dnf layers above rebuilt every time.
ARG SHA_HEAD_SHORT
ENV SHA_HEAD_SHORT=${SHA_HEAD_SHORT}
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/90-image-info.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/arch-customizations.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/cleanup.sh

# ==============================================================================
# Desktop Variant Stages
# Each stage ends with the /opt symlink so chunkah can be run against them.
# ==============================================================================

FROM base-no-de AS base
# Base image with no DE - /opt made writeable via symlink
RUN rm -rf /opt && ln -s /var/opt /opt

FROM base-no-de AS gnome
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/install-desktop.sh gnome
# Extensions are a separate layer so DE package install caches independently
# of submodule updates to extension sources.
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/gnome-extensions.sh
RUN rm -rf /opt && ln -s /var/opt /opt

FROM base-no-de AS cosmic
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/install-desktop.sh cosmic
RUN rm -rf /opt && ln -s /var/opt /opt

FROM base-no-de AS gnome50
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  DESKTOP_FLAVOR=gnome50 /run/context/build_scripts/install-desktop.sh gnome
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/gnome-extensions.sh
RUN rm -rf /opt && ln -s /var/opt /opt

FROM base-no-de AS kde
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/install-desktop.sh kde
RUN rm -rf /opt && ln -s /var/opt /opt

FROM base-no-de AS niri
# Zirconium (DMS/Niri upstream) config payload — niri images only.
COPY --from=zirconium /usr/share/zirconium /usr/share/zirconium
COPY --from=zirconium /usr/share/xdg-terminal-exec /usr/share/xdg-terminal-exec
COPY --from=zirconium /usr/share/greetd /usr/share/greetd
COPY --from=zirconium /usr/share/dms /usr/share/dms
COPY --from=zirconium /usr/lib/pam.d /usr/lib/pam.d
COPY --from=zirconium /usr/lib/systemd/user/chezmoi-init.service /usr/lib/systemd/user/chezmoi-init.service
COPY --from=zirconium /usr/lib/systemd/user/chezmoi-update.service /usr/lib/systemd/user/chezmoi-update.service
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/install-desktop.sh niri
RUN rm -rf /opt && ln -s /var/opt /opt

FROM base-no-de AS xfce
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/install-desktop.sh xfce
RUN rm -rf /opt && ln -s /var/opt /opt
