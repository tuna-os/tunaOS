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

# shellcheck disable=SC1091 # supplied by the Fedora parent image
. /etc/os-release
if [[ "${ID}" != "fedora" ]]; then
	echo "ERROR: the initial X13s profile is supported only on Fedora (bonito)" >&2
	exit 1
fi

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
if [[ ! -r "${config}" ]]; then
	config="/boot/config-${kver}"
fi
if [[ ! -r "${config}" ]]; then
	echo "ERROR: no kernel configuration found for ${kver}" >&2
	exit 1
fi

# W1 tests the distro payload before a kernel fork can be justified. A custom
# hardware kernel here would turn the inspection into evidence about itself.
rpm -q kernel-core >/dev/null
if ! rpm -q --qf '%{VENDOR}\n' kernel-core | grep -q '^Fedora Project$'; then
	echo "ERROR: X13s W1 requires Fedora's stock kernel-core package" >&2
	exit 1
fi

# ── W2: what the X13s needs beyond the stock payload ─────────────────────────
x13s_dtb="${module_dir}/dtb/qcom/sc8280xp-lenovo-thinkpad-x13s.dtb"
if [[ ! -s "${x13s_dtb}" ]]; then
	echo "ERROR: Fedora kernel payload has no X13s DTB at ${x13s_dtb}" >&2
	exit 1
fi

# Adreno 690 (qcom/a660_*) and the board's DSP, audio topology and battery
# manager (qcom/sc8280xp/LENOVO/21BX/). The parent image ships neither.
# The package is in Fedora itself; skip the metadata of the parent's other
# repositories (RPM Fusion, openh264, the updates archive).
dnf -y --repo=fedora --repo=updates install qcom-firmware
dnf clean all

# The firmware boots Linux with ACPI tables, but this laptop needs its device
# tree. ostree deploys /usr/lib/modules/$kver/devicetree into each
# deployment's /boot and writes a `devicetree` line into its boot entry,
# which Fedora's GRUB (blscfg) and systemd-boot both load. Every deployment
# and rollback therefore boots the DTB built with its own kernel. With only
# the dtb/ directory, ostree writes `fdtdir`, which GRUB ignores.
install -m 0644 "${x13s_dtb}" "${module_dir}/devicetree"

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
cat >/usr/lib/dracut/dracut.conf.d/90-x13s.conf <<EOF
# ThinkPad X13s early boot, written by build_scripts/overlay/x13s.sh.
add_drivers+=" ${loadable[*]} "
add_dracutmodules+=" crypt "
EOF
printf 'x13s.sh: %d of %d early-boot modules are loadable modules; the rest are built in or absent\n' \
	"${#loadable[@]}" "${#early_modules[@]}"

# Rebuild the initramfs the way 26-packages-post.sh does for Fedora.
mkdir -p /var/roothome
chmod 0700 /var/roothome
export DRACUT_NO_XATTR=1
/usr/bin/dracut --tmpdir /tmp --no-hostonly --kver "${kver}" --reproducible --zstd --add ostree \
	-f "${module_dir}/initramfs.img"

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
	CONFIG_I2C_HID_OF_ELAN
	CONFIG_I2C_QCOM_GENI
	CONFIG_PCIE_QCOM
	CONFIG_PHY_QCOM_QMP_COMBO
	CONFIG_PHY_QCOM_QMP_PCIE
	CONFIG_PINCTRL_SC8280XP
	CONFIG_QCOM_PMIC_GLINK
	CONFIG_QCOM_Q6V5_PAS
	CONFIG_QRTR
	CONFIG_REGULATOR_QCOM_PM8008
	CONFIG_RPMSG_QCOM_GLINK_SMEM
	CONFIG_SND_SOC_SC8280XP
	CONFIG_SQUASHFS_ZSTD
	CONFIG_TYPEC
	CONFIG_UCSI_PMIC_GLINK
	CONFIG_USB_DWC3
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
	echo "X13s stock Fedora payload inspection"
	echo "architecture=aarch64"
	echo "os=${PRETTY_NAME}"
	echo "kernel=${kver}"
	echo "base_image=${BASE_IMAGE:-unknown}"
	echo
	echo "[kernel-packages]"
	rpm -qa 'kernel*' --qf '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort
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
	if cmp -s "${x13s_dtb}" "${module_dir}/devicetree"; then
		echo "PRESENT devicetree -> ${module_dir}/devicetree (sc8280xp-lenovo-thinkpad-x13s.dtb)"
	else
		echo "MISSING devicetree ${module_dir}/devicetree"
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
