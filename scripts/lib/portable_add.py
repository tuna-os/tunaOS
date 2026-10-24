"""Portable package-add intent and separate non-installing transaction checks.

Planning resolves one user intent across every selected image target from the
trusted configured-source collector (``package_catalogs``/``signed_apt``). It
records index availability only. Transaction verification is a separate step
that consumes the plan and runs a native simulation in a digest-pinned image.
Neither step installs packages on the host, executes ebuilds or edits
configuration.
"""
import hashlib
import json
import re

from . import package_authoring as author
from . import package_catalogs as catalogs
from . import signed_apt

PLAN_SCHEMA = 1
NOT_RUN = {'status': 'not-run'}
INVENTORY = 'docs/BASE-PACKAGE-SEARCH.md#native-adapter-inventory'
IMAGE = re.compile(r'[a-z0-9][a-z0-9._/:-]*@sha256:[0-9a-f]{64}\Z')


class PortableAddError(ValueError):
    """Raised when a plan or transaction is not complete; carries the report."""

    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


def target_id(variant, flavor, platform):
    return f'{variant}:{flavor}:{platform}'


def enabled_targets(document):
    """Every enabled image target in declaration order."""
    result = []
    for variant, entry in document['variants'].items():
        for flavor in entry['flavors']:
            if flavor.get('build_image', False):
                for platform in flavor.get('platforms', entry['platforms']):
                    result.append((variant, flavor['id'], platform))
    return result


def select_targets(document, variants=(), flavors=(), platforms=()):
    known = enabled_targets(document)
    for option, values, position in (('--variant', variants, 0), ('--flavor', flavors, 1),
                                     ('--platform', platforms, 2)):
        unknown = set(values) - {target[position] for target in known}
        if unknown:
            raise PortableAddError(f'{option}: no enabled image target matches: '
                                   + ', '.join(sorted(unknown)))
    selected = [target for target in known
                if (not variants or target[0] in variants)
                and (not flavors or target[1] in flavors)
                and (not platforms or target[2] in platforms)]
    if not selected:
        raise PortableAddError('selection matches no enabled image target')
    return selected


def covering_catalog(document, variant, flavor, platform):
    for catalog_id, catalog in document.get('package_catalogs', {}).items():
        if (catalog.get('variant') == variant and flavor in catalog.get('flavors', [])
                and platform in catalog.get('platforms', [])):
            return catalog_id, catalog
    return None, None


def _source_evidence(results):
    return [{key: result[key] for key in ('source', 'role', 'source_url', 'release',
                                          'architecture', 'signed_at', 'retrieved_at',
                                          'inrelease_sha256', 'keyring_sha256', 'indexes',
                                          'freshness')}
            for result in results]


def plan(document, config_directory, query, selected, native=None, *, now, acquire=None):
    """Resolve every selected target before any emission; fail atomically."""
    acquire = acquire or signed_apt.acquire_catalog
    native = dict(native or {})
    ids = {target_id(*target) for target in selected}
    if set(native) - ids:
        raise PortableAddError('--native overrides must name selected targets: '
                               + ', '.join(sorted(set(native) - ids)))
    author.checked_name(query)
    collected = {}  # One bound, authenticated collection (or its failure) per catalog.
    records = []
    for variant, flavor, platform in selected:
        name = target_id(variant, flavor, platform)
        record = {'target': name, 'variant': variant, 'flavor': flavor, 'platform': platform,
                  'requested': native.get(name, query),
                  'mapping': 'explicit' if name in native else 'exact',
                  'index_availability': {'status': 'not-collected'},
                  'transaction': dict(NOT_RUN), 'installed_image': dict(NOT_RUN)}
        records.append(record)
        catalog_id, catalog = covering_catalog(document, variant, flavor, platform)
        if catalog is None:
            record.update(status='unsupported', reason=(
                'no trusted configured-source collector covers this target; '
                f'names are never guessed for it (see {INVENTORY})'))
            continue
        record['catalog'] = catalog_id
        try:
            catalogs.select(document, catalog_id, variant, flavor, catalog['release'], platform)
            target = catalogs.bind_target_configuration(catalog, document, config_directory, flavor)
            if catalog_id not in collected:
                try:
                    observation, keys = catalogs.bind_observation(catalog, config_directory)
                    collected[catalog_id] = (observation, acquire(
                        catalog, lambda source: keys[source['id']], now))
                except catalogs.CatalogError as exc:
                    collected[catalog_id] = exc
            if isinstance(collected[catalog_id], catalogs.CatalogError):
                raise collected[catalog_id]
            observation, results = collected[catalog_id]
        except catalogs.CatalogError as exc:
            record.update(status='source-error', reason=str(exc))
            continue
        names = set().union(*(result['names'] for result in results))
        record.update(release=catalog['release'], family=catalog['family'],
                      base_image=observation['base_image'],
                      configuration_observed_at=target['observed_at'])
        try:
            resolved = author.resolve(record['requested'], names, catalog['family'])
        except author.AuthoringError as exc:
            record['index_availability'] = {'status': 'absent',
                                            'sources': _source_evidence(results)}
            record.update(status='ambiguous' if 'ambiguous' in str(exc) else 'missing',
                          reason=str(exc))
            continue
        matched = [result['source'] for result in results if resolved in result['names']]
        record['index_availability'] = {'status': 'present', 'matched_sources': matched,
                                        'sources': _source_evidence(results)}
        record.update(status='resolved', native_name=resolved)
    report = {'schema_version': PLAN_SCHEMA, 'query': query,
              'selected_targets': len(records),
              'resolved_targets': sum(r['status'] == 'resolved' for r in records),
              'complete': all(r['status'] == 'resolved' for r in records),
              'targets': records}
    report['emission'] = emission(document, records) if report['complete'] else {
        'status': 'blocked', 'reason': 'not every selected target resolved'}
    if not report['complete']:
        failed = [r['target'] + ' (' + r['status'] + ')' for r in records
                  if r['status'] != 'resolved']
        raise PortableAddError(f'{len(failed)} of {len(records)} selected targets did not '
                               'resolve; nothing emitted: ' + ', '.join(failed), report)
    return report


def emission(document, records):
    """Choose the narrowest addition scope that covers exactly resolved targets.

    Image-wide additions apply to every flavor and platform of a variant, so a
    variant scope requires every enabled target of that variant to be resolved.
    """
    resolved = {record['target']: record['native_name'] for record in records}
    everything = [target_id(*target) for target in enabled_targets(document)]
    names = set(resolved.values())
    if set(everything) == set(resolved) and len(names) == 1:
        return {'status': 'ready', 'scope': 'defaults', 'additions': {'defaults': sorted(names)}}
    additions, blocked = {}, []
    for variant in sorted({record['variant'] for record in records}):
        affected = [target_id(*target) for target in enabled_targets(document)
                    if target[0] == variant]
        uncovered = [target for target in affected if target not in resolved]
        variant_names = {resolved[target] for target in affected if target in resolved}
        if uncovered:
            blocked.append(f'{variant}: a variant addition also affects unresolved targets '
                           + ', '.join(uncovered))
        elif len(variant_names) != 1:
            blocked.append(f'{variant}: native names differ within one variant scope: '
                           + ', '.join(sorted(variant_names)))
        else:
            additions[variant] = sorted(variant_names)
    if blocked:
        return {'status': 'blocked', 'reason': '; '.join(blocked)}
    return {'status': 'ready', 'scope': 'variants', 'additions': additions}


SOURCE_REFRESH_FAILED = 'tunaos: image package-source refresh failed'
APT_SIMULATION = (f'apt-get update -qq || {{ echo "{SOURCE_REFRESH_FAILED}" >&2; exit 90; }}; '
                  'exec apt-get --simulate --no-remove -o Debug::NoLocking=1 install -- "$@"')


def plan_target(report, target):
    if not isinstance(report, dict) or report.get('schema_version') != PLAN_SCHEMA:
        raise PortableAddError('plan: unsupported or malformed portable-add plan')
    if report.get('complete') is not True:
        raise PortableAddError('plan: incomplete plans cannot be verified')
    matches = [record for record in report.get('targets', []) if record.get('target') == target]
    if len(matches) != 1 or matches[0].get('status') != 'resolved':
        raise PortableAddError(f'{target}: not a resolved target of this plan')
    record = matches[0]
    author.checked_name(record.get('native_name'))
    return record


def classify_apt(name, result):
    """Classify one apt simulation; every non-solvable outcome is explicit."""
    output = (result.stdout or '') + (result.stderr or '')
    if result.returncode == 90 and SOURCE_REFRESH_FAILED in output:
        return {'status': 'source-error', 'installs': [], 'removals': [],
                'detail': 'the image could not refresh its configured package sources'}
    installs = re.findall(r'^Inst (\S+)', output, re.MULTILINE)
    removals = re.findall(r'^Remv (\S+)', output, re.MULTILINE)
    if removals or 'Packages need to be removed but remove is disabled' in output:
        return {'status': 'protected-removal', 'installs': installs, 'removals': removals,
                'detail': 'the transaction would remove packages; removals are rejected'}
    if re.search(r'^E: Unable to locate package ', output, re.MULTILINE):
        return {'status': 'missing', 'installs': [], 'removals': [],
                'detail': f'{name} is not available from the image package sources'}
    if 'unmet dependencies' in output or 'held broken packages' in output:
        return {'status': 'solver-gap', 'installs': installs, 'removals': [],
                'detail': 'the native solver cannot satisfy dependencies'}
    if result.returncode != 0:
        tail = output.strip().splitlines()[-3:]
        return {'status': 'error', 'installs': [], 'removals': [],
                'detail': 'native simulation failed: ' + ' | '.join(tail)}
    if name in installs:
        return {'status': 'solvable', 'installs': installs, 'removals': []}
    if re.search(rf'^{re.escape(name)} is already the newest version', output, re.MULTILINE):
        return {'status': 'already-installed', 'installs': [], 'removals': []}
    return {'status': 'error', 'installs': installs, 'removals': [],
            'detail': f'simulation succeeded without scheduling {name}'}


def verify_transaction(report, plan_bytes, target, image, run):
    """Simulate the planned addition natively; never commits a transaction."""
    record = plan_target(report, target)
    if not IMAGE.fullmatch(image):
        raise PortableAddError('--image must be an immutable reference pinned by @sha256 digest')
    name = record['native_name']
    result = {'target': target, 'native_name': name,
              'plan_sha256': hashlib.sha256(plan_bytes).hexdigest(), 'image': image,
              'image_binding': 'operator-supplied; not authenticated against the target',
              'index_availability': record['index_availability']['status'],
              'installed_image': dict(NOT_RUN)}
    if record.get('family') != 'apt':
        result['transaction'] = {'status': 'unsupported', 'detail': (
            f'no reviewed non-installing transaction adapter for {record.get("family")}')}
        raise PortableAddError(f'{target}: transaction verification unsupported', result)
    command = ['podman', 'run', '--rm', '--pull=never', '--entrypoint', 'sh', image,
               '-c', APT_SIMULATION, 'sh', name]
    completed = run(command, text=True, capture_output=True)
    result['transaction'] = classify_apt(name, completed)
    result['transaction']['command'] = command
    if result['transaction']['status'] not in {'solvable', 'already-installed'}:
        raise PortableAddError(f'{target}: transaction {result["transaction"]["status"]}', result)
    return result


def load_plan(data):
    try:
        return json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PortableAddError('plan: expected portable-add plan JSON') from exc
