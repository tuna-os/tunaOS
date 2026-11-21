# shellcheck shell=bash
# Runtime branding assertions: what a user of the INSTALLED, RUNNING system
# sees, as opposed to what the image tree contains. Sourced by
# verify-branding.sh --runtime; it defines functions and records results, it
# prints no verdict of its own.
#
# WHY THIS EXISTS
#
# The build-time contract proved layers 1 and 2 (docs/BRANDING.md) and still
# every one of these shipped on installed systems (BrandScout audit,
# strict-run logs t38 yellowfin:xfce and t68 bonito:niri):
#
#   Boot000A "AlmaLinux Kitten"  \EFI\almalinux\shimx64.efi   UEFI boot entry
#   fedora login:                                              live hostname
#   flatpak-add-fedora-repos.service "Add Fedora flatpak repositories"
#
# None of them exists in an image tree: the firmware entry is written at
# install, the hostname is decided at boot, and the remote is added by a unit
# at boot. Only a check on the booted system can see them.
#
# Every file read is prefixed with TUNAOS_BRANDING_ROOT and every external
# command is looked up on PATH, so tests/bats/test_branding_runtime.bats runs
# each assertion over a fixture tree with stub binaries.

R="${TUNAOS_BRANDING_ROOT:-}"

# Upstream names a user must never be shown. Word match (see deny_hits), so
# "arch" alone is not here: it is a word in ordinary text ("search" is not, but
# "x86_64 arch" is). "arch linux" and "archlinux" carry the brand.
BRANDING_DENYLIST=(
	ubuntu debian fedora centos almalinux "alma linux" kitten rocky rhel
	"red hat" redhat opensuse suse gentoo "arch linux" archlinux elementary
	bluefin aurora bazzite "universal blue"
)

# The denylisted names found in $1, space separated; empty when clean.
# Lower-cased and split on every non-alphanumeric character, so
# "almalinux.org", "fedora-logo-icon" and "AlmaLinux Kitten" all match.
deny_hits() {
	local text name hits=()
	text=" $(printf '%s' "${1,,}" | tr -c 'a-z0-9' ' ' | tr -s ' ') "
	for name in "${BRANDING_DENYLIST[@]}"; do
		[[ "$text" == *" ${name} "* ]] && hits+=("$name")
	done
	printf '%s' "${hits[*]}"
}

# docs/BRANDING.md: "A variant is TunaOS first. It also shows the distro it is
# built on." 90-image-info.sh writes that attribution into /etc/issue as
# "<variant> - built on <base>"; it is the one place an upstream name belongs.
strip_attribution() {
	sed -E 's/[[:space:]]*-?[[:space:]]*[Bb]uilt on .*$//'
}

# ------------------------------------------------------------------ report --

declare -ga BRANDING_CHECK_IDS=()
declare -gA BRANDING_CHECK_STATUS=() BRANDING_CHECK_DETAIL=()

# record <id> <pass|fail|skip> <detail>
record() {
	local id="$1" status="$2" detail="${3:-}"
	BRANDING_CHECK_IDS+=("$id")
	BRANDING_CHECK_STATUS[$id]="$status"
	# One serial line carries the whole report; bound each detail.
	BRANDING_CHECK_DETAIL[$id]="${detail:0:400}"
	case "$status" in
	pass) echo "  ok: [${id}] ${detail}" ;;
	skip) echo "  skip: [${id}] ${detail}" ;;
	*) echo "  FAIL: [${id}] ${detail}" >&2 ;;
	esac
}

json_str() {
	local s="$1"
	s="${s//\\/\\\\}"
	s="${s//\"/\\\"}"
	s="$(printf '%s' "$s" | tr '\n\t\r' '   ' | tr -d '\000-\037')"
	printf '"%s"' "$s"
}

# ------------------------------------------------------------- os-release --

osr_get() { # <file> <key>
	[[ -r "$1" ]] || return 0
	sed -n "s/^${2}=//p" "$1" 2>/dev/null | head -1 | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/'
}

# Keys a user or a desktop shows. ID, ID_LIKE, VERSION_ID, PLATFORM_ID and
# CPE-style fields name the base on purpose: package tooling reads them.
BRANDING_VISIBLE_KEYS=(NAME PRETTY_NAME VARIANT VARIANT_ID VERSION_CODENAME
	DEFAULT_HOSTNAME LOGO HOME_URL DOCUMENTATION_URL SUPPORT_URL BUG_REPORT_URL)

# The publish name 90-image-info.sh wrote, e.g. "bonito" for bonito-rawhide.
expected_image_name() {
	sed -n 's/^[[:space:]]*"image-name":[[:space:]]*"\([^"]*\)".*/\1/p' \
		"${R}/usr/share/ublue-os/image-info.json" 2>/dev/null | head -1
}

check_os_release() {
	local etc="${R}/etc/os-release" usr="${R}/usr/lib/os-release" key a b diffs="" hits="" file
	if [[ ! -r "$usr" && ! -r "$etc" ]]; then
		record os-release.agree fail "no readable /etc/os-release or /usr/lib/os-release"
		record os-release.name fail "no os-release"
		record os-release.denylist fail "no os-release"
		return
	fi
	# Both exist on bases that ship a real /etc/os-release (marlin, filesystem
	# 2025.10.12): readers that open /etc first then show the upstream name.
	if [[ -L "$etc" && "$(readlink -f "$etc")" == "$(readlink -f "$usr")" ]]; then
		record os-release.agree pass "/etc/os-release -> /usr/lib/os-release"
	elif [[ ! -e "$etc" ]]; then
		record os-release.agree pass "/etc/os-release absent; readers fall back to /usr/lib/os-release"
	elif [[ ! -r "$usr" ]]; then
		record os-release.agree fail "/usr/lib/os-release missing while /etc/os-release exists"
	else
		for key in "${BRANDING_VISIBLE_KEYS[@]}"; do
			a="$(osr_get "$etc" "$key")"
			b="$(osr_get "$usr" "$key")"
			[[ "$a" == "$b" ]] || diffs+="${key}: /etc='${a}' /usr/lib='${b}'; "
		done
		if [[ -n "$diffs" ]]; then
			record os-release.agree fail "${diffs%; }"
		else
			record os-release.agree pass "user-visible keys identical in /etc and /usr/lib"
		fi
	fi

	file="$etc"
	[[ -r "$file" ]] || file="$usr"
	local name pretty image want
	name="$(osr_get "$file" NAME)"
	pretty="$(osr_get "$file" PRETTY_NAME)"
	image="$(expected_image_name)"
	if [[ -z "$image" ]]; then
		record os-release.name fail "no image-name in /usr/share/ublue-os/image-info.json to compare NAME/PRETTY_NAME with"
	else
		want="${image^}"
		if [[ "$name" == "$want" && "$pretty" == "$want" ]]; then
			record os-release.name pass "NAME=PRETTY_NAME=${want}"
		else
			record os-release.name fail "NAME='${name}' PRETTY_NAME='${pretty}', want '${want}' (image-name ${image})"
		fi
	fi

	for file in "$etc" "$usr"; do
		[[ -r "$file" ]] || continue
		for key in "${BRANDING_VISIBLE_KEYS[@]}"; do
			a="$(osr_get "$file" "$key")"
			b="$(deny_hits "$a")"
			[[ -z "$b" ]] || hits+="${file#"$R"}:${key}='${a}' (${b}); "
		done
	done
	if [[ -n "$hits" ]]; then
		record os-release.denylist fail "${hits%; }"
	else
		record os-release.denylist pass "no upstream name in ${BRANDING_VISIBLE_KEYS[*]}"
	fi
}

# --------------------------------------------------------------- hostname --

check_hostname() {
	local now static default hits file="${R}/etc/os-release"
	[[ -r "$file" ]] || file="${R}/usr/lib/os-release"
	default="$(osr_get "$file" DEFAULT_HOSTNAME)"
	now="$(cat "${R}/proc/sys/kernel/hostname" 2>/dev/null || true)"
	static="$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "${R}/etc/hostname" 2>/dev/null | head -1 | tr -d '[:space:]')"
	hits="$(deny_hits "$now")"
	if [[ -n "$hits" ]]; then
		record hostname fail "hostname '${now}' names upstream (${hits}); DEFAULT_HOSTNAME=${default:-unset} /etc/hostname=${static:-unset}"
	elif [[ -z "$now" || "$now" == localhost || "$now" == localhost.localdomain || "$now" == "(none)" ]]; then
		record hostname fail "hostname '${now}' is a fallback, not DEFAULT_HOSTNAME=${default:-unset} or an installer-set /etc/hostname"
	elif [[ -n "$default" && "$now" == "$default" ]]; then
		record hostname pass "hostname=${now} (DEFAULT_HOSTNAME)"
	elif [[ -n "$static" && "$now" == "$static" ]]; then
		record hostname pass "hostname=${now} (installer-set /etc/hostname)"
	else
		record hostname fail "hostname '${now}' is neither DEFAULT_HOSTNAME=${default:-unset} nor /etc/hostname=${static:-unset}"
	fi
}

# ------------------------------------------------------------ boot entries --

check_boot_bls() {
	local pretty dir f title found=0 bad="" good="" file="${R}/etc/os-release"
	[[ -r "$file" ]] || file="${R}/usr/lib/os-release"
	pretty="$(osr_get "$file" PRETTY_NAME)"
	for dir in /boot/loader/entries /boot/efi/loader/entries /efi/loader/entries; do
		[[ -d "${R}${dir}" ]] || continue
		for f in "${R}${dir}"/*.conf; do
			[[ -f "$f" ]] || continue
			title="$(sed -n 's/^title[[:space:]]\+//p' "$f" | head -1)"
			found=$((found + 1))
			if [[ -n "$pretty" && "$title" == "$pretty"* && -z "$(deny_hits "$title")" ]]; then
				good+="'${title}' "
			else
				bad+="${f#"$R"}: '${title}'; "
			fi
		done
	done
	if [[ "$found" -eq 0 ]]; then
		if compgen -G "${R}/boot/EFI/Linux/*.efi" >/dev/null || compgen -G "${R}/boot/efi/EFI/Linux/*.efi" >/dev/null; then
			record boot.bls skip "no BLS entries; type-2 UKI entries take their title from the UKI's embedded os-release"
		else
			record boot.bls fail "no boot loader entries readable under /boot/loader/entries, /boot/efi/loader/entries or /efi/loader/entries"
		fi
	elif [[ -n "$bad" ]]; then
		record boot.bls fail "titles not starting with PRETTY_NAME '${pretty}': ${bad%; }"
	else
		record boot.bls pass "${found} entr$([[ "$found" -eq 1 ]] && echo y || echo ies): ${good% }"
	fi
}

# Boot#### descriptions straight from efivarfs, for images without
# efibootmgr. Layout (UEFI 2.10 §3.1.3): 4 bytes efivarfs attributes, then
# EFI_LOAD_OPTION: UINT32 Attributes, UINT16 FilePathListLength, CHAR16
# Description[] NUL-terminated.
efivar_labels() {
	local v num
	for v in "${R}"/sys/firmware/efi/efivars/Boot[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]-8be4df61-93ca-11d2-aa0d-00e098032b8c; do
		[[ -r "$v" ]] || continue
		num="${v##*/Boot}"
		num="${num%%-*}"
		printf 'Boot%s\t' "$num"
		od -An -v -tu1 -j10 "$v" 2>/dev/null | tr -s ' \n' '\n\n' | awk '
			NF == 0 { next }
			{ b[n++] = $1 }
			END {
				for (i = 0; i + 1 < n; i += 2) {
					if (b[i] == 0 && b[i + 1] == 0) break
					if (b[i + 1] == 0 && b[i] >= 32 && b[i] < 127) printf "%c", b[i]; else printf "?"
				}
				printf "\n"
			}'
	done
}

check_boot_efi() {
	local labels line hits bad="" n=0
	if [[ ! -d "${R}/sys/firmware/efi" ]]; then
		record boot.efi skip "not booted through UEFI"
		return
	fi
	if command -v efibootmgr >/dev/null 2>&1 && [[ -z "$R" ]]; then
		labels="$(efibootmgr 2>/dev/null | sed -n 's/^\(Boot[0-9A-Fa-f]\{4\}\)\*\{0,1\} \(.*\)$/\1\t\2/p' | sed 's/\t\(.*\)\t.*/\t\1/')"
	else
		labels="$(efivar_labels)"
	fi
	while IFS=$'\t' read -r num line; do
		[[ -n "$num" ]] || continue
		n=$((n + 1))
		# efibootmgr prints the device path after the label; judge the label.
		line="${line%%	*}"
		line="$(sed -E 's/[[:space:]]+(HD|PciRoot|VenHw|FvVol|Fv|MAC|BBS|VenMsg)\(.*$//' <<<"$line")"
		hits="$(deny_hits "$line")"
		[[ -z "$hits" ]] || bad+="${num} '${line}' (${hits}); "
	done <<<"$labels"
	if [[ "$n" -eq 0 ]]; then
		record boot.efi fail "UEFI boot but no Boot#### entry readable (efibootmgr/efivarfs)"
	elif [[ -n "$bad" ]]; then
		record boot.efi fail "firmware boot entries name upstream: ${bad%; }"
	else
		record boot.efi pass "${n} firmware boot entries, none names upstream"
	fi
}

# ---------------------------------------------------------------- splash --

expected_plymouth_theme() {
	local variant theme="" tsv="${R}/usr/share/tunaos/branding/variant-identity.tsv"
	# install-branding-contract.sh installs the generated table; without it the
	# project default would be a wrong expectation for every variant with its
	# own theme (yellowfin: tropical-fish), so report nothing rather than guess.
	[[ -r "$tsv" ]] || return 0
	variant="$(sed -n "s/^TUNAOS_VARIANT=//p" "${R}/usr/share/tunaos/identity.env" 2>/dev/null | tr -d "'\"" | head -1)"
	[[ -n "$variant" ]] || return 0
	theme="$(awk -F'\t' -v id="$variant" '!/^#/ && $1 == id { print $6; exit }' "$tsv")"
	if [[ -z "$theme" ]]; then
		theme="$(sed -n 's/^TUNAOS_PLYMOUTH_THEME=//p' "${R}/usr/share/tunaos/identity-config.env" 2>/dev/null | tr -d "'\"" | head -1)"
	fi
	printf '%s' "$theme"
}

check_initramfs_plymouth() {
	local theme kver img listing
	theme="$(expected_plymouth_theme)"
	if [[ -z "$theme" ]]; then
		record initramfs.plymouth fail "no expected theme: /usr/share/tunaos/branding/variant-identity.tsv or identity.env TUNAOS_VARIANT missing"
		return
	fi
	if ! compgen -G "${R}/usr/*bin/plymouthd" >/dev/null && ! compgen -G "${R}/usr/libexec/plymouth/plymouthd*" >/dev/null; then
		record initramfs.plymouth skip "plymouth is not installed; no splash to brand (want theme ${theme})"
		return
	fi
	kver="${TUNAOS_BRANDING_KVER:-$(uname -r)}"
	# The booted initramfs: bootc/ostree copy /usr/lib/modules/<kver>/initramfs.img
	# of the booted deployment to /boot byte for byte, and this root IS that
	# deployment.
	img="${R}/usr/lib/modules/${kver}/initramfs.img"
	if [[ ! -r "$img" ]]; then
		record initramfs.plymouth fail "no initramfs at /usr/lib/modules/${kver}/initramfs.img"
		return
	fi
	if command -v lsinitrd >/dev/null 2>&1; then
		listing="$(lsinitrd "$img" 2>/dev/null || true)"
	elif command -v lsinitramfs >/dev/null 2>&1; then
		listing="$(lsinitramfs "$img" 2>/dev/null || true)"
	else
		record initramfs.plymouth skip "neither lsinitrd nor lsinitramfs is installed to list ${img#"$R"}"
		return
	fi
	if grep -qF "share/plymouth/themes/${theme}/${theme}.plymouth" <<<"$listing"; then
		record initramfs.plymouth pass "booted initramfs (kernel ${kver}) carries themes/${theme}/${theme}.plymouth"
	else
		local present
		present="$(grep -oE 'share/plymouth/themes/[^/]+/' <<<"$listing" | sort -u | sed 's#share/plymouth/themes/##; s#/$##' | tr '\n' ' ')"
		record initramfs.plymouth fail "booted initramfs lacks themes/${theme}; themes present: ${present:-none}"
	fi
}

# --------------------------------------------------------------- flatpak --

is_live_boot() {
	grep -qE '(^| )(rd\.live\.image|root=live:)' "${R}/proc/cmdline" 2>/dev/null
}

check_flatpak_remotes() {
	local got want expected_file="${R}/usr/share/tunaos/flatpak-remotes.expected" url
	if ! command -v flatpak >/dev/null 2>&1; then
		record flatpak.remotes skip "flatpak is not installed"
		return
	fi
	# --show-disabled: flatpak-add-fedora-repos.service adds fedora-testing
	# disabled, which is still a configured upstream remote.
	# The live session adds installer-local (file://) for the offline
	# installer (customize-live); it never reaches an installed system.
	got="$(flatpak remotes --system --show-disabled --columns=name,url 2>/dev/null | awk 'NF { u = $2; sub(/\/$/, "", u); print $1 "\t" u }' |
		{ if is_live_boot; then grep -v '^installer-local	'; else cat; fi; } | sort -u)"
	if [[ -r "$expected_file" ]]; then
		want="$(awk -F'\t' 'NF { u = $2; sub(/\/$/, "", u); print $1 "\t" u }' "$expected_file" | sort -u)"
	else
		# Fallback for images that predate flatpak-remotes.expected: the names
		# tuna-flatpak-remote.sh registers (flathub always; tuna-os when
		# tunaos.toml [flatpak_preinstall] remote_url is set).
		url="$(sed -n 's/^TUNAOS_FLATPAK_REMOTE_URL=//p' "${R}/usr/share/tunaos/identity-config.env" 2>/dev/null | tr -d "'\"")"
		want="$(printf 'flathub\n%s' "${url:+tuna-os}" | sed '/^$/d' | sort -u)"
		got="$(cut -f1 <<<"$got" | sort -u)"
	fi
	if [[ "$got" == "$want" ]]; then
		record flatpak.remotes pass "system remotes: $(cut -f1 <<<"$got" | tr '\n' ' ')"
	else
		record flatpak.remotes fail "system remotes [$(tr '\n\t' '; ' <<<"$got")] != configured [$(tr '\n\t' '; ' <<<"$want")]"
	fi
}

# ------------------------------------------------------ installer catalog --

# The TunaOS-branded installer's default list shows this project's images
# only: Bonito's installer listed "Aurora > Aurora DX > Fedora 43"
# (ghcr.io/ublue-os/aurora-dx:43, t68 walkthrough-niri.json:689-803). Other
# projects stay reachable through a custom image reference, not the catalog.
check_installer_catalog() {
	local catalog="${R}/etc/bootc-installer/images.json" recipe="${R}/etc/bootc-installer/recipe.json"
	local own ns ref bad="" n=0 found_own=0
	if [[ ! -r "$catalog" ]]; then
		record installer.catalog skip "no /etc/bootc-installer/images.json on this system"
		return
	fi
	own="$(grep -o '"imgref":[[:space:]]*"[^"]*"' "$recipe" 2>/dev/null | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
	if [[ -z "$own" ]]; then
		record installer.catalog fail "images.json present but recipe.json names no imgref to compare with"
		return
	fi
	ns="${own%/*}/"
	while IFS= read -r ref; do
		n=$((n + 1))
		[[ "$ref" == "$own" ]] && found_own=1
		[[ "$ref" == "$ns"* ]] || bad+="${ref} "
	done < <(grep -o '"imgref":[[:space:]]*"[^"]*"' "$catalog" | sed 's/.*"\([^"]*\)"$/\1/')
	if [[ -n "$bad" ]]; then
		record installer.catalog fail "catalog lists images outside ${ns}: ${bad% }"
	elif [[ "$found_own" -ne 1 ]]; then
		record installer.catalog fail "catalog (${n} images) does not list this image ${own}"
	else
		record installer.catalog pass "${n} catalog image(s), all under ${ns}"
	fi
}

# ------------------------------------------------------- fastfetch, issue --

check_fastfetch() {
	local pretty out os hits file="${R}/etc/os-release" tmp
	[[ -r "$file" ]] || file="${R}/usr/lib/os-release"
	pretty="$(osr_get "$file" PRETTY_NAME)"
	if ! command -v fastfetch >/dev/null 2>&1; then
		record fastfetch skip "fastfetch is not installed"
		return
	fi
	# A fresh user's view: no ~/.config/fastfetch, so the system config in
	# /etc/xdg/fastfetch (90-image-info.sh) is the one that loads.
	tmp="$(mktemp -d)"
	out="$(HOME="$tmp" XDG_CONFIG_HOME="$tmp/.config" XDG_CACHE_HOME="$tmp/.cache" \
		timeout 30 fastfetch --pipe -l none 2>/dev/null || true)"
	rm -rf -- "$tmp"
	# The OS module's line: keyed "system" by 90-image-info.sh's config
	# ("system    Yellowfin  ·  part of TunaOS, built on AlmaLinux Kitten"),
	# "OS:" by fastfetch's own default. The attribution is allowed.
	os="$(grep -m1 -E '^[[:space:]]*(OS|system)([[:space:]]|:)' <<<"$out" || true)"
	hits="$(deny_hits "$(strip_attribution <<<"$os")")"
	if [[ -z "$out" ]]; then
		record fastfetch fail "fastfetch --pipe -l none printed nothing"
	elif [[ -n "$pretty" && "$out" != *"$pretty"* ]]; then
		record fastfetch fail "fastfetch output does not name '${pretty}' (OS line: '${os}')"
	elif [[ -n "$hits" ]]; then
		record fastfetch fail "fastfetch OS line names upstream (${hits}): '${os}'"
	else
		record fastfetch pass "OS line: ${os}"
	fi
}

check_issue() {
	local pretty issue body hits="" f file="${R}/etc/os-release"
	[[ -r "$file" ]] || file="${R}/usr/lib/os-release"
	pretty="$(osr_get "$file" PRETTY_NAME)"
	issue="${R}/etc/issue"
	if [[ ! -r "$issue" ]]; then
		record issue fail "/etc/issue is missing; agetty shows its compiled default"
		return
	fi
	# agetty expands \S{PRETTY_NAME} (and bare \S) from os-release itself.
	if ! grep -qF -- "$pretty" "$issue" && ! grep -qE '\\S(\{PRETTY_NAME\})?' "$issue"; then
		record issue fail "/etc/issue names neither '${pretty}' nor \\S{PRETTY_NAME}"
		return
	fi
	for f in "$issue" "${R}"/etc/issue.d/*.issue "${R}"/run/issue.d/*.issue; do
		[[ -r "$f" ]] || continue
		body="$(sed -E 's/\x1b\[[0-9;]*m//g; s/\\[a-zA-Z](\{[^}]*\})?//g' "$f" | strip_attribution)"
		f="$(deny_hits "$body")"
		[[ -z "$f" ]] || hits+="${f} "
	done
	if [[ -n "$hits" ]]; then
		record issue fail "login banner names upstream outside the 'built on' attribution: ${hits% }"
	else
		record issue pass "/etc/issue names the variant"
	fi
}

# ---------------------------------------------------- applied look, users --

# Accounts a person logs into: uid 1000-59999 with an existing home.
human_users() {
	local passwd
	if [[ -n "$R" ]]; then passwd="$(cat "${R}/etc/passwd" 2>/dev/null)"; else passwd="$(getent passwd)"; fi
	awk -F: '$3 >= 1000 && $3 < 60000 && $7 !~ /(nologin|false)$/ { print $1 ":" $6 }' <<<"$passwd" |
		while IFS=: read -r u h; do [[ -d "${R}${h}" ]] && printf '%s:%s\n' "$u" "$h"; done
}

# What a wallpaper path is: the variant's, another system-shipped one
# (TunaOS ships only the variant's, docs/BRANDING.md "Wallpapers", so any
# other system path is an upstream leftover), or the user's own file.
wallpaper_class() {
	local p="${1#\'}"
	p="${p%\'}"
	p="${p#file://}"
	case "$p" in
	"") echo default ;;
	/usr/share/backgrounds/tunaos/* | /usr/share/wallpapers/TunaOS*) echo variant ;;
	/usr/share/* | /usr/lib/* | /usr/local/share/* | /opt/*) echo system-other ;;
	*) echo user ;;
	esac
}

user_dconf_read() { # <home> <key>
	local h="$1" key="$2" tmp out
	tmp="$(mktemp -d)"
	chmod 0700 "$tmp"
	out="$(HOME="${R}${h}" XDG_CONFIG_HOME="${R}${h}/.config" XDG_RUNTIME_DIR="$tmp" \
		DCONF_PROFILE="${DCONF_PROFILE:-user}" dconf read "$key" 2>/dev/null || true)"
	rm -rf -- "$tmp"
	printf '%s' "$out"
}

check_user_look() {
	local desktop="$1" users u h v cls per="" bad="" n=0 f
	case "$desktop" in
	gnome | pantheon | kde | cosmic | xfce) ;;
	*) return 0 ;;
	esac
	users="$(human_users)"
	if [[ -z "$users" ]]; then
		record "desktop.${desktop}.user" skip "no human account yet; the system default (desktop.${desktop}) is what a new user gets"
		return
	fi
	while IFS=: read -r u h; do
		n=$((n + 1))
		v=""
		case "$desktop" in
		gnome | pantheon)
			if command -v dconf >/dev/null 2>&1; then
				v="$(user_dconf_read "$h" /org/gnome/desktop/background/picture-uri)"
			fi
			;;
		kde)
			local laf=""
			if command -v kreadconfig6 >/dev/null 2>&1; then
				laf="$(HOME="${R}${h}" XDG_CONFIG_HOME="${R}${h}/.config" kreadconfig6 --group KDE --key LookAndFeelPackage 2>/dev/null || true)"
			fi
			if [[ -n "$laf" && "$laf" != org.tunaos.* ]]; then
				bad+="${u}: LookAndFeelPackage=${laf}; "
			fi
			f="${R}${h}/.config/plasma-org.kde.plasma.desktop-appletsrc"
			[[ -r "$f" ]] && v="$(sed -n 's/^Image=//p' "$f" | grep -v '^$' | head -1)"
			;;
		cosmic)
			f="${R}${h}/.config/cosmic/com.system76.CosmicBackground/v1/all"
			[[ -r "$f" ]] && v="$(sed -n 's/.*source:[[:space:]]*Path("\([^"]*\)").*/\1/p' "$f" | head -1)"
			;;
		xfce)
			f="${R}${h}/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml"
			if [[ -r "$f" ]]; then
				local img
				while IFS= read -r img; do
					[[ "$(wallpaper_class "$img")" == system-other ]] && bad+="${u}: xfdesktop last-image=${img}; "
				done < <(grep -o 'name="last-image" type="string" value="[^"]*"' "$f" | sed 's/.*value="\([^"]*\)"/\1/')
				v="$(grep -o 'name="last-image" type="string" value="[^"]*"' "$f" | sed 's/.*value="\([^"]*\)"/\1/' | head -1)"
			fi
			;;
		esac
		cls="$(wallpaper_class "$v")"
		per+="${u}=${cls}${v:+(${v})} "
		[[ "$cls" != system-other || "$desktop" == xfce ]] || bad+="${u}: wallpaper ${v}; "
	done <<<"$users"
	if [[ -n "$bad" ]]; then
		record "desktop.${desktop}.user" fail "upstream look applied to an account: ${bad%; }"
	else
		record "desktop.${desktop}.user" pass "${n} account(s): ${per% }"
	fi
}
