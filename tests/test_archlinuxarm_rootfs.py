"""Rootfs extraction must require the official detached signature.

Falsification: tamper with rootfs, signature, pinned key, producer or published
manifest identity. Cryptographic verification or receipt creation must fail.
All commands in these tests execute in CI; no local test run is authorized.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    'alarm_rootfs', Path(__file__).parents[1] / 'scripts/verify-archlinuxarm-rootfs.py')
alarm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alarm)


@pytest.mark.parametrize('url', ['http://fl.us.mirror.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz',
                                 alarm.ROOTFS_URL + '?token=secret', alarm.ROOTFS_URL + '#fragment',
                                 'https://evil.example/rootfs',
                                 'https://fl.us.mirror.archlinuxarm.org/os/landing.html',
                                 'https://user@fl.us.mirror.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz'])
def test_source_fetch_rejects_unapproved_locations(url):
    with pytest.raises(alarm.VerificationError):
        alarm.safe_url(url)


def test_only_fixed_official_source_and_key_paths_are_allowed():
    for url in (alarm.ROOTFS_URL, alarm.ROOTFS_URL + '.sig', alarm.KEY_URL):
        assert alarm.safe_url(url) == url
    assert alarm.KEY_REVISION in alarm.KEY_URL


def test_proof_json_cannot_override_duplicate_identity(tmp_path):
    path = tmp_path / 'proof.json'
    path.write_text('{"imageDigest":"old","imageDigest":"new"}')
    with pytest.raises(alarm.VerificationError, match='duplicate-proof-json-key'):
        alarm.read_json(path)


def test_ci_empty_repository_override_inherits_required_global_policy():
    assert alarm.effective_siglevel('Required DatabaseOptional', '') == (
        'PackageRequired PackageTrustedOnly DatabaseOptional DatabaseTrustedOnly')


def test_repository_database_override_preserves_global_package_requirement():
    assert 'PackageRequired' in alarm.effective_siglevel('Required DatabaseOptional', 'DatabaseRequired')


@pytest.mark.parametrize('global_value,override', [('Required', 'PackageOptional'),
                                                 ('Required', 'Never'), ('Optional', ''),
                                                 ('Required', 'PackageTrustAll'),
                                                 ('Required', 'unexpected')])
def test_policy_inheritance_never_blesses_unsigned_or_untrusted_packages(global_value, override):
    with pytest.raises(alarm.VerificationError):
        alarm.effective_siglevel(global_value, override)


def test_raw_ci_policy_files_emit_canonical_effective_requirements(tmp_path):
    (tmp_path / 'native-global-siglevel.txt').write_text('Required\nDatabaseOptional\n')
    (tmp_path / 'native-repositories.txt').write_text('core\nextra\n')
    (tmp_path / 'native-repo-core.siglevel.txt').write_text('')
    (tmp_path / 'native-repo-extra.siglevel.txt').write_text('DatabaseRequired\n')
    alarm.signature_policy(tmp_path)
    lines = (tmp_path / 'native-signature-policy.txt').read_text().splitlines()
    assert lines[0] == 'core PackageRequired PackageTrustedOnly DatabaseOptional DatabaseTrustedOnly'
    assert lines[1] == 'extra PackageRequired PackageTrustedOnly DatabaseRequired DatabaseTrustedOnly'


def test_download_bound_blocks_before_retaining_oversize_source(tmp_path, monkeypatch):
    class Response:
        headers = {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, size):
            return b'oversize'
    monkeypatch.setattr(alarm.urllib.request, 'build_opener', lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response()))
    path = tmp_path / 'rootfs'
    with pytest.raises(alarm.VerificationError):
        alarm.fetch(alarm.ROOTFS_URL, path, 2)
    assert not path.exists()
    assert not path.with_suffix('.partial').exists()


@pytest.fixture
def signed_source(tmp_path, monkeypatch):
    """Generated test key exercises real GPG, without trusting it in production."""
    assert shutil.which('gpg'), 'CI must provide GnuPG'
    home = tmp_path / 'signer'
    home.mkdir(mode=0o700)
    prefix = ['gpg', '--homedir', str(home), '--batch', '--pinentry-mode', 'loopback', '--passphrase', '']
    subprocess.run(prefix + ['--quick-generate-key', 'CI Fixture <fixture@example.invalid>', 'rsa2048', 'sign', '0'], check=True, capture_output=True)
    keys = subprocess.run(prefix + ['--with-colons', '--list-keys'], check=True, capture_output=True, text=True).stdout
    fingerprint = next(line.split(':')[9] for line in keys.splitlines() if line.startswith('fpr:'))
    rootfs = tmp_path / 'rootfs.tar.gz'
    rootfs.write_bytes(b'bounded rootfs fixture; no extraction occurs')
    subprocess.run(prefix + ['--detach-sign', '--output', str(tmp_path / 'rootfs.sig'), str(rootfs)], check=True, capture_output=True)
    key = subprocess.run(prefix + ['--armor', '--export', fingerprint], check=True, capture_output=True).stdout
    (tmp_path / 'upstream.asc').write_bytes(key)
    monkeypatch.setattr(alarm, 'KEY_SHA256', hashlib.sha256(key).hexdigest())
    monkeypatch.setattr(alarm, 'FINGERPRINT', fingerprint)
    return tmp_path


def test_actual_detached_signature_verifies_without_cpu_or_publication_claim(signed_source):
    proof = alarm.verify(signed_source)
    assert proof['rootfsSignatureVerified'] is True
    assert proof['cpuBaselineVerified'] is False
    assert proof['readiness'] is False
    assert proof['key']['fingerprint'] == alarm.FINGERPRINT
    assert proof['rootfs']['sha256'] == hashlib.sha256((signed_source / 'rootfs.tar.gz').read_bytes()).hexdigest()


@pytest.mark.parametrize('file', ['rootfs.tar.gz', 'rootfs.sig', 'upstream.asc'])
def test_actual_crypto_rejects_tampered_source_signature_or_key(signed_source, file):
    (signed_source / file).write_bytes(b'tampered')
    with pytest.raises(alarm.VerificationError):
        alarm.verify(signed_source)


def test_real_key_cannot_replace_pinned_official_fingerprint(signed_source, monkeypatch):
    monkeypatch.setattr(alarm, 'FINGERPRINT', 'A' * 40)
    with pytest.raises(alarm.VerificationError, match='fingerprint-mismatch'):
        alarm.verify(signed_source)


def receipt_fixture(directory, monkeypatch):
    source = {'rootfs': {'sha256': 'a' * 64}, 'signature': {'sha256': 'b' * 64},
              'key': {'fingerprint': alarm.FINGERPRINT}}
    (directory / 'source-verification.json').write_text(json.dumps(source))
    monkeypatch.setattr(alarm, 'verify', lambda path: source.copy())
    manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                'config': {'digest': 'sha256:' + 'c' * 64}, 'layers': []}
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    (directory / 'digest.txt').write_text('sha256:' + hashlib.sha256((directory / 'manifest.json').read_bytes()).hexdigest())
    (directory / 'arch.txt').write_text('aarch64\n')
    (directory / 'inventory.txt').write_text('base 3-1\npacman 7.0-1\n')
    (directory / 'policy.txt').write_text('core PackageRequired DatabaseOptional\n')
    return SimpleNamespace(source_revision='d' * 40, repository='tuna-os/tunaOS',
                           workflow_ref='tuna-os/tunaOS/.github/workflows/build-archlinuxarm-base.yml@refs/heads/main',
                           run_id='123', run_attempt='1', image_repository='ghcr.io/tuna-os/archlinuxarm',
                           image_digest_file=str(directory / 'digest.txt'), manifest_file=str(directory / 'manifest.json'),
                           runtime_arch_file=str(directory / 'arch.txt'), inventory_file=str(directory / 'inventory.txt'),
                           signature_policy_file=str(directory / 'policy.txt'))


def test_candidate_receipt_binds_single_manifest_and_inventory(tmp_path, monkeypatch):
    args = receipt_fixture(tmp_path, monkeypatch)
    result = alarm.receipt(tmp_path, args)
    assert result['scope'] == 'candidate'
    assert result['imageManifestKind'] == 'single-image-manifest'
    assert result['packageCount'] == 2
    assert result['readiness'] is False
    assert result['cpuBaselineVerified'] is False


@pytest.mark.parametrize('field,value', [('source_revision', 'main'), ('run_id', 'x'),
                                       ('workflow_ref', 'other/repo/workflow@main'),
                                       ('image_repository', 'ghcr.io/evil/another-image')])
def test_receipt_rejects_invalid_producer_identity(tmp_path, monkeypatch, field, value):
    args = receipt_fixture(tmp_path, monkeypatch)
    setattr(args, field, value)
    with pytest.raises(alarm.VerificationError):
        alarm.receipt(tmp_path, args)


@pytest.mark.parametrize('file,body', [('arch.txt', 'x86_64'), ('policy.txt', 'core PackageOptional'),
                                     ('digest.txt', 'sha256:' + 'f' * 64), ('inventory.txt', '')])
def test_receipt_rejects_arch_signature_policy_and_digest_contradictions(tmp_path, monkeypatch, file, body):
    args = receipt_fixture(tmp_path, monkeypatch)
    (tmp_path / file).write_text(body)
    with pytest.raises(alarm.VerificationError):
        alarm.receipt(tmp_path, args)


def test_workflow_verifies_before_extraction_and_never_updates_production_tags():
    text = (Path(__file__).parents[1] / '.github/workflows/build-archlinuxarm-base.yml').read_text()
    assert text.index('fetch-verify') < text.index('sudo tar -xpf')
    assert text.index('verify-local') < text.index('sudo tar -xpf')
    assert 'candidate-${GITHUB_SHA}-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}' in text
    assert '"$REF:latest"' not in text
    assert 'subject-digest: ${{ steps.candidate.outputs.digest }}' in text
    assert 'predicate-path: rootfs-evidence/producer-receipt.json' in text


def test_repository_probe_cannot_consume_remaining_loop_input():
    # CI 38074478233 processed core only: buildah inherited the repository list
    # stdin and consumed extra/alarm/aur, leaving required proof files absent.
    text = (Path(__file__).parents[1] / '.github/workflows/build-archlinuxarm-base.yml').read_text()
    probe = text.split('while IFS= read -r repo; do', 1)[1].split('done <', 1)[0]
    assert 'pacman-conf --repo "$repo" SigLevel' in probe
    assert '</dev/null' in probe
