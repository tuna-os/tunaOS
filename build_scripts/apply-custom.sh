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

		def parse_yaml(file_path):
		    data = {}
		    current_key = None
		    with open(file_path, 'r') as f:
		        for line in f:
		            line = line.strip()
		            if not line or line.startswith('#'):
		                continue
		            # Match dictionary keys: "key:" or "key: []"
		            m = re.match(r'^([a-zA-Z0-9_-]+)\s*:\s*(.*)$', line)
		            if m:
		                current_key = m.group(1)
		                rest = m.group(2).strip()
		                if rest == '[]':
		                    data[current_key] = []
		                else:
		                    data[current_key] = []
		                continue
		            # Match list items: "- value"
		            m = re.match(r'^-\s*(.+)$', line)
		            if m and current_key:
		                val = m.group(1).strip().strip('"').strip("'")
		                data[current_key].append(val)
		    return data

		pkg_mgr = os.environ.get("PKG_MGR", "dnf")
		yaml_path = "${CUSTOM_DIR}/packages.yaml"
		if os.path.exists(yaml_path):
		    data = parse_yaml(yaml_path)
		    pkgs = data.get(pkg_mgr, [])
		    if pkgs:
		        print(f"Installing {len(pkgs)} packages for {pkg_mgr}: {', '.join(pkgs)}")
		        # Invoke the pkg_install function via bash
		        subprocess.run(["bash", "-c", f"source /run/context/build_scripts/lib.sh && pkg_install {' '.join(pkgs)}"], check=True)

		    # Handle Fedora/CentOS/RHEL COPRs if on dnf
		    if pkg_mgr == "dnf" and "copr" in data:
		        # Simple regex check for COPR entries
		        # Format:
		        # copr:
		        #   - owner/project
		        for copr in data["copr"]:
		            print(f"Enabling COPR repository: {copr}")
		            subprocess.run(["dnf", "copr", "enable", "-y", copr], check=True)
	PYTHONEOF
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
