# Adoption reports (countme)

TunaOS measures adoption with one weekly report from each installed system
that takes part. There is no account and no device ID. Public results show
weekly estimates, not unique users. See the [public metrics][metrics], the
[RFC][rfc] and the [decision record][adr].

## What your system sends

At most one report per UTC week (Monday to Sunday). Each report contains
only these fields:

- `variant`: the image family (for example `yellowfin`).
- `flavor`: the full image flavor (for example `gnome-hwe`).
- `arch`: the CPU type (for example `x86_64`).
- `age_bucket`: install age as 1 (first week), 2 (weeks 2-4),
  3 (weeks 5-24) or 4 (week 25 onward). Age starts when the reporter first
  sees the system, not on a proven install date.

The client sends an HTTPS POST to `https://countme.tunaos.org/v1/report`.
Before it sends, it writes the week to disk. It never sends a second report
in the same week, even if the first response is lost. This favors
undercount over duplicates.

These are TunaOS's addresses, set by `countme_endpoint` and
`countme_metrics_url` in `tunaos.toml`. A fork sets its own or leaves the
endpoint empty, which turns reports off for that image.

## What your system never sends

No machine ID, no derived ID, no random token, no hostname, no username,
no precise time and no hardware list. The payload has no field for them,
and the collector stores only aggregate counters. Transport still exposes
your source IP to Cloudflare; see the [RFC][rfc] for that disclosure.

## On or off

Reports are on by default on installed systems. To check state:

```sh
tunaos-countme status
```

To opt out (persists across upgrades and image switches):

```sh
sudo tunaos-countme disable
```

This writes `/etc/tunaos/countme/disabled` and masks the timer and the
service. To opt back in:

```sh
sudo tunaos-countme enable
```

Your opt-out stays in place after upgrades and official image switches. A
reinstall or a reset of `/etc` starts fresh, so check state after such events.

Live media, image builds, containers and CI boot tests never report. An
installed virtual machine is an install, so it can report.

## Unattended installs

An unattended install can disable reports before first boot. Write the
opt-out file and mask the units in the installed system. Do this from a
`%post` section or from a first-boot script that runs as root before the
timer can start:

```sh
install -d -m 0755 /etc/tunaos/countme
touch /etc/tunaos/countme/disabled
systemctl mask tunaos-countme.timer tunaos-countme.service
```

If no policy disables reports, the default applies: on.

## Upstream reporters

Each TunaOS image disables the reporters that it inherits from Bluefin,
Dakota and Bluefin LTS. If you disable TunaOS reports, other distribution
analytics do not change. RPM images also run the upstream
`rpm-ostree-countme` service; it has its own controls and is outside this
document.

## Public output

The collector publishes only weeks that are complete. Counts round down to tens.
Counts of 1-9 stay hidden; if one category in a group is that small, the
whole group stays hidden to block recovery by subtraction. The current
week shows no counts until it is complete. Missing weeks stay missing and
never show as zero.

[metrics]: https://tunaos.org/metrics
[rfc]: rfc/rfc012-private-adoption-metrics.md
[adr]: adr/0011-private-adoption-metrics.md
