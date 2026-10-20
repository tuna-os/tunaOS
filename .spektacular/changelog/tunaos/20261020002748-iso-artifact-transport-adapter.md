---
created_date: "2026-10-20"
document_status: draft
project: tunaos
spec: 20261020002748-iso-artifact-transport-adapter
plan: 20261020002748-iso-artifact-transport-adapter
---

# Read-only ISO artifact snapshot adapter

TunaOS can check a selected artifact against a reviewed producer run without enabling production qualification. It rejects mismatched metadata, reruns and corrupt archive bytes. Results explicitly remain unauthenticated.

The adapter uses injected read-only transport, exact run and artifact selection, bounded exact-size/hash checks and post-collection revalidation. It has no network client, archive extraction or production caller. Independent verification passed 562 adapter tests and 502 unchanged contract/schema tests.

Deviation: official uploader source established that artifact size describes uploaded archive bytes. Exact length equality and a second artifact check strengthen the initial plan. Browser/native receipt emitters and real installation proof remain separate work.

Derived from project tunaos, spec/plan 20261020002748-iso-artifact-transport-adapter. See the project-level record for the full feature.
