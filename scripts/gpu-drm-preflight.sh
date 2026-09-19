#!/usr/bin/env bash
# Record the host capability that the QEMU desktop gate will actually use.
# Exit 78 means required infrastructure is unavailable, not that an image
# failed its desktop contract.

set -euo pipefail

require_virgl=0
output=""
while (($#)); do
	case "$1" in
	--require-virgl)
		require_virgl=1
		shift
		;;
	--output)
		[[ $# -ge 2 ]] || {
			echo "ERROR: --output requires a path" >&2
			exit 2
		}
		output="$2"
		shift 2
		;;
	-h | --help)
		echo "usage: $0 [--require-virgl] [--output FILE]"
		exit 0
		;;
	*)
		echo "ERROR: unknown argument: $1" >&2
		exit 2
		;;
	esac
done

host_arch="$(uname -m)"
case "$host_arch" in
aarch64 | arm64)
	gl_device="virtio-gpu-gl-pci"
	qemu_candidates=(/usr/bin/qemu-system-aarch64 /usr/local/bin/qemu-system-aarch64)
	;;
x86_64 | amd64)
	gl_device="virtio-vga-gl"
	qemu_candidates=(/usr/libexec/qemu-kvm /usr/bin/qemu-kvm /usr/bin/qemu-system-x86_64 /home/linuxbrew/.linuxbrew/bin/qemu-system-x86_64)
	;;
*)
	gl_device="unsupported"
	qemu_candidates=()
	;;
esac

qemu="${QEMU:-}"
if [[ -z "$qemu" ]]; then
	for candidate in "${qemu_candidates[@]}"; do
		if [[ -x "$candidate" ]]; then
			qemu="$candidate"
			break
		fi
	done
fi

qemu_version="unavailable"
have_gl_device=0
have_egl_headless=0
if [[ -n "$qemu" && -x "$qemu" ]]; then
	qemu_version="$($qemu --version 2>/dev/null | head -n 1 || true)"
	[[ -n "$qemu_version" ]] || qemu_version="unknown"
	if "$qemu" -device help 2>/dev/null | grep -qF "$gl_device"; then
		have_gl_device=1
	fi
	if "$qemu" -display help 2>/dev/null | grep -qF "egl-headless"; then
		have_egl_headless=1
	fi
else
	qemu="unavailable"
fi

kvm_device="${TUNAOS_PREFLIGHT_KVM_DEVICE:-/dev/kvm}"
kvm="missing"
if [[ -r "$kvm_device" && -w "$kvm_device" ]]; then
	kvm="read-write"
elif [[ -e "$kvm_device" ]]; then
	kvm="not-usable"
fi

render_node="${TBOX_E2E_RENDERNODE:-}"
if [[ -z "$render_node" ]]; then
	dev_root="${TUNAOS_PREFLIGHT_DEV_ROOT:-/dev}"
	shopt -s nullglob
	render_nodes=("$dev_root"/dri/renderD*)
	shopt -u nullglob
	if ((${#render_nodes[@]})); then
		render_node="${render_nodes[0]}"
	fi
fi

render_fingerprint="unavailable"
if [[ -n "$render_node" && -e "$render_node" ]]; then
	sys_root="${TUNAOS_PREFLIGHT_SYS_ROOT:-/sys}"
	render_name="$(basename "$render_node")"
	driver="$(basename "$(readlink -f "$sys_root/class/drm/$render_name/device/driver" 2>/dev/null || true)")"
	[[ -n "$driver" && "$driver" != "." ]] || driver="unknown"
	device_number="$(stat -c '%t:%T' "$render_node" 2>/dev/null || echo unknown)"
	render_fingerprint="$render_node driver=$driver device=$device_number"
fi

mesa_fingerprint="unavailable"
if command -v dpkg-query >/dev/null 2>&1; then
	mesa_fingerprint="$(dpkg-query -W -f='${Package}=${Version} ' libegl-mesa0 libgl1-mesa-dri mesa-vulkan-drivers 2>/dev/null || true)"
elif command -v rpm >/dev/null 2>&1; then
	mesa_fingerprint="$(rpm -qa --qf '%{NAME}=%{VERSION}-%{RELEASE} ' 'mesa-*' 2>/dev/null | sort || true)"
fi
[[ -n "$mesa_fingerprint" ]] || mesa_fingerprint="unavailable"

mode="plain"
status="available"
reasons=()
[[ "$kvm" == "read-write" ]] || reasons+=("KVM is $kvm")
[[ "$qemu" != "unavailable" ]] || reasons+=("QEMU is unavailable")
if [[ -n "$render_node" && -e "$render_node" && "$have_gl_device" -eq 1 && "$have_egl_headless" -eq 1 ]]; then
	mode="virgl"
else
	[[ -n "$render_node" && -e "$render_node" ]] || reasons+=("DRM render node is missing")
	((have_gl_device == 1)) || reasons+=("QEMU lacks $gl_device")
	((have_egl_headless == 1)) || reasons+=("QEMU lacks egl-headless")
fi

if [[ "$kvm" != "read-write" || "$qemu" == "unavailable" ]] || { ((require_virgl == 1)) && [[ "$mode" != "virgl" ]]; }; then
	status="infrastructure-unavailable"
fi

lines=(
	"TUNAOS_GPU_DRM_CAPABILITY status=$status mode=$mode required_virgl=$require_virgl"
	"host: arch=$host_arch kernel=$(uname -r)"
	"kvm: $kvm ($kvm_device)"
	"qemu: $qemu; $qemu_version"
	"qemu-display: mode=$mode gl-device=$gl_device supported=$have_gl_device egl-headless=$have_egl_headless"
	"drm: $render_fingerprint"
	"mesa: $mesa_fingerprint"
)
if ((${#reasons[@]})); then
	lines+=("reasons: $(
		IFS='; '
		echo "${reasons[*]}"
	)")
fi

for line in "${lines[@]}"; do
	echo "$line"
done

if [[ -n "$output" ]]; then
	mkdir -p "$(dirname "$output")"
	printf '%s\n' "${lines[@]}" >"$output"
fi

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
	{
		echo "### GPU/DRM runner capability"
		echo
		echo "- Verdict: **${status}**"
		echo "- QEMU display mode: \`${mode}\`"
		echo "- KVM: \`${kvm}\`"
		echo "- DRM: \`${render_fingerprint}\`"
		echo "- QEMU: \`${qemu_version}\`"
		echo "- Mesa: \`${mesa_fingerprint}\`"
		if ((${#reasons[@]})); then
			echo "- Notes: $(
				IFS='; '
				echo "${reasons[*]}"
			)"
		fi
	} >>"$GITHUB_STEP_SUMMARY"
fi

if [[ "$status" == "infrastructure-unavailable" ]]; then
	echo "::error title=GPU/DRM infrastructure unavailable::The runner cannot provide the capability required by this boot gate" >&2
	exit 78
fi
