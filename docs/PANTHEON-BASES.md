# Pantheon on every base: package availability

Research for [#4731](https://github.com/tuna-os/tunaos/issues/4731), part of
[#4730](https://github.com/tuna-os/tunaos/issues/4730). It answers one
question per base: can the Pantheon stack be installed from that base's package
manager, and what would a flavor need?

This is a **dated measurement** (2026-11-25), not live status. Repositories
move; re-run the commands below before acting on a row. The gurnard package set
in `tunaos.toml` (`[desktops.pantheon.packages.apt]`) is the reference: `gala`,
`wingpanel`, `switchboard`-family, greeter, initial-setup, polkit agent,
session settings, default settings, icon theme, terminal and settings daemon.

## Result

| Base | Package base | Source that carries Pantheon | Verdict |
|---|---|---|---|
| gurnard | Ubuntu 24.04 noble | `ppa:elementary-os/stable` (gala 8.6.2, wingpanel 8.0.4, greeter 8.1.2, initial-setup 8.0.1) | **Shipping.** X11 session, LightDM, GPU runner |
| marlin | Arch | `extra`: full `pantheon` group (gala 8.6.2, wingpanel 8.0.4, switchboard 8.0.3, `pantheon-session` 8.1.0, `pantheon-default-settings` 8.1.1, `lightdm-pantheon-greeter` 8.1.2, `pantheon-initial-setup`, `pantheon-polkit-agent`, `pantheon-wayland`) | **Candidate: all packages in the base repo.** Do first |
| bonito (Fedora 44) | Fedora 44 | Partial: gala 8.4.1, wingpanel 8.0.4, `elementary-settings-daemon`, granite, plank, lightdm. No `switchboard`, greeter, initial-setup or polkit agent | **Needs packages** in `tunaos-packages` (greeter, switchboard, initial-setup, polkit agent, session/default settings). Shelf life: see bonito-rawhide |
| bonito-rawhide | Fedora Rawhide / 45 | None. `gala` and `wingpanel` are orphaned in dist-git (`dead.package`: "Orphaned for 6+ weeks"); F45 and rawhide repos carry only granite, plank, slingshot, icon theme | **Unsupported** until Fedora re-adopts them. F44 loses them at its own EOL for the same reason |
| albacore, yellowfin, skipjack | AlmaLinux 10 / Kitten / CentOS Stream 10 | None. EPEL 10 matched zero Pantheon names (not even `plank`); BaseOS/AppStream have none | **Unsupported for now.** Packaging the whole stack in `tunaos-packages` (as for `xfce-wayland`) is the only route; it is large (granite, gala against EL10's mutter, switchboard plugs, greeter). Needs a maintainer decision |
| flounder, flounder-sid | Debian 13 / sid | Archive has `plank` and `elementary-icon-theme` only (trixie 8.1.0, sid 8.2.0). No gala, wingpanel, switchboard, greeter | **Unsupported** unless built in-house (Tideforge). `PACKAGE-SOURCING.md` forbids using the Ubuntu PPA |
| grouper | Ubuntu 26.04 resolute | Archive: `plank`, icon theme only. PPA publishes `gala` for resolute but not wingpanel, greeter, initial-setup, polkit agent, settings-daemon | **Unsupported** (already recorded in `tunaos.toml`). Revisit when the PPA publishes the rest for 26.04 |
| stingray | Ubuntu rolling (26.10 stonking) | Archive: `plank`, icon theme only. PPA publishes nothing for stonking | **Unsupported** |
| sailfin | openSUSE Tumbleweed | Partial: `pantheon-*` apps, `switchboard` 8.0.3, `pantheon-agent-polkit`, `pantheon-settings-daemon`, `pantheon-dock`, lightdm. No `gala`, `wingpanel`, greeter, initial-setup. `X11:Pantheon` OBS repo returns 404 | **Unsupported** without in-house `gala`/`wingpanel`/greeter packages |
| guppy | Gentoo | Not in `::gentoo`. Third-party overlay `pimvullers/elementary` (listed in the Gentoo overlay index, last push 2026-11-24) has gala 8.6.2, wingpanel, pantheon-greeter 8.1.2, pantheon-meta | **Deferred.** An overlay is outside the sourcing policy without an allowlist entry, and a source build of the stack is slow |
| wahoo | Fedora ELN (tracks Rawhide) | Not measured directly; ELN follows Rawhide, where `gala`/`wingpanel` are retired | **Unsupported** (inference from Rawhide) |
| hummingbird | Rawhide fork | Ships no desktop by design (`docs/HUMMINGBIRD.md`) and Rawhide has no gala | **Unsupported** |

## Per-base record the issue asked for

| Base | Package source | Session | Display manager | GPU runner |
|---|---|---|---|---|
| gurnard | PPA (tier 3 exception) | X11 `pantheon` (Wayland autologin failed, #4547/#4573) | LightDM | yes |
| marlin | Arch `extra` (tier 1) | X11 first; `pantheon-wayland` exists but is unmeasured | LightDM with `lightdm-pantheon-greeter` | yes (software GL does not draw Pantheon) |
| bonito (if packaged) | Fedora + Tideforge | X11 first; `pantheon-wayland` 1.1.0 is in F44 but unmeasured | LightDM (in Fedora) | yes |
| all others | none | n/a | n/a | n/a |

## Defects to carry over from gurnard

Marlin and bonito reuse the fixes in #4609, #4591, #4633, #4642, #4647, #4661
and #4724 only where they are not apt-specific. Two are packaging, not harness,
and need a per-family check:

- The session needs the `gnome-session` systemd user units
  (`gnome-session-*@.target`). On Debian-family they come from
  `gnome-session-common`; Arch `gnome-session` and Fedora `gnome-session`
  (plus `gnome-session-wayland-session`) carry them in one package. Verify in
  the built image, not the manifest.
- The `gnome-settings-daemon` and `at-spi2-core` components must be present.
- `tmp.mount` (#4715) is a Debian-family root-filesystem issue; check it per base.

## Recommendation

1. Take **marlin** as the second reference base: it is the only base where every
   package already exists in the system repo, so no new packaging is needed.
   It needs a `manifests/desktops/pantheon-arch.yaml` (pattern: `xfce-arch.yaml`),
   a `[[variants.marlin.flavors]]` entry with `id = "pantheon"`, a live-ISO
   adapter, and a GPU-runner strict run. Open that as its own issue.
2. **bonito** is feasible but needs five packages built in `tunaos-packages`
   and has an end date (gala and wingpanel are orphaned in Rawhide). Do not
   start it before marlin passes; ask for a decision on whether a flavor with a
   known retirement is worth the packaging.
3. Declare **bonito-rawhide, EL10 (albacore, yellowfin, skipjack), flounder,
   flounder-sid, grouper, stingray, sailfin, wahoo, hummingbird** unsupported
   for Pantheon with the reasons above, in the coverage page tracked by #4730.
   Revisit when a package route changes (PPA publishes for 26.04, Fedora
   re-adopts gala, or a maintainer approves in-house packaging).
4. **guppy** waits on a decision about Gentoo overlays.

## Reproduce

```sh
# Debian / Ubuntu archives (package names starting gala|wingpanel|switchboard|plank|io.elementary.|pantheon|elementary-)
curl -s http://deb.debian.org/debian/dists/trixie/main/binary-amd64/Packages.xz | xz -dc | grep -E '^Package: (gala|wingpanel|switchboard|plank|io\.elementary\.|pantheon|elementary-)'
# elementary PPA, per series (empty entries = not published)
curl -s "https://api.launchpad.net/devel/~elementary-os/+archive/ubuntu/stable?ws.op=getPublishedBinaries&binary_name=io.elementary.wingpanel&exact_match=true&status=Published&distro_arch_series=https://api.launchpad.net/devel/ubuntu/resolute/amd64"
# Fedora / EPEL / openSUSE: fetch repodata/repomd.xml, then the primary.xml.zst it names, and grep <name>
#   https://dl.fedoraproject.org/pub/fedora/linux/releases/44/Everything/x86_64/os/
#   https://dl.fedoraproject.org/pub/epel/10/Everything/x86_64/
#   https://download.opensuse.org/tumbleweed/repo/oss/
# Fedora retirement marker
curl -s https://src.fedoraproject.org/rpms/gala/raw/rawhide/f/dead.package
# Arch
curl -s "https://archlinux.org/packages/search/json/?name=gala"
curl -s https://archlinux.org/groups/x86_64/pantheon/
```
