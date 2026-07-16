# Goal: LUKS E2E fisherman migration

## Objective

Migrate `scripts/iso-e2e.sh --luks` from a raw `sudo bootc install to-disk
--block-setup tpm2-luks` to `sudo fisherman recipe.json` — the same install
backend every TunaOS installer frontend uses (GUI installers, upstream
bootc-installer for gnome) — so the LUKS E2E workflow actually tests what
real users get, not a separate, untested code path. Per
`docs/ci-troubleshooting.md`'s "Key takeaway": every raw `bootc install
to-disk` call in this codebase should be replaced with fisherman.

## Finish condition

**A green run of the `LUKS E2E` GitHub Actions workflow** (`gh workflow run
"LUKS E2E" -R tuna-os/tunaos --ref fix/r2-cost-reduction -f variant=<v> -f
flavor=<f>`) — `conclusion: "success"` — for at least one cell per distinct
install backend this branch touches:

- [ ] **ostree/dnf, fisherman `bootcDirect`+network-pull** — one of
      `yellowfin:kde` / `yellowfin:niri` / `yellowfin:cosmic`
- [ ] **gnome installer path** (upstream `org.bootcinstaller.Installer`
      Flatpak, newly embedded this migration) — `yellowfin:gnome` or
      `albacore:gnome`, once the ostree/dnf backend above is confirmed
- [ ] **composefs/apt** — any `grouper:*` flavor, currently blocked (see
      "Explicitly out of scope" below) — stretch goal, not required to
      call this done

Each checked box = a run ID with `conclusion: success`, recorded in
`docs/ci-troubleshooting.md` §4 or this file's Status section below.

## Explicitly out of scope (do not block on these)

- **grouper networking gap (bug #17)**: no DHCP/network-config service
  ever runs in grouper's live squash — blocks SSH for every grouper
  flavor regardless of desktop. Pre-existing, unrelated to fisherman,
  needs its own investigation/fix in a separate branch or follow-up.
- **grouper:xfce lightdm crash-loop (bug #15)** and **grouper:gnome
  missing wayland-session** — pre-existing desktop packaging gaps.
- **Embedded local OCI store**: TunaOS's tacklebox pipeline doesn't embed
  a local image store into the live squash the way
  `projectbluefin/dakota-iso` does. The current network-pull fix works but
  is slower; building a real embedded store is a separate, larger
  tacklebox feature, not required for this migration's finish condition.
- **Plymouth per-variant boot themes**: unrelated side-task picked up
  mid-session. Already done and merged into this branch (`git log --oneline
  --grep=plymouth`) — not part of this goal's finish condition, mentioned
  here only so it isn't mistaken for unfinished work.

## Status (update after every CI round — do not duplicate the bug table)

Full symptom → root cause → fix table lives in `docs/ci-troubleshooting.md`
§4 ("LUKS E2E fisherman rewrite — full bug chain") — **read that before
re-diagnosing anything**. Condensed pointer in memory:
`luks-e2e-fisherman-migration.md` (auto-loaded via `MEMORY.md` in future
sessions).

- **20 bugs found and fixed** as of commit `a8abe68` (most recent: wrapped
  the fisherman install SSH call in `timeout 1800` after a run hung
  silently for 2+ hours — the network pull appears to stall inside the
  QEMU guest's NAT/SLIRP networking; root cause not yet diagnosed).
- **In flight**: run `29505390021` (yellowfin:kde) on commit `a8abe68`,
  dispatched to get real diagnostic output on the stall (timeout fires at
  ~30 min into the install step instead of hanging indefinitely). Check
  `gh run view 29505390021 -R tuna-os/tunaos --json status,conclusion`.
- **No cell has passed yet.** All three finish-condition boxes above are
  unchecked.

## How to continue

Use the `ci-fix-loop` skill (`~/.pi/agent/skills/james/ci-fix-loop/SKILL.md`):
narrow-dispatch the specific cell being tested, wait via `ScheduleWakeup`
(not manual polling), diagnose failures from real `--log-failed` output,
fix, append to `docs/ci-troubleshooting.md` §4, repeat. Don't dispatch the
full matrix — grouper is out of scope per above, and yellowfin's three
desktop flavors (kde/niri/cosmic) all exercise the same install backend, so
one passing is sufficient to check that box.

## Do not

- Re-guess the fisherman image-ref problem (bugs #13/#14/#16/#18/#19 — five
  attempts before landing on "query the live VM directly, network pull via
  the `image` field"). The current approach is correct given TunaOS's
  infra.
- Retry indefinitely against what might be an external outage — `curl` the
  suspect URL directly first (session hit a false-alarm `pkgs.tailscale.com`
  504 that was runner-specific, confirmed by curling it directly).
- Consider this goal met on "no failures yet" while a run is still
  `in_progress`/`queued` — wait for `conclusion: success`.
