#!/usr/bin/env bash
# x13s.sh — inspect the stock Fedora ARM64 payload for ThinkPad X13s W1.
#
# This overlay deliberately installs no replacement kernel, firmware, boot
# loader, or hardware defaults. Its job is to make the ARM64-only profile fail
# on a dishonest platform declaration and preserve a build-time inventory for
# the W2/W4 decisions. Missing firmware is reported rather than filled here;
# shipping early-boot dependencies belongs to W2 (#3368).
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
if ((${#kernels[@]} != 1)); then
	printf 'ERROR: X13s inspection requires exactly one kernel, found %d: %s\n' \
		"${#kernels[@]}" "${kernels[*]:-(none)}" >&2
	exit 1
fi
kver="${kernels[0]}"
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
	for module in "${inspect_modules[@]}"; do
		module_alt="${module//_/-}"
		path="$(find "${module_dir}/kernel" -type f \
			\( -name "${module}.ko*" -o -name "${module_alt}.ko*" \) -print -quit)"
		if [[ -n "${path}" ]]; then
			printf 'MODULE %s -> %s\n' "${module}" "${path}"
		else
			printf 'BUILT_IN_OR_MISSING %s\n' "${module}"
		fi
	done
	echo
	echo "[dtbs]"
	find "${module_dir}/dtb" -type f -name '*x13s*.dtb' -print | sort
	x13s_dtb="${module_dir}/dtb/qcom/sc8280xp-lenovo-thinkpad-x13s.dtb"
	if [[ ! -s "${x13s_dtb}" ]]; then
		echo "ERROR: Fedora kernel payload has no X13s DTB at ${x13s_dtb}" >&2
		exit 1
	fi
	echo
	echo "[firmware]"
	for firmware in "${inspect_firmware[@]}"; do
		inventory_file "${firmware}"
	done
} | tee "${tmp_report}"

install -d -m 0755 "${report_dir}"
install -m 0644 "${tmp_report}" "${report}"
echo "x13s.sh: inspection stored at ${report}"
