#!/usr/bin/env python3
"""Prepare and gate one route of the six-route package-addition qualification.

`prepare` runs inside the qualify-image-packages workflow checkout. It never
touches the dispatched ref: it makes two local commits (never pushed) so that
scripts/qualify-image-packages.py sees the exact pair it demands.

  stock commit     the checkout, with any mutable base_image pinned to the
                   digest resolved now (the harness needs a digest-pinned base)
  modified commit  its only child; adds one native package per variant to
                   tunaos.toml and regenerates build_scripts/lib/image-packages.tsv

It then prints the builds to run (commit, flavor, local tag) and writes the
harness plan, with images supplied for the selected route only. `gate` reads the
harness report and requires that route to have passed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import tunaos_config  # noqa: E402

HARNESS_SPEC = importlib.util.spec_from_file_location(
    "qualify_image_packages", ROOT / "scripts/qualify-image-packages.py"
)
HARNESS = importlib.util.module_from_spec(HARNESS_SPEC)
HARNESS_SPEC.loader.exec_module(HARNESS)

DEFAULT_FIXTURE = ROOT / "tests/fixtures/package-qualification-cells.json"
PINNED = re.compile(r"@sha256:[0-9a-f]{64}\Z")
PLATFORM = "linux/amd64"
CELL_FIELDS = {"route", "variant", "package", "desktop", "overlay"}
SOURCE_FILES = ("tunaos.toml", "build_scripts/lib/image-packages.tsv")


class PrepareError(ValueError):
    """The qualification input cannot be built into the exact commit pair."""


def need(condition: bool, message: str) -> None:
    if not condition:
        raise PrepareError(message)


def load_cells(fixture: Path) -> list[dict]:
    try:
        document = json.loads(fixture.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PrepareError(f"{fixture}: unreadable fixture: {exc}") from exc
    need(isinstance(document, dict) and set(document) == {"cells"}, f"{fixture}: expected a cells object")
    cells = document["cells"]
    need(isinstance(cells, list), f"{fixture}: cells must be a list")
    for index, cell in enumerate(cells):
        need(isinstance(cell, dict) and set(cell) == CELL_FIELDS, f"{fixture}: cells[{index}] has invalid fields")
        for field in ("route", "variant", "package", "desktop"):
            need(isinstance(cell[field], str) and cell[field], f"{fixture}: cells[{index}].{field} is required")
        # Only EL10 has an overlay stage; every other route builds no fourth image.
        need(
            (cell["route"] == "el10") == isinstance(cell["overlay"], str) and cell["overlay"] != "",
            f"{fixture}: cells[{index}].overlay must be set for el10 and null elsewhere",
        )
    need(
        [cell["route"] for cell in cells] == list(HARNESS.ROUTES),
        f"{fixture}: routes must equal the harness routes {list(HARNESS.ROUTES)}",
    )
    return cells


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    need(result.returncode == 0, f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


def commit(root: Path, message: str) -> str:
    # Local commits only. The identity is passed per command so no repository or
    # global git configuration is written.
    git(root, "add", *SOURCE_FILES)
    git(
        root, "-c", "user.name=qualify-image-packages", "-c", "user.email=qualify@invalid",
        "-c", "commit.gpgsign=false", "commit", "--no-verify", "--quiet", "-m", message,
    )
    return git(root, "rev-parse", "HEAD")


def variant_section(text: str, variant: str) -> tuple[int, int]:
    """Return the half-open line range of `[variants.<variant>]` without its subtables."""
    lines = text.splitlines(keepends=True)
    header = re.compile(rf"\[variants\.{re.escape(variant)}\]\s*(#.*)?\Z")
    starts = [i for i, line in enumerate(lines) if header.match(line.rstrip("\n"))]
    need(len(starts) == 1, f"tunaos.toml: expected exactly one [variants.{variant}] table")
    end = next((i for i in range(starts[0] + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    return starts[0], end


def pin_base_image(text: str, variant: str, reference: str) -> str:
    lines = text.splitlines(keepends=True)
    start, end = variant_section(text, variant)
    rows = [i for i in range(start, end) if lines[i].startswith("base_image")]
    need(len(rows) == 1, f"tunaos.toml: [variants.{variant}] needs exactly one base_image")
    lines[rows[0]] = f'base_image = "{reference}"\n'
    return "".join(lines)


def add_package(text: str, variant: str, package: str) -> str:
    need(
        f"[variants.{variant}.packages]" not in text,
        f"tunaos.toml: [variants.{variant}.packages] already exists; the qualification fixture would merge with it",
    )
    need(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_./-]*", package) is not None, f"invalid package {package!r}")
    separator = "" if text.endswith("\n") else "\n"
    return f'{text}{separator}\n[variants.{variant}.packages]\nadd = ["{package}"]\n'


def resolve_digest(reference: str) -> str:
    """Pin a mutable reference to the digest the registry serves for it right now."""
    result = subprocess.run(
        ["skopeo", "inspect", "--raw", f"docker://{reference}"],
        capture_output=True, check=False,
    )
    need(result.returncode == 0, f"skopeo inspect {reference}: {result.stderr.decode(errors='replace').strip()}")
    return f"{reference}@sha256:{hashlib.sha256(result.stdout).hexdigest()}"


def prepare(root: Path, cells: list[dict], route: str, plan_path: Path) -> dict:
    need(route in HARNESS.ROUTES, f"unknown route {route!r}")
    need(not git(root, "status", "--porcelain", "--untracked-files=all"), "source checkout must be clean")
    config_path = root / "tunaos.toml"
    document = tunaos_config.load(config_path)
    text = config_path.read_text(encoding="utf-8")

    bases = {}
    pinned_text = text
    for cell in cells:
        base = document["variants"][cell["variant"]]["base_image"]
        if not PINNED.search(base):
            base = resolve_digest(base)
            pinned_text = pin_base_image(pinned_text, cell["variant"], base)
        bases[cell["route"]] = base

    if pinned_text != text:
        config_path.write_text(pinned_text, encoding="utf-8")
        stock = commit(root, "qualification stock: pin mutable base images")
    else:
        stock = git(root, "rev-parse", "HEAD")

    modified_text = pinned_text
    for cell in cells:
        modified_text = add_package(modified_text, cell["variant"], cell["package"])
    config_path.write_text(modified_text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/config.py", "generate-image-packages"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    need(result.returncode == 0, f"generate-image-packages: {result.stderr.strip()}")
    modified = commit(root, "qualification modified: one package addition per variant")
    need(stock != modified, "qualification commits did not diverge")

    selected = next(cell for cell in cells if cell["route"] == route)
    variant = selected["variant"]

    def ref(role_tag: str) -> str:
        return f"localhost/{variant}:{role_tag}"

    images = {
        "stockBase": {"ref": ref("stock-base"), "flavor": "base"},
        "modifiedBase": {"ref": ref("modified-base"), "flavor": "base"},
        "modifiedDesktop": {"ref": ref(f"modified-{selected['desktop']}"), "flavor": selected["desktop"]},
    }
    # is_ci=1 is the exact CI build path. The overlay chains on a LOCAL parent, and
    # buildah's --pull-always (IS_CI=1) would ask registry "localhost" for it, so
    # that one build takes the local path (is_ci=0, explicit chain image).
    builds = [
        {"role": "stockBase", "commit": stock, "flavor": "base", "tag": "stock-base", "isCi": "1", "chain": ""},
        {"role": "modifiedBase", "commit": modified, "flavor": "base", "tag": "modified-base", "isCi": "1", "chain": ""},
        {"role": "modifiedDesktop", "commit": modified, "flavor": selected["desktop"],
         "tag": f"modified-{selected['desktop']}", "isCi": "1", "chain": ""},
    ]
    if selected["overlay"]:
        overlay_tag = f"modified-{selected['overlay']}"
        images["modifiedOverlay"] = {"ref": ref(overlay_tag), "flavor": selected["overlay"]}
        builds.append({
            "role": "modifiedOverlay", "commit": modified, "flavor": selected["overlay"],
            "tag": overlay_tag, "isCi": "0", "chain": images["modifiedDesktop"]["ref"],
        })
    for build in builds:
        build["variant"] = variant

    plan = {
        "schemaVersion": 1,
        "platform": PLATFORM,
        "stockCommit": stock,
        "modifiedCommit": modified,
        "cells": [
            {
                "route": cell["route"], "variant": cell["variant"], "package": cell["package"],
                "baseImage": bases[cell["route"]],
                "images": images if cell["route"] == route else None,
            }
            for cell in cells
        ],
    }
    HARNESS.validate_plan(plan)
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"route": route, "platform": PLATFORM, "stockCommit": stock, "modifiedCommit": modified, "builds": builds}


def gate(report_path: Path, route: str) -> str:
    """Require `route` to have passed with every other route recorded as not-run."""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PrepareError(f"{report_path}: unreadable report: {exc}") from exc
    routes = {item.get("route"): item for item in report.get("routes", [])}
    need(set(routes) == set(HARNESS.ROUTES), f"{report_path}: report does not name every route")
    chosen = routes[route]
    need(
        chosen.get("status") == "passed",
        f"{route}: {chosen.get('status')}: {chosen.get('reason')}",
    )
    others = {name: item.get("status") for name, item in routes.items() if name != route}
    need(
        all(status == "not-run" for status in others.values()),
        f"{route}: other routes were not left not-run: {others}",
    )
    return f"{route}: passed ({len(chosen['images'])} immutable image records)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--route", required=True)
    prep.add_argument("--plan", required=True, type=Path)
    prep.add_argument("--source", type=Path, default=ROOT)
    prep.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    check = sub.add_parser("gate")
    check.add_argument("--route", required=True)
    check.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.source.resolve(), load_cells(args.fixture), args.route, args.plan)
            print(json.dumps(result, sort_keys=True))
        else:
            print(gate(args.report, args.route))
    except (PrepareError, tunaos_config.ConfigError, OSError) as exc:
        print(f"ERROR: package qualification: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
