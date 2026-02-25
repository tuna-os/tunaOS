ARG BASE_IMAGE
ARG ENABLE_HWE="${ENABLE_HWE:-0}"
ARG ENABLE_GDX="${ENABLE_GDX:-0}"
ARG AKMODS_VERSION="${AKMODS_VERSION:-centos-10}"
ARG COMMON_IMAGE_REF
ARG BREW_IMAGE_REF
ARG AKMODS_BASE="ghcr.io/ublue-os"

# Upstream mounts akmods-zfs and akmods-nvidia-open; select their tag via AKMODS_VERSION
FROM ${AKMODS_BASE}/akmods-zfs:${AKMODS_VERSION} AS akmods_zfs
FROM ${AKMODS_BASE}/akmods-nvidia-open:${AKMODS_VERSION} AS akmods_nvidia_open
FROM ${COMMON_IMAGE_REF} AS common
FROM ${BREW_IMAGE_REF} AS brew

FROM scratch as context
COPY system_files /files
COPY --from=brew /system_files /files
COPY --from=common /system_files/shared /files
COPY system_files_overrides /overrides
COPY build_scripts /build_scripts

FROM ${BASE_IMAGE}

ARG IMAGE_NAME
ARG IMAGE_VENDOR
ARG SHA_HEAD_SHORT="${SHA_HEAD_SHORT:-deadbeef}"
ARG BASE_IMAGE
ARG ENABLE_HWE="${ENABLE_HWE:-0}"
ARG ENABLE_GDX="${ENABLE_GDX:-0}"
ENV BASE_IMAGE=${BASE_IMAGE}
ENV IMAGE_NAME=${IMAGE_NAME}
ENV IMAGE_VENDOR=${IMAGE_VENDOR}
ENV SHA_HEAD_SHORT=${SHA_HEAD_SHORT}
ENV ENABLE_HWE=${ENABLE_HWE}
ENV ENABLE_GDX=${ENABLE_GDX}

# We pass in BASE_IMAGE as an env var to set it in os-release so that we know what we are building on
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_zfs,src=/rpms,dst=/tmp/akmods-zfs-rpms \
  --mount=type=bind,from=akmods_zfs,src=/kernel-rpms,dst=/tmp/kernel-rpms \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/copy-files.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_zfs,src=/rpms,dst=/tmp/akmods-zfs-rpms \
  --mount=type=bind,from=akmods_zfs,src=/kernel-rpms,dst=/tmp/kernel-rpms \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/00-workarounds.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_zfs,src=/rpms,dst=/tmp/akmods-zfs-rpms \
  --mount=type=bind,from=akmods_zfs,src=/kernel-rpms,dst=/tmp/kernel-rpms \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/10-base-packages.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_zfs,src=/rpms,dst=/tmp/akmods-zfs-rpms \
  --mount=type=bind,from=akmods_zfs,src=/kernel-rpms,dst=/tmp/kernel-rpms \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/20-packages.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_zfs,src=/rpms,dst=/tmp/akmods-zfs-rpms \
  --mount=type=bind,from=akmods_zfs,src=/kernel-rpms,dst=/tmp/kernel-rpms \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/26-packages-post.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_zfs,src=/rpms,dst=/tmp/akmods-zfs-rpms \
  --mount=type=bind,from=akmods_zfs,src=/kernel-rpms,dst=/tmp/kernel-rpms \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/40-services.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_zfs,src=/rpms,dst=/tmp/akmods-zfs-rpms \
  --mount=type=bind,from=akmods_zfs,src=/kernel-rpms,dst=/tmp/kernel-rpms \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/90-image-info.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_zfs,src=/rpms,dst=/tmp/akmods-zfs-rpms \
  --mount=type=bind,from=akmods_zfs,src=/kernel-rpms,dst=/tmp/kernel-rpms \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/arch-customizations.sh

RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/var --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=akmods_zfs,src=/rpms,dst=/tmp/akmods-zfs-rpms \
  --mount=type=bind,from=akmods_zfs,src=/kernel-rpms,dst=/tmp/kernel-rpms \
  --mount=type=bind,from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/cleanup.sh

# Makes `/opt` writeable by default
# Needs to be here to make the main image build strict (no /opt there)
RUN rm -rf /opt && ln -s /var/opt /opt 
