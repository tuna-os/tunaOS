ARG MAJOR_VERSION="${MAJOR_VERSION:-10}"
ARG BASE_IMAGE="${BASE_IMAGE:-quay.io/almalinuxorg/almalinux-bootc}"
ARG BASE_IMAGE_TAG="${BASE_IMAGE_TAG:-10}"

# For chained builds, allows specifying a pre-built image as base instead of the OS base
ARG CHAIN_BASE_IMAGE="${CHAIN_BASE_IMAGE:-}"

FROM scratch as context
COPY system_files /files
COPY system_files_overrides /overrides
COPY build_scripts /build_scripts

# If CHAIN_BASE_IMAGE is provided, use it; otherwise use the original base image
FROM ${CHAIN_BASE_IMAGE:-${BASE_IMAGE}:${BASE_IMAGE_TAG}}

ARG ENABLE_DX="${ENABLE_DX:-0}"
ARG ENABLE_GDX="${ENABLE_GDX:-0}"
ARG IMAGE_NAME="${IMAGE_NAME:-bluefin}"
ARG IMAGE_VENDOR="${IMAGE_VENDOR:-ublue-os}"
ARG MAJOR_VERSION="${MAJOR_VERSION:-lts}"
ARG SHA_HEAD_SHORT="${SHA_HEAD_SHORT:-deadbeef}"
ARG CHAIN_BASE_IMAGE="${CHAIN_BASE_IMAGE:-}"

# Choose the appropriate build script based on whether this is a chained build
RUN --mount=type=tmpfs,dst=/opt \
  --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  if [ -n "${CHAIN_BASE_IMAGE}" ]; then \
    # For chained builds, only apply DX/GDX features \
    IMAGE_NAME=${IMAGE_NAME} /run/context/build_scripts/99-DX.sh; \
  else \
    # For regular builds, run full build process \
    IMAGE_NAME=${IMAGE_NAME} /run/context/build_scripts/build.sh; \
  fi

# Makes `/opt` writeable by default
# Needs to be here to make the main image build strict (no /opt there)
RUN rm -rf /opt && ln -s /var/opt /opt 
