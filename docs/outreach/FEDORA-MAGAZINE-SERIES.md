# Desktop Linux at Scale — Fedora Magazine series proposal

Tracks [#3114](https://github.com/tuna-os/tunaos/issues/3114).
This is a proposal for author and editor review. No author has submitted it.
After acceptance, the author must produce four articles, code runs, and
screenshots. Editors have confirmed no publication slot or byline.

## Submission route

The issue names `magazine@fedoraproject.org`. A different address appears in
the older [single-post pitch](../FEDORA-MAGAZINE-PITCH.md).
Use Fedora's published process. Confirm the mailbox before use.

In the official [Magazine category](https://discussion.fedoraproject.org/c/workflows/magazine/57),
authors can propose ideas with the `fm-proposed` tag.
[How to propose an article](https://discussion.fedoraproject.org/t/how-to-propose-an-article/29729)
also asks authors to set up access for their account first.
The preparation check of these sources took place on 2026-10-23.

An authorized project author must submit the proposal with their own account
and agreed byline. Follow the
[outreach ownership rule](../AGENT_GUIDE.md#community--outreach-initiatives-687).
If editors request email, confirm the address with them in that thread.
Record one submission and follow up there; avoid duplicate pitches.

## Proposal text

<!-- ste-disable: Fedora Magazine pitch uses the editors' audience and editorial vocabulary -->
**Subject / topic: Series proposal — Desktop Linux at Scale (four monthly parts)**

Hello Fedora Magazine editors,

Could a four-part practical series, **Desktop Linux at Scale**, fit the Magazine?
It would help Fedora users explore how bootc changes desktop deployment, from
a disposable test VM to repeatable image builds and contributor workflows.
“Scale” describes the deployment method; we would not claim a proven fleet
size or present an unverified production case study.

We propose using Bonito, the Fedora-based variant of the open-source TunaOS
image factory, as a worked example. Each article would explain a transferable
Fedora concept, show reproducible commands and screenshots, and state the
limitations of the exact image tested. Bonito would be identified as Beta,
without implying Fedora endorsement or replacing Fedora's own desktop guidance.

The proposed sequence is:

1. **November 2026 — Why bootc-based desktops matter:** image identity,
   staged updates, rollback boundaries, and a small VM experiment.
2. **December 2026 — One pipeline, several desktops:** how GNOME, KDE,
   COSMIC, and Niri choices affect image builds and desktop verification.
3. **January 2027 — From Fedora experiments to enterprise requirements:**
   evaluate the Redfin RHEL 10 local-build path, with clear boundaries around
   credentials, redistribution, and responsibility for support.
4. **February 2027 — Make a Fedora integration contribution:** reproduce
   a focused issue, change a desktop definition, validate it, and submit a PR.

Each article would stay at or below 1,500 words and include code examples,
captioned screenshots, prerequisites, and an explicit reader outcome. We can
adapt length and cadence to your preferences. The dates are requests, subject
to your approval and author capacity. We would prepare the first two drafts
before the first publication to help sustain the series.

The enterprise installment would focus on lessons useful to Fedora readers,
rather than a product or sales pitch. Would that scope fit the Magazine?
The final installment would also teach a Fedora user to reproduce a desktop
problem; please advise whether the contributor workflow belongs in the
Magazine or should link to a Community Blog follow-up.

Each installment would invite technical feedback and link to Matrix and the
self-service adopter reporting process. We would welcome Fedora Design SIG
feedback on screenshots and desktop experience, without claiming a partnership.

Thank you for considering the series.

[Authorized author's name and preferred byline — fill before submission]
<!-- ste-enable -->

## Article briefs and acceptance checks

The word budgets include captions and the call to action. Each totals 1,400
words, with 100 words left for editor changes. Code below describes planned
examples. It is not evidence of an image build or a guest test.

### Part 1 — Why bootc-based desktops matter

- **Reader outcome:** explain image identity and distinguish an OS rollback
  from recovery of user data.
- **Budget:** introduction 150; model 300; VM walkthrough 600;
  limitations 250; call to action 100.
- **Example:** in a disposable, installed Bonito VM, capture `bootc status`
  before and after a staged update. Run update and rollback steps only after
  the author tests a recovery path. Explain reboot boundaries and
  which data persists. Start with [USER-GUIDE.md](../USER-GUIDE.md).
- **Screenshots:** the tested desktop with image identity in a terminal;
  status before and after the update. Captions identify the digest and run.
- **Review:** attach command output and reboot results for that VM. Explain
  that rollback does not restore documents, secrets, or every configuration.

### Part 2 — Multi-desktop strategy

- **Reader outcome:** trace desktop selection through configuration.
  Explain why tests for GNOME do not validate KDE, COSMIC, or Niri.
- **Budget:** use case 150; desktop definitions 350; example 550;
  comparison and limits 250; call to action 100.
- **Example:** on a source checkout, inspect the configured Bonito flavors:

  ```bash
  python3 scripts/config.py show
  ./scripts/resolve-flavor.sh bonito gnome
  ./scripts/resolve-flavor.sh bonito kde
  ./scripts/resolve-flavor.sh bonito cosmic
  ./scripts/resolve-flavor.sh bonito niri
  ```

- **Screenshots:** one capture per tested desktop on the same architecture.
  Show session identity. Do not use a GNOME capture as proof for another flavor.
- **Review:** explain separate images and desktop contracts. Do not promise
  that a session stays valid after users add desktop packages or switch images.
  Link the generated [matrix](../MATRIX-STATUS.md) for results.

### Part 3 — Enterprise path: Redfin

- **Reader outcome:** list the evidence and operational responsibilities
  needed before a Fedora experiment becomes an enterprise evaluation.
- **Budget:** Fedora connection 200; responsibilities 350; local-build
  walkthrough 450; evidence and limits 300; call to action 100.
- **Example:** review [rhel-setup.md](../rhel-setup.md) and the
  [local factory example](../../examples/redfin-image-factory/).
  After the author arranges their own build prerequisites, demonstrate
  `just build redfin gnome` and inspect the local image from that build.
- **Screenshots:** a local build result and guest image identity. Remove
  account names, registry credentials, and private infrastructure details.
- **Review:** Redfin is local-build only under repository policy. Offer no
  public Redfin image or ISO. Refer subscription and redistribution questions
  to Red Hat's terms and the reader's organization. Do not infer
  Red Hat support for the customized desktop, certification, compliance, or
  an existing customer fleet. An authorized owner must review these claims.
  Ask editors about the enterprise scope before work on this draft starts.

### Part 4 — Contributor guide and Fedora integration

- **Reader outcome:** reproduce a desktop problem and submit a focused fix
  through the project's fork workflow.
- **Budget:** reader problem 150; source map 300; contribution example 600;
  validation and review 250; call to action 100.
- **Example:** use the [contributor guide](../../CONTRIBUTING.md) to set up the host.
  Run `python3 scripts/config.py validate`, then `just fix` and `just check`.
  Walk through a reviewed diff of a desktop definition and its relevant test.
  Show a signed-off commit and fork PR; choose an unclaimed issue at draft time.
- **Screenshots:** the small diff, relevant check output, and the PR with
  its issue link. Label sample output as sample until the run exists.
- **Review:** distinguish host build tools from packages inside an image.
  Follow the [package policy](../../PACKAGE-SOURCING.md) to explain Fedora
  integration. Do not imply that a TunaOS PR is an accepted Fedora change.

## Shared call to action

<!-- ste-disable: reusable article closing copy addresses Fedora Magazine readers -->
Have a desktop test result or a reproducible problem to share?
[Join us on Matrix](https://matrix.to/#/%23tunaos:reilly.asia).
If you evaluate or use TunaOS, follow the
[ADOPTERS.md self-service process](https://github.com/tuna-os/tunaos/blob/main/ADOPTERS.md)
to submit a consent-reviewed report. Evaluation reports are welcome; no
production deployment is required.
<!-- ste-enable -->

## Production and handoff

1. The maintainer names an author and technical reviewer. The author fills
   the byline, confirms capacity, and reviews the proposal before submission.
2. Check [tunaos.toml](../../tunaos.toml) for the configured base and flavors.
   The preparation checkout (`ce903ef9`) selects `fedora-bootc:44` for Bonito
   and defines GNOME, KDE, COSMIC, and Niri. Configuration does not prove
   image readiness or Fedora 45 support.
3. Apply the [claim checklist](../CONTENT-CLAIM-CHECKLIST.md) and
   [Fedora readiness brief](../FEDORA-OUTREACH-READINESS.md) to each demo.
   Attach the exact digest, architecture, source commit, commands, output,
   and fresh lint, boot, desktop, and install evidence. Stop a recommendation
   when evidence fails or is absent. Keep Beta language until promotion.
4. Capture real screenshots from those runs. Use the
   [gallery](../SCREENSHOTS.md) only when its capture matches the article.
   Add alt text, captions, provenance, and permission for each asset.
   Send assets through the editors' requested workflow.
5. Submit one proposal through the route above. Record the date, author,
   public thread, and response in #3114 and the
   [outreach ledger](../ADOPTION-OUTREACH-STATUS.md). Coordinate with #1137
   so the older single-post pitch does not compete with this series.
6. After acceptance, agree article scope and dates with editors. Complete
   and review the first two drafts before publication starts. If November
   is unavailable, record the revised schedule; do not backdate a submission.
7. Follow up once in the submission thread after two weeks without a reply.
   Record a decline or no response. Keep #3114 open through the external
   submission and publication work.

## Measure outcomes

Use [ADOPTION-METRICS.md](../../ADOPTION-METRICS.md) for monthly reports.
The targets below come from #3114; they are goals, not measured results.
Record evidence in the issue and monthly snapshot. Keep live results there.

| Goal | Evidence and counting rule |
| --- | --- |
| Four articles with a Fedora Magazine byline | Record each published URL, date, author, and part number. Acceptance alone does not count. |
| At least 20 community discussion posts | Link article comments and related public threads. Count substantive reader posts; exclude author replies, bots, and duplicates. Report the count 30 days after each part. |
| At least two Fedora Design SIG members interested | Link explicit public expressions of interest and public affiliation evidence, with consent before naming people. A request for feedback is not a collaboration. |
| At least five new stars from the Fedora community | Record aggregate star change from submission to 30 days after the final part. Attribute only voluntary public reports to Fedora; stars have no reliable per-user referral source. Report attribution as unavailable when it cannot be established. |

Do not infer adoption from reads, comments, stars, or affiliation. Do not
repeat the issue's publication-frequency or readership estimates as facts.
