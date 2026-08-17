#!/usr/bin/env bash
# gentoo-binhost-version-lock.sh — tuna-os/tunaOS#1802.
#
# Why this exists
# ----------------
# The desktop stage of Containerfile.gentoo turns on FEATURES=getbinpkg
# against the official Gentoo binhost, but --getbinpkg only substitutes a
# binary package when its CPV (category/name-version) is an EXACT match for
# what `emerge --sync` just resolved from the live ::gentoo tree — USE flags
# aside, a different version is not a candidate at all.
#
# kde-plasma bumps in lockstep across ~55 kde-plasma/* atoms every few
# weeks; the official binhost is rebuilt on its own, slower cadence. Measured
# on run 31953925629 (2026-08-16): the freshly-synced tree resolved
# kde-plasma to 6.6.5, the binhost had only 6.6.6 built (confirmed live
# against https://distfiles.gentoo.org/releases/amd64/binpackages/23.0/x86-64/Packages
# on 2026-08-17 — no 6.6.5 kde-plasma entries exist there at all), so every
# one of the 70 desktop-stage emerges — including kde-plasma/sddm-kcm, whose
# only IUSE flag (debug) already matched the local config — compiled from
# source. That is a version miss, not a USE miss: 56 of those 70 (80%) are
# kde-plasma/*-6.6.5 atoms, all pulled in transitively off one root atom,
# kde-plasma/plasma-meta, whose own RDEPEND pins the rest of the stack with
# `>=kde-plasma/foo-6.6.6:6`-style atoms — so a bare `emerge --sync` always
# races ahead of the binhost for this category.
#
# What this does
# ---------------
# Reads the binhost configured in /etc/portage/binrepos.conf, and masks any
# version newer than what that binhost has actually published, for every
# package in the anchor category (packages.emerge[0]'s category in the
# desktop manifest — kde-plasma for kde, gnome-base for gnome, xfce-base for
# xfce; see manifests/desktops/*.yaml). Portage's own `>=` dependency chain
# inside the meta package then has nowhere to resolve but the version the
# binhost actually built, instead of whatever the tree sync just pulled.
#
# Safety
# ------
# Best-effort and fails open at every step: no binhost configured, no
# network, an unparseable Packages index, or a version lock that makes the
# package set unresolvable (checked with `emerge --pretend` before the real
# emerge runs) all leave portage's config exactly as it was before this
# script ran. This can only add binpkg matches; it cannot make an emerge
# invocation that used to succeed start failing, and it does not touch
# --binpkg-respect-use or binpkg signature policy (both stay whatever
# Containerfile.gentoo already set).
#
# Usage: gentoo-binhost-version-lock.sh <anchor-category> <emerge-pkg>...
set -uo pipefail

_GBL_ANCHOR_CAT="${1:?Usage: gentoo-binhost-version-lock.sh <anchor-category> <emerge-pkg>...}"
shift
_GBL_EMERGE_PKGS=("$@")

_GBL_MASK_FILE="/etc/portage/package.mask/gentoo-binhost-version-lock"
_GBL_BINREPO_CONF="/etc/portage/binrepos.conf"

if [[ ! -d "${_GBL_BINREPO_CONF}" ]] || ! grep -rhq '^sync-uri' "${_GBL_BINREPO_CONF}" 2>/dev/null; then
	echo "gentoo-binhost-version-lock: no binrepos.conf sync-uri configured, skipping" >&2
	exit 0
fi

_GBL_BINHOST_URI="$(grep -rh '^sync-uri' "${_GBL_BINREPO_CONF}" | head -1 | sed -E 's/^sync-uri[[:space:]]*=[[:space:]]*//')"
_GBL_PKGIDX="$(mktemp)"
trap 'rm -f "${_GBL_PKGIDX}"' EXIT

if ! curl -fsSL -m 180 "${_GBL_BINHOST_URI%/}/Packages" -o "${_GBL_PKGIDX}"; then
	echo "gentoo-binhost-version-lock: could not fetch ${_GBL_BINHOST_URI%/}/Packages, skipping" >&2
	exit 0
fi

mkdir -p "$(dirname "${_GBL_MASK_FILE}")"

if ! python3 - "${_GBL_ANCHOR_CAT}" "${_GBL_PKGIDX}" >"${_GBL_MASK_FILE}.tmp" 2>/tmp/gentoo-binhost-version-lock.err <<'PYEOF'
import re
import sys

anchor_cat, pkgidx_path = sys.argv[1], sys.argv[2]

# PMS version grammar (simplified): digits.digits..., optional letter,
# optional _alpha/_beta/_pre/_rc/_p suffix, optional -rN revision.
VERSION_RE = re.compile(
    r"^\d+(\.\d+)*[a-z]?(_(alpha|beta|pre|rc|p)\d*)*(-r\d+)?$"
)


def split_pn_pv(name_version):
    """Split 'pn-pv' the way portage does: scan from the right for the
    shortest trailing chunk that is a valid version string."""
    parts = name_version.split("-")
    for i in range(len(parts) - 1, 0, -1):
        candidate = "-".join(parts[i:])
        if VERSION_RE.match(candidate):
            return "-".join(parts[:i]), candidate
    return None, None


def version_key(v):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v)]


versions_by_pkg = {}
with open(pkgidx_path, errors="replace") as f:
    for line in f:
        if not line.startswith("CPV: "):
            continue
        cpv = line[len("CPV: "):].strip()
        cat, sep, rest = cpv.partition("/")
        if not sep or cat != anchor_cat:
            continue
        pn, pv = split_pn_pv(rest)
        if pn is None:
            continue
        versions_by_pkg.setdefault(f"{cat}/{pn}", set()).add(pv)

for key in sorted(versions_by_pkg):
    versions = versions_by_pkg[key]
    try:
        newest = sorted(versions, key=version_key)[-1]
    except TypeError:
        # Mixed/unexpected version shapes for this package — fall back to a
        # plain string sort rather than crash; still strictly best-effort.
        newest = sorted(versions)[-1]
    print(f">{key}-{newest}")
PYEOF
then
	echo "gentoo-binhost-version-lock: Packages index parse failed, skipping (see /tmp/gentoo-binhost-version-lock.err)" >&2
	rm -f "${_GBL_MASK_FILE}.tmp"
	exit 0
fi

if [[ ! -s "${_GBL_MASK_FILE}.tmp" ]]; then
	echo "gentoo-binhost-version-lock: binhost has no ${_GBL_ANCHOR_CAT}/* packages, skipping" >&2
	rm -f "${_GBL_MASK_FILE}.tmp"
	exit 0
fi

mv "${_GBL_MASK_FILE}.tmp" "${_GBL_MASK_FILE}"

# Confirm the lock does not make the requested package set unresolvable
# (e.g. the binhost's version was already pruned from the freshly-synced
# tree) before letting the real emerge below see it.
if ! emerge --pretend --verbose "${_GBL_EMERGE_PKGS[@]}" >/tmp/gentoo-binhost-version-lock-pretend.log 2>&1; then
	echo "gentoo-binhost-version-lock: locked versions are unresolvable against the synced tree, reverting (see /tmp/gentoo-binhost-version-lock-pretend.log)" >&2
	rm -f "${_GBL_MASK_FILE}"
	exit 0
fi

echo "gentoo-binhost-version-lock: locked ${_GBL_ANCHOR_CAT}/* to binhost versions from ${_GBL_BINHOST_URI}" >&2
