#!/usr/bin/env bats
# The retracted "first external contributor" claim stays retracted (tunaOS#1633).
#
# The project publicly stated in August 2026 that @shimonenator was its first
# external human contributor. It is not a person: every commit from that account
# across the org carries `commit.author.name: antigravity` — a Google
# Antigravity agent. The maintainer retracted the claim from ROADMAP.md, the Q3
# checkpoint, and the published blog post (tuna-os/docs#252) rather than
# deleting it, on the stated reasoning that "correcting that publicly matters
# more to us than the metric would have".
#
# It then came back. PR #1607, a draft, added a COMMUNITY.md section thanking
# "Shimon" by name as the first external human contributor to return, and
# rewrote ADOPTION-METRICS.md's baseline from "0 external contributors" to "1
# repeat external contributor; 5 merged contributions". Nothing failed — a
# retraction in three documents does not stop a fourth from re-asserting the
# claim.
#
# So: an assertion, not a memory. The name may appear in a retraction — that is
# the point of retracting rather than deleting — but not as recognition, and
# never in the metrics baseline.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

# Files that make public claims about who contributes.
claim_files() {
  local f
  for f in "${REPO_ROOT}/COMMUNITY.md" "${REPO_ROOT}/ADOPTION-METRICS.md" \
           "${REPO_ROOT}/ROADMAP.md" "${REPO_ROOT}/ADOPTERS.md"; do
    [ -f "$f" ] && echo "$f"
  done
}

@test "there are claim files to check (guards a vacuous pass)" {
  run bash -c "$(declare -f claim_files); REPO_ROOT='$REPO_ROOT'; claim_files | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -ge 3 ]
}

@test "nothing thanks the account as a person" {
  # The specific shape that was published: a first-name thank-you.
  local f bad=0
  while read -r f; do
    if grep -qiE 'thank you,? shimon' "$f"; then
      echo "RETRACTED CLAIM: $(basename "$f") thanks the account as a person" >&2
      bad=$((bad + 1))
    fi
  done < <(claim_files)
  [ "$bad" -eq 0 ]
}

@test "nothing calls the account an external human contributor" {
  local f bad=0
  while read -r f; do
    # Allow it inside a retraction — those sentences say the claim WAS made.
    if grep -iE 'first external \*?human\*? contributor' "$f" | grep -qivE 'retract|withdraw|correct|was not|not a person|misidentif'; then
      echo "RETRACTED CLAIM: $(basename "$f") asserts external human contributor" >&2
      bad=$((bad + 1))
    fi
  done < <(claim_files)
  [ "$bad" -eq 0 ]
}

@test "the external-contributor baseline is not inflated by the agent account" {
  # ADOPTION-METRICS' baseline is the number outreach quotes. #1607 would have
  # set it to 1 on the strength of an agent's commits.
  local row
  row="$(grep -E '^\| Community \|.*external contributors' "${REPO_ROOT}/ADOPTION-METRICS.md" | head -1)"
  [ -n "$row" ]
  local baseline
  baseline="$(echo "$row" | awk -F'|' '{print $5}')"
  [[ "$baseline" == *"0 external contributors"* ]]
}

@test "if the name appears at all, it appears as a correction" {
  # Retraction-not-deletion is the project's chosen approach, so a mention is
  # fine — provided the surrounding text says what it is.
  local f
  while read -r f; do
    grep -qi 'shimonenator' "$f" || continue
    if ! grep -qiE 'retract|withdraw|correct|agent, not a person|antigravity' "$f"; then
      echo "UNQUALIFIED MENTION: $(basename "$f") names the account with no correction context" >&2
      return 1
    fi
  done < <(claim_files)
}
