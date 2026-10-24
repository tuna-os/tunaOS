"""Offline subprocess and clock fixtures; no artifact downloads or VM boots."""
import importlib.util
import io
from pathlib import Path
import sys
import pytest
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recovery', ROOT / 'scripts/fetch-native-iso-artifact.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def command(tmp_path, first, later='sys.stdout.buffer.write(b"complete")'):
    marker = tmp_path / 'attempts'
    code = ('import sys\nfrom pathlib import Path\np=Path(' + repr(str(marker)) + ')\n'
            'n=int(p.read_text()) if p.exists() else 0\np.write_text(str(n+1))\n'
            'if n == 0:\n ' + first.replace('\n', '\n ') + '\nelse:\n ' + later.replace('\n', '\n '))
    return [sys.executable, '-c', code], marker


def test_reset_restarts_from_zero_secret_safe(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(m.time, 'sleep', lambda _: None)
    cmd, marker = command(tmp_path, 'sys.stdout.buffer.write(b"part");sys.stdout.flush();sys.stderr.write("connection reset SECRET https://private/?sig=TOKEN");sys.exit(1)')
    out = io.BytesIO()
    assert m.download_archive(cmd, out, 8, 5) == 8
    assert out.getvalue() == b'complete' and marker.read_text() == '2'
    assert 'SECRET' not in capsys.readouterr().out


@pytest.mark.parametrize('status', [401, 403, 404, 408, 410, 429, 500, 503])
def test_http_status_overrides_reset_no_retry(tmp_path, status):
    cmd, marker = command(tmp_path, f'sys.stderr.write("HTTP {status}: connection reset SECRET");sys.exit(1)')
    out = io.BytesIO()
    with pytest.raises(m.TransferError, match=f'http_{status}') as error:
        m.download_archive(cmd, out, 8, 5)
    assert marker.read_text() == '1' and out.getvalue() == b''
    assert 'SECRET' not in str(error.value)


@pytest.mark.parametrize('payload', [b'part', b'complete-extra'])
def test_clean_truncation_or_oversize_never_retry(tmp_path, payload):
    cmd, marker = command(tmp_path, 'sys.stdout.buffer.write(' + repr(payload) + ')')
    out = io.BytesIO()
    with pytest.raises(ValueError):
        m.download_archive(cmd, out, 8, 5)
    assert marker.read_text() == '1' and out.getvalue() == b''


def test_exhausted_attempts_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(m.time, 'sleep', lambda _: None)
    fail = 'sys.stdout.buffer.write(b"part");sys.stderr.write("unexpected EOF");sys.exit(1)'
    cmd, marker = command(tmp_path, fail, fail)
    out = io.BytesIO()
    with pytest.raises(m.TransferError):
        m.download_archive(cmd, out, 8, 5)
    assert marker.read_text() == '3' and out.getvalue() == b''


@pytest.mark.parametrize('cancel', [KeyboardInterrupt, SystemExit])
def test_cancellation_not_retried(monkeypatch, cancel):
    calls = []
    def interrupted(*args):
        calls.append(1)
        args[1].write(b'part')
        raise cancel()
    monkeypatch.setattr(m, 'bounded_command', interrupted)
    out = io.BytesIO()
    with pytest.raises(cancel):
        m.download_archive(['unused'], out, 8, 5)
    assert len(calls) == 1 and out.getvalue() == b''


@pytest.mark.parametrize('reason', ['GitHub transfer deadline exceeded', 'GitHub transfer idle deadline exceeded'])
def test_deadline_error_not_retried(monkeypatch, reason):
    calls = []
    def failed(*args):
        calls.append(1)
        raise m.TransferError(reason, {'category': 'connection_reset', 'returncode': 1})
    monkeypatch.setattr(m, 'bounded_command', failed)
    with pytest.raises(m.TransferError):
        m.download_archive(['unused'], io.BytesIO(), 8, 5)
    assert len(calls) == 1


@pytest.mark.parametrize('idle', [3, 100])
def test_shared_deadline_and_idle_across_backoff(monkeypatch, idle):
    now = [0.0]
    calls = []
    monkeypatch.setattr(m.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(m.time, 'sleep', lambda t: now.__setitem__(0, now[0] + t))
    def failed(command, target, size, timeout, idle_timeout, progress):
        calls.append((progress['deadline'], progress['last_progress']))
        now[0] += 1
        raise m.TransferError('GitHub transfer failed', {'category': 'connection_reset', 'returncode': 1, 'bytes_received': 0})
    monkeypatch.setattr(m, 'bounded_command', failed)
    with pytest.raises(ValueError, match='budget exhausted'):
        m.download_archive(['unused'], io.BytesIO(), 8, 5, idle)
    assert all(deadline == 5 and last == 0 for deadline, last in calls)
    assert now[0] <= 5


def test_expired_budget_does_not_launch(monkeypatch):
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not spawn'))
    with pytest.raises(ValueError, match='budget exhausted'):
        m.bounded_command(['unused'], io.BytesIO(), 8, 5, 120, {'deadline': 0, 'last_progress': 0})


def test_no_range_or_url_reuse_and_hash_precedes_extract():
    source = (ROOT / 'scripts/fetch-native-iso-artifact.py').read_text()
    main = source.split('def main():', 1)[1]
    assert 'download_archive(["gh", "api", f"repos/{args.repository}/actions/artifacts/{args.artifact_id}/zip"]' in main
    assert main.index('digest(archive) != args.archive_digest') < main.index('iso = extract(')
    assert 'Range:' not in source and 'If-Range' not in source


def test_changed_content_same_size_fails_hash(tmp_path):
    import hashlib
    expected = 'sha256:' + hashlib.sha256(b'complete').hexdigest()
    cmd, marker = command(tmp_path, 'sys.stdout.buffer.write(b"changed!")')
    path = tmp_path / 'archive'
    with path.open('xb') as out:
        m.download_archive(cmd, out, 8, 5)
    assert path.stat().st_size == 8 and m.digest(path) != expected
    assert marker.read_text() == '1'


def test_child_termination_not_retried(tmp_path):
    cmd, marker = command(tmp_path, 'import os,signal;sys.stderr.write("connection reset");sys.stderr.flush();os.kill(os.getpid(), signal.SIGTERM)')
    with pytest.raises(m.TransferError):
        m.download_archive(cmd, io.BytesIO(), 8, 5)
    assert marker.read_text() == '1'


def test_wrong_content_never_extracts_or_emits_binding(tmp_path, monkeypatch):
    import argparse
    import hashlib
    args = argparse.Namespace(repository='tuna-os/tunaOS', run_id=1, artifact_id=2, attempt=0,
                              source_sha='a'*40, archive_digest='sha256:'+hashlib.sha256(b'complete').hexdigest(),
                              variant='skipjack', flavor='gnome', output=tmp_path/'out')
    run = dict(id=1, status='completed', conclusion='success', head_sha=args.source_sha,
               path='.github/workflows/live-iso-bootc.yml', repository=dict(full_name=args.repository),
               head_repository=dict(full_name=args.repository))
    artifact = dict(id=2, expired=False, name='skipjack-gnome-live-iso', digest=args.archive_digest,
                    workflow_run=dict(id=1, head_sha=args.source_sha), size_in_bytes=8)
    monkeypatch.setattr(m.argparse.ArgumentParser, 'parse_args', lambda _: args)
    monkeypatch.setattr(m, 'api', lambda repo, suffix: run if '/runs/' in suffix else artifact)
    def download(command, target, *rest):
        target.write(b'changed!')
    monkeypatch.setattr(m, 'download_archive', download)
    monkeypatch.setattr(m, 'extract', lambda *a: pytest.fail('must not extract wrong content'))
    with pytest.raises(ValueError, match='does not match producer artifact'):
        m.main()
    assert not (args.output / 'artifact-binding.json').exists()


def test_truncated_diagnostic_cannot_prove_retryable(tmp_path):
    message = 'connection reset ' + ('x' * m.MAX_STDERR) + ' HTTP 403 denied SECRET'
    cmd, marker = command(tmp_path, 'sys.stderr.write(' + repr(message) + ');sys.exit(1)')
    with pytest.raises(m.TransferError) as error:
        m.download_archive(cmd, io.BytesIO(), 8, 5)
    assert error.value.details['stderr_truncated']
    assert marker.read_text() == '1'
    assert 'SECRET' not in str(error.value)
