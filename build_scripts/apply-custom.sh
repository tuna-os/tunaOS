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
	python3 - <<-PYTHONEOF
		import os, subprocess, re

		def parse_simple_yaml(file_path):
		    data = {}
		    current_key = None
		    with open(file_path, 'r') as f:
		        for line in f:
		            line_strip = line.strip()
		            if not line_strip or line_strip.startswith('#'):
		                continue
		            m_key = re.match(r'^([a-zA-Z0-9_-]+)\s*:\s*(.*)$', line_strip)
		            if m_key:
		                current_key = m_key.group(1)
		                rest = m_key.group(2).strip()
		                if rest == '[]':
		                    data[current_key] = []
		                else:
		                    data[current_key] = []
		                continue
		            m_item = re.match(r'^-\s*(.+)$', line_strip)
		            if m_item and current_key:
		                val = m_item.group(1).strip().strip('"').strip("'")
		                data[current_key].append(val)
		    return data

		pkg_mgr = os.environ.get("PKG_MGR", "dnf")
		yaml_path = "${CUSTOM_DIR}/packages.yaml"
		if os.path.exists(yaml_path):
		    data = parse_simple_yaml(yaml_path)
		    pkgs = data.get(pkg_mgr, [])
		    install_pkgs = []
		    remove_pkgs = []
		    for p in pkgs:
		        if p.startswith('-'):
		            remove_pkgs.append(p[1:])
		        else:
		            install_pkgs.append(p)

		    # Handle package removals
		    if remove_pkgs:
		        print(f"Removing {len(remove_pkgs)} packages for {pkg_mgr}: {', '.join(remove_pkgs)}")
		        subprocess.run(["bash", "-c", f"source /run/context/build_scripts/lib.sh && pkg_remove {' '.join(remove_pkgs)}"], check=True)

		    # Handle package installs
		    if install_pkgs:
		        print(f"Installing {len(install_pkgs)} packages for {pkg_mgr}: {', '.join(install_pkgs)}")
		        subprocess.run(["bash", "-c", f"source /run/context/build_scripts/lib.sh && pkg_install {' '.join(install_pkgs)}"], check=True)

		    # Handle optional packages
		    optional_pkgs = data.get("optional", [])
		    if optional_pkgs:
		        print(f"Installing optional packages: {', '.join(optional_pkgs)}")
		        subprocess.run(["bash", "-c", f"source /run/context/build_scripts/lib.sh && install_available {' '.join(optional_pkgs)}"], check=False)

		    # Handle Fedora/CentOS/RHEL COPRs if on dnf
		    if pkg_mgr == "dnf" and "copr" in data:
		        for copr in data["copr"]:
		            print(f"Enabling COPR repository: {copr}")
		            subprocess.run(["dnf", "copr", "enable", "-y", copr], check=True)

		    # Handle Flatpaks if specified in packages.yaml
		    flatpaks = data.get("flatpak", [])
		    if flatpaks:
		        print(f"Pre-installing flatpaks: {', '.join(flatpaks)}")
		        for fp in flatpaks:
		            subprocess.run(["flatpak", "install", "--system", "-y", "flathub", fp], check=True)
	PYTHONEOF
fi

# 2b. Install Flatpaks from flatpaks.list if present
if [[ -f "${CUSTOM_DIR}/flatpaks.list" ]]; then
	printf "==> Pre-installing flatpaks from flatpaks.list...\n"
	while IFS= read -r fp || [[ -n "$fp" ]]; do
		fp=$(echo "$fp" | sed 's/#.*//' | xargs)
		[[ -z "$fp" ]] && continue
		printf "Installing flatpak: %s\n" "$fp"
		flatpak install --system -y flathub "$fp" || printf "Warning: failed to install flatpak %s\n" "$fp"
	done < "${CUSTOM_DIR}/flatpaks.list"
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
