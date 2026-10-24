# Distribution readiness

Use this checklist for Q4 releases under
[#3222](https://github.com/tuna-os/tunaos/issues/3222). Each project keeps
its release workflow and roadmap. Record channel evidence in
[the shared checklist](https://github.com/tuna-os/tunaos/issues/3828).
This document defines checks for acceptance;
it is not a list of channels that work today.

## Before a release

- [ ] Name the release tag, source commit, release owner, and advertised
  channels. Include the project's root `ROADMAP.md` and release gate issues.
- [ ] For each channel, record the package identifier, target OS and CPU,
  destination, verifier, and expected version. Mark each channel as required
  or deferred, with a reason and a follow-up issue for each deferral.
- [ ] Link credential requests, signature decisions, and brand permissions.
  Each request needs a maintainer owner, a target date, and an evidence check.
- [ ] Confirm that documentation only calls a channel available after an
  installation check passes. Label source builds and unsigned previews as such.

Use this evidence record for each release and channel:

```text
Project / tag / source commit:
Channel / package identifier / OS / CPU:
Required or deferred (reason and follow-up issue):
Release owner / verifier / target date:
Credential or decision issue:
Publish run / destination manifest or asset URL:
Observed version / checksum / signature result:
Clean-machine install command / result / evidence URL:
Result: pending | available | partial | deferred
Next action / owner / target date:
```

An unchecked or unknown result stays `pending`. An upstream submission is not
an available package. A successful build or release job is not evidence that
all channels received the release.

## Channel acceptance checks

| Channel | Evidence required before advertising availability |
|---|---|
| bluefin-cli Homebrew | Link the publish run and the tap's `Formula/bluefin-cli.rb` commit. Confirm its version and checksums match the release. On a clean supported host, install from that tap and check `bluefin-cli --version`. |
| iso-builder native writer | Link a tagged release, packages for each declared OS and CPU, checksums, and build provenance. Download, verify, install, and launch each package on a clean supported host. Record signature and macOS notarization results against the approved signing decision. |
| wootc generic winget | Link the accepted `microsoft/winget-pkgs` PR for `TunaOS.wootc`. After index propagation, install on a clean Windows host and verify the version and publisher. Check the downloaded executable against the release checksum and the release's signature requirements. |
| wootc branded installers | Link the mark owner's recorded permission and agreed winget identifier in `app/branding/<brand>/blessing.json`. Verify the release matrix follows that decision and that the executable has the approved identity. Each advertised branded channel needs its own installation evidence. |

Check other advertised channels, including Scoop, separately. A missing
Homebrew credential does not prove that direct-download RPM or DEB assets
are missing, and a direct-download asset does not prove that Homebrew works.

Use qualified source links to check the blockers in #3222:

- [bluefin-cli#295](https://github.com/tuna-os/bluefin-cli/issues/295)
  tracks the Homebrew credential. Check the publisher and skip conditions in
  [`.goreleaser.yaml`](https://github.com/tuna-os/bluefin-cli/blob/main/.goreleaser.yaml).
- [iso-builder#250](https://github.com/tuna-os/iso-builder/issues/250)
  tracks native packages and release automation. iso-builder#229 concerns
  token permissions in workflows. The signature decision named in #3222 is
  [wootc#229](https://github.com/tuna-os/wootc/issues/229).
- [wootc#221](https://github.com/tuna-os/wootc/issues/221) defines the first
  winget installation check; [wootc#241](https://github.com/tuna-os/wootc/issues/241)
  defines signature and fresh-machine checks. Verify brand permission from
  the source records linked by [wootc#227](https://github.com/tuna-os/wootc/issues/227),
  even after that issue closes. Issue closure alone is not brand permission.
- [remora#56](https://github.com/tuna-os/remora/issues/56) concerns runtime
  package-manager support. Record that evidence separately from application
  publication through a package manager.

## Credential handoff

Follow [the contributor credential checklist](../CONTRIBUTING.md#distribution-credentials).
When a credential, signature decision, or brand permission is missing, link
the request in the shared tracker and name the maintainer action. Contributors
can prepare packages and checks while they wait for that action. Keep the
affected channel `pending` or `deferred` until its acceptance checks pass.

## After a release: publish audit

For Q1 2027, use the evidence record above as the input contract for a
publish audit in each producer repository. Track implementation in the
shared checklist. This document does not install an automated gate.

The audit must compare the declared channels with the destination's observed
version, manifest, checksums, and signature evidence. Include the tag, source
commit, run URL, observation time, and install-test evidence in its report.
Run it after publication and on a schedule to check index propagation again.
Bound retries and record the deadline.

A skipped publisher, missing package, wrong version, or expired retry window
must make a required channel partial and fail the audit. An API error must
remain an error; it must not become success or a deferral. Report deferred
channels with their reason and follow-up issue. Keep the report as a workflow
artifact and link it from the release. Generate any shared status view from
these reports; do not maintain a copied status table in this document.
