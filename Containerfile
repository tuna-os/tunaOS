ARG BASE_IMAGE
ARG ENABLE_HWE="${ENABLE_HWE:-0}"
ARG ENABLE_GDX="${ENABLE_GDX:-0}"
ARG DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
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

# ==============================================================================
# Base stage (no DE) - Shared layer for all variants
# ==============================================================================
FROM ${BASE_IMAGE} AS base-no-de

ARG BASE_IMAGE
ARG ENABLE_HWE
ARG ENABLE_GDX
ARG DESKTOP_FLAVOR
ARG IMAGE_NAME
ARG IMAGE_VENDOR
ARG SHA_HEAD_SHORT

# RHSM Credentials for RHEL registration
ARG RHSM_USER
ARG RHSM_PASSWORD
ARG RHSM_ORG
ARG RHSM_ACTIVATION_KEY

ENV BASE_IMAGE=${BASE_IMAGE}
ENV IMAGE_NAME=${IMAGE_NAME}
ENV IMAGE_VENDOR=${IMAGE_VENDOR}
ENV SHA_HEAD_SHORT=${SHA_HEAD_SHORT}
ENV ENABLE_HWE=${ENABLE_HWE}
ENV ENABLE_GDX=${ENABLE_GDX}

# Pass RHSM credentials as ENV to be used by build scripts
ENV RHSM_USER=${RHSM_USER}
ENV RHSM_PASSWORD=${RHSM_PASSWORD}
ENV RHSM_ORG=${RHSM_ORG}
ENV RHSM_ACTIVATION_KEY=${RHSM_ACTIVATION_KEY}

# Preserve desktop flavor so base-stage scripts don't fall back to GNOME defaults
ENV DESKTOP_FLAVOR=${DESKTOP_FLAVOR}

# Copy system files and apply TunaOS customizations
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/copy-files.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/00-workarounds.sh

# Install base packages WITHOUT DE
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
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

# Makes `/opt` writeable by default (inherited by all desktop variants)
RUN rm -rf /opt && ln -s /var/opt /opt

# ==============================================================================
# Desktop Variant Stages
# ==============================================================================

FROM base-no-de AS base
# Just an alias for base-no-de

FROM base-no-de AS gnome
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/gnome.sh base
RUN dnf versionlock add glib2

FROM base-no-de AS cosmic
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/cosmic.sh base
RUN dnf versionlock add glib2

FROM base-no-de AS gnome50
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/gnome.sh base
RUN dnf versionlock add glib2

FROM base-no-de AS kde
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/kde.sh base
RUN dnf versionlock add glib2

FROM base-no-de AS niri
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/niri.sh base
RUN dnf versionlock add glib2

# ==============================================================================
# Finalization & Chunking
# ==============================================================================

# Select the requested flavor
FROM ${DESKTOP_FLAVOR} AS pre-final

# Chunkify the image at build-time using the oci-archive trick.
# This preserves bootc/ostree metadata while optimizing layer count.
FROM ghcr.io/tuna-os/chunkah:latest AS chunker
RUN --mount=from=pre-final,src=/,target=/chunkah,ro \
    --mount=type=bind,target=/run/out,rw \
    chunkah build > /run/out/out.ociarchive

# The 'final' stage uses the archive generated in the previous step.
# NOTE: In local/CI pipelines, this usually requires a two-pass build if 
# the archive isn't already present in the build context.
FROM oci-archive:out.ociarchive AS final

ARG IMAGE_NAME
ARG IMAGE_VENDOR
ARG DESKTOP_FLAVOR
ARG SHA_HEAD_SHORT

LABEL org.opencontainers.image.title="TunaOS ${IMAGE_NAME} (${DESKTOP_FLAVOR})"
LABEL org.opencontainers.image.vendor="${IMAGE_VENDOR}"
LABEL org.opencontainers.image.version="${SHA_HEAD_SHORT}"
LABEL io.bootc=1
