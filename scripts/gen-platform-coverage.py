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

DESKTOPS = ("gnome", "kde", "cosmic", "niri", "xfce")
DISPLAY = {
    "gnome": "GNOME",
    "kde": "KDE",
    "cosmic": "COSMIC",
    "niri": "Niri",
    "xfce": "XFCE",
}


def load_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def flavor_platforms(config: dict, variant: dict, flavor: dict) -> set[str]:
    """Return the platforms the build matrix gives one flavor."""
    return set(
        flavor.get("platforms")
        or variant.get("platforms")
        or config["config"]["global_platforms"]
    )


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
                if any(
                    p == "linux/amd64" or p.startswith("linux/amd64/")
                    for p in platforms
                ):
                    row["amd64"].add(desktop)
                if "linux/arm64" in platforms:
                    row["arm64"].add(desktop)

            asahi = flavors.get(f"{desktop}-asahi")
            if (
                asahi
                and asahi.get("build_image")
                and "linux/arm64" in flavor_platforms(config, variant, asahi)
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
    out = [
        BEGIN,
        "",
        "### Platform Coverage Matrix",
        "",
        (
            "This matrix is generated from [`.github/build-config.yml`](./.github/build-config.yml). "
            + "It records the desktop/platform combinations the image factory commits to build; it does "
            + "not infer support from registry tags."
        ),
        "",
        (
            "- **S — Supported:** an active standard OCI-image cell (`build_image: true`). Runtime "
            + "evidence and current failures remain visible in [MATRIX-STATUS.md](docs/MATRIX-STATUS.md)."
        ),
        (
            "- **E — Experimental:** an active Apple Silicon/Asahi cell. Static boot-chain verification "
            + "exists, but the installer and real-hardware gates have not graduated it."
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
            + "enabled `*-asahi` flavors. GNOME is the only current Apple Silicon desktop target. KDE, "
            + "COSMIC, Niri, and XFCE are **U — Unsupported** on Apple Silicon, with no parity date or "
            + "release commitment. Expansion is gated rather than assumed: GNOME must first pass a "
            + "real-Mac boot/session gate and the installer must ship; then each additional desktop needs "
            + "its own enabled `-asahi` flavor and the same static and hardware evidence."
        ),
        "",
        (
            "The scheduled Asahi sweep may continue to inspect old promoted tags after their build cell "
            + "is disabled. A tag or sweep entry is historical test inventory, not support. See "
            + "[Asahi hardware CI tiers](docs/ASAHI-HARDWARE-TIERS.md) for the missing hardware evidence."
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
