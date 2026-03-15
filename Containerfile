ARG BASE_IMAGE
ARG ENABLE_HWE="${ENABLE_HWE:-0}"
ARG ENABLE_GDX="${ENABLE_GDX:-0}"
ARG DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
ARG COMMON_IMAGE_REF="ghcr.io/projectbluefin/common:latest"
ARG BREW_IMAGE_REF="ghcr.io/ublue-os/brew:latest"

FROM ${COMMON_IMAGE_REF} AS common
FROM ${BREW_IMAGE_REF} AS brew

# Context layer combines:
# - Local TunaOS customizations (system_files/)
# - Brew tools (/system_files from brew image - homebrew setup)
# - Common shared utilities (/system_files/shared from common - udev rules, scripts, services)
# - Common bluefin branding (/system_files/bluefin from common - theming, wallpapers, dconf)
# - Variant-specific overrides (system_files_overrides/)
# - Build scripts
FROM scratch as context
COPY system_files /files
COPY --from=brew /system_files /files
COPY --from=common /system_files/shared /files
COPY --from=common /system_files/bluefin /files
COPY system_files_overrides /overrides
COPY build_scripts /build_scripts

# ==============================================================================
# Base stage (no DE) - Shared layer for GNOME and KDE variants
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

# We pass in BASE_IMAGE as an env var to set it in os-release so that we know what we are building on
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/copy-files.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/00-workarounds.sh

# Install base packages WITHOUT DE (calls install_base_packages_no_de function)
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

# ==============================================================================
# GNOME variant - Adds GNOME desktop to base-no-de
# ==============================================================================
FROM base-no-de AS gnome

ARG DESKTOP_FLAVOR=gnome
ENV DESKTOP_FLAVOR=gnome

# Install GNOME desktop environment
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/gnome.sh base

# Lock glib2 after GNOME installation
RUN dnf versionlock add glib2

# Makes `/opt` writeable by default
# Needs to be here to make the main image build strict (no /opt there)
RUN rm -rf /opt && ln -s /var/opt /opt

# ==============================================================================
# GNOME 50 variant - Adds GNOME 50 (c10s-gnome-50 COPR) desktop to base-no-de
# ==============================================================================
FROM base-no-de AS gnome50

ARG DESKTOP_FLAVOR=gnome50
ENV DESKTOP_FLAVOR=gnome50

# Install GNOME 50 desktop environment
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/gnome.sh base

# Lock glib2 after GNOME installation
RUN dnf versionlock add glib2

# Makes `/opt` writeable by default
RUN rm -rf /opt && ln -s /var/opt /opt

# ==============================================================================
# KDE variant - Adds KDE desktop to base-no-de
# ==============================================================================
FROM base-no-de AS kde

ARG DESKTOP_FLAVOR=kde
ENV DESKTOP_FLAVOR=kde

# Install KDE desktop environment
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/kde.sh base

# Lock glib2 after KDE installation
RUN dnf versionlock add glib2

# Makes `/opt` writeable by default
# Needs to be here to make the main image build strict (no /opt there)
RUN rm -rf /opt && ln -s /var/opt /opt

# ==============================================================================
# Niri variant - Adds Niri+DMS desktop to base-no-de
# ==============================================================================
FROM base-no-de AS niri

ARG DESKTOP_FLAVOR=niri
ENV DESKTOP_FLAVOR=niri

# Install Niri desktop environment
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/niri.sh base

# Lock glib2 after Niri installation
RUN dnf versionlock add glib2

# Makes `/opt` writeable by default
# Needs to be here to make the main image build strict (no /opt there)
RUN rm -rf /opt && ln -s /var/opt /opt
