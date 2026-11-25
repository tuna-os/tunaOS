"""Installer medium cells (tunaOS#4905, #4907, #4913).

Every variant:flavor in the tunaos.toml matrix resolves to one medium row by
rule, so the cell list cannot drift from the matrix:

- frontend: `[installer_medium.frontends]` maps the flavor's desktop (the
  flavor up to its first dash, so `kde-nvidia` is kde) to a directory in
  installer-medium/frontends. A desktop in `headless` gets no medium.
- bootloader, backend, filesystem: the result of
  live-iso/common/src/installer-recipe-backend.sh on the published image,
  recorded with the image digest in installer-medium/evidence/images.json
  (written by installer-medium/evidence/scan-images.py). EL bases stay on
  xfs; other bases use btrfs, or ext4 for a composefs image whose kernel
  lacks the fs-verity fix. A cell with no readable image is `unverified`
  with the reason; nothing is guessed from a name.
- `[[installer_medium.cells]]` holds the explicit rows: `promoted = true`
  puts a cell in the nightly, and a declared layout covers an image the
  scan cannot read (tromso:kde). A declaration never contradicts evidence.

`installer-medium/` build scripts read this through `cells()` and `cell()`;
`tunaos_config.validate` rejects anything else.
"""

import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA_VERSION = 2
FILESYSTEMS = ("xfs", "btrfs", "ext4")
BOOTLOADERS = ("grub", "systemd-boot")
BACKENDS = ("ostree", "composefs")
LIVE_KARG = "tunaos.live"
# Frontend directories installer-medium/frontends/install-frontend.sh can
# wire, and the installer each one shows. A desktop with no entry in
# [installer_medium.frontends] or `headless` fails validation: the dispatcher
# never falls back to a default (AGENTS.md, "A detection default is a silent
# fallback").
FRONTENDS = {
    "gnome": "gnome-setup",
    "tuna": "gnome-setup",
    "pantheon": "gnome-setup",
    "kde": "org.tunaos.InstallerKde",
    "cosmic": "org.tunaos.InstallerCosmic",
    "niri": "org.tunaos.InstallerNiri",
    "xfce": "org.tunaos.InstallerXfce",
}
STATUSES = ("promoted", "supported", "unverified", "no-medium")
EVIDENCE = Path(__file__).resolve().parents[2] / "installer-medium/evidence/images.json"
PROBE_BOOTLOADER = {"grub2": "grub", "systemd": "systemd-boot"}
# The EL words of installer-recipe-backend.sh rule 1, used only to cross-check
# a recorded xfs result against the recorded os-release.
EL_WORDS = frozenset(("rhel", "centos", "almalinux", "rocky", "ol"))
MAX_CHUNK_BYTES = 256 << 20
# EL10 bootc bases (tunaOS#4908): AlmaLinux and CentOS Stream 10. Measured
# 2026-11-22 from the variants.*.base_image pins in tunaos.toml: yellowfin and
# albacore carry almalinux-bootc:10, skipjack carries centos-bootc:stream10.
EL10_BASE = re.compile(r"almalinux|centos-bootc")
CELL = re.compile(r"[a-z0-9][a-z0-9-]*:[a-z0-9][a-z0-9-]*")
COMMIT = re.compile(r"[0-9a-f]{40}")
MAX_DECLARED = 64
SECURE_BOOT = ("distro-chain", "tunaos-key")
SECURE_BOOT_ENROLL = ("if-safe", "manual", "off", "force")
SHA256 = re.compile(r"[0-9a-f]{64}")
# The BuildStream XFCE image is `brussels`; `xfce-linux` is its former name
# and stays valid as a deprecated alias, for the sibling id and for a cell.
SIBLING_ALIASES = {"xfce-linux": "brussels"}
SECURE_BOOT_BASES = Path(__file__).resolve().parents[2] / "installer-medium/secure-boot/bases.toml"


class MediumError(ValueError):
    """An installer_medium declaration is invalid."""


def _keys(value, required, optional=(), where="installer_medium"):
    if (
        not isinstance(value, dict)
        or set(required) - set(value)
        or set(value) - set(required) - set(optional)
    ):
        raise MediumError(f"{where}: expected fields {list(required)}")


def desktop_of(name):
    """The desktop a cell's flavor names: `gnome-hwe` is gnome, `kde` is kde."""
    return name.partition(":")[2].partition("-")[0]


def is_el10(base_image):
    """True when a variant base image is an EL10 bootc base."""
    return bool(EL10_BASE.search(base_image or ""))


def load_evidence(path=None):
    """Evidence records by cell name. A missing file means nothing is verified."""
    path = Path(path or EVIDENCE)
    if not path.exists():
        return {}
    document = json.loads(path.read_text())
    if document.get("schema_version") != 1 or not isinstance(document.get("images"), list):
        raise MediumError(f"{path}: expected schema_version 1 and an images list")
    return {record["cell"]: record for record in document["images"]}


def _policy(primary):
    """Validate the scalar fields, the frontend map and the shape of each explicit row."""
    _keys(
        primary.get("installer_medium", {}),
        (
            "schema_version",
            "systemd_repo",
            "systemd_ref",
            "fisherman_repo",
            "fisherman_ref",
            "chunk_bytes",
            "headless",
            "frontends",
            "cells",
        ),
    )
    policy = primary["installer_medium"]
    if type(policy["schema_version"]) is not int or policy["schema_version"] != SCHEMA_VERSION:
        raise MediumError(f"installer_medium.schema_version: expected integer {SCHEMA_VERSION}")
    repo = policy["systemd_repo"]
    if not isinstance(repo, str) or urlsplit(repo).scheme != "https" or not urlsplit(repo).hostname:
        raise MediumError("installer_medium.systemd_repo: expected an https:// git URL")
    if not isinstance(policy["systemd_ref"], str) or not COMMIT.fullmatch(policy["systemd_ref"]):
        raise MediumError(
            "installer_medium.systemd_ref: expected a full 40-hex systemd main commit, never a branch"
        )
    fisherman = policy["fisherman_repo"]
    if (
        not isinstance(fisherman, str)
        or urlsplit(fisherman).scheme != "https"
        or not urlsplit(fisherman).hostname
    ):
        raise MediumError("installer_medium.fisherman_repo: expected an https:// git URL")
    if fisherman.removesuffix(".git").lower().endswith("projectbluefin/fisherman"):
        raise MediumError(
            "installer_medium.fisherman_repo: projectbluefin/fisherman stopped moving; use tuna-os/fisherman"
        )
    if not isinstance(policy["fisherman_ref"], str) or not COMMIT.fullmatch(policy["fisherman_ref"]):
        raise MediumError(
            "installer_medium.fisherman_ref: expected a full 40-hex fisherman commit, never a branch"
        )
    chunk = policy["chunk_bytes"]
    if type(chunk) is not int or chunk < (1 << 20) or chunk > MAX_CHUNK_BYTES:
        raise MediumError(
            f"installer_medium.chunk_bytes: expected 1 MiB..{MAX_CHUNK_BYTES} (contract v1 caps a chunk at 256 MiB)"
        )
    frontends, headless = policy["frontends"], policy["headless"]
    if not isinstance(frontends, dict) or not frontends:
        raise MediumError("installer_medium.frontends: expected a desktop = frontend table")
    for desktop, frontend in frontends.items():
        if frontend not in FRONTENDS:
            raise MediumError(
                f"installer_medium.frontends.{desktop}: no frontend {frontend!r}; expected one of {list(FRONTENDS)}"
            )
    if not isinstance(headless, list) or any(not isinstance(d, str) for d in headless):
        raise MediumError("installer_medium.headless: expected a list of desktop names")
    both = sorted(set(headless) & set(frontends))
    if both:
        raise MediumError(f"installer_medium.headless: {both} also have a frontend")
    declared = policy["cells"]
    if not isinstance(declared, list) or not declared or len(declared) > MAX_DECLARED:
        raise MediumError(
            f"installer_medium.cells: expected a non-empty list of at most {MAX_DECLARED} explicit cells"
        )
    seen = set()
    for i, entry in enumerate(declared):
        where = f"installer_medium.cells[{i}]"
        _keys(
            entry,
            ("cell",),
            (
                "promoted",
                "filesystem",
                "bootloader",
                "backend",
                "reason",
                "secure_boot",
                "secure_boot_enroll",
                "secure_boot_vendor_sha256",
                "secure_boot_reason",
            ),
            where=where,
        )
        name = entry["cell"]
        if not isinstance(name, str) or not CELL.fullmatch(name):
            raise MediumError(f"{where}.cell: expected variant:flavor, such as albacore:gnome")
        if name in seen:
            raise MediumError(f"{where}.cell: duplicate cell {name!r}")
        seen.add(name)
        if len(entry) == 1:
            raise MediumError(f"{where}: declares nothing; set promoted or a layout")
        if "promoted" in entry and type(entry["promoted"]) is not bool:
            raise MediumError(f"{where}.promoted: expected true or false")
        for key, allowed in (("filesystem", FILESYSTEMS), ("bootloader", BOOTLOADERS), ("backend", BACKENDS)):
            if key in entry and entry[key] not in allowed:
                raise MediumError(f"{where}.{key}: expected one of {list(allowed)}")
        layout = [key for key in ("filesystem", "bootloader", "backend") if key in entry]
        if layout and (not isinstance(entry.get("reason"), str) or not entry["reason"].strip()):
            raise MediumError(f"{where}.reason: a declared {layout[0]} needs the reason it is declared")
        if "reason" in entry and not layout:
            raise MediumError(f"{where}.reason: only a declared layout takes a reason")
        mode = entry.get("secure_boot")
        if "secure_boot" in entry and mode not in SECURE_BOOT:
            raise MediumError(f"{where}.secure_boot: expected one of {list(SECURE_BOOT)}")
        if mode and (not isinstance(entry.get("secure_boot_reason"), str) or not entry["secure_boot_reason"].strip()):
            raise MediumError(f"{where}.secure_boot_reason: a declared secure_boot needs its reason")
        for key in ("secure_boot_enroll", "secure_boot_vendor_sha256", "secure_boot_reason"):
            if key in entry and not mode:
                raise MediumError(f"{where}.{key}: declare secure_boot with it")
        if "secure_boot_enroll" in entry:
            if mode != "tunaos-key":
                raise MediumError(f"{where}.secure_boot_enroll: only a tunaos-key cell enrolls a key")
            if entry["secure_boot_enroll"] not in SECURE_BOOT_ENROLL:
                raise MediumError(f"{where}.secure_boot_enroll: expected one of {list(SECURE_BOOT_ENROLL)}")
        if "secure_boot_vendor_sha256" in entry:
            pins = entry["secure_boot_vendor_sha256"]
            if mode != "distro-chain":
                raise MediumError(f"{where}.secure_boot_vendor_sha256: only a distro-chain cell pins a vendor certificate")
            if not isinstance(pins, list) or not pins or any(not isinstance(x, str) or not SHA256.fullmatch(x) for x in pins):
                raise MediumError(f"{where}.secure_boot_vendor_sha256: expected a list of 64-hex SHA-256 values")
    return policy


def _platforms(primary, variant, flavor):
    """Architectures a flavor builds for: its own platforms, else the variant's."""
    platforms = (
        flavor.get("platforms")
        or variant.get("platforms")
        or primary.get("build", {}).get("global_platforms", [])
    )
    out = []
    for platform in platforms:
        arch = platform.split("/")[1]
        if arch not in out:
            out.append(arch)
    return out


def _published(primary, variant_name, flavor_id):
    """The image ref a variant flavor publishes as (tunaos_config.published_name_tag)."""
    entry = primary["variants"][variant_name]
    suffix = entry.get("tag_suffix") or ""
    publish = primary.get("build", {}).get("publish", {})
    registry = publish.get("registry") or "ghcr.io"
    namespace = publish.get("namespace") or "tuna-os"
    tag = f"{flavor_id}-{suffix}" if suffix else flavor_id
    return f"{registry}/{namespace}/{entry.get('publish_name') or variant_name}:{tag}"


def canonical(name):
    """A cell name with a deprecated sibling id replaced: xfce-linux:xfce is brussels:xfce."""
    variant_name, _, flavor_id = name.partition(":")
    return f"{SIBLING_ALIASES.get(variant_name, variant_name)}:{flavor_id}"


def _sibling(primary, name):
    """The sibling image entry a cell names, when its desktop is listed there.

    The entry may carry the current id or its deprecated alias.
    """
    variant_name, _, flavor_id = canonical(name).partition(":")
    for sibling in primary.get("sibling_images", []):
        sibling_id = sibling.get("id")
        if SIBLING_ALIASES.get(sibling_id, sibling_id) == variant_name and flavor_id in {
            str(desktop).lower() for desktop in sibling.get("desktops", [])
        }:
            return sibling
    return None


def _candidates(primary, policy):
    """One bare row per matrix flavor, then one per declared sibling cell."""
    frontends, headless = policy["frontends"], policy["headless"]
    rows = []
    for variant_name, variant in primary.get("variants", {}).items():
        for flavor in variant.get("flavors", []):
            name = f"{variant_name}:{flavor['id']}"
            desktop = desktop_of(name)
            if desktop not in frontends and desktop not in headless:
                raise MediumError(
                    f"installer_medium.frontends: no entry for desktop {desktop!r} of {name}; "
                    "map it to a frontend or list it in headless"
                )
            rows.append(
                {
                    "cell": name,
                    "desktop": desktop,
                    "frontend": frontends.get(desktop),
                    "architectures": _platforms(primary, variant, flavor),
                    "image": _published(primary, variant_name, flavor["id"]),
                    "el": is_el10(variant.get("base_image", "")),
                    "built": flavor.get("build_image", True) is not False,
                }
            )
    known = {row["cell"] for row in rows}
    for i, entry in enumerate(policy["cells"]):
        name = entry["cell"]
        if name in known:
            continue
        sibling = _sibling(primary, name)
        if sibling is None:
            raise MediumError(
                f"installer_medium.cells[{i}].cell: unknown variant/flavor or sibling desktop {name!r}"
            )
        desktop = desktop_of(name)
        if desktop not in frontends:
            raise MediumError(f"installer_medium.cells[{i}].cell: no medium frontend for desktop {desktop!r}")
        rows.append(
            {
                "cell": name,
                "desktop": desktop,
                "frontend": frontends[desktop],
                "architectures": ["amd64"],
                # A sibling publishes `latest`/`stable`, not one tag per
                # desktop: `installer_tag` names the tag the medium reads.
                "image": (
                    f"{sibling['image']}:{sibling.get('installer_tag') or name.partition(':')[2]}"
                    if sibling.get("image")
                    else None
                ),
                "el": False,
                "built": True,
                "sibling": True,
            }
        )
    return rows


def _measured(record):
    """(layout, reason) from one evidence record: the probe result, or why there is none."""
    if record is None:
        return None, "no evidence record: run installer-medium/evidence/scan-images.py"
    if "unverified" in record:
        return None, record["unverified"]
    probe = record.get("probe", {})
    try:
        layout = {
            "filesystem": probe["filesystem"],
            "bootloader": PROBE_BOOTLOADER[probe["bootloader"]],
            "backend": {"true": "composefs", "false": "ostree"}[probe["composeFsBackend"]],
        }
    except KeyError:
        return None, "evidence record has no usable probe result"
    if layout["filesystem"] not in FILESYSTEMS:
        return None, f"probe filesystem {layout['filesystem']!r} is not a medium filesystem"
    return layout, None


def _os_words(record):
    words = set()
    for line in (record or {}).get("facts", {}).get("os_release", "").splitlines():
        key, _, value = line.partition("=")
        if key in ("ID", "ID_LIKE"):
            words.update(value.strip("\"'").split())
    return words


def load_secure_boot_bases(path=None):
    """Rows of installer-medium/secure-boot/bases.toml by name; {} when the file is absent.

    tunaOS#4958 adds that file. When it is present it is the authority for
    `shim_accepts` and for the vendor certificate pins.
    """
    path = Path(path or SECURE_BOOT_BASES)
    if not path.exists():
        return {}
    # The reviewed parser of tunaos_config, never the host's tomllib
    # (tests/test_config_parser.py: a parser import is a grammar choice).
    spec = importlib.util.spec_from_file_location(
        "installer_medium_toml", Path(__file__).with_name("tunaos_config.py")
    )
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return {row["name"]: row for row in reader.parse(path.read_bytes(), str(path)).get("base", [])}


def _secure_boot(name, where, entry, bootloader, signed, sb_bases, record=None):
    """The Secure Boot fields of one supported cell (tunaOS#4955).

    Rules: tunaos-key needs systemd-boot. systemd-boot on the distro chain
    needs a base whose shim accepts the signed systemd-boot. Only a
    tunaos-key cell enrolls a key; only a distro-chain cell pins a vendor
    certificate. An explicit row is checked against the same rules.
    """
    variant = canonical(name).partition(":")[0]
    base_name = signed["variants"].get(variant)
    base = signed["bases"].get(base_name) if base_name else None
    sb_row = sb_bases.get(signed.get("secure_boot_bases", {}).get(variant))
    accepts = (sb_row or base or {}).get("shim_accepts") == "yes"
    mode = entry.get("secure_boot")
    reason = entry.get("secure_boot_reason")
    if mode is None:
        if base is None and sb_row is None:
            raise MediumError(f"{where}: {name} has no Secure Boot record for its base; declare secure_boot")
        label = base_name or sb_row["name"]
        if bootloader == "grub":
            mode, reason = "distro-chain", f"{label}: the distribution signs shim, GRUB and the kernel"
        elif accepts:
            mode, reason = "distro-chain", f"{label}: the shim accepts the signed systemd-boot of the distribution"
            wanted = (base or {}).get("signed_file")
            files = (record or {}).get("facts", {}).get("files")
            if wanted and files is not None and wanted not in files:
                # Measured, so stated: the mode is what the base supports, and
                # the image does not carry the signed binary yet.
                reason += f"; the image read on {record.get('read')} has no {wanted.rsplit('/', 1)[-1]}, so the chain is not complete yet"
        else:
            mode = "tunaos-key"
            reason = f"{label}: no signed systemd-boot that a shim accepts, so tunaOS CI signs"
    if mode == "tunaos-key" and bootloader != "systemd-boot":
        raise MediumError(f"{where}.secure_boot: tunaos-key needs systemd-boot, and {name} boots {bootloader}")
    if mode == "distro-chain" and bootloader == "systemd-boot" and not accepts:
        raise MediumError(
            f"{where}.secure_boot: systemd-boot on the distro chain needs a base whose shim accepts it "
            f"(shim_accepts = yes); {name} has none"
        )
    out = {"secure_boot": mode, "secure_boot_reason": reason, "secure_boot_enroll": None, "secure_boot_vendor_sha256": []}
    if mode == "tunaos-key":
        out["secure_boot_enroll"] = entry.get("secure_boot_enroll", "if-safe")
    else:
        out["secure_boot_vendor_sha256"] = list(
            entry.get("secure_boot_vendor_sha256") or (sb_row or {}).get("shim_vendor_sha256", [])
        )
    return out


def resolve(primary, evidence=None, strict=True):
    """Resolve every matrix cell to its medium row. Returns rows in matrix order.

    With strict off, a promoted cell that has no evidence stays unverified
    and raises nothing: `validate` uses that when the evidence file is absent.

    Each row has cell, desktop, frontend, installer, filesystem, bootloader,
    backend, architectures, image, status (see STATUSES), promoted, source
    (`probe` or `declared`), reason, and digest/read from the evidence.
    """
    policy = _policy(primary)
    evidence = load_evidence() if evidence is None else evidence
    signed, sb_bases = load_signed_boot(), load_secure_boot_bases()
    declared = {entry["cell"]: (i, entry) for i, entry in enumerate(policy["cells"])}
    rows = []
    for base in _candidates(primary, policy):
        name = base["cell"]
        index, entry = declared.get(name, (None, {}))
        where = f"installer_medium.cells[{index}]"
        row = {
            "cell": name,
            "desktop": base["desktop"],
            "frontend": base["frontend"],
            "installer": FRONTENDS.get(base["frontend"]),
            "filesystem": None,
            "bootloader": None,
            "backend": None,
            "architectures": base["architectures"],
            "image": base["image"],
            "status": "unverified",
            "promoted": False,
            "source": None,
            "reason": "",
            "digest": None,
            "read": None,
            "secure_boot": None,
            "secure_boot_enroll": None,
            "secure_boot_vendor_sha256": [],
            "secure_boot_reason": "",
        }
        rows.append(row)
        if base["frontend"] is None:
            row.update(status="no-medium", reason=f"{base['desktop']} has no graphical session")
            if entry:
                raise MediumError(f"{where}.cell: {name} is headless and gets no medium")
            continue
        # Keyed by cell name, not image ref: a fork that publishes the same
        # cells elsewhere keeps the measured layout.
        record = evidence.get(name)
        if not base["built"]:
            layout, reason = None, "not built: build_image is false in tunaos.toml"
        else:
            layout, reason = _measured(record)
        if layout is not None:
            el = base["el"] or bool(_os_words(record) & EL_WORDS)
            if layout["filesystem"] == "xfs" and not el:
                layout, reason = None, "probe kept xfs for an OS family it does not know"
            elif base["el"] and layout["filesystem"] != "xfs":
                layout, reason = (
                    None,
                    f"EL10 base with a sealed composefs image: the probe says {layout['filesystem']}, "
                    "the policy says xfs (tunaOS#4908)",
                )
        explicit = {key: entry[key] for key in ("filesystem", "bootloader", "backend") if key in entry}
        if layout is not None:
            for key in ("bootloader", "backend"):
                if key in explicit and explicit[key] != layout[key]:
                    raise MediumError(
                        f"{where}.{key}: {explicit[key]!r} contradicts the image evidence ({layout[key]!r}); "
                        "refresh the evidence instead"
                    )
            if "filesystem" in explicit and explicit["filesystem"] != layout["filesystem"]:
                # ext4 is the one safe step away from a measured btrfs. For a
                # sibling image the declared filesystem stands: the probe knows
                # the OS families of the matrix only, so its filesystem answer
                # for a BuildStream image is the unchanged fallback, not a
                # measurement. verify-cell-layout.sh warns in the same case.
                if not base.get("sibling") and (layout["filesystem"], explicit["filesystem"]) != ("btrfs", "ext4"):
                    raise MediumError(
                        f"{where}.filesystem: {explicit['filesystem']!r} contradicts the image evidence "
                        f"({layout['filesystem']!r})"
                    )
                layout["filesystem"] = explicit["filesystem"]
            row.update(layout, source="probe", digest=record.get("digest"), read=record.get("read"))
        elif explicit:
            if len(explicit) != 3:
                raise MediumError(
                    f"{where}: {name} has no image evidence, so filesystem, bootloader and backend "
                    "must all be declared"
                )
            if not base["built"]:
                raise MediumError(f"{where}.cell: {name} is not built")
            if base["el"] and explicit["filesystem"] != "xfs":
                raise MediumError(
                    f"{where}.filesystem: EL10 base {name.partition(':')[0]!r} stays on xfs (tunaOS#4908)"
                )
            if not base["el"] and explicit["filesystem"] == "xfs":
                raise MediumError(
                    f"{where}.filesystem: non-EL base {name.partition(':')[0]!r} uses btrfs, "
                    "or ext4 without the btrfs fs-verity fix"
                )
            row.update(explicit, source="declared", reason=entry["reason"])
        else:
            row["reason"] = reason
            if base["el"]:
                row["filesystem"] = "xfs"
            if entry.get("promoted") and strict:
                raise MediumError(f"{where}.promoted: {name} is unverified ({reason})")
            if "secure_boot" in entry and strict:
                raise MediumError(f"{where}.secure_boot: {name} is unverified ({reason})")
            continue
        row.update(_secure_boot(name, where, entry, row["bootloader"], signed, sb_bases, record))
        row["promoted"] = bool(entry.get("promoted"))
        row["status"] = "promoted" if row["promoted"] else "supported"
    return rows


def validate(primary):
    """Validate [installer_medium] against the variant/flavor matrix and the evidence."""
    # tunaos_config.load runs this in copies of the tree that hold only the
    # config sources (tests/test_primary_config.py, a sparse checkout). The
    # evidence file is not a config source, so its absence must not stop a
    # config load: the rows are then unverified and no build accepts them.
    # tests/test_installer_medium_config.py proves the checked-in file makes
    # every promoted cell supported.
    resolve(primary, strict=EVIDENCE.exists())
    return primary["installer_medium"]


def cells(primary, promoted_only=False):
    """The supported rows in matrix order; only the promoted ones on request."""
    wanted = ("promoted",) if promoted_only else ("promoted", "supported")
    return [row for row in resolve(primary) if row["status"] in wanted]


def cell(primary, name):
    """The row of one supported variant:flavor cell. Fails with the reason otherwise."""
    rows = resolve(primary)
    if name not in {row["cell"] for row in rows}:
        name = canonical(name)
    for row in rows:
        if row["cell"] == name:
            if row["status"] in ("promoted", "supported"):
                return row
            raise MediumError(f"installer_medium: cell {name!r} is {row['status']}: {row['reason']}")
    raise MediumError(f"installer_medium: no cell {name!r} in the matrix")


def scan_candidates(primary):
    """Cells whose published image scan-images.py reads: built, with a frontend and an image."""
    policy = _policy(primary)
    out = []
    for row in _candidates(primary, policy):
        if row["frontend"] is None or not row["built"] or not row["image"]:
            continue
        arches = row["architectures"]
        out.append(
            {"cell": row["cell"], "image": row["image"], "arch": "amd64" if "amd64" in arches else arches[0]}
        )
    return out


TARGETS = Path(__file__).resolve().parents[2] / "installer-medium/evidence/bootloader-target.json"
ANSWERS = ("yes", "no", "unknown")


def load_signed_boot(path=None):
    """The per-base signed systemd-boot records and the variant -> base map (tunaOS#4955)."""
    path = Path(path or TARGETS)
    if not path.exists():
        return {"bases": {}, "variants": {}}
    document = json.loads(path.read_text())
    if document.get("schema_version") != 1:
        raise MediumError(f"{path}: expected schema_version 1")
    bases, variants = document.get("bases"), document.get("variants")
    if not isinstance(bases, dict) or not isinstance(variants, dict):
        raise MediumError(f"{path}: expected bases and variants tables")
    for name, base in bases.items():
        where = f"{path.name}: bases.{name}"
        if any(base.get(key) not in ANSWERS for key in ("signed", "shim_accepts", "shim_grub")):
            raise MediumError(f"{where}: signed, shim_accepts and shim_grub must each be one of {list(ANSWERS)}")
        if base["signed"] == "yes" and not (base.get("signed_package") and base.get("signer")):
            raise MediumError(f"{where}: a signed systemd-boot needs its package and its signer")
        if base["signed"] != "unknown" and not base.get("sources"):
            raise MediumError(f"{where}: an answer needs at least one source")
        if not isinstance(base.get("notes", ""), str):
            raise MediumError(f"{where}: notes must be text")
    for variant, name in variants.items():
        if name not in bases:
            raise MediumError(f"{path.name}: variants.{variant} names unknown base {name!r}")
    return document


def bootloader_targets(primary, evidence=None, signed=None):
    """One bootloader target per variant, separate from what the images carry today.

    Owner decision tunaOS#4955: systemd-boot where the base publishes a signed
    systemd-boot that its shim accepts; shim and GRUB only where Secure Boot
    needs them. `today` is the measured bootloader/backend of the variant's
    images. `target` is `systemd-boot`, `grub` or `unknown`, with the reason;
    nothing here changes a cell.
    """
    evidence = load_evidence() if evidence is None else evidence
    signed = load_signed_boot() if signed is None else signed
    rows = resolve(primary, evidence)
    out = []
    for variant in primary.get("variants", {}):
        measured = [
            row for row in rows if row["cell"].partition(":")[0] == variant and row["source"] == "probe"
        ]
        today = sorted({f"{row['bootloader']}/{row['backend']}" for row in measured})
        backends = {row["backend"] for row in measured}
        if not measured:
            bootc = "unknown: no image of this variant was read"
        elif backends == {"composefs"}:
            bootc = "applies: the images use the composefs backend"
        else:
            bootc = "does not apply today: bootc takes it with the composefs backend only, and the images are ostree"
        base_name = signed["variants"].get(variant)
        base = signed["bases"].get(base_name) if base_name else None
        entry = {
            "variant": variant,
            "base": base_name,
            "today": ", ".join(today),
            "signed": "unknown",
            "package": None,
            "signer": None,
            "bootc_systemd": bootc,
            "target": "unknown",
            "secure_boot": "unknown",
            "reason": "no signed systemd-boot record for this base",
        }
        out.append(entry)
        if base is None:
            continue
        entry.update(signed=base["signed"], package=base.get("signed_package") or base.get("package"))
        notes = base.get("notes", "").strip()
        if base["signed"] == "yes":
            entry["signer"] = base["signer"]
            if base["shim_accepts"] == "yes":
                entry.update(target="systemd-boot", secure_boot="distro-chain")
                entry["reason"] = f"{base['signed_package']} is signed and the shim accepts the signer"
                if not bootc.startswith("applies"):
                    entry["reason"] += "; the switch waits for a composefs image"
            elif base["shim_accepts"] == "no" and base["shim_grub"] == "yes":
                entry.update(target="grub", secure_boot="distro-chain")
                entry["reason"] = (
                    f"{base['signed_package']} is signed, but the shim rejects the signer; "
                    "Secure Boot needs shim and GRUB"
                )
            else:
                entry["reason"] = f"{base['signed_package']} is signed; that the shim accepts the signer is not shown"
        elif base["signed"] == "no":
            if base["shim_grub"] == "yes":
                entry.update(target="grub", secure_boot="distro-chain")
                entry["reason"] = "no signed systemd-boot; Secure Boot needs the signed shim and GRUB of the base"
            elif base["shim_grub"] == "no":
                entry.update(target="systemd-boot", secure_boot="tunaos-key")
                entry["reason"] = "the base signs nothing for Secure Boot, so no shim is needed and tunaOS CI signs systemd-boot"
            else:
                entry["reason"] = "no signed systemd-boot; the shim and GRUB of the base were not inspected"
        else:
            entry["reason"] = notes or "not established"
        if notes and base["signed"] != "unknown":
            entry["reason"] += f" ({notes})"
    return out
