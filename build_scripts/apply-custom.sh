#!/usr/bin/env bash
set -euo pipefail

printf "::group:: === Apply Custom Overlay ===\n"

# Source the TunaOS build environment libraries
source /run/context/build_scripts/lib.sh

CUSTOM_DIR="/custom"

# 1. Run Pre-Build Hook
if [[ -x "${CUSTOM_DIR}/build.pre.sh" ]]; then
	printf "==> Running build.pre.sh hook...\n"
	"${CUSTOM_DIR}/build.pre.sh"
fi

# 2. Parse and Install Packages from packages.yaml
if [[ -f "${CUSTOM_DIR}/packages.yaml" ]]; then
	printf "==> Installing custom packages...\n"
	CUSTOM_PACKAGES_TOOL="/run/context/build_scripts/lib/custom_packages.py"
	CUSTOM_PACKAGES_FILE="${CUSTOM_DIR}/packages.yaml"

	python3 "${CUSTOM_PACKAGES_TOOL}" --validate "${CUSTOM_PACKAGES_FILE}"
	custom_package_items() {
		python3 "${CUSTOM_PACKAGES_TOOL}" --items "$1" "${CUSTOM_PACKAGES_FILE}"
	}

	pkg_mgr="${PKG_MGR:-dnf}"
	mapfile -t package_entries < <(custom_package_items "${pkg_mgr}")
	install_pkgs=()
	remove_pkgs=()
	for package in "${package_entries[@]}"; do
		if [[ "${package}" == -* ]]; then
			remove_pkgs+=("${package#-}")
		else
			install_pkgs+=("${package}")
		fi
	done

	if ((${#remove_pkgs[@]})); then
		printf "Removing %d packages for %s: %s\n" \
			"${#remove_pkgs[@]}" "${pkg_mgr}" "${remove_pkgs[*]}"
		pkg_remove "${remove_pkgs[@]}"
	fi

	if ((${#install_pkgs[@]})); then
		printf "Installing %d packages for %s: %s\n" \
			"${#install_pkgs[@]}" "${pkg_mgr}" "${install_pkgs[*]}"
		pkg_install "${install_pkgs[@]}"
	fi

	mapfile -t optional_pkgs < <(custom_package_items optional)
	if ((${#optional_pkgs[@]})); then
		printf "Installing optional packages: %s\n" "${optional_pkgs[*]}"
		install_available "${optional_pkgs[@]}" || true
	fi

	if [[ "${pkg_mgr}" == dnf ]]; then
		mapfile -t coprs < <(custom_package_items copr)
		for copr in "${coprs[@]}"; do
			printf "Enabling COPR repository: %s\n" "${copr}"
			dnf copr enable -y "${copr}"
		done
	fi

	mapfile -t flatpaks < <(custom_package_items flatpak)
	if ((${#flatpaks[@]})); then
		printf "Pre-installing Flatpaks: %s\n" "${flatpaks[*]}"
		for flatpak in "${flatpaks[@]}"; do
			flatpak install --system -y flathub "${flatpak}"
		done
	fi
fi

# 2b. Install Flatpaks from flatpaks.list if present
if [[ -f "${CUSTOM_DIR}/flatpaks.list" ]]; then
	printf "==> Pre-installing flatpaks from flatpaks.list...\n"
	while IFS= read -r fp || [[ -n "$fp" ]]; do
		fp=$(echo "$fp" | sed 's/#.*//' | xargs)
		[[ -z "$fp" ]] && continue
		printf "Installing flatpak: %s\n" "$fp"
		flatpak install --system -y flathub "$fp" || printf "Warning: failed to install flatpak %s\n" "$fp"
	done <"${CUSTOM_DIR}/flatpaks.list"
fi

# 3. Copy Custom Files Overlay
if [[ -d "${CUSTOM_DIR}/files" ]] && [ "$(ls -A "${CUSTOM_DIR}/files")" ]; then
	printf "==> Copying custom file overrides...\n"
	cp -aT "${CUSTOM_DIR}/files/" /
fi

# 4. Copy Systemd Units and Enable them
if [[ -d "${CUSTOM_DIR}/systemd" ]] && [ "$(ls -A "${CUSTOM_DIR}/systemd")" ]; then
	printf "==> Copying and enabling systemd units...\n"
	# Copy systemd units to /etc/systemd/system
	cp -a "${CUSTOM_DIR}/systemd/"* /etc/systemd/system/
	# Enable copied services
	for unit in "${CUSTOM_DIR}/systemd/"*; do
		unit_name=$(basename "${unit}")
		printf "Enabling systemd unit: %s\n" "${unit_name}"
		systemctl enable "${unit_name}" || printf "Warning: failed to enable %s\n" "${unit_name}"
	done
fi

# 5. Copy Custom Just/Ujust Recipes
if [[ -d "${CUSTOM_DIR}/just" ]] && [ "$(ls -A "${CUSTOM_DIR}/just")" ]; then
	printf "==> Copying custom just/ujust recipes...\n"
	mkdir -p /usr/share/ublue-os/just
	cp -a "${CUSTOM_DIR}/just/"*.just /usr/share/ublue-os/just/
fi

# 6. Run Post-Build Hook
if [[ -x "${CUSTOM_DIR}/build.post.sh" ]]; then
	printf "==> Running build.post.sh hook...\n"
	"${CUSTOM_DIR}/build.post.sh"
fi

printf "::endgroup::\n"
