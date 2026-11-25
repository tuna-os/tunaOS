#!/usr/bin/env bash
# Protected native-package removal (RFC 017, #4352; spec PR-1..PR-9).
#
# `remove` rows of image-packages.tsv run here, as the LAST package transaction
# of a stage, after that stage's additions. Adapters exist for dnf and apt only;
# Portage and unknown managers fail before anything runs. The primary validator
# (scripts/lib/tunaos_config.py) rejects removal intent for every cell that is
# not in REMOVAL_ADMISSION, so this file has no caller on `main` yet.
#
# Contract: the native solver's removal closure must be EXACTLY the requested
# identities. Any extra removal, any add/upgrade, any protected identity, any
# stale repository fails the build and the disposable root is discarded. The
# protected set is projected from the installed owners of the base contract
# (build_scripts/checks/verify-base-contract.sh --list-contract) plus native
# protection metadata; there is no checked-in list of package names.
#
# Every refusal is one `::error::<code>: ...` line (spec PR-9).

TUNAOS_REMOVAL_RECEIPT_REL="usr/share/tunaos/package-removal.tsv"

_removal_fail() {
	local code="$1"
	shift
	printf '::error::%s: %s\n' "$code" "$*" >&2
	return 1
}

# Names reach package managers as arguments; refuse anything but one plain name.
_removal_check_name() {
	local name="$1"
	if [[ ! "$name" =~ ^[a-z0-9A-Z][a-zA-Z0-9+_.-]*$ ]] || [[ "$name" == -* ]]; then
		_removal_fail schema "'${name}' (package-removal.sh input) is not one exact package name"
	fi
}

# --- native inventory, one identity per line, sorted ---------------------------
_removal_inventory() {
	case "$PKG_MGR" in
	dnf) rpm -qa --qf '%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | LC_ALL=C sort ;;
	apt) dpkg-query -W -f '${Package}:${Architecture}=${Version}\n' | LC_ALL=C sort ;;
	*) _removal_fail unsupported-family "${PKG_MGR:-unknown} has no removal adapter" ;;
	esac
}

# Installed package names (no version) for one requested input; exactly one.
_removal_resolve() {
	local name="$1" found
	case "$PKG_MGR" in
	dnf) found="$(rpm -q --qf '%{NAME}\n' -- "$name" 2>/dev/null | LC_ALL=C sort -u)" || found="" ;;
	apt) found="$(dpkg-query -W -f '${Package}\n' -- "$name" 2>/dev/null | LC_ALL=C sort -u)" || found="" ;;
	esac
	# rpm -q treats a provide/alias as a name only when it is the name itself.
	[[ "$found" == "$name" ]] || {
		if [[ -z "$found" || "$found" == *"is not installed"* ]]; then
			_removal_fail not-installed "'${name}' (variants.*.packages.remove) has no installed owner"
		else
			_removal_fail ambiguous-name "'${name}' (variants.*.packages.remove) matches: ${found//$'\n'/, }"
		fi
		return 1
	}
	printf '%s\n' "$found"
}

# --- protected set --------------------------------------------------------------
# Owner of one contract path on the native manager; empty = unowned.
_removal_owner() {
	case "$PKG_MGR" in
	dnf) rpm -qf --qf '%{NAME}\n' -- "$1" 2>/dev/null | LC_ALL=C sort -u | grep -v 'not owned' ;;
	apt) dpkg-query -S -- "$1" 2>/dev/null | sed -n 's/^\([^:]*\)\(:[^:]*\)\?: .*/\1/p' | LC_ALL=C sort -u ;;
	esac
}

# Print "<package>\t<reason>" for every protected package. Reasons come from the
# base contract's own item list; an unowned item fails with contract-unowned.
tunaos_removal_protected() {
	local checker="${TUNAOS_BASE_CONTRACT_CHECK:-/run/context/build_scripts/checks/verify-base-contract.sh}"
	local items kind path owners owner rc=0
	[[ -r "$checker" ]] || {
		_removal_fail contract-unowned "base contract checker not found: ${checker}"
		return 1
	}
	items="$(bash "$checker" --list-contract)" || {
		_removal_fail contract-unowned "base contract could not be listed (${checker})"
		return 1
	}
	[[ -n "$items" ]] || {
		_removal_fail contract-unowned "base contract listed no items"
		return 1
	}
	while IFS=$'\t' read -r kind path; do
		[[ -n "$kind" ]] || continue
		owners="$(_removal_owner "$path")"
		if [[ -z "$owners" ]]; then
			_removal_fail contract-unowned "contract item ${kind} ${path} has no native owner"
			rc=1
			continue
		fi
		while IFS= read -r owner; do printf '%s\t%s\n' "$owner" "$kind"; done <<<"$owners"
	done <<<"$items"
	((rc == 0)) || return 1
	# Native protection metadata.
	case "$PKG_MGR" in
	apt)
		dpkg-query -W -f '${Package}\t${Essential}${Protected}\n' |
			awk -F'\t' '$2 ~ /yes/ { print $1 "\tnative-essential" }'
		;;
	dnf)
		local f
		for f in /etc/dnf/protected.d/*.conf; do
			if [[ -r "$f" ]]; then awk 'NF && $1 !~ /^#/ { print $1 "\tnative-protected" }' "$f"; fi
		done
		;;
	esac
	return 0
}

# --- solver closure -------------------------------------------------------------
# Print the exact package names the native solver would remove for $@, or fail
# with dependency-induced / solver-unavailable. Never mutates.
tunaos_removal_closure() {
	local out
	case "$PKG_MGR" in
	apt)
		command -v apt-get >/dev/null 2>&1 || {
			_removal_fail solver-unavailable "apt-get is not installed"
			return 1
		}
		out="$(apt-get --simulate --no-install-recommends --no-auto-remove remove -- "$@" 2>/dev/null)" ||
			{
				_removal_fail solver-unavailable "apt-get --simulate failed for: $*"
				return 1
			}
		# Machine-stable action lines only: Remv/Purg are removals; anything that
		# installs, configures or upgrades makes the plan inexact.
		if grep -Eq '^(Inst|Conf) ' <<<"$out"; then
			_removal_fail dependency-induced "plan contains install/upgrade/configure actions for: $*"
			return 1
		fi
		sed -n 's/^\(Remv\|Purg\) \([^ ]*\).*/\2/p' <<<"$out" | sed 's/:.*//' | LC_ALL=C sort -u
		;;
	dnf)
		# rpm never cascades: the test transaction succeeds only if nothing
		# installed still needs the requested packages, so dnf's removal
		# (run with clean_requirements_on_remove off) takes out exactly them.
		if ! command -v rpm >/dev/null 2>&1 || ! command -v dnf >/dev/null 2>&1; then
			_removal_fail solver-unavailable "rpm or dnf is not installed"
			return 1
		fi
		if ! rpm -e --test -- "$@" >/dev/null 2>&1; then
			_removal_fail dependency-induced "installed packages depend on: $*"
			return 1
		fi
		printf '%s\n' "$@" | LC_ALL=C sort -u
		;;
	*)
		_removal_fail unsupported-family "${PKG_MGR:-unknown} has no removal adapter"
		return 1
		;;
	esac
}

_removal_execute() {
	case "$PKG_MGR" in
	apt) apt-get remove -y --no-auto-remove -- "$@" ;;
	dnf) dnf remove -y --setopt=clean_requirements_on_remove=False --setopt=protect_running_kernel=True -- "$@" ;;
	esac
}

# A digest over everything the transaction depends on (PR-1 "fingerprint").
_removal_fingerprint() {
	{
		printf 'manager %s\n' "$PKG_MGR"
		printf 'requested %s\n' "$*"
		printf 'inventory\n'
		_removal_inventory
		printf 'protected\n'
		tunaos_removal_protected | LC_ALL=C sort -u
		printf 'closure\n'
		tunaos_removal_closure "$@"
	} | sha256sum | awk '{ print $1 }'
}

# tunaos_apply_removals <root> <name>...
# root redirects the receipt only (tests). The caller runs this after additions.
tunaos_apply_removals() {
	local root="$1"
	shift
	(($# > 0)) || return 0
	case "${PKG_MGR:-}" in
	dnf | apt) ;;
	*)
		_removal_fail unsupported-family "package removal is not supported on ${PKG_MGR:-an unknown manager}"
		return 1
		;;
	esac
	local name
	local -a requested=() resolved=()
	for name in "$@"; do
		_removal_check_name "$name" || return 1
		requested+=("$name")
	done
	# Explicit metadata refresh; no later step refreshes (PR-5 step 2).
	pkg_refresh || {
		_removal_fail repository-stale "repository metadata refresh failed"
		return 1
	}
	local before protected closure expected extra intersect
	before="$(_removal_inventory)" || return 1
	for name in "${requested[@]}"; do
		resolved+=("$(_removal_resolve "$name")") || return 1
	done
	protected="$(tunaos_removal_protected)" || return 1
	intersect="$(LC_ALL=C sort -u <<<"$protected" | awk -F'\t' 'NR==FNR { want[$1]; next } ($1 in want) { print $1 " (" $2 ")" }' \
		<(printf '%s\n' "${resolved[@]}") -)"
	if [[ -n "$intersect" ]]; then
		_removal_fail protected "requested identity is protected: ${intersect//$'\n'/, }"
		return 1
	fi
	closure="$(tunaos_removal_closure "${resolved[@]}")" || return 1
	expected="$(printf '%s\n' "${resolved[@]}" | LC_ALL=C sort -u)"
	if [[ "$closure" != "$expected" ]]; then
		extra="$(comm -13 <(printf '%s\n' "$expected") <(printf '%s\n' "$closure") | paste -sd, -)"
		_removal_fail dependency-induced "closure differs from the request; extra or missing: ${extra:-<missing requested>}"
		return 1
	fi
	# Fingerprint at qualification, recomputed immediately before mutation.
	local qualified applied
	qualified="$(_removal_fingerprint "${resolved[@]}")" || return 1
	applied="$(_removal_fingerprint "${resolved[@]}")" || return 1
	[[ -n "$qualified" && "$qualified" == "$applied" ]] || {
		_removal_fail plan-drift "fingerprint changed between qualification (${qualified}) and application (${applied})"
		return 1
	}
	_removal_execute "${resolved[@]}" || {
		_removal_fail transaction-failed "native removal failed for: ${resolved[*]}"
		return 1
	}
	local after want_after
	after="$(_removal_inventory)" || return 1
	# before minus the removed names (inventory lines start with the name).
	want_after="$(awk 'NR==FNR { gone[$1]; next } { n=$0; sub(/[-:=].*/, "", n); if (!(n in gone)) print }' \
		<(printf '%s\n' "${resolved[@]}") <(printf '%s\n' "$before") | LC_ALL=C sort)"
	if [[ "$after" != "$want_after" ]]; then
		_removal_fail inventory-drift "after-inventory is not the before-inventory minus: ${resolved[*]}"
		return 1
	fi
	# Atomic success receipt, only after every check passed.
	local receipt="${root%/}/${TUNAOS_REMOVAL_RECEIPT_REL}" tmp
	mkdir -p "${receipt%/*}" || return 1
	tmp="$(mktemp "${receipt}.XXXXXX")" || return 1
	{
		printf '# Written by build_scripts/lib/package-removal.sh (RFC 017).\n'
		printf 'manager\t%s\n' "$PKG_MGR"
		printf 'fingerprint\t%s\n' "$applied"
		printf 'after-inventory-sha256\t%s\n' "$(sha256sum <<<"$after" | awk '{ print $1 }')"
		for name in "${resolved[@]}"; do printf 'removed\t%s\n' "$name"; done
	} >"$tmp"
	if ! mv -f "$tmp" "$receipt"; then
		rm -f "$tmp"
		return 1
	fi
	printf 'package removal: removed %s for %s\n' "${resolved[*]}" "$PKG_MGR"
}

# A later stage or publication step on a configuration with removal intent.
tunaos_require_removal_receipt() {
	local root="${1:-/}" receipt
	receipt="${root%/}/${TUNAOS_REMOVAL_RECEIPT_REL}"
	[[ -s "$receipt" ]] || {
		_removal_fail receipt-missing "no success receipt at ${receipt}"
		return 1
	}
}
