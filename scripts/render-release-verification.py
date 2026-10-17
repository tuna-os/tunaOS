#!/usr/bin/env python3
"""Render the public release-verification block from matrix provenance JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BEGIN = "<!-- release-verification:start -->"
END = "<!-- release-verification:end -->"


def axis_tally(cells: dict, axis: str) -> tuple[int, int, int]:
    verdicts = [axes[axis]["verdict"] for axes in cells.values() if axis in axes]
    return (
        sum(verdict == "pass" for verdict in verdicts),
        sum(verdict != "untested" for verdict in verdicts),
        len(verdicts),
    )


def fraction(cells: dict, axis: str) -> str:
    passed, tested, total = axis_tally(cells, axis)
    return f"{passed}/{total} pass ({tested}/{total} tested)"



def stored_image_identity(body: str) -> tuple[str, str]:
    """Recover the immutable image identity generated into a release card."""
    matches = set(
        re.findall(
            r"(ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+)@(sha256:[0-9a-f]{64})",
            body,
        )
    )
    if len(matches) != 1:
        raise ValueError("release body does not contain one immutable image identity")
    return matches.pop()

def render(payload: dict, image: str, digest: str, sbom_packages: int) -> str:
    summary = payload["summary"]
    cells = payload["cells"]
    health = summary["factory_health"]
    regressions = summary["known_regressions"]
    built, _, built_total = axis_tally(cells, "builds")

    digest_text = f"`{digest}`" if digest else "not reported"
    sbom_text = (
        f"✅ SPDX inventory contains {sbom_packages} packages"
        if sbom_packages > 0
        else "❌ no usable SPDX inventory was supplied"
    )
    return "\n".join(
        [
            BEGIN,
            "## TunaOS Release Verification",
            "",
            "Generated from the same [matrix provenance](https://github.com/tuna-os/tunaOS/blob/main/docs/matrix-provenance.json) as the public factory-health summary.",
            "",
            "### Images",
            f"- Built and promoted: **{built}/{built_total}** cells",
            f"- Signed: **{built}/{built_total}** promoted cells (promotion requires the keyless signing job)",
            f"- SBOM: {sbom_text}",
            "",
            "### Runtime",
            f"- Booted: **{fraction(cells, 'boots')}**",
            f"- Desktop contract: **{fraction(cells, 'desktop')}**",
            f"- Installer and encrypted-disk path: **{fraction(cells, 'install')}**",
            "",
            "### Lifecycle",
            f"- Update, rebase, and rollback: **{fraction(cells, 'lifecycle')}**",
            "",
            "### Supply chain",
            f"- Image: `{image}`",
            f"- Digest: {digest_text}",
            "- Promotion requires an immutable manifest and a verified keyless signature; the SPDX inventory is attached to this release.",
            "",
            "### Regressions",
            f"- **{regressions['blocking']} blocking**, **{regressions['advisory']} advisory** failing cell/criterion assertions",
            f"- **{summary['never_tested']}** applicable assertions have no current test evidence",
            f"- Factory health: **{health['green']}/{health['total']}** composite-green cells",
            f"- Last full install/lifecycle sweep represented: **{summary['last_full_sweep'] or 'unknown'}**",
            END,
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provenance", type=Path, default=Path("docs/matrix-provenance.json"))
    parser.add_argument("--image")
    parser.add_argument("--stored-identity", type=Path)
    parser.add_argument("--sbom-packages", type=int, default=0)
    parser.add_argument("--body", type=Path, help="existing release body to update")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.stored_identity:
        try:
            repository, digest = stored_image_identity(args.stored_identity.read_text())
        except ValueError as exc:
            parser.error(str(exc))
        print(repository)
        print(digest)
        return 0
    if not args.image:
        parser.error("--image is required unless --stored-identity is used")

    payload = json.loads(args.provenance.read_text())
    if not payload.get("summary") or not payload.get("cells"):
        parser.error(f"{args.provenance} has no generated summary/cells payload")
    report = render(payload, args.image, args.digest, args.sbom_packages) + "\n"
    if args.body:
        body = args.body.read_text().rstrip()
        old_block = re.compile(
            rf"\n*{re.escape(BEGIN)}.*?{re.escape(END)}\n*", re.DOTALL
        )
        body = old_block.sub("\n", body).rstrip()
        report = f"{body}\n\n{report}" if body else report
    if args.output:
        args.output.write_text(report)
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
