# --- CI recipes called from workflows: checks ---
# Each recipe is a workflow step moved out of YAML so it can be run and tested locally.
# Recipe names are prefixed ci- (just imports share one flat namespace).

# Probe one variant's published catalog images for catalog-facts.yml: writes shard.json; reads WANT_VARIANT, IMAGE_REGISTRY; registers pulled images and labels run containers for `just ci-cleanup`
ci-catalog-facts-probe:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}
    # shellcheck source=scripts/lib/ci-scope.sh
    source {{ justfile_directory() }}/scripts/lib/ci-scope.sh
    ci_labels=()
    mapfile -t ci_labels < <(ci_label_args)
    # "<registry>/<namespace>": [build.publish] in tunaos.toml, else
    # ghcr.io/<owner>. The catalog key is the same path without the host.
    PUBLISH_DEST="$(bash {{ justfile_directory() }}/scripts/publish-destination.sh)"
    # Same selection the browser catalog offers: published desktop images
    # (build_image, plain desktop tags — no -nvidia/-hwe, no base).
    mapfile -t CELLS < <(yq -o=json '.' .github/build-config.yml | jq -r \
      --arg v "$WANT_VARIANT" '
        .variants[] | .id as $var | .flavors[]
        | select(.build_image == true)
        | select(.id | test("^(gnome|kde|cosmic|niri|xfce)$"))
        | select($var == $v)
        | "\($var):\(.id)"')
    echo "probing ${#CELLS[@]} images for ${WANT_VARIANT}"

    echo '{}' > shard.json
    for CELL in "${CELLS[@]}"; do
      IMG="${PUBLISH_DEST}/${CELL}"
      echo "::group::${CELL}"
      # Digest first: it is what the app validates its cache against, and
      # a miss means the image is not published — skip rather than emit
      # a stale entry.
      DIGEST=$(skopeo inspect --format '{{ "{{" }}.Digest}}' "docker://${IMG}" 2>/dev/null || true)
      # An image already in storage before the pull is not this job's to remove.
      pre_pulled=0
      if podman image exists "$IMG"; then pre_pulled=1; fi
      if [[ -z "$DIGEST" ]] || ! podman pull -q "$IMG" >/dev/null 2>&1; then
        echo "unavailable; skipping"; echo "::endgroup::"; continue
      fi
      if [[ "$pre_pulled" -eq 0 ]]; then ci_own_image "$IMG"; fi

      # Probe the same signals purefs.Introspect derives from the
      # unpacked tree, so the app shows identical facts.
      PROBE=$(podman run --rm "${ci_labels[@]}" --entrypoint="" "$IMG" sh -c '
        echo "kernelVer=$(ls /usr/lib/modules 2>/dev/null | head -1)"
        if   [ -f /usr/share/wayland-sessions/plasma.desktop ] \
          || [ -f /usr/share/wayland-sessions/plasmawayland.desktop ]; then echo "desktop=kde"
        elif [ -f /usr/share/wayland-sessions/niri.desktop ];   then echo "desktop=niri"
        elif [ -f /usr/share/wayland-sessions/cosmic.desktop ]; then echo "desktop=cosmic"
        elif ls /usr/share/xsessions/xfce*.desktop >/dev/null 2>&1 \
          || ls /usr/share/wayland-sessions/xfce*.desktop >/dev/null 2>&1; then echo "desktop=xfce"
        else echo "desktop=gnome"; fi
        [ -f /usr/lib/systemd/boot/efi/systemd-bootx64.efi ] && echo "hasSdBoot=true" || echo "hasSdBoot=false"
        if   command -v dnf >/dev/null 2>&1 || command -v dnf5 >/dev/null 2>&1; then echo "pkgManager=dnf"; echo "repoFamily=fedora"
        elif command -v zypper >/dev/null 2>&1; then echo "pkgManager=zypper"; echo "repoFamily=opensuse"
        elif command -v pacman >/dev/null 2>&1; then echo "pkgManager=pacman"; echo "repoFamily=arch"
        elif command -v apt >/dev/null 2>&1 || command -v apt-get >/dev/null 2>&1; then echo "pkgManager=apt"; echo "repoFamily=debian"
        elif command -v apk >/dev/null 2>&1; then echo "pkgManager=apk"; echo "repoFamily=alpine"
        else echo "pkgManager="; echo "repoFamily="; fi
      ' 2>/dev/null || true)

      get() { echo "$PROBE" | grep "^$1=" | head -1 | cut -d= -f2-; }
      jq --arg k "${PUBLISH_DEST#*/}/${CELL}" --arg d "$DIGEST" \
         --arg de "$(get desktop)" --arg kv "$(get kernelVer)" \
         --arg sb "$(get hasSdBoot)" --arg pm "$(get pkgManager)" \
         --arg rf "$(get repoFamily)" \
         '.[$k] = {digest:$d, desktop:$de, kernelVer:$kv,
                   hasSdBoot:($sb=="true"), pkgManager:$pm, repoFamily:$rf}' \
         shard.json > shard.tmp && mv shard.tmp shard.json

      podman rmi "$IMG" >/dev/null 2>&1 || true
      echo "::endgroup::"
    done
    jq . shard.json

# Verify one published image for daily-verify.yml: bootc labels, then `bootc install print-configuration`; reads VARIANT, FLAVOR, OWNER; registers the pulled image and labels the run container for `just ci-cleanup`
ci-daily-verify-image:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}
    # shellcheck source=scripts/lib/ci-scope.sh
    source {{ justfile_directory() }}/scripts/lib/ci-scope.sh
    ci_labels=()
    mapfile -t ci_labels < <(ci_label_args)
    IMAGE_REF="ghcr.io/${OWNER}/${VARIANT}:${FLAVOR}"
    echo "==> Verifying ${IMAGE_REF}"

    # 1. Check the image exists and pull its manifest
    if ! skopeo inspect "docker://${IMAGE_REF}" > /tmp/manifest.json 2>&1; then
      echo "::error::Image not found or not accessible: ${IMAGE_REF}"
      cat /tmp/manifest.json
      exit 1
    fi

    # 2. Verify key bootc labels are present
    BOOTABLE=$(jq -r '.Labels["containers.bootc"] // empty' /tmp/manifest.json)
    if [[ "$BOOTABLE" != "1" ]]; then
      echo "::error::Missing containers.bootc=1 label on ${IMAGE_REF}"
      exit 1
    fi
    echo "  ✓ containers.bootc=1"

    OSTREE=$(jq -r '.Labels["ostree.bootable"] // empty' /tmp/manifest.json)
    if [[ "$OSTREE" != "1" ]]; then
      echo "::error::Missing ostree.bootable=1 label on ${IMAGE_REF}"
      exit 1
    fi
    echo "  ✓ ostree.bootable=1"

    # 3. Pull the image and validate bootc install config
    echo "==> Pulling image for bootc config validation..."
    # An image already in storage before the pull is not this job's to remove.
    pre_pulled=0
    if podman image exists "${IMAGE_REF}"; then pre_pulled=1; fi
    podman pull "${IMAGE_REF}"
    if [[ "$pre_pulled" -eq 0 ]]; then ci_own_image "${IMAGE_REF}"; fi

    echo "==> Running bootc install print-configuration..."
    podman run --rm --privileged "${ci_labels[@]}" \
      -v "{{ justfile_directory() }}/system_files/usr/lib/bootc/install/00-tunaos.toml:/usr/lib/bootc/install/00-tunaos.toml:ro" \
      "${IMAGE_REF}" \
      bootc install print-configuration

    echo "✓ ${VARIANT}:${FLAVOR} passed verification"
