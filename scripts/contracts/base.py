"""Validate bounded offline OCI bytes against configured base and exact platform."""
from __future__ import annotations
import base64
import hashlib
import re
from typing import Any
from .evidence import EvidenceError, loads
from .targets import split_platform

REFERENCE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*(?::[^\s@]+)?@sha256:[0-9a-f]{64}$')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
INDEX_TYPES = {'application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json'}
IMAGE_TYPES = {'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'}
CONFIG_TYPES = {'application/vnd.oci.image.config.v1+json', 'application/vnd.docker.container.image.v1+json'}
MAX_BYTES = 4 * 1024 * 1024


def _blob(encoded: str, digest: str) -> tuple[dict, int]:
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise EvidenceError('invalid OCI digest')
    if not isinstance(encoded, str) or len(encoded) > (MAX_BYTES * 4 // 3 + 8):
        raise EvidenceError('OCI blob exceeds bounded size')
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_BYTES:
            raise EvidenceError('OCI blob exceeds bounded size')
        if 'sha256:' + hashlib.sha256(raw).hexdigest() != digest:
            raise EvidenceError('OCI bytes do not match digest')
        return loads(raw.decode('utf-8')), len(raw)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise EvidenceError(f'invalid OCI blob: {exc}') from exc


def _descriptor(value: Any) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get('mediaType'), str) or not DIGEST.fullmatch(str(value.get('digest', ''))) or type(value.get('size')) is not int or value['size'] < 0:
        raise EvidenceError('malformed OCI descriptor')
    return value


def _reference(reference: Any, *, pinned: bool = False) -> str:
    if not isinstance(reference, str) or "://" in reference or "?" in reference or "#" in reference or "\\" in reference:
        raise EvidenceError('invalid OCI reference syntax')
    if reference.count('@') > 1 or any(part in {'', '.', '..'} for part in reference.split('@', 1)[0].split('/')):
        raise EvidenceError('invalid OCI repository path')
    name, separator, digest = reference.partition('@')
    if separator and not DIGEST.fullmatch(digest):
        raise EvidenceError('invalid OCI reference digest')
    if pinned and not separator:
        raise EvidenceError('OCI reference must be digest pinned')
    if '/' not in name:
        raise EvidenceError('OCI reference requires explicit registry and repository')
    host, repository = name.split('/', 1)
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]+)?', host):
        raise EvidenceError('invalid OCI registry host')
    if ':' in repository:
        repository, tag = repository.rsplit(':', 1)
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag):
            raise EvidenceError('invalid OCI tag')
    if not re.fullmatch(r'[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*', repository):
        raise EvidenceError('invalid OCI repository name')
    return reference


def _repository(reference: str) -> str:
    name = reference.rsplit('@', 1)[0]
    slash, colon = name.rfind('/'), name.rfind(':')
    return name[:colon] if colon > slash else name


def validate_base(record: dict[str, Any], target: dict, configured_reference: str) -> dict:
    fields = {'configuredReference', 'reference', 'indexDigest', 'childDigest', 'configDigest', 'platform',
              'cpuBaseline', 'indexBytes', 'childBytes', 'configBytes', 'baselineEvidence'}
    if not isinstance(record, dict) or set(record) != fields:
        raise EvidenceError('base record requires exact index/child/config/baseline evidence')
    if record['configuredReference'] != configured_reference:
        raise EvidenceError('base record differs from configured base')
    _reference(configured_reference)
    if '@' in configured_reference and configured_reference.rsplit('@', 1)[1] != record['indexDigest']:
        raise EvidenceError('configured base digest differs from observed index')
    _reference(record['reference'], pinned=True)
    if _repository(record['reference']) != _repository(configured_reference):
        raise EvidenceError('base child repository differs from configured repository')
    if record['reference'].rsplit('@', 1)[1] != record['childDigest']:
        raise EvidenceError('base child reference differs from observed digest')
    index, _ = _blob(record['indexBytes'], record['indexDigest'])
    child, child_size = _blob(record['childBytes'], record['childDigest'])
    config, config_size = _blob(record['configBytes'], record['configDigest'])
    if type(index.get('schemaVersion')) is not int or index['schemaVersion'] != 2 or index.get('mediaType') not in INDEX_TYPES or not isinstance(index.get('manifests'), list):
        raise EvidenceError('base index is not a supported OCI index')
    if type(child.get('schemaVersion')) is not int or child['schemaVersion'] != 2 or child.get('mediaType') not in IMAGE_TYPES or not isinstance(child.get('layers'), list):
        raise EvidenceError('base child is not a supported OCI image manifest')
    config_descriptor = _descriptor(child.get('config'))
    if config_descriptor['mediaType'] not in CONFIG_TYPES or config_descriptor['digest'] != record['configDigest'] or config_descriptor['size'] != config_size:
        raise EvidenceError('child does not bind actual config bytes')
    for layer in child['layers']:
        _descriptor(layer)
    if record['platform'] != target['platform'] or record['cpuBaseline'] != target['cpuBaseline']:
        raise EvidenceError('base platform or CPU baseline differs from consumer')
    os_name, arch, variant = split_platform(target['platform'])
    matches = []
    for raw_descriptor in index['manifests']:
        descriptor = _descriptor(raw_descriptor)
        platform = descriptor.get('platform')
        if platform is None:
            continue
        if not isinstance(platform, dict):
            raise EvidenceError('index descriptor has malformed platform identity')
        actual_variant = platform.get('variant')
        allowed_variant = actual_variant == variant or (arch == 'arm64' and variant is None and actual_variant == 'v8')
        if platform.get('os') == os_name and platform.get('architecture') == arch and allowed_variant:
            matches.append(descriptor)
    if len(matches) != 1 or matches[0]['digest'] != record['childDigest'] or matches[0]['size'] != child_size or matches[0]['mediaType'] != child['mediaType']:
        raise EvidenceError('index does not uniquely bind exact child platform bytes')
    observed_platform = matches[0]['platform']
    if config.get('os') != os_name or config.get('architecture') != arch:
        raise EvidenceError('actual child config architecture disagrees with index')
    # Alma v2 configs omit variant; the index plus baseline proof carries v2.
    config_variant = config.get('variant')
    if config_variant is not None and config_variant != observed_platform.get('variant') and not (arch == 'arm64' and config_variant == 'v8' and observed_platform.get('variant') in {None, 'v8'}):
        raise EvidenceError('actual child config variant disagrees with exact descriptor')
    evidence = record['baselineEvidence']
    if not isinstance(evidence, list) or not evidence or any(not isinstance(x, dict) or set(x) != {'digest', 'url'} or not DIGEST.fullmatch(str(x['digest'])) or not isinstance(x['url'], str) or not x['url'].startswith('https://') for x in evidence):
        raise EvidenceError('CPU baseline needs immutable measured evidence')
    output = {key: record[key] for key in fields - {'indexBytes', 'childBytes', 'configBytes'}}
    output['observedPlatform'] = {key: observed_platform[key] for key in ('os', 'architecture', 'variant') if key in observed_platform}
    return output


REGISTRY_HOSTS = frozenset({'quay.io', 'registry.fedoraproject.org', 'registry.opensuse.org',
                           'docker.io', 'registry-1.docker.io', 'ghcr.io'})
AUTH_HOSTS = REGISTRY_HOSTS | {'auth.docker.io'}


def resolve_public_base(configured_reference: str, target: dict, baseline_evidence: list[dict]) -> dict:
    """Resolve public OCI metadata once; callers must build from returned child pin.

    Authentication challenges are bounded to known HTTPS hosts. Tokens exist only
    in memory and are never returned in metadata or exception messages.
    """
    import urllib.request
    import urllib.error
    import urllib.parse
    from .targets import validate_target
    validate_target(target)
    _reference(configured_reference)
    host, slash, rest = configured_reference.partition('/')
    if not slash or host not in REGISTRY_HOSTS:
        raise EvidenceError('registry is outside public resolver allowlist')
    if '@' in rest:
        tagged_name, selected_ref = rest.rsplit('@', 1)
        name = _repository(tagged_name)
    elif ':' in rest.rsplit('/', 1)[-1]:
        name, selected_ref = rest.rsplit(':', 1)
    else:
        name, selected_ref = rest, 'latest'
    transport_host = 'registry-1.docker.io' if host == 'docker.io' else host
    if host == 'docker.io' and '/' not in name:
        name = 'library/' + name
    base_url = f'https://{transport_host}/v2/{name}'
    headers = {'Accept': ', '.join(sorted(INDEX_TYPES | IMAGE_TYPES)), 'User-Agent': 'tunaos-contract-resolver'}

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, response_headers, newurl):
            raise EvidenceError('registry redirect rejected; resolve metadata from approved origin')

    opener = urllib.request.build_opener(NoRedirect())

    def get(url: str, *, auth: bool = True) -> bytes:
        try:
            with opener.open(urllib.request.Request(url, headers=headers if auth else {'User-Agent': 'tunaos-contract-resolver'}), timeout=30) as response:
                data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise EvidenceError('registry response exceeds bounded size')
            return data
        except urllib.error.HTTPError as exc:
            if not auth or exc.code != 401 or 'Authorization' in headers:
                raise EvidenceError(f'public registry request unavailable (HTTP {exc.code})') from None
            challenge = exc.headers.get('WWW-Authenticate', '')
            if not challenge.startswith('Bearer '):
                raise EvidenceError('unsupported registry authentication challenge') from None
            params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
            realm = urllib.parse.urlsplit(params.get('realm', ''))
            if realm.scheme != 'https' or realm.hostname not in AUTH_HOSTS or realm.username or realm.password or realm.fragment:
                raise EvidenceError('registry authentication origin rejected') from None
            scope = params.get('scope', f'repository:{name}:pull')
            if scope != f'repository:{name}:pull':
                raise EvidenceError('registry authentication scope rejected') from None
            query = urllib.parse.urlencode({'scope': scope, 'service': params.get('service', transport_host)})
            auth_url = urllib.parse.urlunsplit((realm.scheme, realm.netloc, realm.path, query, ''))
            token_document = loads(get(auth_url, auth=False).decode('utf-8'))
            token = token_document.get('token', token_document.get('access_token'))
            if not isinstance(token, str) or not token or len(token) > 16384:
                raise EvidenceError('public registry token unavailable')
            headers['Authorization'] = 'Bearer ' + token
            return get(url)
        except (urllib.error.URLError, TimeoutError, UnicodeError) as exc:
            raise EvidenceError('public registry metadata unavailable') from None

    index_bytes = get(base_url + '/manifests/' + selected_ref)
    index_digest = 'sha256:' + hashlib.sha256(index_bytes).hexdigest()
    index = loads(index_bytes.decode('utf-8'))
    if index.get('mediaType') not in INDEX_TYPES or not isinstance(index.get('manifests'), list):
        raise EvidenceError('public base is not an indexed image; exact platform evidence unavailable')
    os_name, architecture, variant = split_platform(target['platform'])
    candidates = []
    for value in index['manifests']:
        descriptor = _descriptor(value)
        platform = descriptor.get('platform')
        if platform is None:
            continue
        if not isinstance(platform, dict):
            raise EvidenceError('public index has malformed platform')
        actual_variant = platform.get('variant')
        if platform.get('os') == os_name and platform.get('architecture') == architecture and (actual_variant == variant or architecture == 'arm64' and variant is None and actual_variant == 'v8'):
            candidates.append(descriptor)
    if len(candidates) != 1:
        raise EvidenceError('required exact platform child absent or ambiguous')
    child_digest = candidates[0]['digest']
    child_bytes = get(base_url + '/manifests/' + child_digest)
    child = loads(child_bytes.decode('utf-8'))
    config_digest = _descriptor(child.get('config'))['digest']
    config_bytes = get(base_url + '/blobs/' + config_digest)
    repository = _repository(configured_reference)
    record = {'configuredReference': configured_reference, 'reference': repository + '@' + child_digest,
              'indexDigest': index_digest, 'childDigest': child_digest, 'configDigest': config_digest,
              'platform': target['platform'], 'cpuBaseline': target['cpuBaseline'],
              'indexBytes': base64.b64encode(index_bytes).decode('ascii'),
              'childBytes': base64.b64encode(child_bytes).decode('ascii'),
              'configBytes': base64.b64encode(config_bytes).decode('ascii'),
              'baselineEvidence': baseline_evidence}
    validate_base(record, target, configured_reference)
    return record


def main() -> None:
    import argparse
    import pathlib
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--target', required=True, help='path to canonical target JSON')
    parser.add_argument('--baseline-evidence', required=True, help='path to measured evidence JSON object {evidence: [...] }')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    target = loads(pathlib.Path(args.target).read_text())
    baseline = loads(pathlib.Path(args.baseline_evidence).read_text())
    if set(baseline) != {'evidence'}:
        raise EvidenceError('baseline input must contain only evidence')
    record = resolve_public_base(args.reference, target, baseline['evidence'])
    pathlib.Path(args.output).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
