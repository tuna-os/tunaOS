"""Conservative changed-path scope: uncertainty widens scope, never implies pass."""
from pathlib import PurePosixPath
import re


def affected_cells(cells, paths, capacity=2):
    if capacity < 1:
        raise ValueError('capacity must be positive')
    baseline = sorted((c for c in cells if c['platform'] == 'linux/amd64' and c['install_admitted']), key=lambda c: c['id'])
    desktops = {c['flavor'] for c in baseline}
    variants = {c['variant'] for c in baseline}
    affected = set()
    classified = []
    for raw in sorted(set(paths)):
        path = PurePosixPath(raw)
        if path.is_absolute() or '..' in path.parts or '\\' in raw or not raw:
            raise ValueError(f'invalid repository-relative path: {raw!r}')
        reason = 'unclassified: conservatively affects all baseline cells'
        matches = baseline
        desktop_match = re.fullmatch(r'live-iso/common/src/desktop-([a-z0-9-]+)\.sh', raw)
        manifest_match = re.fullmatch(r'manifests/desktops/([a-z0-9-]+)\.yaml', raw)
        workflow_match = re.fullmatch(r'\.github/workflows/build-([a-z0-9-]+)\.yml', raw)
        runtime_specs = {'tests/install-pipeline-screens.yaml', 'tests/installer-screens.yaml',
                         'tests/live-iso-verify.yaml', 'tests/anaconda-ks.cfg'}
        if raw in runtime_specs:
            reason = 'runtime installer/checkpoint contract: all baseline cells'
        elif raw.startswith(('docs/', 'tests/', '.spektacular/')) or raw in ('README.md', 'ROADMAP.md'):
            matches = []
            reason = 'static tests/docs only; no automatic expensive cell'
        elif desktop_match and desktop_match[1] in desktops:
            matches = [c for c in baseline if c['flavor'] == desktop_match[1]]
            reason = 'desktop live adapter'
        elif manifest_match:
            # Platform-specific desktop manifests still affect the whole desktop
            # until resolver dependency edges have their own tested ownership.
            desktop = next((d for d in sorted(desktops) if manifest_match[1] == d or manifest_match[1].startswith(d + '-')), None)
            if desktop:
                matches = [c for c in baseline if c['flavor'] == desktop]
                reason = 'desktop manifest (conservative across base families)'
        elif workflow_match and workflow_match[1] in variants:
            matches = [c for c in baseline if c['variant'] == workflow_match[1]]
            reason = 'variant build workflow'
        elif raw == 'tunaos.toml' or raw.startswith(('scripts/', 'build_scripts/', 'live-iso/', '.github/actions/')) or raw.startswith('Containerfile'):
            reason = 'shared build/config/installer dependency: all baseline cells'
        affected.update(c['id'] for c in matches)
        classified.append({'path': raw, 'reason': reason, 'affected_count': len(matches)})
    candidates = [c for c in baseline if c['id'] in affected]
    # Deterministic explicit sampling, not a false complete changed-cell gate.
    # Prefer measured GNOME lane first, then maximize base/frontend diversity.
    selected = []
    while candidates and len(selected) < capacity:
        def rank(c):
            if not selected:
                return (c['variant'] != 'skipjack' or c['flavor'] != 'gnome', c['id'])
            return (c['flavor'] in {s['flavor'] for s in selected},
                    c['variant'] in {s['variant'] for s in selected}, c['id'])
        pick = min(candidates, key=rank)
        selected.append(pick)
        candidates.remove(pick)
    return {'paths': classified, 'affected_ids': sorted(affected), 'selected': selected,
            'deferred': candidates, 'overflow': bool(candidates),
            'selection_kind': 'representative sample' if candidates else 'all affected baseline cells',
            'complete_coverage': False,
            'required_followup': 'queue deferred cells within the same approved budget; selection is not qualification'}
