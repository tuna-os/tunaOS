# One-cell OCI RPM diagnostic

This manual workflow is opt-in. It tests only the reviewed DNF4 consumer and native solver.
It uses the existing GNOME 50 EL10 x86_64 candidate.
It does **not** build or boot a desktop, retire endpoints or change production pins.
It does not qualify other architectures or package families.

Its receipts are diagnostic-only. Never accept them as production release evidence.

## Exact cell and trust

`scripts/diagnostics/rpm_rehearsal.json` records the verified candidate digest and
its **candidate-workflow** signer. It also records the producer commit, tool checksum,
native public-key checksum, ORAS 1.3.4 and Cosign checksums.
It pins the current base for Skipjack (CentOS Stream 10) by immutable reference.
The diagnostic uses no unpublished input or sibling worktree.

The read-only `plan` command checks the configured base and hash of the full EL10 policy.
It derives the 28 required package names and adds `gnome50-el10-compat`.
Drift in policy needs review; it never silently changes the diagnostic.

Official dependencies come only from explicit CentOS Stream 10 x86_64 paths:
BaseOS, AppStream and CRB at `mirror.stream.centos.org`.
Preparation verified their detached repomd signatures with the official SHA256 key.
**Every run must verify them again.** Both `gpgcheck=1` and `repo_gpgcheck=1` remain mandatory.
Before DNF, the helper verifies packages from the factory and repomd against isolated reviewed keys.
The base's bootstrap trust and installed software remain trusted inputs.
This work does not protect against a compromised kernel, Docker daemon or base image.

## Boundary and required live preflight

The local environment has not run a network preflight.
The tests run offline and check paths through code, not Docker routes or native DNF behavior.
The first approved run can fail closed on an absent prerequisite, new upstream
redirect, signature, dependency conflict or unavailable tool.

Requirements:

- A clean reviewed checkout and Docker **28+** on local Linux, in rootful mode.
- A linux/amd64 runner and at least 16 GiB of free scratch space.
- A base with `/usr/bin/python3` and DNF4; the runtime checks must fail otherwise.
- No daemon socket, credentials, private keys or write token in either container.
- A 120-minute job limit, with tighter subprocess timeouts.
- Workload limits of 5 GiB RAM and two CPUs.
- Proxy limits of 128 MiB RAM and half a CPU.

The runner creates only disposable resources with unique names:

* An IPv4 `--internal` bridge with `gateway_mode_ipv4=isolated`.
  The runner inspects it before use. Ordinary internal bridges are insufficient:
  host bridge services can remain reachable. The runner does not change host firewall rules.
* The workload has only that bridge. It has no external DNS or NET_ADMIN / NET_RAW.
  It has no host PID/IPC/network or published ports.
  Inputs are read-only; an output bind mount holds receipts.
  Only the proxy also joins a separate egress bridge.
  It is nonroot and read-only, with cap-drop ALL, no-new-privileges and no host ports.
* The CONNECT proxy has bounds. It admits only exact hosts over HTTPS from `rpm_proxy.py`.
  All IPv4 DNS answers must be public unicast addresses.
  Connections use the validated address directly.
  The proxy denies hosts that it does not know, credentials, alternate ports, numeric IP targets and unknown headers.
  TLS remains end-to-end.
* Before **any** DNF transaction, controlled R2 aliases must receive explicit 403 responses.
  Official CentOS/GHCR CONNECTs must succeed.
  Direct socket connections to the **same public IPs that the proxy reached in the positive control** must fail.
  Numeric IP CONNECTs must receive 403 responses.
  Official HTTPS metadata must be reachable.
  Generic network failure does not count as a successful negative control.

The runner acquires inputs before this native-network boundary.
Downloads of pinned sources, keys and tools need exact allowlists for HTTPS hosts on every redirect. They also need byte checksums.
The runner trusts Docker's immutable base pull as prefetch. This is not evidence of denied R2 egress.

No static scan proves the absence of third-party storage behind an allowed public service.
This qualification covers only direct egress from the native workload to controlled R2 hosts.
It makes no claim about service providers' internal infrastructure.

## Native scope and evidence

The disposable workload archives and removes its stock repository configuration.
It installs only bootstrap Python/GnuPG prerequisites from signed official repos.
It invokes the reviewed helper with factory priority 1 and all 29 requests.
It records each control result as it happens, including failed errno values and elapsed times.
It also records input hashes, Docker inspections, network counters, baseline/final
package inventories, native logs, the consumer receipt and proxy connection/byte counters.

Cleanup tries every named resource independently, even after errors.
The runner records errors and fails the run. A receipt can pass only after cleanup succeeds.
The workflow uploads only seven-day `diagnostic-only-*` artifacts. It does not push an image.

This diagnostic does **not** exercise the full image's three before-operations or eight groups.
It omits options for group solvers (`--nobest --allowerasing`), exclusions, the libselinux
ceiling and kernel versionlocks. It also omits EPEL/negativo17 setup and other build pipeline operations.
The plan retains the complete excluded policy.
Full real-pipeline build parity, a final audit of image repositories and boot tests remain separate required gates.
GNOME 50 transport validation is not GNOME 51 acceptance.

## Proposed authorization (not yet executed)

1. Review and publish this diagnostic-only change without production configuration edits.
   Run the focused offline tests and normal repository checks.
2. Separately authorize **one** manual `diagnostic-oci-rpm-consumer` run at that reviewed commit.
   Use `acknowledge_scope=true`, read-only permissions, no private keys and a maximum of 120 minutes.
   Do not relax trust or network controls for a retry.
   Inspect failures and request review of necessary changes.
3. Accept only a completed native result, all mandatory controls, complete receipts and successful resource cleanup.
   This allows a plan for later full-image qualification.
   It does not authorize a production switch or endpoint retirement.

Local read-only preview:

```sh
python3 scripts/diagnostics/run_rpm_rehearsal.py plan
pytest -q tests/test_oci_rpm_consumer.py tests/test_rpm_diagnostic.py
```
