#!/usr/bin/env bats
#
# The GDM login gate drives a real VM through corral, so this suite fakes the
# guest boundary (corral, ssh, loginctl, systemctl, journalctl) and proves the
# attempt logic: newer GDM needs only Enter, others need Tab+Enter or
# type-ahead selection, and lock/unlock follow logind state.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/scripts/gdm-login-gate.sh"
  ROOT="${BATS_TEST_TMPDIR}/gate"
  STATE="${ROOT}/state"
  FAKEBIN="${ROOT}/bin"
  OUT="${ROOT}/out"
  mkdir -p "${STATE}" "${FAKEBIN}" "${OUT}/corral"
  cat >"${OUT}/corral/result.json" <<'JSON'
{"ssh": {"host": "127.0.0.1", "port": 2222, "user": "root", "identityFile": "/tmp/gate-id"}}
JSON
  export GDM_GATE_STATE="${STATE}"
  export GDM_GATE_USER="tuna-ci-login"
  export TUNAOS_GDM_TEST_PASSWORD="test-password"
  export TUNAOS_GDM_ACCOUNTS_DIR="${ROOT}/accts"
  export CORRAL="${FAKEBIN}/corral"
  export GDM_GATE_TAB_WORKS=1
  export GDM_GATE_TYPEAHEAD_WORKS=1

  cat >"${FAKEBIN}/sleep" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
  cat >"${FAKEBIN}/corral" <<'STUB'
#!/usr/bin/env bash
STATE="${GDM_GATE_STATE:?}"
sub="$1"; shift
case "$sub" in
screenshot)
  file=""
  prev=""
  for a in "$@"; do
    if [[ "$prev" == -o ]]; then file="$a"; fi
    prev="$a"
  done
  mkdir -p "$(dirname "$file")"
  : >"$file"
  # The first frame is blank (fresh greeter); everything after paints.
  if [[ -f "${STATE}/shot-once" ]]; then
    echo "Screenshot written to $file (1280x800, deviation 0.5000 — painted)"
  else
    touch "${STATE}/shot-once"
    echo "Screenshot written to $file (1280x800, deviation 0.0000 — blank)"
  fi
  ;;
key)
  echo "key $*" >>"${STATE}/calls"
  touch "${STATE}/input-seen"
  if [[ "$*" == *tab* && "${GDM_GATE_TAB_WORKS:-1}" == 1 ]]; then touch "${STATE}/tabbed"; fi
  if [[ "$*" == *ret* && -f "${STATE}/pw-typed" ]]; then
    rm -f "${STATE}/pw-typed"
    if [[ -f "${STATE}/session-preseed" || -f "${STATE}/tabbed" || -f "${STATE}/typed-user" ]]; then
      rm -f "${STATE}/locked"
    fi
  fi
  ;;
type)
  echo "type $*" >>"${STATE}/calls"
  touch "${STATE}/input-seen"
  text="${2:-}"
  if [[ "$text" == "${GDM_GATE_USER:?}" && "$*" != *--enter* && "${GDM_GATE_TYPEAHEAD_WORKS:-1}" == 1 ]]; then
    touch "${STATE}/typed-user"
  fi
  if [[ "$text" == "${TUNAOS_GDM_TEST_PASSWORD:?}" && "$*" != *--enter* ]]; then
    touch "${STATE}/pw-typed"
  fi
  ;;
*) echo "unexpected corral call: $sub $*" >&2; exit 1 ;;
esac
exit 0
STUB
  cat >"${FAKEBIN}/ssh" <<'STUB'
#!/usr/bin/env bash
STATE="${GDM_GATE_STATE:?}"
echo "ssh $*" >>"${STATE}/calls"
while [[ $# -gt 0 ]]; do
  case "$1" in
  *@*) shift; break ;;
  -F|-i|-p|-o) shift 2 ;;
  -*) shift ;;
  *) break ;;
  esac
done
exec "$@"
STUB
  cat >"${FAKEBIN}/loginctl" <<'STUB'
#!/usr/bin/env bash
STATE="${GDM_GATE_STATE:?}"
session_up=0
if [[ -f "${STATE}/session-preseed" || -f "${STATE}/tabbed" || -f "${STATE}/typed-user" ]]; then
  session_up=1
fi
cmd="$1"; shift
case "$cmd" in
list-sessions)
  if [[ "$session_up" == 1 ]]; then
    echo "41 1000 tuna-ci-login seat0 9999 user tty1 no"
  fi
  ;;
show-session)
  id="$1"; shift
  value_only=0
  if [[ "$*" == *--value* ]]; then value_only=1; fi
  locked=no
  if [[ -f "${STATE}/locked" ]]; then locked=yes; fi
  active=no
  if [[ "$session_up" == 1 ]]; then active=yes; fi
  for a in "$@"; do
    case "$a" in
    Type) v=wayland ;;
    Seat) v=seat0 ;;
    Active) v="$active" ;;
    LockedHint) v="$locked" ;;
    IdleHint) v=no ;;
    Name) v=tuna-ci-login ;;
    State) v=active ;;
    Service) v=gdm-password ;;
    *) continue ;;
    esac
    if [[ "$value_only" == 1 ]]; then echo "$v"; else echo "$a=$v"; fi
  done
  ;;
lock-session)
  if [[ "$session_up" == 1 ]]; then
    touch "${STATE}/locked"
  else
    echo "no such session" >&2
    exit 1
  fi
  ;;
session-status)
  echo "41 - tuna-ci-login (1000)"
  echo "           Since: now; Leader: PID 41 (tuna-session)"
  echo "          tuna-session(41) ─┬─tuna-compositor(100)"
  ;;
*) echo "unexpected loginctl call: $cmd $*" >&2; exit 1 ;;
esac
exit 0
STUB
  cat >"${FAKEBIN}/id" <<'STUB'
#!/usr/bin/env bash
if [[ "${1:-}" == "-u" && "${2:-}" == "${GDM_GATE_USER:?}" ]]; then echo 1000; exit 0; fi
exec /usr/bin/id "$@"
STUB
  cat >"${FAKEBIN}/runuser" <<'STUB'
#!/usr/bin/env bash
# runuser -u USER -- command...
shift 3
exec "$@"
STUB
  cat >"${FAKEBIN}/busctl" <<'STUB'
#!/usr/bin/env bash
# Stand-in for the org.gnome.ScreenSaver contract on the user's session bus.
STATE="${GDM_GATE_STATE:?}"
if [[ -f "${STATE}/no-screensaver" ]]; then
  echo "Failed to call: service org.gnome.ScreenSaver is not available" >&2
  exit 1
fi
method="${!#}"
case "$method" in
GetActive)
  if [[ -f "${STATE}/locked" ]]; then echo "b true"; else echo "b false"; fi
  ;;
Lock)
  echo "busctl lock" >>"${STATE}/calls"
  if [[ -f "${STATE}/screensaver-stuck" ]]; then
    :
  elif [[ -f "${STATE}/lock-lossy" && ! -f "${STATE}/lock-armed" ]]; then
    touch "${STATE}/lock-armed"
  elif [[ -f "${STATE}/session-preseed" || -f "${STATE}/tabbed" || -f "${STATE}/typed-user" ]]; then
    touch "${STATE}/locked"
  fi
  ;;
*) echo "unexpected busctl call: $*" >&2; exit 1 ;;
esac
exit 0
STUB
  cat >"${FAKEBIN}/systemctl" <<'STUB'
#!/usr/bin/env bash
if [[ "${1:-}" == "is-active" ]]; then exit 0; fi
echo "stub systemctl $*"
exit 0
STUB
  cat >"${FAKEBIN}/journalctl" <<'STUB'
#!/usr/bin/env bash
echo "stub journal"
STUB
  chmod +x "${FAKEBIN}/sleep" "${FAKEBIN}/corral" "${FAKEBIN}/ssh" \
    "${FAKEBIN}/loginctl" "${FAKEBIN}/systemctl" "${FAKEBIN}/journalctl" \
    "${FAKEBIN}/id" "${FAKEBIN}/runuser" "${FAKEBIN}/busctl"
  export PATH="${FAKEBIN}:${PATH}"
}

run_gate() {
  run bash "$SCRIPT" testvm "$OUT" "$GDM_GATE_USER"
}

@test "login succeeds on the second attempt when the tile needs Tab first" {
  export GDM_GATE_TYPEAHEAD_WORKS=0
  run_gate
  [ "$status" -eq 0 ]
  grep -Fq 'TUNAOS_GDM_LOGIN_OK user=tuna-ci-login session=41' <<<"$output"
  grep -Fq 'TUNAOS_GDM_LOCK_OK user=tuna-ci-login session=41' <<<"$output"
  grep -Fq 'TUNAOS_GDM_UNLOCK_OK user=tuna-ci-login session=41' <<<"$output"
  grep -Fq 'key testvm tab' "${STATE}/calls"
  grep -Fq 'key testvm esc' "${STATE}/calls"
  grep -Fqx 'Session=tuna' "${ROOT}/accts/tuna-ci-login"
  grep -Fq 'systemctl restart gdm.service' "${STATE}/calls"
  grep -Fq 'tuna-session(41)' <<<"$output"
  grep -Fq 'busctl lock' "${STATE}/calls"
  [ -f "${OUT}/gdm-attempt-1.png" ]
  [ -f "${OUT}/gdm-attempt-2.png" ]
  [ ! -e "${OUT}/gdm-attempt-3.png" ]
  [ -f "${OUT}/gdm-logged-in.png" ]
  [ -f "${OUT}/gdm-locked.png" ]
  [ -f "${OUT}/gdm-unlocked.png" ]
}

@test "login falls back to type-ahead selection when Tab does not work" {
  export GDM_GATE_TAB_WORKS=0
  run_gate
  [ "$status" -eq 0 ]
  grep -Fq 'TUNAOS_GDM_LOGIN_OK user=tuna-ci-login session=41' <<<"$output"
  grep -Fq "type testvm ${GDM_GATE_USER}" "${STATE}/calls"
  [ -f "${OUT}/gdm-attempt-3.png" ]
}

@test "a failed login attempt leaves evidence and diagnostics" {
  export GDM_GATE_TAB_WORKS=0
  export GDM_GATE_TYPEAHEAD_WORKS=0
  run_gate
  [ "$status" -eq 1 ]
  grep -Fq 'GDM did not start an active Wayland session' <<<"$output"
  grep -Fq '==> loginctl sessions' <<<"$output"
  [ -f "${OUT}/gdm-login-failed.png" ]
  [ -f "${OUT}/gdm-attempt-1.png" ]
  [ -f "${OUT}/gdm-attempt-2.png" ]
  [ -f "${OUT}/gdm-attempt-3.png" ]
}

@test "lock reports the session state when the hint never flips" {
  # The session appears once the gate starts typing; the lock never engages.
  touch "${STATE}/screensaver-stuck"
  cat >"${FAKEBIN}/loginctl" <<'STUB'
#!/usr/bin/env bash
STATE="${GDM_GATE_STATE:?}"
cmd="$1"; shift
case "$cmd" in
list-sessions)
  if [[ -f "${STATE}/input-seen" ]]; then
    echo "41 1000 tuna-ci-login seat0 9999 user tty1 no"
  fi
  ;;
show-session)
  shift
  value_only=0
  if [[ "$*" == *--value* ]]; then value_only=1; fi
  for a in "$@"; do
    case "$a" in
    Type) v=wayland ;;
    Seat) v=seat0 ;;
    Active) v=yes ;;
    LockedHint) v=no ;;
    *) continue ;;
    esac
    if [[ "$value_only" == 1 ]]; then echo "$v"; else echo "$a=$v"; fi
  done
  ;;
lock-session) exit 0 ;;
*) exit 1 ;;
esac
exit 0
STUB
  chmod +x "${FAKEBIN}/loginctl"
  run_gate
  [ "$status" -eq 1 ]
  grep -Fq 'did not report its session locked' <<<"$output"
  grep -Fq '==> session 41' <<<"$output"
  [ -f "${OUT}/gdm-lock-failed.png" ]
}

@test "lock retries until a slow shell engages the ScreenSaver" {
  # The first Lock request lands before the shell is ready and is lost.
  touch "${STATE}/lock-lossy"
  run_gate
  [ "$status" -eq 0 ]
  grep -Fq 'TUNAOS_GDM_LOCK_OK user=tuna-ci-login session=41' <<<"$output"
  [ "$(grep -c '^busctl lock' "${STATE}/calls")" -ge 2 ]
}

@test "lock falls back to logind when the ScreenSaver service is absent" {
  touch "${STATE}/no-screensaver"
  run_gate
  [ "$status" -eq 0 ]
  grep -Fq 'TUNAOS_GDM_LOCK_OK user=tuna-ci-login session=41' <<<"$output"
  grep -Fq 'TUNAOS_GDM_UNLOCK_OK user=tuna-ci-login session=41' <<<"$output"
}
