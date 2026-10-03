#!/usr/bin/env bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
REPORT="${REPO_ROOT}/scripts/hacktoberfest-conversion-report.py"

setup() {
  FAKE_BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$FAKE_BIN"
  cat >"${FAKE_BIN}/gh" <<'EOF'
#!/usr/bin/env python3
import json
import sys

query = next(arg[2:] for arg in sys.argv if arg.startswith("q="))
if "merged:<2026-10-01" in query:
    author = query.split("author:", 1)[1].split()[0]
    print(json.dumps({"total_count": 2 if author == "returning-dev" else 0, "items": []}))
    raise SystemExit

items = [
    {
        "repository_url": "https://api.github.com/repos/tuna-os/docs",
        "number": 401,
        "title": "First change",
        "html_url": "https://github.com/tuna-os/docs/pull/401",
        "user": {"login": "new-dev", "type": "User"},
        "author_association": "NONE",
        "pull_request": {"merged_at": "2026-10-02T10:00:00Z"},
    },
    {
        "repository_url": "https://api.github.com/repos/tuna-os/docs",
        "number": 402,
        "title": "Second change",
        "html_url": "https://github.com/tuna-os/docs/pull/402",
        "user": {"login": "new-dev", "type": "User"},
        "author_association": "CONTRIBUTOR",
        "pull_request": {"merged_at": "2026-10-03T10:00:00Z"},
    },
    {
        "repository_url": "https://api.github.com/repos/tuna-os/wootc",
        "number": 80,
        "title": "Returned",
        "html_url": "https://github.com/tuna-os/wootc/pull/80",
        "user": {"login": "returning-dev", "type": "User"},
        "author_association": "CONTRIBUTOR",
        "pull_request": {"merged_at": "2026-10-02T12:00:00Z"},
    },
    {
        "repository_url": "https://api.github.com/repos/tuna-os/tunaos",
        "number": 3000,
        "title": "Maintainer change",
        "user": {"login": "maintainer", "type": "User"},
        "author_association": "MEMBER",
        "pull_request": {"merged_at": "2026-10-02T13:00:00Z"},
    },
    {
        "repository_url": "https://api.github.com/repos/tuna-os/tunaos",
        "number": 3001,
        "title": "Automation",
        "user": {"login": "custom-automation", "type": "Bot"},
        "author_association": "CONTRIBUTOR",
        "pull_request": {"merged_at": "2026-10-02T14:00:00Z"},
    },
]
print(json.dumps({"total_count": len(items), "items": items}))
EOF
  chmod +x "${FAKE_BIN}/gh"
}

@test "report separates new, returning, internal, and bot authors" {
  run env PATH="${FAKE_BIN}:$PATH" "$REPORT"
  [ "$status" -eq 0 ]
  [[ "$output" == *"Merged PRs from new contributors: 2 / 10"* ]]
  [[ "$output" == *"Unique new contributors: 1"* ]]
  [[ "$output" == *"Merged PRs from returning external contributors: 1"* ]]
  [[ "$output" == *"Total external-human merged PRs: 3"* ]]
  [[ "$output" != *"maintainer"* ]]
  [[ "$output" != *"custom-automation"* ]]
}

@test "JSON output is suitable for the monthly metrics snapshot" {
  run env PATH="${FAKE_BIN}:$PATH" "$REPORT" --json --target 12
  [ "$status" -eq 0 ]
  run python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["target_new_contributor_merged_prs"] == 12; assert d["unique_new_contributors"] == 1' <<<"$output"
  [ "$status" -eq 0 ]
}

@test "report rejects an inverted date window" {
  run "$REPORT" --start 2026-10-31 --end 2026-10-01
  [ "$status" -eq 2 ]
  [[ "$output" == *"--start must not be after --end"* ]]
}
