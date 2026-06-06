ARG BASE_IMAGE
ARG ENABLE_HWE="${ENABLE_HWE:-0}"
ARG ENABLE_NVIDIA="${ENABLE_NVIDIA:-0}"
ARG DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
ARG HW_VARIANT="${HW_VARIANT:-no-de}"
ARG AKMODS_VERSION="${AKMODS_VERSION:-centos-10}"
ARG AKMODS_NVIDIA_VERSION="${AKMODS_NVIDIA_VERSION:-centos-10}"
ARG AKMODS_BASE="${AKMODS_BASE:-ghcr.io/ublue-os}"
ARG COMMON_IMAGE_REF="ghcr.io/projectbluefin/common:latest"
ARG BREW_IMAGE_REF="ghcr.io/ublue-os/brew:latest"

FROM ${COMMON_IMAGE_REF} AS common
FROM ${BREW_IMAGE_REF} AS brew

# Context layer combines build-time dependencies and configuration files
FROM scratch as context
COPY system_files /files
COPY --from=brew /system_files /files
COPY --from=common /system_files/shared /files
COPY --from=common /system_files/bluefin /files
COPY system_files_overrides /overrides
COPY build_scripts /build_scripts

# Akmods images for HWE/NVIDIA variant base stages
FROM ${AKMODS_BASE}/akmods-nvidia-open:${AKMODS_VERSION} AS akmods_nvidia_open
FROM ghcr.io/ublue-os/akmods-nvidia-open:${AKMODS_NVIDIA_VERSION} AS akmods_nvidia_open_full

# ==============================================================================
# Base stage (no DE) - Shared layer for all variants
# ==============================================================================
FROM ${BASE_IMAGE} AS base-no-de

ARG BASE_IMAGE
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
ARG DESKTOP_FLAVOR
ARG IMAGE_NAME
ARG IMAGE_VENDOR
ARG SHA_HEAD_SHORT

# RHSM credentials are NOT declared as ARG here — they're passed via
# `--secret id=rhsm` from the Justfile and consumed in the
# install_base_packages_no_de RUN below. Keeping them out of ARG/ENV
# ensures they never appear in `podman history --no-trunc` or in the
# final image config (`podman inspect`).

ENV BASE_IMAGE=${BASE_IMAGE}
ENV IMAGE_NAME=${IMAGE_NAME}
ENV IMAGE_VENDOR=${IMAGE_VENDOR}
ENV SHA_HEAD_SHORT=${SHA_HEAD_SHORT}
ENV ENABLE_HWE=${ENABLE_HWE}
ENV ENABLE_NVIDIA=${ENABLE_NVIDIA}

# Preserve desktop flavor so base-stage scripts don't fall back to GNOME defaults
ENV DESKTOP_FLAVOR=${DESKTOP_FLAVOR}

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
  bash -c "source /run/context/build_scripts/lib.sh && source /run/context/build_scripts/10-base-packages.sh && install_base_packages_no_de"

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
# HWE Base stage - Adds HWE kernel packages on top of BASE_IMAGE
# (used for chain builds where BASE_IMAGE is a pre-built variant)
# ==============================================================================
FROM ${BASE_IMAGE} AS base-hwe

ARG BASE_IMAGE
ARG IMAGE_NAME
ARG IMAGE_VENDOR
ARG SHA_HEAD_SHORT
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
ARG DESKTOP_FLAVOR
ENV BASE_IMAGE=${BASE_IMAGE}
ENV IMAGE_NAME=${IMAGE_NAME}
ENV IMAGE_VENDOR=${IMAGE_VENDOR}
ENV SHA_HEAD_SHORT=${SHA_HEAD_SHORT}
ENV ENABLE_HWE=${ENABLE_HWE}
ENV ENABLE_NVIDIA=${ENABLE_NVIDIA}
ENV DESKTOP_FLAVOR=${DESKTOP_FLAVOR}

RUN rm -rf /opt && mkdir /opt

RUN \
  --mount=type=tmpfs,dst=/opt \
  --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
    /run/context/build_scripts/HWE.sh

# ==============================================================================
# NVIDIA Base stage - Adds graphics/developer extras on top of BASE_IMAGE
# (used for chain builds where BASE_IMAGE is a pre-built variant)
# ==============================================================================
FROM ${BASE_IMAGE} AS base-nvidia

ARG BASE_IMAGE
ARG IMAGE_NAME
ARG IMAGE_VENDOR
ARG IMAGE_NAME_VARIANT
ARG SHA_HEAD_SHORT
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
ARG DESKTOP_FLAVOR
ENV BASE_IMAGE=${BASE_IMAGE}
ENV IMAGE_NAME=${IMAGE_NAME}
ENV IMAGE_VENDOR=${IMAGE_VENDOR}
ENV IMAGE_NAME_VARIANT=${IMAGE_NAME_VARIANT}
ENV SHA_HEAD_SHORT=${SHA_HEAD_SHORT}
ENV ENABLE_HWE=${ENABLE_HWE}
ENV ENABLE_NVIDIA=${ENABLE_NVIDIA}
ENV DESKTOP_FLAVOR=${DESKTOP_FLAVOR}

RUN rm -rf /opt && mkdir /opt

RUN \
  --mount=type=tmpfs,dst=/opt \
  --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_nvidia_open_full,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
    /run/context/build_scripts/nvidia.sh

# ==============================================================================
# Desktop Variant Stages
# Each stage ends with the /opt symlink so chunkah can be run against them.
# ==============================================================================

FROM base-${HW_VARIANT} AS base
# Base image with no DE - /opt made writeable via symlink
RUN rm -rf /opt && ln -s /var/opt /opt

FROM base-${HW_VARIANT} AS gnome
# Run DE script only for from-scratch builds (no-de); chain builds (hwe/nvidia)
# already have the DE installed in the parent BASE_IMAGE.
# post-desktop.sh runs unconditionally — versionlock + /opt symlink.
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  bash -c 'if [ "${ENABLE_HWE}" != "1" ] && [ "${ENABLE_NVIDIA}" != "1" ]; then /run/context/build_scripts/gnome.sh base; fi; /run/context/build_scripts/post-desktop.sh'

FROM base-${HW_VARIANT} AS cosmic
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  bash -c 'if [ "${ENABLE_HWE}" != "1" ] && [ "${ENABLE_NVIDIA}" != "1" ]; then /run/context/build_scripts/cosmic.sh base; fi; /run/context/build_scripts/post-desktop.sh'

FROM base-${HW_VARIANT} AS gnome50
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  bash -c 'if [ "${ENABLE_HWE}" != "1" ] && [ "${ENABLE_NVIDIA}" != "1" ]; then /run/context/build_scripts/gnome.sh base; fi; /run/context/build_scripts/post-desktop.sh'

FROM base-${HW_VARIANT} AS gnome49
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  bash -c 'if [ "${ENABLE_HWE}" != "1" ] && [ "${ENABLE_NVIDIA}" != "1" ]; then /run/context/build_scripts/gnome.sh base; fi; /run/context/build_scripts/post-desktop.sh'

FROM base-${HW_VARIANT} AS kde
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  bash -c 'if [ "${ENABLE_HWE}" != "1" ] && [ "${ENABLE_NVIDIA}" != "1" ]; then /run/context/build_scripts/kde.sh base; fi; /run/context/build_scripts/post-desktop.sh'

FROM base-${HW_VARIANT} AS niri
ARG ENABLE_HWE
ARG ENABLE_NVIDIA
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  bash -c 'if [ "${ENABLE_HWE}" != "1" ] && [ "${ENABLE_NVIDIA}" != "1" ]; then /run/context/build_scripts/niri.sh base; fi; /run/context/build_scripts/post-desktop.sh'
