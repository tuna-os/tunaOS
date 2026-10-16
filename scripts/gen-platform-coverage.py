#!/usr/bin/env python3
"""Generate ROADMAP.md's desktop-by-platform support matrix.

The source of truth is `.github/build-config.yml`. A standard architecture is
supported for a desktop only when that desktop flavor has `build_image: true`
and declares the architecture. Apple Silicon is separate from generic arm64:
it requires an enabled `<desktop>-asahi` flavor and remains experimental until
real-hardware and installer gates graduate it.

Usage:
    scripts/gen-platform-coverage.py [--check]
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "build-config.yml"
DOC = ROOT / "ROADMAP.md"
BEGIN = "<!-- BEGIN GENERATED — scripts/gen-platform-coverage.py -->"
END = "<!-- END GENERATED — scripts/gen-platform-coverage.py -->"

DESKTOPS = ("gnome", "kde", "cosmic", "niri", "xfce", "pantheon", "tuna")
DISPLAY = {
    "gnome": "GNOME",
    "kde": "KDE",
    "cosmic": "COSMIC",
    "niri": "Niri",
    "xfce": "XFCE",
    "pantheon": "Pantheon",
    "tuna": "Tuna",
}


def load_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def flavor_platforms(config: dict, variant: dict, flavor: dict) -> set[str]:
    """Return the platforms the build matrix gives one flavor."""
    # By key presence, as build-variant.yml's jq `//` does: an explicit
    # empty list means no platforms, not "inherit".
    platforms = flavor.get("platforms")
    if platforms is None:
        platforms = variant.get("platforms")
    if platforms is None:
        platforms = config["config"]["global_platforms"]
    if not isinstance(platforms, list) or not all(
        isinstance(p, str) for p in platforms
    ):
        raise ValueError(
            f"{variant['id']}/{flavor['id']}: platforms must be a list of "
            f"strings, got {platforms!r}"
        )
    return set(platforms)


def has_arch(platforms: set[str], arch: str) -> bool:
    """True if any platform is linux/<arch>, including variant suffixes."""
    base = f"linux/{arch}"
    return any(p == base or p.startswith(base + "/") for p in platforms)


def coverage(config: dict) -> list[dict]:
    """Derive standard-architecture and Asahi desktop commitments."""
    rows = []
    for variant in config["variants"]:
        flavors = {flavor["id"]: flavor for flavor in variant.get("flavors", [])}
        row = {
            "variant": variant["id"],
            "amd64": set(),
            "arm64": set(),
            "asahi": set(),
        }
        for desktop in DESKTOPS:
            standard = flavors.get(desktop)
            if standard and standard.get("build_image"):
                platforms = flavor_platforms(config, variant, standard)
                if has_arch(platforms, "amd64"):
                    row["amd64"].add(desktop)
                if has_arch(platforms, "arm64"):
                    row["arm64"].add(desktop)

            asahi = flavors.get(f"{desktop}-asahi")
            if (
                asahi
                and asahi.get("build_image")
                and has_arch(flavor_platforms(config, variant, asahi), "arm64")
            ):
                row["asahi"].add(desktop)
        rows.append(row)
    return rows


def status_cell(included: set[str], label: str) -> str:
    present = ", ".join(DISPLAY[d] for d in DESKTOPS if d in included)
    absent = ", ".join(DISPLAY[d] for d in DESKTOPS if d not in included)
    parts = [f"**{label}:** {present}"] if present else []
    if absent:
        parts.append(f"**U:** {absent}")
    return "; <br>".join(parts)


def build(config: dict) -> str:
    rows = coverage(config)
    apple_cells = sum(len(row["asahi"]) for row in rows)
    non_gnome = [DISPLAY[d] for d in DESKTOPS if d != "gnome"]
    non_gnome_text = ", ".join(non_gnome[:-1]) + ", and " + non_gnome[-1]
    out = [
        BEGIN,
        "",
        "### Platform Coverage Matrix",
        "",
        (
            "`scripts/gen-platform-coverage.py` makes this matrix from [`.github/build-config.yml`](./.github/build-config.yml). "
            + "It records the desktop/platform combinations the image factory commits to build; it does "
            + "not infer support from registry tags."
        ),
        "",
        (
            "- **S — Supported:** an active cell for a standard OCI image (`build_image: true`). Runtime "
            + "evidence and current failures remain visible in [MATRIX-STATUS.md](docs/MATRIX-STATUS.md)."
        ),
        (
            "- **E — Experimental:** an active Apple Silicon/Asahi cell. The boot chain has static "
            + "verification, but the installer and real-hardware gates have not graduated it."
        ),
        "- **U — Unsupported:** no active image cell and no release or maintenance commitment.",
        "",
        "| Variant | x86_64 | aarch64 | Apple Silicon (M1/M2, Asahi) |",
        "|---|---|---|---|",
    ]
    for row in rows:
        out.append(
            f"| **{row['variant']}** | {status_cell(row['amd64'], 'S')} | "
            + f"{status_cell(row['arm64'], 'S')} | {status_cell(row['asahi'], 'E')} |"
        )

    out += [
        "",
        "#### Platform parity commitment",
        "",
        (
            "Standard aarch64 support is a per-variant commitment, not a claim that every desktop "
            + "works on every base. The flavor-equality mandate applies to cells marked **S**; it does "
            + "not turn a missing package stack into a supported cell."
        ),
        "",
        (
            f"Apple Silicon has **{apple_cells} active experimental desktop cell(s)**, all derived from "
            + "enabled `*-asahi` flavors. GNOME is the only Apple Silicon target for a desktop now. "
            + f"{non_gnome_text} are **U — Unsupported** on Apple Silicon, with no parity date or "
            + "release commitment. Gates control expansion. First, GNOME must pass a gate for boot and "
            + "session on a real Mac, and the installer must ship. Then each additional desktop needs "
            + "its own enabled `-asahi` flavor and the same static and hardware evidence."
        ),
        "",
        (
            "The scheduled Asahi sweep can continue to inspect old tags after a build cell is "
            + "disabled. A tag or sweep entry is historical test inventory, not support. See "
            + "[the hardware tiers for Asahi CI](docs/ASAHI-HARDWARE-TIERS.md) for the missing hardware evidence."
        ),
        "",
        END,
    ]
    return "\n".join(out)


def replace_block(text: str, generated: str) -> str:
    if BEGIN not in text or END not in text:
        raise ValueError(f"{DOC} is missing the platform coverage GENERATED markers")
    head, rest = text.split(BEGIN, 1)
    _committed, tail = rest.split(END, 1)
    return head + generated + tail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if ROADMAP.md would change"
    )
    args = parser.parse_args()

    text = DOC.read_text(encoding="utf-8")
    generated = build(load_config())
    try:
        updated = replace_block(text, generated)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    if updated == text:
        print("ROADMAP.md platform coverage block already current")
        return 0
    if args.check:
        print("ROADMAP.md platform coverage block is out of date", file=sys.stderr)
        print(
            "\n".join(
                difflib.unified_diff(
                    text.splitlines(),
                    updated.splitlines(),
                    fromfile="ROADMAP.md",
                    tofile="generated",
                    lineterm="",
                )
            ),
            file=sys.stderr,
        )
        return 1
    DOC.write_text(updated, encoding="utf-8")
    print("ROADMAP.md platform coverage block regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
