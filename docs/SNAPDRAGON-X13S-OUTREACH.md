# Snapdragon community outreach proposal

Issues: [#3221](https://github.com/tuna-os/tunaOS/issues/3221), after
[#1374](https://github.com/tuna-os/tunaOS/issues/1374).
This is a proposal for maintainer review, not a record of external contact or
an established partnership.

## Technical starting point

Use [SNAPDRAGON.md](SNAPDRAGON.md) for the Copilot-PC answer, NPU references
and test-report fields. The old draft used Bonito/Dakota X13s guides that are now in the archive.
Those pages do not establish a usable TunaOS path.
[X13s qualification #3368](https://github.com/tuna-os/tunaOS/issues/3368)
needs actual TunaOS boot, installation, update and rollback evidence.
Do not publish the old draft as a release announcement.

The ThinkPad X13s uses 8cx Gen 3 / SC8280XP, not Snapdragon X Elite.
Keep any test invitation tied to the exact device and image. Linux results
from another distribution are useful inputs, not TunaOS qualification.

## Proposed collaboration

1. Publish the bounded answer to Discussion #93, tracked in
   [#2947](https://github.com/tuna-os/tunaOS/issues/2947), before you recruit
   new hardware testers. The prepared reply is in SNAPDRAGON.md.
2. Have the maintainer choose a public identity and approve contact under
   #3221. Ask Qualcomm/postmarketOS device maintainers whether
   a test request with a narrow scope is welcome and where it belongs.
3. Propose an exchange of reproducible boot/firmware results for each model.
   Link upstream fixes back to #3368. Invite owners who already have
   hardware; do not encourage purchases based on unqualified support claims.
4. Use the report fields in SNAPDRAGON.md and link public results into the
   qualification issue, including failures and untested functions. Publish
   progress only when a report supplies evidence for the specific claim.
5. Consider cross-promotion after useful joint results and explicit agreement
   from both projects. A message or test report does not establish a partnership or justify an adopter entry.

Asahi Linux develops support for Apple Silicon Macs. Any future exchange with
that project should concern experience with bootc or reports. Its hardware matrix does not qualify devices with Snapdragon.

## Publication checklist

- [ ] Discussion #93 has a linked public reply.
- [ ] #3221 records the approved channel, identity and final text.
- [ ] The publisher has checked the community's current rules for posts.
- [ ] The invitation has evidence for each device and lists open qualification gaps.
- [ ] Record contact URLs and test reports after they exist.

The reply count and hardware-report goals in #3116 are outcomes to measure
from public threads, not numbers to fill in before engagement happens.
