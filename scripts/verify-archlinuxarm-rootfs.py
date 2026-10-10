#!/usr/bin/env python3
"""Verify official ALARM source bytes before extraction; record candidate proof.

The rolling rootfs is not pinned to yesterday's hash. Its detached signature is
checked using an immutable upstream key revision, exact key hash and official
fingerprint. Producer receipts require GitHub's separate signed attestation for
authentication; neither native uname nor this receipt proves an ARM ISA ceiling.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOTFS_URL = 'https://fl.us.mirror.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz'
KEY_REVISION = '91e6b11698f8df66042d56aaa56fbe9c9263847d'
KEY_URL = f'https://raw.githubusercontent.com/archlinuxarm/archlinuxarm-keyring/{KEY_REVISION}/packager/builder.asc'
KEY_SHA256 = '26196ae6d6efbb1138be6805245d577adbcd94b887eaf0569f88efe003e6b3d9'
FINGERPRINT = '68B3537F39A313B3E574D06777193F152BDBE6A6'
# Official release signer: https://archlinuxarm.org/about/downloads
MAX_ROOTFS = 1024 * 1024 * 1024
MAX_SMALL = 1024 * 1024


class VerificationError(ValueError):
    pass


def sha256(path, limit):
    size = 0
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(MAX_SMALL):
            size += len(chunk)
            if size > limit:
                raise VerificationError('source-exceeds-size-bound')
            value.update(chunk)
    return value.hexdigest(), size


def safe_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.hostname not in ('fl.us.mirror.archlinuxarm.org', 'raw.githubusercontent.com')):
        raise VerificationError('unapproved-source-url')
    if url not in (ROOTFS_URL, ROOTFS_URL + '.sig', KEY_URL):
        raise VerificationError('unapproved-source-path')
    return url


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (after.scheme != 'https' or before.netloc != after.netloc or
                after.username or after.password or after.query or after.fragment):
            raise VerificationError('unsafe-source-redirect')
        # Do not accept a landing page or a different pathname under that origin.
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, destination, limit):
    safe_url(url)
    opener = urllib.request.build_opener(SameOriginRedirect())
    deadline = time.monotonic() + 900
    for attempt in range(3):
        temporary = destination.with_suffix(destination.suffix + '.partial')
        try:
            size = 0
            with opener.open(url, timeout=60) as response, temporary.open('wb') as stream:
                modified = response.headers.get('Last-Modified')
                content_type = response.headers.get('Content-Type')
                while chunk := response.read(MAX_SMALL):
                    size += len(chunk)
                    if size > limit or time.monotonic() > deadline:
                        raise VerificationError('source-size-or-deadline-exceeded')
                    stream.write(chunk)
            temporary.replace(destination)
            value, size = sha256(destination, limit)
            destination.chmod(0o444)
            return {'url': url, 'sha256': value, 'bytes': size,
                    'lastModified': modified, 'contentType': content_type}
        except (OSError, urllib.error.URLError):
            temporary.unlink(missing_ok=True)
            if attempt == 2 or time.monotonic() > deadline:
                raise VerificationError('source-download-failed')
            time.sleep(2)
        except VerificationError:
            temporary.unlink(missing_ok=True)
            raise
    raise VerificationError('source-download-failed')


def command(arguments):
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_SMALL, MAX_SMALL))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = subprocess.run(arguments, stdout=out, stderr=err, timeout=60,
                                    preexec_fn=limits, env={**os.environ, 'LC_ALL': 'C'})
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VerificationError('signature-command-unavailable') from exc
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(MAX_SMALL + 1), err.read(MAX_SMALL + 1)
        if max(len(stdout), len(stderr)) > MAX_SMALL:
            raise VerificationError('signature-output-exceeds-bound')
        return {'exitCode': result.returncode, 'stdout': stdout.decode('utf-8', 'strict'),
                'stderr': stderr.decode('utf-8', 'strict')}


def verify(directory):
    rootfs, signature, key = directory / 'rootfs.tar.gz', directory / 'rootfs.sig', directory / 'upstream.asc'
    key_hash, _ = sha256(key, MAX_SMALL)
    if key_hash != KEY_SHA256:
        raise VerificationError('upstream-key-digest-mismatch')
    rootfs_hash, rootfs_size = sha256(rootfs, MAX_ROOTFS)
    signature_hash, signature_size = sha256(signature, MAX_SMALL)
    # Every invocation uses a fresh public keyring, without user trust/keyservers.
    with tempfile.TemporaryDirectory(prefix='alarm-verify-', dir=directory) as home:
        common = ['gpg', '--homedir', home, '--batch', '--no-auto-key-retrieve']
        shown = command(common + ['--with-colons', '--import-options', 'show-only', '--dry-run', '--import', str(key)])
        lines = shown['stdout'].splitlines()
        primaries = []
        awaiting = False
        for line in lines:
            if line.startswith('pub:'):
                awaiting = True
            elif line.startswith('fpr:') and awaiting:
                fields = line.split(':')
                if len(fields) < 10:
                    raise VerificationError('malformed-upstream-fingerprint')
                primaries.append(fields[9])
                awaiting = False
        if shown['exitCode'] or primaries != [FINGERPRINT]:
            raise VerificationError('upstream-key-fingerprint-mismatch')
        imported = command(common + ['--import', str(key)])
        if imported['exitCode']:
            raise VerificationError('upstream-key-import-failed')
        result = command(common + ['--status-fd', '1', '--verify', str(signature), str(rootfs)])
        valid = [line.split() for line in result['stdout'].splitlines() if line.startswith('[GNUPG:] VALIDSIG ')]
        if (result['exitCode'] or len(valid) != 1 or len(valid[0]) < 12 or
                valid[0][2] != FINGERPRINT or valid[0][-1] != FINGERPRINT or
                valid[0][9] not in ('8', '9', '10', '11') or valid[0][10] != '00' or
                any(code in result['stdout'] for code in ('BADSIG', 'ERRSIG', 'EXPSIG', 'EXPKEYSIG', 'REVKEYSIG'))):
            raise VerificationError('rootfs-signature-not-verified')
    return {'schemaVersion': 1, 'kind': 'archlinuxarm-rootfs-verification',
            'measuredAt': datetime.now(timezone.utc).isoformat(),
            'rootfs': {'url': ROOTFS_URL, 'sha256': rootfs_hash, 'bytes': rootfs_size},
            'signature': {'url': ROOTFS_URL + '.sig', 'sha256': signature_hash,
                          'bytes': signature_size, 'createdAtEpoch': int(valid[0][4])},
            'key': {'url': KEY_URL, 'sha256': key_hash, 'revision': KEY_REVISION,
                    'fingerprint': FINGERPRINT}, 'verification': result,
            'rootfsSignatureVerified': True, 'cpuBaselineVerified': False, 'readiness': False}


def write_json(path, document):
    path.write_text(json.dumps(document, sort_keys=True, indent=2) + '\n')


def read_json(path):
    sha256(path, MAX_SMALL)
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise VerificationError('duplicate-proof-json-key')
            result[key] = value
        return result
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise VerificationError('invalid-proof-json-envelope')
    return value


def effective_siglevel(global_value, repository_value):
    """Apply documented ordered SigLevel inheritance and Package/Database scopes.

    pacman.conf(5): repository values start from [options]; the built-in default
    is Required TrustedOnly. pacman-conf can print nothing for a repository
    without an explicit override, as observed in CI run 38074201833.
    """
    policy = {'Package': {'check': 'Required', 'trust': 'TrustedOnly'},
              'Database': {'check': 'Required', 'trust': 'TrustedOnly'}}
    for token in (global_value + ' ' + repository_value).split():
        match = re.fullmatch(r'(Package|Database)?(Required|Optional|Never|TrustedOnly|TrustAll)', token)
        if not match:
            raise VerificationError('unknown-native-signature-policy')
        scope, value = match.groups()
        for target in ([scope] if scope else ['Package', 'Database']):
            policy[target]['check' if value in ('Required', 'Optional', 'Never') else 'trust'] = value
    if policy['Package'] != {'check': 'Required', 'trust': 'TrustedOnly'}:
        raise VerificationError('native-package-signature-policy-not-required')
    return ' '.join(scope + policy[scope][field] for scope in ('Package', 'Database') for field in ('check', 'trust'))


def signature_policy(directory):
    global_file = directory / 'native-global-siglevel.txt'
    repos_file = directory / 'native-repositories.txt'
    sha256(global_file, MAX_SMALL)
    sha256(repos_file, MAX_SMALL)
    repositories = repos_file.read_text().splitlines()
    if (not repositories or len(repositories) != len(set(repositories)) or
            any(not re.fullmatch('[A-Za-z0-9_.-]+', repo) for repo in repositories)):
        raise VerificationError('invalid-native-repository-list')
    lines = []
    for repo in repositories:
        path = directory / ('native-repo-' + repo + '.siglevel.txt')
        sha256(path, MAX_SMALL)
        lines.append(repo + ' ' + effective_siglevel(global_file.read_text(), path.read_text()))
    (directory / 'native-signature-policy.txt').write_text('\n'.join(lines) + '\n')


def verified_attestations(directory):
    """Reconcile outputs of the preceding CI gh cryptographic verification.

    This function is not a signature verifier. The workflow must first run
    gh attestation verify with exact repository/workflow/source policy; raw
    JSON supplied by a caller alone never establishes that trust boundary.
    """
    receipt_document = read_json(directory / 'producer-receipt.json')
    image_digest = receipt_document['imageDigest'].removeprefix('sha256:')
    image_repository = receipt_document['imageRepository']
    for filename, predicate_type in [('build-attestation-verification.json', 'https://slsa.dev/provenance/v1'),
                                     ('receipt-attestation-verification.json', 'https://tunaos.org/attestations/archlinuxarm-base/v1')]:
        path = directory / filename
        sha256(path, 16 * MAX_SMALL)
        rows = json.loads(path.read_text())
        if not isinstance(rows, list) or not rows:
            raise VerificationError('missing-verified-attestation-statements')
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('verificationResult'), dict):
                raise VerificationError('malformed-verified-attestation')
            statement = row['verificationResult'].get('statement')
            if not isinstance(statement, dict) or statement.get('predicateType') != predicate_type:
                raise VerificationError('verified-attestation-predicate-mismatch')
            subjects = statement.get('subject')
            if (not isinstance(subjects, list) or len(subjects) != 1 or
                    subjects[0] != {'name': image_repository, 'digest': {'sha256': image_digest}}):
                raise VerificationError('verified-attestation-subject-mismatch')
            if predicate_type.endswith('archlinuxarm-base/v1') and statement.get('predicate') != receipt_document:
                raise VerificationError('verified-receipt-content-mismatch')
    write_json(directory / 'attestation-reconciliation.json', {
        'schemaVersion': 1, 'kind': 'archlinuxarm-attestation-reconciliation',
        'imageDigest': receipt_document['imageDigest'],
        'producerIdentity': receipt_document['producerIdentity'],
        'receiptDigest': 'sha256:' + sha256(directory / 'producer-receipt.json', MAX_SMALL)[0],
        'verificationResultDigests': ['sha256:' + sha256(directory / name, 16 * MAX_SMALL)[0]
                                      for name in ('build-attestation-verification.json', 'receipt-attestation-verification.json')],
        'readiness': False, 'cpuBaselineVerified': False})


def fetch_verify(directory):
    directory.mkdir(parents=True, exist_ok=False)
    sources = [fetch(ROOTFS_URL, directory / 'rootfs.tar.gz', MAX_ROOTFS),
               fetch(ROOTFS_URL + '.sig', directory / 'rootfs.sig', MAX_SMALL),
               fetch(KEY_URL, directory / 'upstream.asc', MAX_SMALL)]
    result = verify(directory)
    result['downloads'] = sources
    write_json(directory / 'source-verification.json', result)
    return result


def receipt(directory, args):
    # Rehash persisted source bytes against the cryptographic verification record.
    source_path = directory / 'source-verification.json'
    source = read_json(source_path)
    fresh = verify(directory)
    if any(source.get(field) != fresh[field] for field in ('rootfs', 'signature', 'key')):
        raise VerificationError('source-changed-after-verification')
    if (not re.fullmatch('[0-9a-f]{40}', args.source_revision) or
            not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository) or
            not args.run_id.isdecimal() or not args.run_attempt.isdecimal() or
            not args.workflow_ref.startswith(args.repository + '/.github/workflows/build-archlinuxarm-base.yml@')):
        raise VerificationError('invalid-producer-identity')
    image_digest = Path(args.image_digest_file).read_text().strip()
    if not re.fullmatch('sha256:[0-9a-f]{64}', image_digest):
        raise VerificationError('invalid-produced-image-digest')
    manifest_path = Path(args.manifest_file)
    if 'sha256:' + sha256(manifest_path, MAX_SMALL)[0] != image_digest:
        raise VerificationError('published-manifest-digest-mismatch')
    manifest = read_json(manifest_path)
    if (type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 2 or
            manifest.get('mediaType') not in ('application/vnd.oci.image.manifest.v1+json',
                                             'application/vnd.docker.distribution.manifest.v2+json') or
            not isinstance(manifest.get('config'), dict) or
            not re.fullmatch('sha256:[0-9a-f]{64}', str(manifest['config'].get('digest', '')))):
        raise VerificationError('published-image-is-not-single-manifest')
    if not re.fullmatch('ghcr.io/[a-z0-9_.-]+/archlinuxarm', args.image_repository):
        raise VerificationError('invalid-image-repository')
    if Path(args.runtime_arch_file).read_text().strip() != 'aarch64':
        raise VerificationError('producer-not-native-arm')
    inventory = Path(args.inventory_file)
    inventory_hash, _ = sha256(inventory, 16 * MAX_SMALL)
    lines = inventory.read_text().splitlines()
    if not lines or any(not re.fullmatch(r'[A-Za-z0-9@._+:-]+\s+\S+', line) for line in lines):
        raise VerificationError('invalid-native-package-inventory')
    policy = Path(args.signature_policy_file)
    policy_hash, _ = sha256(policy, MAX_SMALL)
    policy_lines = policy.read_text().splitlines()
    if not policy_lines or any('PackageRequired' not in line.split() or
                               any(value in line.split() for value in ('PackageOptional', 'PackageNever'))
                               for line in policy_lines):
        raise VerificationError('native-package-signature-policy-not-required')
    result = {'schemaVersion': 1, 'kind': 'archlinuxarm-base-candidate',
              'measuredAt': datetime.now(timezone.utc).isoformat(),
              'producerIdentity': {'repository': args.repository, 'sourceRevision': args.source_revision,
                                   'workflowRef': args.workflow_ref, 'runId': args.run_id, 'runAttempt': args.run_attempt},
              'sourceVerificationDigest': 'sha256:' + sha256(source_path, MAX_SMALL)[0],
              'source': source, 'imageDigest': image_digest, 'imageRepository': args.image_repository,
              'imageManifestKind': 'single-image-manifest', 'configDigest': manifest['config']['digest'],
              'scope': 'candidate', 'observedNativeArchitecture': 'aarch64',
              'installedPackageInventoryDigest': 'sha256:' + inventory_hash,
              'effectiveSignaturePolicyDigest': 'sha256:' + policy_hash,
              'packageCount': len(lines), 'cpuBaselineVerified': False, 'readiness': False,
              'requiredTrust': ['verify-github-attestation-for-exact-image-and-receipt']}
    write_json(directory / 'producer-receipt.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['fetch-verify', 'verify-local', 'signature-policy', 'verified-attestations', 'receipt'])
    parser.add_argument('--directory', required=True)
    for name in ('source-revision', 'repository', 'workflow-ref', 'run-id', 'run-attempt',
                 'image-digest-file', 'image-repository', 'manifest-file', 'runtime-arch-file', 'inventory-file', 'signature-policy-file'):
        parser.add_argument('--' + name)
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    try:
        if args.operation == 'fetch-verify':
            fetch_verify(directory)
        elif args.operation == 'verify-local':
            verify(directory)
        elif args.operation == 'signature-policy':
            signature_policy(directory)
        elif args.operation == 'verified-attestations':
            verified_attestations(directory)
        else:
            if any(getattr(args, name) is None for name in ('source_revision', 'repository', 'workflow_ref', 'run_id',
                    'run_attempt', 'image_digest_file', 'image_repository', 'manifest_file', 'runtime_arch_file', 'inventory_file', 'signature_policy_file')):
                raise VerificationError('missing-receipt-input')
            receipt(directory, args)
    except (VerificationError, OSError, ValueError) as exc:
        parser.exit(1, 'Arch Linux ARM source verification blocked: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
