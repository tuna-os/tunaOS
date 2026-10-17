#!/usr/bin/env python3
"""Build the scoped workflow matrix and fork pull-request event payloads.

The scope is deliberately explicit.  Running the image/ISO workflows under
``act`` would rebuild or boot multi-gigabyte images three times every week;
PR #2604 measured that design and was closed for that reason.  Every PR
workflow must therefore be classified here.  Workflows whose fork-sensitive
write paths can run cheaply belong in SIMULATED; heavyweight or read-only
lanes need a recorded reason in EXCLUDED.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# These are the workflows with write/secret paths that can be exercised under
# act without building an image.  The classification test makes additions to
# the repository's pull_request workflow set fail closed until reviewed.
SIMULATED = (
    "drop-bot-review-requests.yml",
    "just-fix.yml",
    "matrix-status.yml",
    "pr-nudges.yml",
)

EXCLUDED = {
    "arm64-ulimit-probe.yml": "mutates two hosted runner architectures; no secret or write path",
    "check-download-checksums.yml": "read-only download verification; no secret or write path",
    "corral-boot-gate.yml": "boots two multi-gigabyte published images under KVM",
    "installer-fisherman-pins.yml": "read-only cross-repository check; no secret or write path",
    "iso-e2e.yml": "builds or boots a live ISO under privileged KVM",
    "lint.yml": "read-only lint lane; no secret or write path",
    "live-iso-bootc.yml": "builds a multi-gigabyte live ISO",
    "ste.yml": "read-only reusable prose workflow; no secret or write path",
    "test.yml": "read-only test lane; OIDC is covered by the static fork-safety test",
    "validate-renovate.yaml": "read-only configuration validation; no secret or write path",
}

PERSONAS = {
    "first-time-external": {
        "actor": "fork-simulation-newcomer",
        "association": "FIRST_TIME_CONTRIBUTOR",
        "actor_type": "User",
        "same_repo": False,
    },
    "same-repo-contributor": {
        "actor": "fork-simulation-contributor",
        "association": "MEMBER",
        "actor_type": "User",
        "same_repo": True,
    },
    "renovate": {
        "actor": "renovate[bot]",
        "association": "CONTRIBUTOR",
        "actor_type": "Bot",
        "same_repo": True,
    },
}


def triggers(document: dict) -> dict:
    value = document.get("on", document.get(True, {}))
    if isinstance(value, str):
        return {value: None}
    if isinstance(value, list):
        return dict.fromkeys(value)
    return value or {}


def pull_request_workflows() -> list[str]:
    result = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if "pull_request" in triggers(document):
            result.append(path.name)
    return result


def matrix() -> list[dict[str, str]]:
    return [
        {"workflow": workflow, "persona": persona}
        for workflow in SIMULATED
        for persona in PERSONAS
    ]


def event(persona: str, repository: str, head_sha: str, base_sha: str) -> dict:
    profile = PERSONAS[persona]
    owner, _ = repository.split("/", 1)
    head_repo = repository if profile["same_repo"] else f"{profile['actor']}/tunaos"
    branch = f"fork-simulation/{persona}"
    user = {"login": profile["actor"], "type": profile["actor_type"]}
    return {
        "action": "opened",
        "number": 1,
        "repository": {
            "full_name": repository,
            "default_branch": "main",
            "owner": {"login": owner},
        },
        "sender": user,
        "pull_request": {
            "number": 1,
            "draft": False,
            "author_association": profile["association"],
            "user": user,
            "head": {
                "label": f"{profile['actor']}:{branch}",
                "ref": branch,
                "sha": head_sha,
                "repo": {
                    "fork": not profile["same_repo"],
                    "full_name": head_repo,
                },
            },
            "base": {
                "label": f"{owner}:main",
                "ref": "main",
                "sha": base_sha,
                "repo": {"fork": False, "full_name": repository},
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("matrix")
    subparsers.add_parser("classifications")
    actor_parser = subparsers.add_parser("actor")
    actor_parser.add_argument("persona", choices=PERSONAS)
    event_parser = subparsers.add_parser("event")
    event_parser.add_argument("persona", choices=PERSONAS)
    event_parser.add_argument("--repository", required=True)
    event_parser.add_argument("--head-sha", required=True)
    event_parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()

    if args.command == "matrix":
        print(json.dumps({"include": matrix()}, separators=(",", ":")))
    elif args.command == "classifications":
        print(json.dumps({"simulated": SIMULATED, "excluded": EXCLUDED}, sort_keys=True))
    elif args.command == "actor":
        print(PERSONAS[args.persona]["actor"])
    else:
        print(json.dumps(event(args.persona, args.repository, args.head_sha, args.base_sha)))


if __name__ == "__main__":
    main()
