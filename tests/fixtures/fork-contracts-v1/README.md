# Fork contract fixtures v1

`cases.json` is the machine-readable index for the shared TunaOS integration
contracts. It records the owner, contract version, consumer, compatibility
policy and known gaps for each boundary.

The inputs are intentionally small and synthetic:

- `intent/` exercises RFC 013 YAML resolution and inherited intent precedence.
- `branding/` exercises the generated manifest consumed before branding writes.
- `packages/` exercises v1 package receipts, optional misses and unavailable
  source failure.
- `frontend/capabilities.json` declares the backend and explicit unsupported
  operations for each installer frontend.
- `../iso-media-provenance-v2/` remains the authoritative RFC 014 v2 evidence
  fixture family; this index references its digest/platform rejection vectors
  instead of copying them.
- `normalized/` contains deterministic expected outputs for accepted inputs.

Every invalid case names its expected rejection text. Every accepted case has a
normalized expected output. These fixtures do not claim package availability,
image publication, boot, login, installation, frontend rendering or release
qualification.

The TunaOS adapter suite is:

```sh
python3 -m pytest -q tests/test_fork_contract_fixtures.py
```

Do not edit a fixture or schema without updating `cases.json`, the expected
output/rejection, the integration test, and [`docs/FORK-CONTRACTS.md`](../../../docs/FORK-CONTRACTS.md).
External frontend changes belong in their own repositories and must link the
fixture version and checks they consume.
