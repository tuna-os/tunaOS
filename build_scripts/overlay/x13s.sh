#!/usr/bin/env bash
# x13s.sh — make bonito:gnome boot and work on the ThinkPad X13s (W2), and
# record what the image carries.
#
# Fedora's stock kernel already has every SC8280XP driver and both X13s DTBs
# (W1 inventory). This overlay adds what a working X13s install needs on top,
# each taken from what postmarketOS boots this laptop with:
#   - the GPU and DSP/audio firmware (Fedora's qcom-firmware);
#   - the DTB, carried per deployment by ostree (see below);
#   - the kernel arguments, through bootc kargs.d;
#   - display, keyboard and storage drivers in the initramfs, so the LUKS
#     passphrase prompt is visible and typeable.
# It then writes the inventory and fails if anything is still missing.
set -euo pipefail

if [[ "$(uname -m)" != "aarch64" ]]; then
	echo "ERROR: the X13s overlay only applies to aarch64 builds" >&2
	exit 1
fi

# shellcheck disable=SC1091 # supplied by the parent image
. /etc/os-release
case "${ID}" in
fedora) family=fedora ;; # bonito: ostree, GRUB via bootupd
archarm) family=arch ;;  # marlin: composefs, systemd-boot
*)
	echo "ERROR: the X13s profile supports Fedora (bonito) and Arch Linux ARM (marlin) parents, not ${ID}" >&2
	exit 1
	;;
esac

mapfile -t kernels < <(
	find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -V
)
if ((${#kernels[@]} == 0)); then
	echo "ERROR: X13s inspection requires a kernel" >&2
	exit 1
fi
last_kernel_index=$((${#kernels[@]} - 1))
kver="${kernels[$last_kernel_index]}"
if ((${#kernels[@]} > 1)); then
	printf 'WARNING: X13s inspection found %d kernels (%s); using newest %s\n' \
		"${#kernels[@]}" "${kernels[*]}" "${kver}" >&2
fi
module_dir="/usr/lib/modules/${kver}"

config="${module_dir}/config"
for candidate in "${module_dir}/config" "/boot/config-${kver}" "${module_dir}/build/.config"; do
	if [[ -r "${candidate}" ]]; then
		config="${candidate}"
		break
	fi
done
if [[ ! -r "${config}" ]]; then
	echo "ERROR: no kernel configuration found for ${kver}" >&2
	exit 1
fi

# The distro's own kernel, not a hardware fork: W1 showed it already carries
# every SC8280XP driver, and a custom kernel would make the inventory evidence
# about itself.
if [[ "${family}" == fedora ]]; then
	rpm -q kernel-core >/dev/null
	if ! rpm -q --qf '%{VENDOR}\n' kernel-core | grep -q '^Fedora Project$'; then
		echo "ERROR: the X13s profile requires Fedora's stock kernel-core package" >&2
		exit 1
	fi
else
	# linux-aarch64 ships /boot/Image, which ostree-layout.sh copies to
	# vmlinuz, so no package owns that file; match the version instead.
	kernel_pkg_version="$(pacman -Q linux-aarch64 | awk '{print $2}')"
	if [[ "${kver}" != "${kernel_pkg_version}-"* ]]; then
		echo "ERROR: kernel ${kver} is not Arch Linux ARM's stock linux-aarch64 ${kernel_pkg_version}" >&2
		exit 1
	fi
fi

# ── W2: what the X13s needs beyond the stock payload ─────────────────────────
x13s_dtb="${module_dir}/dtb/qcom/sc8280xp-lenovo-thinkpad-x13s.dtb"

if [[ "${family}" == fedora ]]; then
	if [[ ! -s "${x13s_dtb}" ]]; then
		echo "ERROR: Fedora kernel payload has no X13s DTB at ${x13s_dtb}" >&2
		exit 1
	fi

	# Adreno 690 (qcom/a660_*) and the board's DSP, audio topology and
	# battery manager (qcom/sc8280xp/LENOVO/21BX/). The parent image ships
	# neither. The package is in Fedora itself; skip the metadata of the
	# parent's other repositories (RPM Fusion, openh264, the updates archive).
	dnf -y --repo=fedora --repo=updates install qcom-firmware
	dnf clean all

	# The firmware boots Linux with ACPI tables, but this laptop needs its
	# device tree. ostree deploys /usr/lib/modules/$kver/devicetree into each
	# deployment's /boot and writes a `devicetree` line into its boot entry,
	# which Fedora's GRUB (blscfg) and systemd-boot both load. Every
	# deployment and rollback therefore boots the DTB built with its own
	# kernel. With only the dtb/ directory, ostree writes `fdtdir`, which
	# GRUB ignores.
	install -m 0644 "${x13s_dtb}" "${module_dir}/devicetree"
else
	# linux-aarch64 ships its DTBs only under /boot/dtbs, which the base
	# build deletes (bootc/ostree-layout.sh). Take the X13s DTB from the very
	# package version that is installed; a newer one in the repository would
	# describe a different kernel, so refuse it instead of mixing them.
	pacman -Sy --noconfirm
	repo_version="$(pacman -Si linux-aarch64 | awk -F': ' '/^Version/ {print $2; exit}')"
	if [[ "${repo_version}" != "${kernel_pkg_version}" ]]; then
		echo "ERROR: installed linux-aarch64 ${kernel_pkg_version} but the repository now has ${repo_version}; rebuild the parent first" >&2
		exit 1
	fi
	pkg_cache="$(mktemp -d)"
	pacman -Sw --noconfirm --cachedir "${pkg_cache}" linux-aarch64
	install -d -m 0755 "${module_dir}/dtb/qcom"
	# The cache also holds the detached .sig; read the package itself.
	kernel_pkg="$(find "${pkg_cache}" -maxdepth 1 -name "linux-aarch64-${kernel_pkg_version}-*.pkg.tar.*" ! -name '*.sig' -print -quit)"
	bsdtar -xOf "${kernel_pkg}" boot/dtbs/qcom/sc8280xp-lenovo-thinkpad-x13s.dtb >"${x13s_dtb}"
	rm -rf "${pkg_cache}"
	if [[ ! -s "${x13s_dtb}" ]]; then
		echo "ERROR: linux-aarch64 ${kernel_pkg_version} has no X13s DTB" >&2
		exit 1
	fi

	# GPU, DSP, audio topology and battery firmware, as on Fedora.
	pacman -S --noconfirm --needed linux-firmware-qcom

	# bootc's composefs systemd-boot entries carry no `devicetree` line
	# (tuna-os/bootc-migrate#461, U3). Instead the kernel itself carries the
	# DTB: wrap vmlinuz in systemd-stub with a .dtbauto section and the
	# hardware-ID table, so the stub picks this DTB by the machine's CHID. The
	# initramfs and command line still come from the boot entry; the stub
	# adds no .cmdline. This is the mechanism of Fedora's kernel-dtb-loader.
	# systemd-ukify pins systemd to its own version; installing it against a
	# different systemd would be a partial upgrade of the init system.
	# The dependency names a pkgver (systemd=262.1); pacman -Q adds -pkgrel.
	ukify_systemd="$(pacman -Si systemd-ukify | sed -n 's/^Depends On *: .*systemd=\([^ ]*\).*/\1/p')"
	installed_systemd="$(pacman -Q systemd | awk '{print $2}')"
	if [[ "${installed_systemd%-*}" != "${ukify_systemd%-*}" ]]; then
		echo "ERROR: systemd-ukify needs systemd ${ukify_systemd}; the parent has ${installed_systemd}; rebuild the parent first" >&2
		exit 1
	fi
	pacman -S --noconfirm --needed systemd-ukify
	ukify build \
		--linux="${module_dir}/vmlinuz" \
		--devicetree-auto="${x13s_dtb}" \
		--hwids=/usr/lib/systemd/boot/hwids/aa64 \
		--stub=/usr/lib/systemd/boot/efi/linuxaa64.efi.stub \
		--uname="${kver}" \
		--output=/tmp/vmlinuz.dtbauto
	# Record the PE sections while pefile (a ukify dependency) is installed.
	python3 -c 'import pefile, sys
for s in pefile.PE(sys.argv[1], fast_load=True).sections:
    print(s.Name.rstrip(b"\0").decode())' /tmp/vmlinuz.dtbauto >/tmp/x13s-stub-sections
	install -m 0755 /tmp/vmlinuz.dtbauto "${module_dir}/vmlinuz"
	rm -f /tmp/vmlinuz.dtbauto
	pacman -Rns --noconfirm systemd-ukify
	pacman -Scc --noconfirm >/dev/null
fi

# The arguments postmarketOS boots the X13s with: pointer authentication is
# broken in the firmware, and unused clocks and power domains must stay on
# until their drivers load or the display and USB drop out.
install -d -m 0755 /usr/lib/bootc/kargs.d
cat >/usr/lib/bootc/kargs.d/10-x13s.toml <<'EOF'
# ThinkPad X13s (SC8280XP), written by build_scripts/overlay/x13s.sh.
kargs = ["arm64.nopauth", "clk_ignore_unused", "pd_ignore_unused"]
match-architectures = ["aarch64"]
EOF

# Early-boot drivers: postmarketOS's device-lenovo-21bx modules-initfs list,
# kept to the modules this kernel actually ships (some are built in). Without
# them the initramfs has no display or keyboard, and a LUKS prompt is blind.
early_modules=(
	apr dispcc_sc8280xp dwc3 dwc3_qcom extcon_core gpio_sbu_mux gpucc_sc8280xp
	hci_uart hid_generic hid_multitouch i2c_hid_of i2c_hid_of_elan i2c_qcom_cci
	i2c_qcom_geni icc_bwmon icc_osm_l3 leds_gpio leds_qcom_lpg llcc_qcom
	lpasscc_sc8280xp msm nvme panel_edp pci_pwrctrl_pwrseq pcie_qcom phy_qcom_edp
	phy_qcom_qmp_combo phy_qcom_qmp_pcie phy_qcom_qmp_usb phy_qcom_snps_femto_v2
	pinctrl_sc8280xp_lpass_lpi pmic_glink pmic_glink_altmode pwm_bl pwrseq_core
	pwrseq_qcom_wcn q6apm_dai q6apm_lpass_dais q6prm q6prm_clocks
	qcom_pm8008_regulator qcom_battmgr qcom_camss qcom_common qcom_pm8008
	qcom_pon qcom_q6v5_pas qcom_rng qcom_spmi_adc5 qcom_spmi_adc_tm5
	qcom_spmi_temp_alarm qcom_stats qcom_wdt qrtr qrtr_smd rtc_pm8xxx typec
	videocc_sm8350
)
loadable=()
for module in "${early_modules[@]}"; do
	if modinfo -k "${kver}" -F filename "${module}" 2>/dev/null | grep -q '\.ko'; then
		loadable+=("${module}")
	fi
done
# Drivers for GPUs this laptop does not have pull in their firmware (NVIDIA
# GSP alone is about 100M); leaving them out keeps the boot set small enough
# for an ESP shared with postmarketOS (tuna-os/bootc-migrate#461).
cat >/usr/lib/dracut/dracut.conf.d/90-x13s.conf <<EOF
# ThinkPad X13s early boot, written by build_scripts/overlay/x13s.sh.
add_drivers+=" ${loadable[*]} "
add_dracutmodules+=" crypt "
omit_drivers+=" nouveau nvidia amdgpu radeon i915 xe "
EOF
printf 'x13s.sh: %d of %d early-boot modules are loadable modules; the rest are built in or absent\n' \
	"${#loadable[@]}" "${#early_modules[@]}"

# Rebuild the initramfs the way the parent built it.
if [[ "${family}" == fedora ]]; then
	# As 26-packages-post.sh does for Fedora.
	mkdir -p /var/roothome
	chmod 0700 /var/roothome
	export DRACUT_NO_XATTR=1
	/usr/bin/dracut --tmpdir /tmp --no-hostonly --kver "${kver}" --reproducible --zstd --add ostree \
		-f "${module_dir}/initramfs.img"
else
	# As Containerfile.arch does: dracut-config.sh writes the composefs
	# configuration, then dracut builds against the named kernel. The X13s
	# GPU is msm; the default early-KMS list (i915 amdgpu nouveau) would add
	# about 230M of other vendors' firmware.
	TUNAOS_DRACUT_KMS_DRIVERS=msm /run/context/build_scripts/bootc/dracut-config.sh "${kver}"
	dracut --force "${module_dir}/initramfs.img" "${kver}"
fi

# What the laptop needs to boot and work: SoC, display, keyboard and touchpad,
# NVMe, USB-C, Wi-Fi, Bluetooth, audio, battery. A missing one fails the build.
required_kconfigs=(
	CONFIG_ARCH_QCOM
	CONFIG_ARM_QCOM_CPUFREQ_HW
	CONFIG_ATH11K_PCI
	CONFIG_BATTERY_QCOM_BATTMGR
	CONFIG_BLK_DEV_NVME
	CONFIG_BT_HCIUART_QCA
	CONFIG_DRM_MSM
	CONFIG_DRM_PANEL_EDP
	CONFIG_I2C_HID_OF
	CONFIG_I2C_QCOM_GENI
	CONFIG_PCIE_QCOM
	CONFIG_PHY_QCOM_QMP_COMBO
	CONFIG_PHY_QCOM_QMP_PCIE
	CONFIG_PINCTRL_SC8280XP
	CONFIG_QCOM_PMIC_GLINK
	CONFIG_QCOM_Q6V5_PAS
	CONFIG_QRTR
	CONFIG_RPMSG_QCOM_GLINK_SMEM
	CONFIG_SND_SOC_SC8280XP
	CONFIG_TYPEC
	CONFIG_UCSI_PMIC_GLINK
	CONFIG_USB_DWC3
)

# Features some X13s units or uses lack; reported, never silently dropped.
# Arch Linux ARM's linux-aarch64 7.2.11 has none of these three.
optional_kconfigs=(
	CONFIG_I2C_HID_OF_ELAN       # Elan touchscreen (touchscreen models only)
	CONFIG_REGULATOR_QCOM_PM8008 # camera sensor supplies
	CONFIG_SQUASHFS_ZSTD         # live ISO root; this profile builds no ISO
)

# Names come from postmarketOS's device-lenovo-21bx early-module inventory.
# A missing .ko is not automatically a gap because Fedora builds some of these
# into vmlinuz; the Kconfig section above distinguishes that case.
inspect_modules=(
	ath11k_pci
	dispcc_sc8280xp
	dwc3_qcom
	gpucc_sc8280xp
	i2c_hid_of
	i2c_hid_of_elan
	i2c_qcom_geni
	msm
	nvme
	panel_edp
	pcie_qcom
	phy_qcom_qmp_combo
	phy_qcom_qmp_pcie
	phy_qcom_qmp_usb
	pmic_glink
	pmic_glink_altmode
	qcom_battmgr
	qcom_q6v5_pas
	qrtr
	snd_soc_sc8280xp
)

# The firmware list is the board inventory, not a redistribution request. Both
# Fedora's compressed payloads and uncompressed files satisfy the inventory.
# Linux firmware loading supports .xz and .zst, not arbitrary backup suffixes.
inspect_firmware=(
	/usr/lib/firmware/qca/hpbtfw21.tlv
	/usr/lib/firmware/qca/hpnv21.b8c
	/usr/lib/firmware/qca/hpnv21g.b8c
	/usr/lib/firmware/qcom/a660_gmu.bin
	/usr/lib/firmware/qcom/a660_sqe.fw
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/qcvss8280.mbn
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/adspr.jsn
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/adspua.jsn
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/audioreach-tplg.bin
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/battmgr.jsn
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/cdspr.jsn
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/qcadsp8280.mbn
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/qccdsp8280.mbn
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/qcdxkmsuc8280.mbn
	/usr/lib/firmware/qcom/sc8280xp/LENOVO/21BX/qcslpi8280.mbn
	/usr/lib/firmware/ath11k/WCN6855/hw2.1/amss.bin
	/usr/lib/firmware/ath11k/WCN6855/hw2.1/board-2.bin
	/usr/lib/firmware/ath11k/WCN6855/hw2.1/m3.bin
	/usr/lib/firmware/ath11k/WCN6855/hw2.1/regdb.bin
)

. "$(dirname "${BASH_SOURCE[0]}")/lib/x13s_inventory.sh"

report_dir=/usr/share/tunaos
report="${report_dir}/x13s-inspection.txt"
tmp_report="$(mktemp)"
trap 'rm -f "${tmp_report}"' EXIT

{
	echo "X13s payload inspection (${family})"
	echo "architecture=aarch64"
	echo "os=${PRETTY_NAME}"
	echo "kernel=${kver}"
	echo "base_image=${BASE_IMAGE:-unknown}"
	echo
	echo "[kernel-packages]"
	if [[ "${family}" == fedora ]]; then
		rpm -qa 'kernel*' --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort
	else
		pacman -Q linux-aarch64
	fi
	echo
	echo "[kernel-config]"
	missing_kconfig=()
	for symbol in "${required_kconfigs[@]}"; do
		line="$(grep -m1 -E "^${symbol}=(y|m)$" "${config}" || true)"
		if [[ -n "${line}" ]]; then
			echo "${line}"
		else
			missing_kconfig+=("${symbol}")
			printf 'MISSING %s\n' "${symbol}"
		fi
	done
	printf 'missing_kconfig_count=%d\n' "${#missing_kconfig[@]}"
	for symbol in "${optional_kconfigs[@]}"; do
		line="$(grep -m1 -E "^${symbol}=(y|m)$" "${config}" || true)"
		if [[ -n "${line}" ]]; then
			echo "${line}"
		else
			printf 'OPTIONAL-MISSING %s\n' "${symbol}"
		fi
	done
	echo
	echo "[modules]"
	declare -A module_paths=()
	if [[ -d "${module_dir}/kernel" ]]; then
		while IFS= read -r path; do
			module_file="${path##*/}"
			module_name="${module_file%.zst}"
			module_name="${module_name%.xz}"
			module_name="${module_name%.ko}"
			module_paths["$module_name"]="$path"
		done < <(
			find "${module_dir}/kernel" -type f \
				\( -name '*.ko' -o -name '*.ko.xz' -o -name '*.ko.zst' \) \
				-print 2>/dev/null | LC_ALL=C sort || true
		)
	fi
	for module in "${inspect_modules[@]}"; do
		module_alt="${module//_/-}"
		path="${module_paths[$module]:-${module_paths[$module_alt]:-}}"
		if [[ -n "${path}" ]]; then
			printf 'MODULE %s -> %s\n' "${module}" "${path}"
		else
			printf 'BUILT_IN_OR_MISSING %s\n' "${module}"
		fi
	done
	echo
	echo "[dtbs]"
	if [[ -d "${module_dir}/dtb" ]]; then
		find "${module_dir}/dtb" -type f -name '*x13s*.dtb' -print | LC_ALL=C sort
	fi
	echo
	echo "[boot]"
	if [[ "${family}" == fedora ]]; then
		if cmp -s "${x13s_dtb}" "${module_dir}/devicetree"; then
			echo "PRESENT devicetree -> ${module_dir}/devicetree (sc8280xp-lenovo-thinkpad-x13s.dtb)"
		else
			echo "MISSING devicetree ${module_dir}/devicetree"
		fi
	else
		for section in linux dtbauto hwids; do
			if grep -q "^\.${section}" /tmp/x13s-stub-sections; then
				echo "PRESENT vmlinuz section .${section}"
			else
				echo "MISSING vmlinuz section .${section}"
			fi
		done
	fi
	grep -h '^kargs' /usr/lib/bootc/kargs.d/10-x13s.toml || echo "MISSING kargs /usr/lib/bootc/kargs.d/10-x13s.toml"
	echo
	echo "[initramfs]"
	initramfs_list="$(lsinitrd "${module_dir}/initramfs.img")"
	for module in "${loadable[@]}" crypt; do
		if [[ "${module}" == crypt ]]; then
			pattern='systemd-cryptsetup'
		else
			pattern="/${module//_/[-_]}\.ko"
		fi
		if grep -qE "${pattern}" <<<"${initramfs_list}"; then
			echo "PRESENT ${module}"
		else
			echo "MISSING ${module} (initramfs)"
		fi
	done
	echo
	echo "[firmware]"
	for firmware in "${inspect_firmware[@]}"; do
		inventory_file "${firmware}"
	done
} | tee "${tmp_report}"

install -d -m 0755 "${report_dir}"
install -m 0644 "${tmp_report}" "${report}"
echo "x13s.sh: inspection stored at ${report}"

# W2 ships a bootable payload: a missing symbol, DTB, argument, early module
# or firmware file fails the build instead of shipping a blind or dark laptop.
if grep -q '^MISSING ' "${report}"; then
	echo "ERROR: X13s payload incomplete:" >&2
	grep '^MISSING ' "${report}" >&2
	exit 1
fi
