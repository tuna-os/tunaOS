#!/usr/bin/env python3
"""Emit an org-wide starter-task census, including zero-GFI repositories (#3065).

Read-only; requires gh authentication. Redirect stdout to retain a dated JSON receipt.
API failures abort rather than being reported as an empty starter pool.
"""

import datetime
import json
import subprocess


def pages(endpoint):
    result = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", endpoint],
        check=True, capture_output=True, text=True,
    )
    return [item for page in json.loads(result.stdout) for item in page]


def summarize(repo, labels, issues):
    starters = [
        issue for issue in issues
        if "pull_request" not in issue
        and "good first issue" in {label["name"] for label in issue["labels"]}
    ]
    available = [issue for issue in starters if not issue.get("assignees")]
    return {
        "repository": repo["full_name"],
        "archived": repo["archived"],
        "issues_enabled": repo["has_issues"],
        "has_gfi_label": any(label["name"] == "good first issue" for label in labels),
        "open_gfi": len(starters),
        "unassigned_gfi": len(available),
        "paired_unassigned_gfi": sum(
            "help wanted" in {label["name"] for label in issue["labels"]}
            for issue in available
        ),
        "starter_urls": [issue["html_url"] for issue in available],
    }


def main():
    repositories = pages("orgs/tuna-os/repos?type=public&per_page=100")
    rows = []
    for repo in sorted(repositories, key=lambda item: item["full_name"].lower()):
        if repo["archived"] or not repo["has_issues"]:
            rows.append({
                "repository": repo["full_name"], "archived": repo["archived"],
                "issues_enabled": repo["has_issues"], "excluded": True,
            })
            continue
        endpoint = f"repos/{repo['full_name']}"
        labels = pages(f"{endpoint}/labels?per_page=100")
        issues = pages(
            f"{endpoint}/issues?state=open&labels=good%20first%20issue&per_page=100"
        )
        rows.append(summarize(repo, labels, issues))
    print(json.dumps({
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "organization": "tuna-os",
        "repositories": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
