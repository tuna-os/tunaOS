# ADR 0011: Private adoption metrics

- Status: Accepted by the task owner for publication on 2026-09-27.
- Owner: `hanthor`.
- RFC: [012](../rfc/rfc012-private-adoption-metrics.md).
- Tracker: [#2775](https://github.com/tuna-os/tunaOS/issues/2775).

## Context

Registry pulls include CI, mirrors and updates. They cannot count installations. Official TunaOS images use several package managers, so upstream counts do not cover each family.

## Decision

Ship one Python client and systemd timer across the official matrix. Enable reports by default with a persistent opt-out. Send variant, full flavor, architecture and age bucket once per UTC week, with no device identifier. Flush the marker for each try before the request and do not retry a lost response.

Use a dedicated Cloudflare Worker and D1 database for independent aggregate counters. Freeze closed weeks; round down to tens and suppress small groups. Publish the same values as JSON, CSV and a public dashboard. Use a service binding from the site to the collector. Disable logs of requests, Tail consumers and preview surfaces for the collector.

## Consequences and evidence

These counts estimate weekly reports, not unique people or retention. Systems that stay offline and requests that fail cause undercounts. Anyone can forge an anonymous report. Cloudflare must process the IP address of each source, and database recovery history can reveal category tuples through differences. The public notice states these limits and history retention of up to 30 days.

The user gave approval for default participation, Cloudflare deployment and source publication. Live health and JSON checks passed. The live browser had no page errors or axe violations. Tests cover 200 client/image/CI cases, 10 D1 cases and integration with the site in native workerd. A built RPM artifact has the correct identity, timer, inherited masks and container exclusion.

Full-family installed boot, ARM and upgrade/switch pilot checks remain unmeasured. The API returned HTTP 403 for logs at account level. The agent did not verify privacy and spend controls at account level. The accepted-report cap is not an infrastructure spend limit. User opt-out and the collector switch remain available.
