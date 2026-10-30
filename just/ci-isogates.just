# --- CI recipes called from workflows: isogates ---
# Each recipe is a workflow step moved out of YAML so it can be run and tested locally.
# Recipe names are prefixed ci- (just imports share one flat namespace).

# Run the installer walkthrough on the freshly built ISO and fail loudly on a missing report, missing OCR or zero detected screens (reads VARIANT, FLAVOR); root-owned output is chowned back even when the walkthrough fails
ci-installer-walkthrough:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}

    # `|| true`: under pipefail a second match could SIGPIPE `find`; the old
    # step (no pipefail) took the first line regardless.
    ISO=$(find . -maxdepth 1 -name "${VARIANT}-${FLAVOR}-*.iso" | head -1 || true)
    if [[ -z "$ISO" ]]; then
        echo "::error::No ISO found for ${VARIANT}-${FLAVOR}"
        exit 1
    fi
    # FLAVOR must be set AND must survive sudo (-E), or run-walkthrough.sh
    # falls back to FLAVOR=de and both matrix legs write the same
    # walkthrough-de.json — a parity report that names neither frontend
    # it came from.
    # `|| true` so a walkthrough failure still reaches the chown below.
    # run-walkthrough.sh runs as root, so everything it writes —
    # serial.log included — is root-owned; without the chown the
    # if: always() debug upload dies with EACCES and destroys the one
    # piece of evidence a failed run produces. Run 31168173594 did
    # exactly that: the walkthrough failed, `set -e` skipped the chown,
    # and the serial log could not be uploaded.
    rc=0
    sudo -E FLAVOR="${FLAVOR}" \
        bash {{ justfile_directory() }}/scripts/run-walkthrough.sh "$ISO" walkthrough-out || rc=$?
    sudo chown -R "${USER:-$(id -un)}:$(id -gn)" walkthrough-out || true
    if [[ "$rc" -ne 0 ]]; then
        echo "::error::run-walkthrough.sh exited $rc"
        exit "$rc"
    fi

    # Fail loudly rather than publish a report with the screen rows
    # unfilled. installer-walkthrough.py degrades to "screen detection
    # skipped" when tesseract is missing and still exits 0, so a missing
    # dependency looked exactly like a passing run — which is how this
    # job produced ocr:false reports for months while green.
    json="walkthrough-out/walkthrough-${FLAVOR}.json"
    if [[ ! -f "$json" ]]; then
        echo "::error::$json was not written"
        exit 1
    fi
    if [[ "$(jq -r .ocr "$json")" != "true" ]]; then
        echo "::error::walkthrough ran without OCR — every screen row in"
        echo "::error::this report is unfilled. tesseract-ocr missing?"
        exit 1
    fi
    jq -r '.screens | to_entries[] | "  \(.key): \(.value)"' "$json"

    # ocr:true only proves tesseract RAN. It says nothing about whether
    # anything was recognised, and on run 31171184497 that gap was the
    # whole story: the step went green while the harness's own TAP output
    # read
    #
    #   not ok - gnome: screen changes between steps
    #     # 0/10 transitions changed >500px
    #     # 1 distinct visual state(s) across 11 frames
    #   # Results: 2 passed, 7 failed, 9 total
    #   # screens reached: (none detected)
    #
    # and every screen row came back false. installer-walkthrough.py
    # reports those failures and exits 0 unless --strict is passed, so
    # the assertion above — mine — was a gate that could not fire on the
    # only question the job exists to answer.
    #
    # A run that detected NO screen at all has not produced a parity
    # report; it has produced an empty one, which is worse, because the
    # matrix cannot tell "we looked and found nothing" from "we never
    # looked". Blank frames on the GPU-less runner are a known and
    # expected limitation for cosmic/niri/xfwl4 — but the correct
    # response to a limitation is to say so out loud, not to publish a
    # green tick over six false rows.
    reached=$(jq -r '[.screens[] | select(. == true)] | length' "$json")
    total=$(jq -r '.screens | length' "$json")
    echo "screens detected: ${reached}/${total}"
    if [[ "$reached" -eq 0 ]]; then
        echo "::error::the walkthrough detected NONE of the ${total} spec'd"
        echo "::error::screens. The installer UI was never reached, so this"
        echo "::error::report would fill the parity matrix with six false"
        echo "::error::rows. See the DIAGNOSIS line above and the captured"
        echo "::error::PNGs in the installer-shots-${FLAVOR} artifact."
        exit 1
    fi

# Copy walkthrough-out/*.png into staged/ under CAPTURE_PREFIX and fail when none were captured (reads CAPTURE_PREFIX, default empty)
ci-installer-stage-captures:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ justfile_directory() }}

    mkdir -p staged
    count=0
    for png in walkthrough-out/*.png; do
        [[ -f "$png" ]] || continue
        cp "$png" "staged/${CAPTURE_PREFIX:-}$(basename "$png")"
        count=$((count + 1))
    done
    echo "Captured ${count} screenshots"
    if [[ "$count" -lt 6 ]]; then
        echo "::warning::expected 6 walkthrough screenshots, got ${count} — flow may have drifted (see serial.log artifact)"
    fi
    if [[ "$count" -eq 0 ]]; then
        echo "::error::no screenshots captured"
        exit 1
    fi
