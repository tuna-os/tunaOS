#!/usr/bin/env python3
"""Build the workflow matrix and pull_request payloads for fork-simulation.yml."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

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
    actor_parser = subparsers.add_parser("actor")
    actor_parser.add_argument("persona", choices=PERSONAS)
    event_parser = subparsers.add_parser("event")
    event_parser.add_argument("persona", choices=PERSONAS)
    event_parser.add_argument("--repository", required=True)
    event_parser.add_argument("--head-sha", required=True)
    event_parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()

    if args.command == "matrix":
        print(json.dumps({"workflow": pull_request_workflows()}, separators=(",", ":")))
    elif args.command == "actor":
        print(PERSONAS[args.persona]["actor"])
    else:
        print(json.dumps(event(args.persona, args.repository, args.head_sha, args.base_sha)))


if __name__ == "__main__":
    main()
