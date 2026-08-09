#!/usr/bin/env bats
# The identity variables 90-image-info.sh reads, and the stages that must carry
# them.
#
# The global `ARG IMAGE_VENDOR` at the top of a Containerfile reaches `FROM`
# interpolation and nothing else. A stage that runs a script needing it must
# re-declare it — and ENV, unlike ARG, is inherited by CHILD stages, which is
# where this gets subtle: Containerfile.gentoo promoted them in `system` and
# then ran 90-image-info.sh again in `desktop`, whose chain is
# base -> builder -> desktop-build -> desktop. `system` is a sibling. Nothing
# on the desktop branch set them, and the script is `set -euo pipefail`:
#
#   90-image-info.sh: line 8: IMAGE_VENDOR: unbound variable
#
# So the property is not "the ARG/ENV blocks match" — they legitimately differ,
# and Containerfile.ubuntu deliberately declares SHA_HEAD_SHORT late to keep
# per-commit values out of its expensive layers. The property is: every stage
# that runs the script can resolve the variables the script cannot default.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
INFO="${REPO_ROOT}/build_scripts/90-image-info.sh"

CONTAINERFILES=(
  Containerfile.el10
  Containerfile.arch
  Containerfile.debian
  Containerfile.ubuntu
  Containerfile.opensuse
  Containerfile.gentoo
)

# Variables 90-image-info.sh dereferences with NO `:-` fallback. These are the
# ones that turn into "unbound variable" under set -u; the rest degrade to a
# default and are not this test's business.
REQUIRED=(IMAGE_VENDOR BASE_IMAGE)

# IMAGE_NAME is deliberately NOT in REQUIRED. The script defaults each of the
# identity pair to the other:
#
#   IMAGE_NAME="$(canonical_variant "${IMAGE_NAME:-${IMAGE_NAME_VARIANT:-}}")"
#   VARIANT_KEY="$(canonical_variant "${IMAGE_NAME_VARIANT:-${IMAGE_NAME}}")"
#
# so neither one alone is an "unbound variable" risk, and demanding both would
# fail Containerfiles that legitimately pass only IMAGE_NAME. But supplying
# NEITHER is still a build failure — just a different one: the codename lookup
# gets an empty key and hits its abort branch. So the property for this pair is
# "at least one", checked separately below rather than dropped.
IDENTITY=(IMAGE_NAME IMAGE_NAME_VARIANT)

@test "the required set still is the set with no default" {
  # If someone gives IMAGE_VENDOR a `:-` fallback, or drops one, this test's
  # list is wrong and the failure it guards changes shape.
  local v
  for v in "${REQUIRED[@]}"; do
    grep -qE "\\\$\{${v}\}" "$INFO" || {
      echo "FAIL: ${v} is no longer dereferenced bare in 90-image-info.sh" >&2
      return 1
    }
    if grep -qE "\\\$\{${v}:-" "$INFO"; then
      echo "FAIL: ${v} now has a default — remove it from REQUIRED" >&2
      return 1
    fi
  done
  # And the script must still be the strict kind, or none of this matters.
  grep -qE '^set -[a-z]*u' "$INFO"
}

@test "the identity pair still defaults to each other, so neither is required alone" {
  # This is what justifies IMAGE_NAME sitting in IDENTITY instead of REQUIRED.
  # If the mutual fallback is ever removed, the var that loses it becomes an
  # "unbound variable" risk again and belongs back in REQUIRED — fail loudly
  # here rather than let the strict per-stage check silently stop applying.
  local v
  for v in "${IDENTITY[@]}"; do
    grep -qE "\\\$\{${v}:-" "$INFO" || {
      echo "FAIL: ${v} no longer has a fallback in 90-image-info.sh —" >&2
      echo "      move it from IDENTITY to REQUIRED" >&2
      return 1
    }
  done
}

@test "every stage that runs 90-image-info.sh can resolve them" {
  local f
  for f in "${CONTAINERFILES[@]}"; do
    run python3 - "${REPO_ROOT}/$f" "${REQUIRED[@]}" --any-of "${IDENTITY[@]}" <<'PY'
import re, sys
path, rest = sys.argv[1], sys.argv[2:]
# Everything before --any-of must be present; at least one of what follows it.
split = rest.index('--any-of')
required, any_of = rest[:split], rest[split + 1:]
lines = open(path).read().split('\n')

bounds = []
for i, l in enumerate(lines):
    m = re.match(r'^FROM\s+(\S+)(?:\s+[Aa][Ss]\s+(\S+))?', l)
    if m:
        bounds.append((i, m.group(2) or f'<anon{i}>', m.group(1)))
bounds.append((len(lines), '<eof>', None))

stages, order = {}, []
for k in range(len(bounds) - 1):
    s, e = bounds[k][0], bounds[k + 1][0]
    name, parent = bounds[k][1], bounds[k][2]
    body = '\n'.join(lines[s:e])
    # Strip comments: several of these files quote the variable names in
    # prose explaining this very bug.
    code = '\n'.join(l for l in lines[s:e] if not l.lstrip().startswith('#'))
    stages[name] = dict(
        parent=parent,
        args=set(re.findall(r'^ARG\s+([A-Z_]+)', code, re.M)),
        envs=set(re.findall(r'(?:^ENV\s+|^\s+)([A-Z_]+)=', code, re.M)),
        runs=bool(re.search(r'^[^#]*90-image-info\.sh', code, re.M)),
    )
    order.append(name)

def env_chain(name, seen=None):
    """ENV set here plus ENV inherited from ancestors. ARG is NOT inherited."""
    seen = seen or set()
    st = stages.get(name)
    if not st or name in seen:
        return set()
    seen.add(name)
    parent = st['parent'] if st['parent'] in stages else None
    return st['envs'] | (env_chain(parent, seen) if parent else set())

bad = []
for name in order:
    st = stages[name]
    if not st['runs']:
        continue
    # ARG declared in this stage is visible to its own RUNs; ENV additionally
    # reaches children.
    available = st['args'] | env_chain(name)
    missing = [v for v in required if v not in available]
    if missing:
        bad.append(f"{name}: {', '.join(missing)}")
    # The identity pair defaults to each other, so one is enough — but zero
    # leaves the codename lookup with an empty key and aborts the build.
    if any_of and not (set(any_of) & available):
        bad.append(f"{name}: none of {' / '.join(any_of)}")

if bad:
    print(f"{path}: stages running 90-image-info.sh without the vars it cannot default:")
    for b in bad:
        print(f"  {b}")
    sys.exit(1)
PY
    [ "$status" -eq 0 ] || {
      echo "$output" >&2
      return 1
    }
  done
}

@test "install-desktop.sh never runs before the image is branded" {
  # install-desktop.sh ends by running the branding contract, which reads
  # os-release. Every Containerfile but one satisfies that by running
  # 90-image-info.sh in the base stage first. Containerfile.gentoo's desktop
  # branch (builder -> desktop-build) skipped it — `system`, which has it, is a
  # sibling — so the contract ran against stock Gentoo:
  #
  #   FAIL: PRETTY_NAME is 'Gentoo Linux' — still names the upstream distro
  #   TUNAOS_BRANDING_FAIL variant=xfce failures=14
  #
  # "variant 'xfce'" because install-desktop.sh falls back to the desktop name
  # when IMAGE_NAME is unset, so the codename lookup is asked for a variant
  # that does not exist.
  local f
  for f in "${CONTAINERFILES[@]}"; do
    run python3 - "${REPO_ROOT}/$f" <<'PY'
import re, sys
path = sys.argv[1]
lines = open(path).read().split('\n')

bounds = []
for i, l in enumerate(lines):
    m = re.match(r'^FROM\s+(\S+)(?:\s+[Aa][Ss]\s+(\S+))?', l)
    if m:
        bounds.append((i, m.group(2) or f'<anon{i}>', m.group(1)))
bounds.append((len(lines), '<eof>', None))

stages = {}
for k in range(len(bounds) - 1):
    s, e = bounds[k][0], bounds[k + 1][0]
    name, parent = bounds[k][1], bounds[k][2]
    code = [l for l in lines[s:e] if not l.lstrip().startswith('#')]
    def first(pat):
        for off, l in enumerate(code):
            if pat in l:
                return off
        return None
    stages[name] = dict(parent=parent, brand=first('90-image-info.sh'),
                        desk=first('install-desktop.sh'))

def branded_before(name, seen=None):
    """Did 90-image-info.sh run anywhere at or above this stage?"""
    seen = seen or set()
    st = stages.get(name)
    if not st or name in seen:
        return False
    seen.add(name)
    if st['brand'] is not None:
        return True
    parent = st['parent'] if st['parent'] in stages else None
    return branded_before(parent, seen) if parent else False

bad = []
for name, st in stages.items():
    if st['desk'] is None:
        continue
    # Branding must already be in place when install-desktop.sh runs, either
    # earlier in this stage or anywhere in an ancestor. A later re-run in this
    # stage is a repair (install-desktop.sh can overwrite os-release), not a
    # violation, so it only counts when nothing branded the image beforehand.
    if st['brand'] is not None and st['brand'] < st['desk']:
        continue
    parent = st['parent'] if st['parent'] in stages else None
    if parent and branded_before(parent):
        continue
    if st['brand'] is not None:
        bad.append(f"{name}: 90-image-info.sh runs AFTER install-desktop.sh")
    else:
        bad.append(f"{name}: install-desktop.sh runs with no branding anywhere above it")

if bad:
    print(f"{path}:")
    for b in bad:
        print(f"  {b}")
    sys.exit(1)
PY
    [ "$status" -eq 0 ] || {
      echo "$output" >&2
      return 1
    }
  done
}

@test "install-desktop.sh never runs before the branding assets are in place" {
  # Branding is not only os-release. Three of the contract's fourteen
  # assertions are about files, and running 90-image-info.sh does not put them
  # there:
  #
  #   FAIL: LOGO=tunaos but no matching file under /usr/share/pixmaps or hicolor
  #   FAIL: no TunaOS wallpaper under /usr/share/backgrounds (only upstream artwork)
  #   FAIL: plymouth default is not a TunaOS theme
  #   TUNAOS_BRANDING_FAIL variant=guppy failures=3
  #
  # That is what Containerfile.gentoo's desktop-build measured once it was
  # branded but before it had system_files: the assets are
  # /usr/share/pixmaps/tunaos.svg, /usr/share/backgrounds/tunaos and the
  # default.plymouth symlink into themes/tunaos, and they arrive one of exactly
  # two ways — `COPY --from=context /files /`, or 00-copy-files.sh, which
  # copies the same tree (Containerfile.ubuntu and .el10 fold common's shared
  # files into /files at the context stage and take that path).
  local f
  for f in "${CONTAINERFILES[@]}"; do
    run python3 - "${REPO_ROOT}/$f" <<'PY'
import re, sys
path = sys.argv[1]
lines = open(path).read().split('\n')

bounds = []
for i, l in enumerate(lines):
    m = re.match(r'^FROM\s+(\S+)(?:\s+[Aa][Ss]\s+(\S+))?', l)
    if m:
        bounds.append((i, m.group(2) or f'<anon{i}>', m.group(1)))
bounds.append((len(lines), '<eof>', None))

def is_asset_copy(l):
    # The image-side copy, not the context stage assembling /files from
    # `COPY system_files /files` (which has no --from=context).
    if re.match(r'^\s*COPY\s+--from=context\s+/files\s+/\s*$', l):
        return True
    return '00-copy-files.sh' in l

stages = {}
for k in range(len(bounds) - 1):
    s, e = bounds[k][0], bounds[k + 1][0]
    name, parent = bounds[k][1], bounds[k][2]
    code = [l for l in lines[s:e] if not l.lstrip().startswith('#')]
    assets = next((off for off, l in enumerate(code) if is_asset_copy(l)), None)
    desk = next((off for off, l in enumerate(code)
                 if 'install-desktop.sh' in l), None)
    stages[name] = dict(parent=parent, assets=assets, desk=desk)

def assets_above(name, seen=None):
    seen = seen or set()
    st = stages.get(name)
    if not st or name in seen:
        return False
    seen.add(name)
    if st['assets'] is not None:
        return True
    parent = st['parent'] if st['parent'] in stages else None
    return assets_above(parent, seen) if parent else False

bad = []
for name, st in stages.items():
    if st['desk'] is None:
        continue
    if st['assets'] is not None:
        if st['assets'] < st['desk']:
            continue
        bad.append(f"{name}: the branding assets are copied AFTER install-desktop.sh")
        continue
    parent = st['parent'] if st['parent'] in stages else None
    if not (parent and assets_above(parent)):
        bad.append(f"{name}: install-desktop.sh runs with no branding assets anywhere above it")

if bad:
    print(f"{path}:")
    for b in bad:
        print(f"  {b}")
    sys.exit(1)
PY
    [ "$status" -eq 0 ] || {
      echo "$output" >&2
      return 1
    }
  done
}
