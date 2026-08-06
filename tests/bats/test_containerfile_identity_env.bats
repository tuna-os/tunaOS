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
REQUIRED=(IMAGE_NAME IMAGE_VENDOR BASE_IMAGE)

@test "the required set still is the set with no default" {
  # If someone gives IMAGE_VENDOR a `:-` fallback, or drops one on IMAGE_NAME,
  # this test's list is wrong and the failure it guards changes shape.
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

@test "every stage that runs 90-image-info.sh can resolve them" {
  local f
  for f in "${CONTAINERFILES[@]}"; do
    run python3 - "${REPO_ROOT}/$f" "${REQUIRED[@]}" <<'PY'
import re, sys
path, required = sys.argv[1], sys.argv[2:]
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
    # Branded in an ancestor is fine. Branded in THIS stage is fine only if it
    # comes first.
    if st['brand'] is not None:
        if st['brand'] < st['desk']:
            continue
        bad.append(f"{name}: 90-image-info.sh runs AFTER install-desktop.sh")
        continue
    parent = st['parent'] if st['parent'] in stages else None
    if not (parent and branded_before(parent)):
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
