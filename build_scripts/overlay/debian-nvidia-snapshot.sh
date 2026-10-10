#!/usr/bin/env bash
# Recover the measured Debian 550/7.1 pair when sid has retired its kernel.
# Metadata inventory: Debian snapshot 20260909T000000Z, sid/main; all package
# digests below come from its Packages index. APT authenticates that index
# through Debian's signed InRelease using the installed archive keyring.
set -euo pipefail

. /etc/os-release
if [[ "${ID:-}" != debian ]]; then
	echo 'ERROR: Debian snapshot fallback requires a native Debian image' >&2
	exit 1
fi
if [[ "${1:-}" != 550.163.01-5.1 || ! "${2:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\+deb14-amd64$ ||
	"$(dpkg --print-architecture)" != amd64 ]]; then
	echo 'ERROR: no measured Debian snapshot fallback for this driver/kernel/architecture' >&2
	exit 1
fi
KEYRING=/usr/share/keyrings/debian-archive-keyring.gpg
test -s "$KEYRING" || { echo 'ERROR: Debian archive keyring missing' >&2; exit 1; }
APT_ROOT="${TUNAOS_APT_ROOT:-/etc/apt}"
SOURCE="$APT_ROOT/sources.list.d/tunaos-nvidia-kernel-snapshot.sources"
PREF="$APT_ROOT/preferences.d/tunaos-nvidia-kernel-snapshot"
mkdir -p "$APT_ROOT/sources.list.d" "$APT_ROOT/preferences.d"
cat >"$SOURCE" <<EOF
Types: deb
URIs: https://snapshot.debian.org/archive/debian/20260909T000000Z/
Suites: sid
Components: main
Architectures: amd64
Signed-By: $KEYRING
Check-Valid-Until: no
EOF
# Only this historical source disables expiration. Signature and package
# digest authentication remain mandatory; all other snapshot packages are
# forbidden so the rolling userspace and driver continue using native sid.
cat >"$PREF" <<'EOF'
Package: *
Pin: origin "snapshot.debian.org"
Pin-Priority: -1

Package: linux-image-7.1.13+deb14-amd64 linux-binary-7.1.13+deb14-amd64 linux-modules-7.1.13+deb14-amd64 linux-base-7.1.13+deb14-amd64 linux-headers-7.1.13+deb14-amd64 linux-headers-7.1.13+deb14-common linux-kbuild-7.1.13+deb14
Pin: version 7.1.13-1
Pin-Priority: 1001
EOF
apt-get -o Acquire::AllowInsecureRepositories=false \
	-o Acquire::AllowDowngradeToInsecureRepositories=false update >&2
while read -r package digest; do
	metadata="$(apt-cache show "$package=7.1.13-1")"
	if [[ "$(sed -n 's/^Version: //p' <<<"$metadata" | sort -u)" != 7.1.13-1 ||
		"$(sed -n 's/^SHA256: //p' <<<"$metadata" | sort -u)" != "$digest" ]]; then
		echo "ERROR: snapshot package identity/digest mismatch: $package" >&2
		exit 1
	fi
done <<'EOF'
linux-image-7.1.13+deb14-amd64 0b95e4a84487c63a6a76653c918567861021ae0c3c37032a7cc08f50708b12e5
linux-binary-7.1.13+deb14-amd64 61d025ab9d2fa82a193be55a0d2a478d36ed453b539c8d4ceafa6ec5490ed1bb
linux-modules-7.1.13+deb14-amd64 a196a904568e6d59b2c173fca3ca56bcda7109a84430eca534b0de0a993fb593
linux-base-7.1.13+deb14-amd64 89a08daf6620c0b4cb8dacb7e8ff5199102dba2ae009281406b3b307ba3cb9c0
linux-headers-7.1.13+deb14-amd64 a7c629573f3cd9a7b39d3e510ea371d9379255f60eb57b6c54a3ccd8ca3dc5a1
linux-headers-7.1.13+deb14-common 02074fc2ab421537b1f3bffee185bf949b463eae98c39d2f00c72ab45a8b400f
linux-kbuild-7.1.13+deb14 8ea4872d0c2d3014dc499bc5ef72751e5327c2a17d686873443a63ae5e7f3165
EOF
echo 7.1.13+deb14-amd64
