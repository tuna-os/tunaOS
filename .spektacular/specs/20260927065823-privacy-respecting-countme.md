---
created_date: "2026-09-27"
document_status: draft
---

# Feature: Privacy-respecting TunaOS countme

Status: Draft proposal. Procedural workflow review by the agent under AGENTS.md; maintainer RFC sign-off and participation default remain pending.

## Overview

TunaOS will offer privacy-respecting adoption measurements across its official installed images. Maintainers and the public can see weekly reporting trends and broad installation-age cohorts without accounts or individual identifiers. Counts describe participating installations, with gaps and uncertainty shown explicitly.

## Requirements

- [ ] **All official images**
  Installed systems participate across every supported variant, desktop, driver/kernel flavor and architecture, without depending on an RPM package manager.
- [ ] **Limited reports**
  The system submits at most one attempted report per UTC week, without retry after an ambiguous response, and sends only variant, full image flavor, architecture and a broad age bucket. Age ranges are first week, weeks 2–4, weeks 5–24 and week 25 onward, measured from first eligible observation. Offline systems can try later in the week if they have not attempted a report.
- [ ] **No individual identity**
  The system does not transmit machine IDs, derived machine IDs, random device tokens, usernames, hostnames, precise install times or hardware inventory.
- [ ] **Public metrics**
  Everyone can read historical weekly reporting totals and privacy-safe category trends without logging in.
- [ ] **Persistent choice**
  Users can disable reporting before its first request; disabling survives upgrades and image switches.
- [ ] **Honest coverage**
  The dashboard distinguishes completed weeks, incomplete weeks, suppressed small groups and unavailable data. Counts of 1–9 are suppressed; if any category is in that range, the whole dimension is withheld to prevent subtraction. Published counts are rounded down to multiples of 10.
- [ ] **Installed-system scope**
  Live media, image builds, containers and CI boot tests do not contribute to adoption metrics.
- [ ] **No operational dependency**
  Collector failures do not block boots, logins, updates or installation.

## Constraints

- Cross-cutting image changes must follow RFC-PROCESS.md, including maintainer sign-off before rollout.
- A Cloudflare-hosted collector cannot promise that the provider never processes source IPs; serving network requests requires that processing.

## Acceptance Criteria

- [ ] **Image coverage**
  Reporting and user controls work on every supported installed image.
- [ ] **Report privacy**
  Captured payloads contain only the approved categories and age bucket; no client-supplied personal or persistent identifier appears in payloads, application storage or public output. Provider transport processing is disclosed separately.
- [ ] **Weekly scheduling**
  Week-boundary, offline, concurrent-run and ambiguous-response scenarios produce no more than one attempted report per week under the specified retry policy.
- [ ] **Persistent choice**
  Disabling reporting prevents requests, including after upgrades and image switches.
- [ ] **Public disclosure**
  Everyone can access closed-week aggregates, without events or precise report times; small-group suppression applies to every public view and export, including subtraction scenarios.
- [ ] **Excluded modes**
  Live-media and CI boot scenarios submit no reports.
- [ ] **Failure isolation**
  Failed networking leaves normal boot, login, installation and update operation intact.
- [ ] **Storage privacy**
  Inspection of application storage and configured application logs reveals aggregate counters without report records or client-supplied identifiers.

## Technical Approach

- Cloudflare Workers and D1 implement the collector with independent aggregate margins and frozen public snapshots.
- Research compares identifier-free Dakota direct reporting and Bluefin LTS repository countme; the client follows the direct reporting model across package managers.
- The user selected enabled by default with persistent opt-out on 2026-09-27.

## Success Metrics

- Weekly publication latency: public metrics appear within 24 hours after a collection week closes.
- Freshness: every published week states its observation window and collection health; a missing week is never silently shown as zero.
- Public value: maintainers and contributors can compare weekly reporting trends and available category shares from the same public data.

## Non-Goals

- Exact unique users, daily/monthly unique counts and individual retention.
- Location, application usage or session duration metrics.
- Registry pulls as a proxy for installed adoption.
- Cloud deployment or production telemetry enablement as part of this draft.



## Implementation scope accepted 2026-09-27

The user requested full implementation and testing, including a public adoption dashboard in tuna-os/docs. Participation is enabled by default with a persistent opt-out. The domain owner was identified; Cloudflare authentication and production deployment remain pending. The site must distinguish suppressed and missing data, expose the same privacy-filtered snapshots to maintainers and visitors, and show weekly reports as estimates rather than unique users.
