# Shared fork contracts

Issue: [#3475](https://github.com/tuna-os/tunaOS/issues/3475)

TunaOS owns integration at these boundaries. The fixture family under
[`tests/fixtures/fork-contracts-v1/`](../tests/fixtures/fork-contracts-v1/)
defines the offline compatibility boundary. It is not a second distro
catalog, a package resolver, a backend service, or image qualification.

## Inventory

| Boundary | Owner and version | Consumer | Compatibility policy | Current gap |
|---|---|---|---|---|
| Fork intent: target selection, branding delta and package intent | [RFC 013](rfc/rfc013-single-fork-config.md), `scripts/resolve-fork-config.py`, v1 YAML | `scripts/prepare-fork-config.py`; generated manifest consumers | Closed schema. Unknown fields, duplicate keys, stale source pins, unknown selectors, old/new versions and inherited package conflicts reject. | Safe removals, family-specific non-RPM repository trust, parent/overlay closure and native evidence remain out of v1. |
| Branding input and image destination | `docs/FORK-BRANDING.md`, `build_scripts/lib/fork-branding.sh`, generated manifest v1 JSON | `90-image-info.sh` plus both desktop runtime paths | Exact generated keys. Cell, package manager, platform, source receipt, image registry and namespace must match before mutation. The destination is a local preview coordinate; it does not authorize publication. | Name/logo, embedded installer/Plymouth assets and produced-image proof are not part of the preview. The preview does not claim an image digest. |
| Package intent and transaction receipt | `build_scripts/lib/fork-packages.sh`, generated receipt v1 JSON | The package adapter's repeat-application guard and downstream image checks | A completed receipt binds the exact manifest digest and package manager. Required failures produce no completed receipt; optional misses are recorded. Reapplication is idempotent only for the same receipt. | A wrapper receipt is not solver-level dependency/removal proof or a claim that a package is available on another family. |
| Image identity and destination evidence | RFC 013 `image`/cell fields, with immutable source/platform identity in [RFC 014](rfc/rfc014-iso-media-provenance.md) v2 | Fork preparation and ISO provenance consumers | Registry/namespace and canonical variant/flavor/platform are checked separately. OCI source digest, platform and CPU baseline are typed fields in provenance v2; a tag or self-claim cannot replace them. | No production fork publisher or trusted image-digest collector is wired here. |
| Installer input/evidence | [RFC 014](rfc/rfc014-iso-media-provenance.md), `schemas/iso-media-provenance-v2.schema.json`, v2 Python checker | `scripts/iso_media_provenance.py` and the read-only artifact adapter | v2 is strict and role-typed. v1 is diagnostic-only. Expected producer and artifact context is supplied independently; mismatched digest, platform, frontend, builder or media bytes reject. | A valid synthetic document is not authenticated evidence. Trusted collection, real matching browser/native media, offline install and target-only reboot remain separate gates. |
| Frontend/backend capability declaration | TunaOS integration fixture v1, `frontend/capabilities.json`, `scripts/installer-capabilities.py` | Installer parity review and integration tests; external frontend repositories must consume the same version | Every frontend names one backend, supported operations and explicit unsupported operations. `require_capability` fails on an unsupported or undeclared operation; it never selects another backend. | The five external frontend repositories still need synchronized declarations and fixture-version/check links. This PR does not change frontend behavior. |

### RFC 013 and #3431 reconciliation

The open [#3431](https://github.com/tuna-os/tunaOS/pull/3431) stack contains
broader catalog, workflow and qualification integration. Do not import it as
a second source of truth. This repository consumes the landed RFC 013 fork
intent/consumer contracts and the landed RFC 014 provenance contract. A future
catalog or trusted-collector integration must preserve those owners, pass this
fixture family and avoid another catalog.

## Fixture contract

`tests/fixtures/fork-contracts-v1/cases.json` indexes every case and records
its owner, version, consumer, compatibility policy and gap. The cases cover:

- inherited global and variant package and brand overrides with deterministic
  normalized intent;
- unknown fields, unsupported versions and inherited package conflicts;
- strict brand input and image-platform mismatch rejection;
- a package receipt with an optional miss, plus failure for an unavailable
  offline source before a completed receipt;
- RFC 014 checks image digests and platform values; and
- explicit capabilities for GNOME/bootc-installer and fisherman frontends.

The fixtures are synthetic. They are not package availability, boot, login,
installer, native-install or release evidence.

Run the integration suite with:

```sh
python3 -m pytest -q tests/test_fork_contract_fixtures.py
```

Schema or fixture changes need updates to `cases.json`, its expected
normalized/rejection values and this inventory in one change. A frontend
repository change must link its synchronized fixture version and checks here.
Screenshots from [#3347](https://github.com/tuna-os/tunaOS/pull/3347) are visual
evidence only; they do not prove behavioral conformance.
