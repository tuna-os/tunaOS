#!/usr/bin/env bash
# SELinux home-directory labelling: keep /etc/default/useradd, the generated
# file_contexts.homedirs and the file_contexts.subs{,_dist} aliases in
# agreement (tunaOS#4047).
#
# Sourced by build_scripts/selinux-home-labels.sh (fix) and
# build_scripts/checks/verify-selinux-home-labels.sh (gate).
#
# THE FAILURE
#
# libsemanage's genhomedircon writes file_contexts.homedirs with HOME= from
# /etc/default/useradd as the prefix. libselinux then rewrites every lookup
# through file_contexts.subs (local) and file_contexts.subs_dist (shipped)
# BEFORE it matches a rule. The two directions are a matched pair, and the
# EL10 bootc bases ship HOME=/var/home with subs_dist `/home /var/home` (rules
# under /var/home, /home rewritten onto them). The selinux-policy 43.1 built
# by tuna-os/tunaos-packages (the GNOME 50 repo, priority 1) is Fedora's
# policy and ships subs_dist `/var/home /home`: the opposite direction. With
# HOME=/var/home, the 205 generated rules sit under /var/home, every lookup
# is rewritten to /home, and nothing under /home has a rule:
#
#   matchpathcon /var/home/user/.ssh/authorized_keys -> default_t
#
# sshd cannot read authorized_keys and GNOME session processes get EACCES under
# ~/.local/share. restorecon cannot help: the policy itself says default_t.
#
# THE FIX, AND WHY THIS DIRECTION
#
# Keep HOME and turn the alias around: a subs rule whose SOURCE is the HOME
# prefix is replaced by its reverse (`/var/home /home` -> `/home /var/home`).
# HOME=/var/home is the ostree convention (ostree-layout.sh sets it
# deliberately so passwd records the real directory rather than the /home
# symlink) and the EL10 policy's own direction; the generated rules and any
# later `semodule -B` regenerate under the same prefix. Changing HOME instead
# would move every newly created account's passwd home onto the symlink.
#
# TUNAOS_SELINUX_ROOT prefixes every path, so the same code runs against a
# fixture tree (tests/regressions/test_issue_4047_*.py) or a mounted image.

_selhome_root() { printf '%s' "${TUNAOS_SELINUX_ROOT:-}"; }

# SELINUXTYPE from the target's /etc/selinux/config; targeted when absent.
_selhome_type() {
	local t=""
	if [[ -r "$(_selhome_root)/etc/selinux/config" ]]; then
		t=$(sed -n 's/^SELINUXTYPE=//p' "$(_selhome_root)/etc/selinux/config" | head -1)
	fi
	printf '%s' "${t:-targeted}"
}

_selhome_files_dir() {
	printf '%s/etc/selinux/%s/contexts/files' "$(_selhome_root)" "$(_selhome_type)"
}

# True when this root carries a policy at all (Debian, Arch and Gentoo images do
# not, and SELinux is simply not in play there).
selhome_has_policy() {
	[[ -f "$(_selhome_files_dir)/file_contexts.subs_dist" ||
	-f "$(_selhome_files_dir)/file_contexts.homedirs" ]]
}

# HOME= from /etc/default/useradd, without a trailing slash; useradd's own
# default (/home) when the file or the key is absent.
selhome_useradd_home() {
	local h=""
	if [[ -r "$(_selhome_root)/etc/default/useradd" ]]; then
		h=$(sed -n 's/^HOME=//p' "$(_selhome_root)/etc/default/useradd" | head -1)
	fi
	h="${h:-/home}"
	[[ "$h" == / ]] || h="${h%/}"
	printf '%s' "$h"
}

# One libselinux alias pass (selabel_sub): file order is reversed because
# libselinux prepends each entry to its list, the first prefix match at a path
# boundary wins, and a line with fewer than two fields is ignored. Prints the
# rewritten path; exit 1 when no alias applies.
_selhome_sub() {
	local file=$1 key=$2
	[[ -r "$file" ]] || return 1
	awk -v key="$key" '
		/^[ \t]*(#|$)/ { next }
		NF >= 2 { n++; src[n] = $1; dst[n] = $2 }
		END {
			for (i = n; i >= 1; i--) {
				l = length(src[i])
				if (substr(key, 1, l) == src[i] &&
				    (length(key) == l || substr(key, l + 1, 1) == "/")) {
					print dst[i] substr(key, l + 1)
					exit 0
				}
			}
			exit 1
		}' "$file"
}

# The path libselinux actually looks up: local subs first, then subs_dist on the
# result (selabel_sub_key in libselinux's label_file.c).
selhome_resolve() {
	local d out
	d=$(_selhome_files_dir)
	if out=$(_selhome_sub "${d}/file_contexts.subs" "$1"); then
		_selhome_sub "${d}/file_contexts.subs_dist" "$out" || printf '%s\n' "$out"
	else
		_selhome_sub "${d}/file_contexts.subs_dist" "$1" || printf '%s\n' "$1"
	fi
}

# SELinux type the generated home rules (and local overrides) give a path after
# alias resolution: the type of the first matching rule, `default_t` when none
# matches. Rules are `regex [filetype] context`; `<<none>>` has no type.
selhome_type_of() {
	local d resolved f t=""
	d=$(_selhome_files_dir)
	resolved=$(selhome_resolve "$1")
	for f in file_contexts.homedirs file_contexts.local; do
		[[ -r "${d}/${f}" ]] || continue
		t=$(awk -v key="$resolved" '
			/^[ \t]*(#|$)/ { next }
			NF >= 2 && $NF ~ /object_r:/ && match(key, "^(" $1 ")$") {
				n = split($NF, c, ":")
				print c[3]
				exit
			}' "${d}/${f}") || t=""
		[[ -n "$t" ]] && break
	done
	printf '%s' "${t:-default_t}"
}

# Rewrite every alias in one file whose source is the HOME prefix $2 into its
# reverse, so the lookup lands where the generated rules are. Nothing is
# written when no line matches. Returns 2 when the reverse would collide with
# an existing alias (two rules for one source: the result would depend on file
# order, which is not a state to guess at).
_selhome_flip_file() {
	local file=$1 home=$2 tmp
	[[ -f "$file" ]] || return 0
	tmp=$(mktemp)
	awk -v home="$home" '
		/^[ \t]*(#|$)/ { print; next }
		NF >= 2 && $1 == home && $2 != home {
			print $2 " " home
			print "selinux-home: flipped alias \047" $1 " " $2 "\047 to \047" $2 " " home "\047" > "/dev/stderr"
			changed = 1
			next
		}
		{ print }
		END { exit changed ? 0 : 3 }' "$file" >"$tmp"
	local rc=$?
	if [[ $rc -eq 0 ]]; then
		cat "$tmp" >"$file"
		echo "selinux-home: rewrote ${file#"$(_selhome_root)"}" >&2
	fi
	rm -f "$tmp"
	[[ $rc -eq 3 ]] && return 0
	return "$rc"
}

# Make the aliases agree with HOME. Idempotent; a tree that already agrees is
# left byte-identical.
selhome_fix() {
	selhome_has_policy || {
		echo "selinux-home: no SELinux policy in this image; nothing to align" >&2
		return 0
	}
	local d home target f rc=0 other
	d=$(_selhome_files_dir)
	home=$(selhome_useradd_home)
	for f in file_contexts.subs file_contexts.subs_dist; do
		[[ -f "${d}/${f}" ]] || continue
		target=$(awk -v home="$home" '
			/^[ \t]*(#|$)/ { next }
			NF >= 2 && $1 == home && $2 != home { print $2; exit }' "${d}/${f}")
		[[ -n "$target" ]] || continue
		# The reverse alias must not already exist in either file.
		for other in file_contexts.subs file_contexts.subs_dist; do
			if [[ -f "${d}/${other}" ]] && awk -v t="$target" '
				/^[ \t]*(#|$)/ { next }
				NF >= 2 && $1 == t { found = 1 }
				END { exit found ? 0 : 1 }' "${d}/${other}"; then
				echo "selinux-home: FAIL: ${other} already has an alias for ${target}; cannot reverse '${home} ${target}' without a conflict" >&2
				return 2
			fi
		done
		_selhome_flip_file "${d}/${f}" "$home" || rc=$?
		[[ $rc -eq 0 ]] || return "$rc"
	done
	return 0
}

# The gate. Resolves the paths an ostree system reaches the same file by (/home
# and /var/home, plus HOME if it is neither) and requires a real label for each.
# Static layer: the files above, so it runs against a fixture. Live layer:
# libselinux itself via matchpathcon, only against the running root.
selhome_check() {
	selhome_has_policy || {
		echo "selinux-home: no SELinux policy in this image; check skipped"
		return 0
	}
	local home failed=0 p t r roots=(/home /var/home)
	home=$(selhome_useradd_home)
	[[ "$home" == /home || "$home" == /var/home ]] || roots+=("$home")
	echo "selinux-home: HOME=${home} subs=[$(
		cat "$(_selhome_files_dir)"/file_contexts.subs{,_dist} 2>/dev/null |
			awk '/^[ \t]*(#|$)/ { next } NF >= 2 && ($1 ~ /home/ || $2 ~ /home/) { printf "%s%s -> %s", sep, $1, $2; sep = "; " }'
	)]"
	local base
	for base in "${roots[@]}"; do
		for p in "${base}/tunaos-check/.ssh/authorized_keys" "${base}/tunaos-check/.local/share/tunaos-check"; do
			r=$(selhome_resolve "$p")
			if [[ -r "$(_selhome_files_dir)/file_contexts.homedirs" ]]; then
				t=$(selhome_type_of "$p")
				echo "selinux-home: ${p} -> ${r} rule_type=${t}"
				if [[ "$t" == default_t ]]; then
					echo "selinux-home: FAIL: ${p} resolves to ${r}, which no home rule matches (default_t)" >&2
					failed=1
				fi
			fi
			if [[ -z "$(_selhome_root)" ]] && command -v matchpathcon >/dev/null 2>&1; then
				if t=$(matchpathcon -n "$p" 2>/dev/null); then
					echo "selinux-home: matchpathcon ${p} = ${t}"
					if [[ "$t" == *:default_t:* ]]; then
						echo "selinux-home: FAIL: matchpathcon ${p} = ${t}" >&2
						failed=1
					fi
				else
					echo "selinux-home: matchpathcon could not look up ${p}; static result stands" >&2
				fi
			fi
		done
	done
	if [[ $failed -ne 0 ]]; then
		echo "selinux-home: HOME in /etc/default/useradd and the subs aliases disagree; see docs/ci-troubleshooting.md (tunaOS#4047)" >&2
		return 1
	fi
	return 0
}
