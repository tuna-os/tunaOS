---
created_date: "2026-10-29"
document_status: final
closed_date: "2026-10-29"
---

# Manual obligations for the Mesa #3969 source candidate

Status: **NOT EXECUTED. NO RUNTIME APPROVAL.** This artifact describes later hosted execution and human review. It does not authorize a merge, variable creation, dispatch, key, package/image build or guest. Source CI is not an experiment result. Keep #3969, #3380 and #3668 acceptance separate.

The plan classifies Metric1 (source safety) and Metric2 (no automatic runtime) as automated/source verification. Their cases remain in CI; this document does not repeat them. The procedures below cover only Metric3 and the two explicit manual reviews. All boxes remain unchecked until an authorized person records the actual receipts.

## Review A — owner approval of the exact runtime head

- [ ] Owner has reviewed and explicitly approved the exact future runtime SHA; not performed by this implementation.

**Who / when:** Repository owner, after source review and separately authorized workflow merge/registration, before the first native run. The workflow must exist on the default branch before GitHub accepts its manual dispatch. Permission to prepare source, a green source PR, or approval of an earlier branch SHA is not runtime authority.

1. Review draft PR4058 and the final source diff. Read `.github/workflows/mesa-3969-compare.yml`, `tests/manual/mesa-3969-build.sh`, `tests/manual/mesa-3969-guest.sh` and the three `mesa_3969*.py` modules. Confirm the fixed inputs and one-attempt resource policy below.
2. Obtain separate permission to merge/register the workflow. After registration, choose the actual dispatch ref. The commands here use `main`; record its full40-character SHA with this read-only command:

   ```bash
   gh api repos/tuna-os/tunaOS/commits/main --jq .sha
   ```

3. Obtain explicit owner runtime approval of that exact SHA, including the build/key/two-guest cost and absence of production publication. Set `REVIEWED_HEAD` in the operator's shell to the **owner-approved value**, not an automatically accepted current SHA. Record who approved it and the approval URL/time. A merge may change the SHA and requires approval of the actual dispatch head.
4. Inspect prior runs of this exact workflow/head. Any prior attempt, including a failed admission or cancellation, consumes that head. Do not rerun jobs, delete history or reset settings to bypass this boundary. A further experiment requires separately approved new inputs/head.
5. Only after that grant, the owner may create/update the repository variable:

   ```bash
   gh variable set MESA_3969_APPROVED_HEAD --repo tuna-os/tunaOS --body "$REVIEWED_HEAD"
   ```

   This variable authorizes the **build-only** scope. A two-guest comparison additionally needs a separate `MESA_3969_RUNTIME_APPROVED_HEAD` set to the same SHA, only after its own explicit grant; without it `run_scope=compare` is refused at admission and still consumes the head. Do not create an environment, secret or production trust key. These commands have **not** been run by the source implementation.
6. Re-read the chosen ref and confirm it is still the approved SHA immediately before dispatch. If it moved, stop for fresh review. The runtime admission must also bind actual checkout/GitHub/live API identity; a race must refuse before expensive effects.

**Pass condition:** One explicit owner grant names the exact dispatch SHA and scope, the variable matches it, the official workflow/ref matches, and there are zero earlier runs for that workflow/head. A source-only self-approval is not a passing result.

**Reviewed limits:** Preparation runs on a hosted `ubuntu-24.04` runner (the RunsOn `build-amd64` label was starved), in a180-minute job with a9900-second body timeout; hosted runners have 4 vCPU, so build duration is unmeasured. Runtime uses Ubuntu24.04 with KVM,60-minute job and3300-second root body timeout. One VM per arm, sequentially; the unchanged helper retains900-second boot and its original GDM/UI deadlines. Input archive24GiB, unpacked32GiB, safe evidence32MiB and artifact retention one day. These are bounds, not measured resource use.

## Metric3 — later attributable paired report

- [ ] A later authorized hosted run produces the complete control/candidate report; no run has occurred.

**Who / when:** Maintainer, once Review A passes, in GitHub Actions for the comparison. Local builds and tests are permitted for the package pair (`mesa-3969-build.sh local-build`, separate local-only authority); local guests are not. A failure is an observation, not permission to retry.

**How:** Dispatch exactly once using the real workflow inputs:

```bash
gh workflow run mesa-3969-compare.yml --repo tuna-os/tunaOS --ref lab/mesa-3969-source-only-20261029 -f reviewed_head="$REVIEWED_HEAD" -f confirmation=RUN_MESA_3969_ONCE -f run_scope=compare
```

Record the numeric `RUN_ID` from the actual created run in Actions. Do not select an unrelated latest run or artifact by name alone. Inspect its read-only server metadata and wait for that run:

```bash
gh api "repos/tuna-os/tunaOS/actions/runs/$RUN_ID"   --jq '{id,head_sha,event,run_attempt,path,status,conclusion}'
gh run watch "$RUN_ID" --repo tuna-os/tunaOS --exit-status
```

Expected metadata: official repository, exact approved `head_sha`, `workflow_dispatch`, `run_attempt:1`, and `.github/workflows/mesa-3969-compare.yml`. The workflow performs its own live admission before setup and authenticated same-run producer/artifact/digest checks before consumption.

The real build job is **Build signed Mesa pair**. Its input artifact is `mesa3969-inputs-<RUN_ID>-<full head SHA>`; build evidence is `mesa3969-build-evidence-<RUN_ID>`. The runtime job is **Compare two software-rendered guests**. Before the one-day expiry, retain its selected comparison artifact using the exact run:

```bash
gh run download "$RUN_ID" --repo tuna-os/tunaOS   --name "mesa3969-comparison-$RUN_ID" --dir "mesa3969-evidence-$RUN_ID"
```

This is evidence retrieval, not a local native test. Keep the GitHub artifact ID/digest and producer metadata with the receipt. If native tools, source identity, signatures, transport, KVM or real evidence fail, retain the negative report and stop; do not substitute synthetic metadata, cached output or a different source version.

**What to measure / expected pass:**

- Exactly two arm reports, `control/report.json` and `candidate/report.json`, from distinct guest boot IDs, one VM each. The reports must retain real gate exits, observations and failure reasons.
- `control/probe.json` has four ordered cases: `clean`, `software`, `override`, `combined`, with exits `[0,139,139,139]`; clean has status `initialized`. A control GDM failure stays visible and does not substitute for this independent reproduction.
- `candidate/probe.json` has the same four cases and probe hash. Clean must have exit0 and status `initialized`. Each other case must either initialize with exit0, or retain exit3/4 as an explicitly unexercised EGLDevice path. No candidate crash, timeout or other failure may pass. Exit3/4 is **not** successful EGL initialization and cannot support an all-four-paths initialization claim.
- Candidate `gate_exit` equals0. `transitions.login`, `.lock`, `.unlock` and `.same_session` are all true. Review the four real images under `candidate/screenshots/`: `ready.png`, `logged-in.png`, `locked.png`, `unlocked.png`.
- Candidate snapshots in `candidate/report.json` contain actual software-renderer records for both greeter and user. Bind journal/process/boot/UID/start-time/monotonic identity, allowed renderer environment and the actual gate user's Wayland session. Requested flags alone are not evidence. `renderer.json` is supplemental first-snapshot data; inspect all report snapshots for the later user session.
- All snapshots preserve SELinux `Enforcing`, the original software-policy hash and the exact selected RPM header/source closure without unrelated package drift. Control/candidate share the manifest's frozen baseline/buildroot and temporary signer.
- Top-level `comparison.json` has `ok:true`, `verdict:"lab-repair-demonstrated"`, `distinct_arm_boots:true` and zero failures in both `arms`. A missing, failed/cancelled or cleanup-failed result is not a pass. The scope remains **one VM per arm**, not ISO, hardware or epic qualification.

Record actual job duration, artifact sizes, inventories, signer/probe identities and any unexercised path. Do not invent a performance improvement or successful native compatibility result from the declared caps.

## Review B — human interpretation and retained evidence

- [ ] Owner has reviewed the actual native artifacts and accepted only their demonstrated scope; not performed.

**Who / when:** Owner or named reviewer after Metric3 completes, before declaring #3969 repaired or deciding whether any separately held downstream campaign may proceed.

Inspect the exact same-run manifest and selected build/comparison evidence. Check fixed parent/SRPM/patch/helper hashes against `tests/manual/mesa_3969.py` at the approved head. Confirm complete original/candidate package sets, immutable installed RPM headers, isolated native signature checks and the shared frozen root/baseline. Only an ephemeral lab public key may enter these images; no production trust change is allowed.

Review the raw outcomes represented in the sanitized reports and all four visible candidate screenshots. Confirm genuine software rendering for the affected condition and the same real user session through login/lock/unlock. Preserve control failures and unexercised device paths. If control GDM also works, do not claim this comparison proves that Mesa caused every missing-login or unlock symptom; interpret the actual probe regression and candidate UI results separately.

Inspect owned cleanup results and final workflow steps. Require successful cleanup of this run's VM/container/tag/key/work/tooling state without global pruning. Reject publication of private keys, raw SSH state, VM disks or ISOs, and any evidence that exceeds its declared bound. No R2 object or production package/image publication belongs to this experiment.

**Pass condition:** The reviewer records identity agreement, zero candidate crashes, all required real software/UI evidence, preserved policy/trust, successful owned cleanup, and explicit limitations. Record the reviewer, run/artifact links and decision. A successful lab comparison alone supplies **zero** ISO-install, encrypted-unlock, branded lifecycle, eight-image config, production publication or epic-completion credit. Those named acceptance receipts and any further runtime approval remain separate.
