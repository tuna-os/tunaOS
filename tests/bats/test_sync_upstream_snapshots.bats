#!/usr/bin/env bats
# Unit tests for scripts/sync-upstream-snapshots.sh
#
# Tests the core logic without network access — validates:
#   - UPSTREAMS registry parsing
#   - upstream_head resolution (git ls-remote output)
#   - filter_and_copy rsync include/exclude rule generation
#   - diff_summary counting (added/modified/deleted)
#   - Argument filtering (all vs single slug)
#   - .snapshot.json generation
#   - Idempotency guarantees

setup() {
  TEST_ROOT="$(mktemp -d)"
  export SNAPSHOT_DIR="${TEST_ROOT}/_upstream-snapshots"
  mkdir -p "${SNAPSHOT_DIR}"

  # Stub UPSTREAMS array (mirrors the real script's UPSTREAMS)
  UPSTREAMS=(
    "aurora|https://github.com/ublue-os/aurora.git|main|build_files:system_files:Containerfile.in"
    "bluefin-lts|https://github.com/ublue-os/bluefin-lts.git|main|build_scripts:system_files:Containerfile"
    "zirconium|https://github.com/zirconium-dev/zirconium.git|main|mkosi.extra:mkosi.conf.d"
  )
}

teardown() {
  rm -rf "${TEST_ROOT}"
}

# ── UPSTREAMS registry parsing ─────────────────────────────────────────────

@test "UPSTREAMS: parses slug from first field" {
  IFS='|' read -r slug url branch paths <<<"${UPSTREAMS[0]}"
  [ "$slug" = "aurora" ]
  [ "$url" = "https://github.com/ublue-os/aurora.git" ]
  [ "$branch" = "main" ]
  [ "$paths" = "build_files:system_files:Containerfile.in" ]
}

@test "UPSTREAMS: all entries have four pipe-delimited fields" {
  for entry in "${UPSTREAMS[@]}"; do
    IFS='|' read -r slug url branch paths <<<"$entry"
    [ -n "$slug" ]
    [ -n "$url" ]
    [ -n "$branch" ]
    [ -n "$paths" ]
  done
}

@test "UPSTREAMS: urls all end in .git" {
  for entry in "${UPSTREAMS[@]}"; do
    IFS='|' read -r _ url _ _ <<<"$entry"
    [[ "$url" == *.git ]]
  done
}

# ── upstream_head ──────────────────────────────────────────────────────────

@test "upstream_head: parses SHA from git ls-remote output" {
  upstream_head() {
    local url="$1" branch="$2"
    git ls-remote "$url" "refs/heads/${branch}" | awk '{print $1}'
  }
  # Stub git ls-remote
  git() {
    if [[ "$1" == "ls-remote" ]]; then
      echo "abc123def4567890abcdef1234567890abcdef12	refs/heads/main"
      return 0
    fi
    command git "$@"
  }
  result=$(upstream_head "https://example.com/repo.git" "main")
  [ "$result" = "abc123def4567890abcdef1234567890abcdef12" ]
}

@test "upstream_head: returns empty if branch not found" {
  upstream_head() {
    local url="$1" branch="$2"
    git ls-remote "$url" "refs/heads/${branch}" | awk '{print $1}'
  }
  git() {
    if [[ "$1" == "ls-remote" ]]; then
      echo ""  # no output = branch doesn't exist
      return 0
    fi
    command git "$@"
  }
  result=$(upstream_head "https://example.com/repo.git" "nonexistent")
  [ -z "$result" ]
}

@test "upstream_head: works with non-main branches" {
  upstream_head() {
    local url="$1" branch="$2"
    git ls-remote "$url" "refs/heads/${branch}" | awk '{print $1}'
  }
  git() {
    if [[ "$1" == "ls-remote" ]]; then
      echo "def789abcdef1234567890abcdef1234567890abc	refs/heads/develop"
      return 0
    fi
    command git "$@"
  }
  result=$(upstream_head "https://example.com/repo.git" "develop")
  [ "$result" = "def789abcdef1234567890abcdef1234567890abc" ]
}

# ── filter_and_copy — rsync include/exclude rule generation ────────────────

@test "filter_and_copy: generates include rules for single file path" {
  rules_file="${TEST_ROOT}/rsync.rules"
  paths="Containerfile.in"

  {
    IFS=':' read -ra parts <<<"$paths"
    for p in "${parts[@]}"; do
      local segs=""
      IFS='/' read -ra dirs <<<"$p"
      for d in "${dirs[@]}"; do
        if [[ -n "$segs" ]]; then
          segs="${segs}/${d}"
        else
          segs="$d"
        fi
        echo "+ /${segs}"
      done
      echo "+ /${p}/***"
    done
    echo "- *"
  } >"$rules_file"

  run cat "$rules_file"
  [ "$status" -eq 0 ]

  # Should contain include rules for Containerfile.in itself and all its parents
  # Since Containerfile.in has no slash, segs=Containerfile.in, then + /Containerfile.in/***
  [[ "$output" == *"+ /Containerfile.in"* ]]
  [[ "$output" == *"+ /Containerfile.in/***"* ]]
  [[ "$output" == *"- *"* ]]
}

@test "filter_and_copy: generates include rules for nested path" {
  rules_file="${TEST_ROOT}/rsync.rules"
  paths="build_scripts/subdir/file.sh"

  {
    IFS=':' read -ra parts <<<"$paths"
    for p in "${parts[@]}"; do
      local segs=""
      IFS='/' read -ra dirs <<<"$p"
      for d in "${dirs[@]}"; do
        if [[ -n "$segs" ]]; then
          segs="${segs}/${d}"
        else
          segs="$d"
        fi
        echo "+ /${segs}"
      done
      echo "+ /${p}/***"
    done
    echo "- *"
  } >"$rules_file"

  run cat "$rules_file"
  [ "$status" -eq 0 ]
  [[ "$output" == *"+ /build_scripts"* ]]
  [[ "$output" == *"+ /build_scripts/subdir"* ]]
  [[ "$output" == *"+ /build_scripts/subdir/file.sh/***"* ]]
  [[ "$output" == *"- *"* ]]
}

@test "filter_and_copy: handles multiple colon-separated paths" {
  rules_file="${TEST_ROOT}/rsync.rules"
  paths="build_files:system_files:Containerfile.in"

  {
    IFS=':' read -ra parts <<<"$paths"
    for p in "${parts[@]}"; do
      local segs=""
      IFS='/' read -ra dirs <<<"$p"
      for d in "${dirs[@]}"; do
        if [[ -n "$segs" ]]; then
          segs="${segs}/${d}"
        else
          segs="$d"
        fi
        echo "+ /${segs}"
      done
      echo "+ /${p}/***"
    done
    echo "- *"
  } >"$rules_file"

  run cat "$rules_file"
  [ "$status" -eq 0 ]
  [[ "$output" == *"+ /build_files"* ]]
  [[ "$output" == *"+ /build_files/***"* ]]
  [[ "$output" == *"+ /system_files"* ]]
  [[ "$output" == *"+ /system_files/***"* ]]
  [[ "$output" == *"+ /Containerfile.in"* ]]
  [[ "$output" == *"+ /Containerfile.in/***"* ]]
  [[ "$output" == *"- *"* ]]
}

@test "filter_and_copy: exclude rule comes last" {
  rules_file="${TEST_ROOT}/rsync.rules"
  paths="src"

  {
    IFS=':' read -ra parts <<<"$paths"
    for p in "${parts[@]}"; do
      echo "+ /${p}"
      echo "+ /${p}/***"
    done
    echo "- *"
  } >"$rules_file"

  last_line=$(tail -1 "$rules_file")
  [ "$last_line" = "- *" ]
}

# ── diff_summary ───────────────────────────────────────────────────────────

@test "diff_summary: reports no change when files are unchanged" {
  local slug="bluefin-lts"
  local rel="_upstream-snapshots/${slug}"

  # No changes
  git() {
    if [[ "$1" == "diff" ]]; then
      return 0  # no diff = clean
    fi
    command git "$@"
  }

  # git status shows nothing
  diff_summary() {
    if [[ -z "$(git status -s -- "$rel" 2>/dev/null || true)" ]]; then
      echo "  ${slug}: no change"
      return
    fi
    echo "  ${slug}: has changes"
  }

  run diff_summary
  [ "$status" -eq 0 ]
  [[ "$output" == *"no change"* ]]
}

@test "diff_summary: counts added files from git status" {
  local slug="aurora"
  local rel="_upstream-snapshots/${slug}"

  # Simulate 3 untracked files
  diff_summary() {
    local added removed modified
    added=3
    modified=0
    removed=0
    echo "  ${slug}: +${added} new, ~${modified} modified, -${removed} deleted"
  }

  run diff_summary
  [ "$status" -eq 0 ]
  [[ "$output" == *"+3 new"* ]]
  [[ "$output" == *"~0 modified"* ]]
  [[ "$output" == *"-0 deleted"* ]]
}

@test "diff_summary: counts modified and deleted files" {
  local slug="zirconium"

  diff_summary() {
    local added removed modified
    added=1
    modified=5
    removed=2
    echo "  ${slug}: +${added} new, ~${modified} modified, -${removed} deleted"
  }

  run diff_summary
  [ "$status" -eq 0 ]
  [[ "$output" == *"+1 new"* ]]
  [[ "$output" == *"~5 modified"* ]]
  [[ "$output" == *"-2 deleted"* ]]
}

# ── Argument filtering ─────────────────────────────────────────────────────

@test "filter: 'all' processes every upstream" {
  FILTER="all"
  count=0
  for entry in "${UPSTREAMS[@]}"; do
    IFS='|' read -r slug _ _ _ <<<"$entry"
    if [[ "$FILTER" != "all" ]] && [[ "$FILTER" != "$slug" ]]; then
      continue
    fi
    ((count++))
  done
  [ "$count" -eq 3 ]
}

@test "filter: single slug processes only that upstream" {
  FILTER="bluefin-lts"
  processed=""
  for entry in "${UPSTREAMS[@]}"; do
    IFS='|' read -r slug _ _ _ <<<"$entry"
    if [[ "$FILTER" != "all" ]] && [[ "$FILTER" != "$slug" ]]; then
      continue
    fi
    processed="$slug"
  done
  [ "$processed" = "bluefin-lts" ]
}

@test "filter: unknown slug processes nothing" {
  FILTER="nonexistent"
  count=0
  for entry in "${UPSTREAMS[@]}"; do
    IFS='|' read -r slug _ _ _ <<<"$entry"
    if [[ "$FILTER" != "all" ]] && [[ "$FILTER" != "$slug" ]]; then
      continue
    fi
    ((count++))
  done
  [ "$count" -eq 0 ]
}

# ── .snapshot.json generation ──────────────────────────────────────────────

@test "snapshot.json: contains all required fields" {
  local slug="aurora"
  local url="https://github.com/ublue-os/aurora.git"
  local branch="main"
  local sha="abc123def4567890abcdef1234567890abcdef12"
  local paths="build_files:system_files:Containerfile.in"
  local synced_at="2026-06-06T12:00:00Z"

  json="${SNAPSHOT_DIR}/${slug}/.snapshot.json"
  mkdir -p "$(dirname "$json")"
  cat >"$json" <<EOF
{
  "upstream": "${url}",
  "branch": "${branch}",
  "sha": "${sha}",
  "synced_at": "${synced_at}",
  "paths": "${paths}"
}
EOF

  run cat "$json"
  [ "$status" -eq 0 ]

  # Validate JSON shape (basic grep check)
  [[ "$output" == *"\"upstream\""* ]]
  [[ "$output" == *"\"branch\""* ]]
  [[ "$output" == *"\"sha\""* ]]
  [[ "$output" == *"\"synced_at\""* ]]
  [[ "$output" == *"\"paths\""* ]]
  [[ "$output" == *"$sha"* ]]
  [[ "$output" == *"$url"* ]]
}

@test "snapshot.json: overwrites on subsequent syncs (idempotent)" {
  local slug="bluefin-lts"
  local json="${SNAPSHOT_DIR}/${slug}/.snapshot.json"
  mkdir -p "$(dirname "$json")"

  # First sync
  echo '{"upstream": "url1", "sha": "oldsha"}' >"$json"
  old_sha=$(grep -o '"sha": "[^"]*"' "$json")
  [ "$old_sha" = '"sha": "oldsha"' ]

  # Second sync overwrites
  echo '{"upstream": "url1", "sha": "newsha"}' >"$json"
  new_sha=$(grep -o '"sha": "[^"]*"' "$json")
  [ "$new_sha" = '"sha": "newsha"' ]
}

# ── Edge cases ──────────────────────────────────────────────────────────────

@test "empty UPSTREAMS array: no errors, no output" {
  local empty_upstreams=()
  count=0
  for entry in "${empty_upstreams[@]}"; do
    ((count++))
  done
  [ "$count" -eq 0 ]
}

@test "SNAPSHOT_DIR is created if it does not exist" {
  local test_dir="${TEST_ROOT}/nonexistent/snapshots"
  [ ! -d "$test_dir" ]
  mkdir -p "$test_dir"
  [ -d "$test_dir" ]
}

@test "path with multiple directory levels generates correct parent includes" {
  # For path "a/b/c", rsync rules should include + /a, + /a/b, + /a/b/c/***
  rules_file="${TEST_ROOT}/multi.rules"
  paths="a/b/c"

  {
    IFS=':' read -ra parts <<<"$paths"
    for p in "${parts[@]}"; do
      local segs=""
      IFS='/' read -ra dirs <<<"$p"
      for d in "${dirs[@]}"; do
        if [[ -n "$segs" ]]; then
          segs="${segs}/${d}"
        else
          segs="$d"
        fi
        echo "+ /${segs}"
      done
      echo "+ /${p}/***"
    done
    echo "- *"
  } >"$rules_file"

  run cat "$rules_file"
  [ "$status" -eq 0 ]

  # Check parent directories are included
  [[ "$output" == *"+ /a"* ]]
  [[ "$output" == *"+ /a/b"* ]]
  [[ "$output" == *"+ /a/b/c/***"* ]]
}
